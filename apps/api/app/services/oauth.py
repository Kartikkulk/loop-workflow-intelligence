"""The OAuth authorisation-code flow, with PKCE.

Standard three-legged OAuth: build an authorise URL, the provider redirects
back with a code, exchange the code for tokens, store them locally.

Two things are not optional and are easy to leave out:

* **State.** Generated per attempt, stored server-side, consumed once. Without
  it, anything that can reach the callback could hand it a code of its own and
  connect *their* account to this LOOP.
* **PKCE.** The verifier never leaves this machine; only its hash goes to the
  provider. An intercepted authorisation code is then useless on its own.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection, OAuthState
from app.services.normaliser import as_utc
from app.services.oauth_providers import OAuthProvider, redirect_uri

logger = logging.getLogger("loop.oauth")

#: A pending authorisation older than this is abandoned, not resumed.
STATE_TTL = timedelta(minutes=10)

#: Refresh a token this long before it actually expires.
REFRESH_MARGIN = timedelta(minutes=5)


class OAuthError(RuntimeError):
    """Raised when a provider rejects us, with a message safe to show a user."""


def _pkce_pair() -> tuple[str, str]:
    """Return (verifier, challenge) for PKCE S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")[:128]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


async def begin(
    session: AsyncSession, provider: OAuthProvider, base_url: str
) -> str:
    """Create a pending authorisation and return the URL to send the user to."""
    if not provider.configured:
        raise OAuthError(
            f"{provider.label} is not set up yet. Register an OAuth app and put "
            f"{provider.client_id_env} and {provider.client_secret_env} in .env."
        )

    # Clear anything stale so an abandoned attempt cannot be resumed later.
    cutoff = datetime.now(UTC) - STATE_TTL
    await session.execute(delete(OAuthState).where(OAuthState.created_at < cutoff))

    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()
    callback = redirect_uri(provider.key, base_url)

    session.add(
        OAuthState(
            state=state,
            provider=provider.key,
            code_verifier=verifier,
            redirect_uri=callback,
        )
    )
    await session.flush()

    params = {
        "client_id": provider.client_id,
        "redirect_uri": callback,
        "response_type": "code",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **provider.extra_authorize_params,
    }
    # Slack puts personal scopes on user_scope; a bot scope would be the wrong
    # thing entirely for a personal tool.
    if provider.key == "slack":
        params["user_scope"] = " ".join(provider.scopes)
    else:
        params["scope"] = " ".join(provider.scopes)

    return f"{provider.authorize_url}?{httpx.QueryParams(params)}"


async def complete(
    session: AsyncSession, provider: OAuthProvider, code: str, state: str
) -> Connection:
    """Consume the pending authorisation and exchange the code for tokens."""
    pending = await session.get(OAuthState, state)
    if pending is None or pending.provider != provider.key:
        raise OAuthError(
            "This sign-in link is not one we started, or it has already been used. "
            "Press Connect again."
        )
    if pending.created_at and datetime.now(UTC) - as_utc(pending.created_at) > STATE_TTL:
        await session.delete(pending)
        raise OAuthError("That sign-in took too long and expired. Press Connect again.")

    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": pending.redirect_uri,
        "client_id": provider.client_id,
        "client_secret": provider.client_secret,
        "code_verifier": pending.code_verifier,
    }

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            provider.token_url,
            data=payload,
            headers={"Accept": "application/json"},
        )

    # Single-use: gone whether the exchange worked or not.
    await session.delete(pending)

    if response.status_code >= 400:
        logger.error("token exchange failed for %s: %s", provider.key, response.text[:400])
        raise OAuthError(
            f"{provider.label} refused the sign-in. Check that the redirect URI in your "
            f"OAuth app exactly matches {pending.redirect_uri}."
        )

    body = response.json()
    # Slack nests the personal token under authed_user rather than at the top.
    if provider.key == "slack":
        body = {**body, **(body.get("authed_user") or {})}

    access = body.get("access_token")
    if not access:
        raise OAuthError(f"{provider.label} did not return an access token.")

    expires_in = body.get("expires_in")
    expires_at = (
        datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in else None
    )

    connection = await session.get(Connection, provider.key)
    if connection is None:
        connection = Connection(provider=provider.key, access_token=access)
        session.add(connection)

    connection.access_token = access
    # Providers omit refresh_token on re-consent; keep the one we have.
    if body.get("refresh_token"):
        connection.refresh_token = body["refresh_token"]
    connection.expires_at = expires_at
    connection.scopes = str(body.get("scope", "")).split() or provider.scopes
    connection.last_error = None
    connection.extra = {
        k: v
        for k, v in body.items()
        if k in ("token_type", "cloud_id", "team", "bot_user_id") and v
    }

    await session.flush()
    if provider.key == "atlassian":
        await resolve_atlassian_site(session, connection)
    await _label_account(session, provider, connection)
    return connection


async def resolve_atlassian_site(session: AsyncSession, connection: Connection) -> None:
    """Record which Jira site this token can reach.

    Atlassian is the one provider whose token says nothing about where to send
    a request. One token may span several sites, so the cloud id lives behind
    `accessible-resources` and has to be fetched separately — the token
    response has no `cloud_id` to read, and never did. Skipping this step left
    every Jira sync reporting that Jira "did not report a site" on a connection
    that had in fact authorised perfectly well, which reconnecting could not
    fix because reconnecting was never the missing part.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                "https://api.atlassian.com/oauth/token/accessible-resources",
                headers={"Authorization": f"Bearer {connection.access_token}"},
            )
        response.raise_for_status()
        resources = response.json() or []
    except Exception as exc:  # noqa: BLE001 — recorded for the UI, not raised
        logger.info("could not list atlassian sites: %s", exc)
        connection.last_error = (
            "Connected, but LOOP could not ask Atlassian which Jira site to read. "
            "Press Sync to try again."
        )
        await session.flush()
        return

    if not resources:
        connection.last_error = (
            "Connected, but this Atlassian account has no Jira site granted to the "
            "integration. Open the site as an admin and install the app, or pick an "
            "account that already has Jira."
        )
        await session.flush()
        return

    # A token can span several sites; prefer one that actually granted Jira.
    chosen = next(
        (r for r in resources if any("jira" in s for s in (r.get("scopes") or []))),
        resources[0],
    )
    connection.extra = {
        **(connection.extra or {}),
        "cloud_id": str(chosen.get("id") or ""),
        "site_url": str(chosen.get("url") or ""),
    }
    connection.last_error = None
    await session.flush()


async def _label_account(
    session: AsyncSession, provider: OAuthProvider, connection: Connection
) -> None:
    """Ask the provider who this is, so the UI can show which account is linked."""
    endpoints = {
        "google": ("https://www.googleapis.com/oauth2/v2/userinfo", "email"),
        "microsoft": ("https://graph.microsoft.com/v1.0/me", "userPrincipalName"),
        "atlassian": ("https://api.atlassian.com/me", "email"),
        "slack": ("https://slack.com/api/auth.test", "user"),
    }
    target = endpoints.get(provider.key)
    if target is None:
        return
    url, field = target
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {connection.access_token}"}
            )
        if response.is_success:
            connection.account_label = str(response.json().get(field) or "")[:200]
            await session.flush()
    except Exception as exc:  # noqa: BLE001 — a missing label must not fail the connect
        logger.info("could not label %s account: %s", provider.key, exc)


async def valid_token(
    session: AsyncSession, provider: OAuthProvider, connection: Connection
) -> str:
    """Return a usable access token, refreshing it first if it is about to expire."""
    if connection.expires_at is None:
        return connection.access_token
    if datetime.now(UTC) + REFRESH_MARGIN < as_utc(connection.expires_at):
        return connection.access_token
    if not connection.refresh_token:
        raise OAuthError(
            f"Your {provider.label} session expired and there is no refresh token. "
            "Press Connect again."
        )

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            provider.token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": connection.refresh_token,
                "client_id": provider.client_id,
                "client_secret": provider.client_secret,
            },
            headers={"Accept": "application/json"},
        )

    if response.status_code >= 400:
        raise OAuthError(
            f"Could not refresh your {provider.label} session. Press Connect again."
        )

    body = response.json()
    connection.access_token = body["access_token"]
    if body.get("refresh_token"):
        connection.refresh_token = body["refresh_token"]
    if body.get("expires_in"):
        connection.expires_at = datetime.now(UTC) + timedelta(seconds=int(body["expires_in"]))
    await session.flush()
    return connection.access_token


async def connected(session: AsyncSession) -> dict[str, Connection]:
    """Every connected account, keyed by provider."""
    result = await session.execute(select(Connection))
    return {c.provider: c for c in result.scalars().all()}
