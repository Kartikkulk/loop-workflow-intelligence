"""Connecting your own accounts.

LOOP runs on one person's laptop and reads that person's own work. There is no
tenant, no administrator, and no LOOP cloud in the middle — which is why the
whole flow here is ordinary personal OAuth: press a button, sign in with the
account you already use, come back with a read-only token that lives in a
database file on your own disk.

Three properties are load-bearing, and each is enforced here rather than left
to good behaviour:

  * **No secret ever reaches the browser.** Credentials are posted in and never
    echoed back; the token exchange happens server-side; `/providers` reports
    that a secret is set, not what it is.
  * **The callback only accepts a sign-in this instance started.** A state we
    did not issue is refused, and consuming one destroys it.
  * **Disconnecting really disconnects.** Tokens and every event they produced
    are deleted together, so "remove it" does not leave a shadow copy of your
    inbox behind.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_session
from app.models.cluster import Cluster
from app.models.connection import AppCredential, Connection
from app.models.event import Event
from app.schemas.connections import (
    ProviderList,
    ProviderOut,
    SaveCredentialsRequest,
    StartOut,
    SyncResult,
)
from app.services import oauth
from app.services.activity_import import fetch_activity
from app.services.ids import new_id
from app.services.normaliser import as_utc
from app.services.oauth_providers import (
    PROVIDERS,
    PROVIDERS_BY_KEY,
    OAuthProvider,
    redirect_uri,
)
from app.services.pipeline import run_detection
from app.services.sources import ensure_app_registered

router = APIRouter(prefix="/connect", tags=["connect"])
logger = logging.getLogger("loop.connect")


def _source_id(provider_key: str) -> str:
    """Marks every event that came from this connection, so it can be removed."""
    return f"conn:{provider_key}"


def _query(params: dict[str, str]) -> str:
    """Encode redirect parameters, dropping the empty ones."""
    return str(httpx.QueryParams({k: v for k, v in params.items() if v}))


def _provider_or_404(key: str) -> OAuthProvider:
    provider = PROVIDERS_BY_KEY.get(key)
    if provider is None:
        raise HTTPException(404, f"LOOP does not know a provider called {key!r}.")
    return provider


async def reload_credentials(session: AsyncSession) -> None:
    """Push saved credentials into the resolver the providers read from."""
    result = await session.execute(select(AppCredential))
    saved = {
        row.provider: {"client_id": row.client_id, "client_secret": row.client_secret}
        for row in result.scalars().all()
    }
    from app.services.oauth_providers import refresh_credentials

    refresh_credentials(saved)


# ── what can be connected, and what is ──────────────────────────────────────

@router.get("/providers", response_model=ProviderList)
async def list_providers(session: AsyncSession = Depends(get_session)) -> ProviderList:
    """Every account LOOP can read, with its current state."""
    await reload_credentials(session)
    live = await oauth.connected(session)

    items: list[ProviderOut] = []
    for provider in PROVIDERS:
        connection = live.get(provider.key)
        client_id = provider.client_id

        items.append(
            ProviderOut(
                key=provider.key,
                label=provider.label,
                reads=provider.reads,
                scopes=list(provider.scopes),
                configured=provider.configured,
                setup_url=provider.setup_url,
                setup_steps=list(provider.setup_steps),
                redirect_uri=redirect_uri(provider.key, settings.api_base_url),
                client_id_env=provider.client_id_env,
                client_secret_env=provider.client_secret_env,
                # Enough to recognise which app, not enough to be the app.
                client_id_hint=(client_id[:14] + "…") if len(client_id) > 14 else client_id,
                has_secret=bool(provider.client_secret),
                connected=connection is not None,
                account_label=connection.account_label if connection else "",
                last_sync_at=(
                    connection.last_sync_at.isoformat()
                    if connection and connection.last_sync_at
                    else None
                ),
                events_imported=connection.events_imported if connection else 0,
                last_error=connection.last_error if connection else None,
            )
        )

    return ProviderList(items=items, connected_count=len(live))


# ── the person's own app registration ───────────────────────────────────────

@router.put("/{provider_key}/credentials", response_model=ProviderList)
async def save_credentials(
    provider_key: str,
    body: SaveCredentialsRequest,
    session: AsyncSession = Depends(get_session),
) -> ProviderList:
    """Store the client id and secret from the person's own OAuth app.

    These arrive over the local loopback connection and go straight into the
    local database. They are not returned by this endpoint or any other.
    """
    provider = _provider_or_404(provider_key)

    row = await session.get(AppCredential, provider.key)
    if row is None:
        row = AppCredential(provider=provider.key)
        session.add(row)
    row.client_id = body.client_id.strip()
    row.client_secret = body.client_secret.strip()
    await session.commit()

    return await list_providers(session)


@router.delete("/{provider_key}/credentials", response_model=ProviderList)
async def forget_credentials(
    provider_key: str, session: AsyncSession = Depends(get_session)
) -> ProviderList:
    """Forget the app registration — and disconnect, since it can no longer refresh."""
    provider = _provider_or_404(provider_key)
    await session.execute(delete(AppCredential).where(AppCredential.provider == provider.key))
    await _disconnect(session, provider)
    await session.commit()
    return await list_providers(session)


# ── the sign-in round trip ──────────────────────────────────────────────────

@router.get("/{provider_key}/start", response_model=StartOut)
async def start(
    provider_key: str, session: AsyncSession = Depends(get_session)
) -> StartOut:
    """Build the provider's sign-in URL for the browser to follow."""
    provider = _provider_or_404(provider_key)
    await reload_credentials(session)

    if not provider.configured:
        raise HTTPException(
            409,
            f"Register your own {provider.label} app first, then paste the client "
            f"id and secret in. It takes about two minutes — the steps are on this page.",
        )

    url = await oauth.begin(session, provider, settings.api_base_url)
    await session.commit()
    return StartOut(authorize_url=url)


@router.get("/{provider_key}/callback", include_in_schema=False)
async def callback(
    provider_key: str,
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Where the provider sends the browser back.

    Always ends in a redirect to the Sources page, carrying either a success or
    a readable reason — a raw JSON error at a URL the person did not type is a
    dead end.
    """
    provider = _provider_or_404(provider_key)
    back = f"{settings.console_url}/sources"

    def failed(message: str) -> RedirectResponse:
        logger.info("connect %s failed: %s", provider.key, message)
        params = _query({"connected": provider.key, "error": message})
        return RedirectResponse(f"{back}?{params}", status_code=303)

    if error:
        return failed(error_description or error)
    if not code or not state:
        return failed("The provider sent us back without an authorisation code.")

    await reload_credentials(session)
    try:
        connection = await oauth.complete(session, provider, code, state)
    except oauth.OAuthError as exc:
        await session.commit()  # the consumed state must still be gone
        return failed(str(exc))
    except Exception as exc:  # noqa: BLE001 — never strand the browser
        logger.exception("connect %s crashed", provider.key)
        await session.rollback()
        return failed(f"Could not finish connecting: {exc}")

    await session.commit()
    label = connection.account_label or provider.label
    params = _query({"connected": provider.key, "account": label})
    return RedirectResponse(f"{back}?{params}", status_code=303)


# ── reading the account, and then noticing the repetition ───────────────────

@router.post("/{provider_key}/sync", response_model=SyncResult)
async def sync(
    provider_key: str, session: AsyncSession = Depends(get_session)
) -> SyncResult:
    """Pull recent activity, store it as events, then re-run detection.

    Detection runs here rather than on a button elsewhere because of what the
    person actually asked for: connect an account and have LOOP notice the
    repetitive parts. Making them press a second button to find that out would
    be making them do the work the tool exists to do.
    """
    provider = _provider_or_404(provider_key)
    await reload_credentials(session)

    connection = await session.get(Connection, provider.key)
    if connection is None:
        raise HTTPException(409, f"{provider.label} is not connected yet.")

    try:
        incoming = await fetch_activity(session, provider, connection)
    except oauth.OAuthError as exc:
        connection.last_error = str(exc)
        await session.commit()
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("sync %s failed", provider.key)
        connection.last_error = f"{type(exc).__name__}: {exc}"
        await session.commit()
        raise HTTPException(502, f"Could not read {provider.label}: {exc}") from exc

    # Re-importing the same window must not double-count the same work, or the
    # hours-per-year figures inflate every time the person presses Sync.
    existing = await session.execute(
        select(Event.object_id, Event.app, Event.action).where(
            Event.source_id == _source_id(provider.key)
        )
    )
    seen = {(row.app, row.action, row.object_id) for row in existing}

    known_apps: set[str] = set()
    added = 0
    latest = as_utc(connection.last_sync_at) if connection.last_sync_at else None

    for event in incoming:
        key = (event.app, event.action, event.object_id)
        if key in seen:
            continue
        seen.add(key)

        if event.app not in known_apps:
            known_apps.add(event.app)
            await ensure_app_registered(session, event.app)

        session.add(
            Event(
                id=new_id("evt"),
                user_id=event.user_id,
                team=event.team,
                timestamp=event.timestamp,
                app=event.app,
                action=event.action,
                object_type=event.object_type,
                object_id=event.object_id,
                duration_ms=event.duration_ms,
                payload=event.payload,
                session_id=event.session_id,
                source=event.source,
                source_id=_source_id(provider.key),
            )
        )
        added += 1
        if latest is None or event.timestamp > latest:
            latest = event.timestamp

    connection.events_imported = (connection.events_imported or 0) + added
    connection.last_sync_at = latest
    connection.last_error = None
    await session.flush()

    clusters = await run_detection(session)
    await session.commit()

    total = int((await session.execute(select(func.count(Event.id)))).scalar() or 0)

    if added == 0:
        message = f"Nothing new in {provider.label} since the last sync."
    elif clusters:
        message = (
            f"Read {added} new {'thing' if added == 1 else 'things'} you did in "
            f"{provider.label}. LOOP now sees {len(clusters)} "
            f"{'pattern' if len(clusters) == 1 else 'patterns'} worth a look."
        )
    else:
        message = (
            f"Read {added} new {'thing' if added == 1 else 'things'} from "
            f"{provider.label}. Not enough repetition yet to call anything a "
            "pattern — connect another account or come back in a few days."
        )

    return SyncResult(
        provider=provider.key,
        events_imported=added,
        total_events=total,
        clusters_found=len(clusters),
        message=message,
    )


# ── taking it back ──────────────────────────────────────────────────────────

async def _disconnect(session: AsyncSession, provider: OAuthProvider) -> int:
    """Delete the tokens and everything they produced. Returns events removed."""
    removed = await session.execute(
        delete(Event).where(Event.source_id == _source_id(provider.key))
    )
    await session.execute(delete(Connection).where(Connection.provider == provider.key))
    return int(removed.rowcount or 0)


@router.delete("/{provider_key}", response_model=SyncResult)
async def disconnect(
    provider_key: str, session: AsyncSession = Depends(get_session)
) -> SyncResult:
    """Disconnect an account and delete every event it contributed.

    Deliberately destructive. A person who disconnects an account has withdrawn
    consent, and leaving the events behind would mean LOOP kept a record of
    their inbox after being told to stop reading it. Detection is re-run so the
    findings reflect only what remains.
    """
    provider = _provider_or_404(provider_key)
    removed = await _disconnect(session, provider)
    await session.flush()

    clusters = await run_detection(session)
    await session.commit()

    total = int((await session.execute(select(func.count(Event.id)))).scalar() or 0)
    remaining = int((await session.execute(select(func.count(Cluster.id)))).scalar() or 0)

    return SyncResult(
        provider=provider.key,
        events_imported=-removed,
        total_events=total,
        clusters_found=len(clusters) or remaining,
        message=(
            f"Disconnected {provider.label} and deleted the {removed} "
            f"{'event' if removed == 1 else 'events'} it contributed."
        ),
    )
