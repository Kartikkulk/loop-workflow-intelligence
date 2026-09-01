"""Connecting a personal account, end to end.

Three of the properties asserted here are the ones that would actually hurt if
they broke, and none of them are visible by looking at the screen:

  * a client secret must never come back out of the API,
  * an authorisation state must work exactly once,
  * disconnecting must delete the events, not just the token.

Google is stubbed at the HTTP boundary rather than at our own function, so the
real token-exchange and import code runs — including the parts that read the
provider's response shape, which is where these things usually break.
"""

from __future__ import annotations

import os
import urllib.parse as urlparse
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.models.connection import Connection, OAuthState
from app.models.event import Event

DB = "./test_connect.db"

CREDENTIALS = {
    "client_id": "1234567890-loop.apps.googleusercontent.com",
    "client_secret": "GOCSPX-this-must-never-come-back",
}


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(f"sqlite+aiosqlite:///{DB}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.maker = maker  # type: ignore[attr-defined]
        yield c

    app.dependency_overrides.clear()
    from app.services.oauth_providers import refresh_credentials

    refresh_credentials({})
    await engine.dispose()
    if os.path.exists(DB):
        os.remove(DB)


def google_provider(request: httpx.Request) -> httpx.Response:
    """Enough of Google to exercise our side of the conversation."""
    url = str(request.url)

    if url.startswith("https://oauth2.googleapis.com/token"):
        form = dict(urlparse.parse_qsl(request.content.decode()))
        # PKCE is the whole point of the state row; refuse to play along
        # without it, so a regression that drops the verifier fails loudly.
        if not form.get("code_verifier"):
            return httpx.Response(400, json={"error": "missing code_verifier"})
        return httpx.Response(
            200,
            json={
                "access_token": "at-live",
                "refresh_token": "rt-live",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/gmail.metadata",
            },
        )

    if "oauth2/v3/userinfo" in url or "userinfo" in url:
        return httpx.Response(200, json={"email": "asha@example.com"})

    if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/messages?"):
        return httpx.Response(
            200, json={"messages": [{"id": f"m{i}", "threadId": f"t{i}"} for i in range(3)]}
        )

    if "gmail/v1/users/me/messages/" in url:
        message_id = url.split("/messages/")[1].split("?")[0]
        stamp = int((datetime.now(UTC) - timedelta(days=1)).timestamp() * 1000)
        return httpx.Response(
            200,
            json={
                "id": message_id,
                "threadId": f"t{message_id[1:]}",
                "internalDate": str(stamp),
                "labelIds": ["SENT"],
                "payload": {
                    "headers": [
                        {"name": "To", "value": "billing@vendor.example.com"},
                        {"name": "Subject", "value": "Invoice"},
                    ]
                },
            },
        )

    return httpx.Response(404, json={"error": f"unstubbed {url}"})


@pytest.fixture
def stub_google(monkeypatch):
    """Answer every outbound call as Google would, without leaving the process."""
    transport = httpx.MockTransport(google_provider)
    original = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = transport
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)


async def save_credentials(client) -> None:
    response = await client.put("/api/v1/connect/google/credentials", json=CREDENTIALS)
    assert response.status_code == 200


async def authorize(client) -> str:
    """Run the start step and return the state parameter it issued."""
    response = await client.get("/api/v1/connect/google/start")
    assert response.status_code == 200, response.text
    query = urlparse.parse_qs(urlparse.urlsplit(response.json()["authorize_url"]).query)
    return query["state"][0]


# ── what the person sees before they have done anything ─────────────────────

@pytest.mark.asyncio
async def test_providers_are_listed_unconfigured(client):
    body = (await client.get("/api/v1/connect/providers")).json()
    assert body["connected_count"] == 0
    keys = {item["key"] for item in body["items"]}
    assert {"google", "microsoft"} <= keys
    assert all(not item["configured"] for item in body["items"])


@pytest.mark.asyncio
async def test_every_scope_is_read_only(client):
    """A personal tool that asks for write access does not deserve a second look."""
    body = (await client.get("/api/v1/connect/providers")).json()
    for item in body["items"]:
        for scope in item["scopes"]:
            lowered = scope.lower()
            assert not any(
                word in lowered for word in ("write", "send", "modify", "compose", "manage")
            ), f"{item['key']} asks for {scope}, which is not read-only"


@pytest.mark.asyncio
async def test_signing_in_before_setup_explains_itself(client):
    response = await client.get("/api/v1/connect/google/start")
    assert response.status_code == 409
    assert "Register your own Google app" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_provider_is_404(client):
    assert (await client.get("/api/v1/connect/dropbox/start")).status_code == 404


# ── the secret goes in and does not come back ───────────────────────────────

@pytest.mark.asyncio
async def test_secret_is_never_returned(client):
    await save_credentials(client)

    text = (await client.get("/api/v1/connect/providers")).text
    assert CREDENTIALS["client_secret"] not in text
    # `client_secret_env` is only the name of an environment variable; a bare
    # `client_secret` field would be the value itself.
    assert '"client_secret"' not in text

    google = next(
        item
        for item in (await client.get("/api/v1/connect/providers")).json()["items"]
        if item["key"] == "google"
    )
    assert google["configured"] is True
    assert google["has_secret"] is True
    # A hint identifies the app without being the app.
    assert google["client_id_hint"].endswith("…")
    assert google["client_id_hint"] != CREDENTIALS["client_id"]


@pytest.mark.asyncio
async def test_credentials_typed_in_beat_the_environment(client, monkeypatch):
    monkeypatch.setenv("LOOP_GOOGLE_CLIENT_ID", "from-the-environment")
    monkeypatch.setenv("LOOP_GOOGLE_CLIENT_SECRET", "also-from-the-environment")
    await save_credentials(client)

    response = await client.get("/api/v1/connect/google/start")
    query = urlparse.parse_qs(urlparse.urlsplit(response.json()["authorize_url"]).query)
    assert query["client_id"][0] == CREDENTIALS["client_id"]


# ── the sign-in round trip ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_authorize_url_carries_pkce_and_offline_access(client):
    await save_credentials(client)
    response = await client.get("/api/v1/connect/google/start")
    query = urlparse.parse_qs(urlparse.urlsplit(response.json()["authorize_url"]).query)

    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) >= 42
    assert len(query["state"][0]) >= 42
    # Without both of these Google issues no refresh token, and the connection
    # silently dies an hour later.
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]


@pytest.mark.asyncio
async def test_forged_state_is_refused(client):
    await save_credentials(client)
    response = await client.get(
        "/api/v1/connect/google/callback?code=whatever&state=never-issued",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]

    async with client.maker() as session:
        assert (await session.execute(select(Connection))).scalars().first() is None


@pytest.mark.asyncio
async def test_provider_error_lands_back_on_sources(client):
    await save_credentials(client)
    response = await client.get(
        "/api/v1/connect/google/callback?error=access_denied&error_description=You+cancelled",
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert "/sources" in location
    assert "You+cancelled" in location or "You%20cancelled" in location


@pytest.mark.asyncio
async def test_successful_callback_connects_the_account(client, stub_google):
    await save_credentials(client)
    state = await authorize(client)

    response = await client.get(
        f"/api/v1/connect/google/callback?code=good-code&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" not in response.headers["location"]

    async with client.maker() as session:
        connection = await session.get(Connection, "google")
        assert connection is not None
        assert connection.access_token == "at-live"
        assert connection.refresh_token == "rt-live"
        assert connection.account_label == "asha@example.com"
        # Single use: the pending state is gone.
        assert (await session.execute(select(OAuthState))).scalars().first() is None


@pytest.mark.asyncio
async def test_a_state_cannot_be_replayed(client, stub_google):
    """The second use of a code+state pair must fail, even though the first worked."""
    await save_credentials(client)
    state = await authorize(client)

    first = await client.get(
        f"/api/v1/connect/google/callback?code=good-code&state={state}",
        follow_redirects=False,
    )
    assert "error=" not in first.headers["location"]

    second = await client.get(
        f"/api/v1/connect/google/callback?code=good-code&state={state}",
        follow_redirects=False,
    )
    assert "error=" in second.headers["location"]


# ── reading the account ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_before_connecting_is_refused(client):
    await save_credentials(client)
    response = await client.post("/api/v1/connect/google/sync")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_sync_imports_activity_and_runs_detection(client, stub_google):
    await save_credentials(client)
    state = await authorize(client)
    await client.get(
        f"/api/v1/connect/google/callback?code=good-code&state={state}",
        follow_redirects=False,
    )

    result = (await client.post("/api/v1/connect/google/sync")).json()
    assert result["events_imported"] == 3
    assert result["total_events"] == 3
    # Detection having run at all is the point; three emails are not a pattern.
    assert "clusters_found" in result

    async with client.maker() as session:
        events = (await session.execute(select(Event))).scalars().all()
        assert len(events) == 3
        assert {e.app for e in events} == {"gmail"}
        assert all(e.source_id == "conn:google" for e in events)


@pytest.mark.asyncio
async def test_no_message_bodies_are_stored(client, stub_google):
    """The subject line was in the response we stubbed. It must not be in the log."""
    await save_credentials(client)
    state = await authorize(client)
    await client.get(
        f"/api/v1/connect/google/callback?code=good-code&state={state}",
        follow_redirects=False,
    )
    await client.post("/api/v1/connect/google/sync")

    async with client.maker() as session:
        for event in (await session.execute(select(Event))).scalars().all():
            blob = str(event.payload)
            assert "Invoice" not in blob
            assert "billing@" not in blob
            # The counterparty is kept as a domain, which is what makes
            # "the same vendor, every week" visible without a contact list.
            assert event.payload["counterparty"] == "vendor.example.com"


@pytest.mark.asyncio
async def test_syncing_twice_does_not_double_count(client, stub_google):
    await save_credentials(client)
    state = await authorize(client)
    await client.get(
        f"/api/v1/connect/google/callback?code=good-code&state={state}",
        follow_redirects=False,
    )

    first = (await client.post("/api/v1/connect/google/sync")).json()
    second = (await client.post("/api/v1/connect/google/sync")).json()

    assert first["events_imported"] == 3
    assert second["events_imported"] == 0
    assert second["total_events"] == 3
    assert "Nothing new" in second["message"]


# ── taking it back ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disconnecting_deletes_the_events_too(client, stub_google):
    """Withdrawing consent must not leave a copy of the inbox behind."""
    await save_credentials(client)
    state = await authorize(client)
    await client.get(
        f"/api/v1/connect/google/callback?code=good-code&state={state}",
        follow_redirects=False,
    )
    await client.post("/api/v1/connect/google/sync")

    result = (await client.delete("/api/v1/connect/google")).json()
    assert result["events_imported"] == -3
    assert result["total_events"] == 0

    async with client.maker() as session:
        assert await session.get(Connection, "google") is None
        assert (await session.execute(select(Event))).scalars().first() is None


@pytest.mark.asyncio
async def test_forgetting_credentials_also_disconnects(client, stub_google):
    """A connection that can no longer be refreshed must not be shown as live."""
    await save_credentials(client)
    state = await authorize(client)
    await client.get(
        f"/api/v1/connect/google/callback?code=good-code&state={state}",
        follow_redirects=False,
    )

    body = (await client.delete("/api/v1/connect/google/credentials")).json()
    google = next(item for item in body["items"] if item["key"] == "google")
    assert google["configured"] is False
    assert google["connected"] is False
    assert google["has_secret"] is False
