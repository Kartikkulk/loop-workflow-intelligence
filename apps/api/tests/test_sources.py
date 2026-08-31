"""Source onboarding, collector ingest, and the privacy guarantees.

The privacy tests are not decoration. A collector that leaks a field value is
not a product that gets deployed twice, so the guarantees are asserted rather
than described.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.services.web_activity import (
    RawSignal,
    canonical_app_for_host,
    infer_action,
    interpret,
    sanitise_url,
)


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///./test_sources.db")
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
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()
    import os

    if os.path.exists("./test_sources.db"):
        os.remove("./test_sources.db")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


async def _connect(client, **overrides) -> tuple[str, str]:
    body = {
        "kind": "browser_extension",
        "label": "Asha — Chrome",
        "user_id": "u_asha",
        "team": "accounts_payable",
        "consent": True,
        "denylist": ["bank.example.com"],
    }
    body.update(overrides)
    response = await client.post("/api/v1/sources", json=body)
    assert response.status_code == 201, response.text
    data = response.json()
    return data["source"]["id"], data["token"]


def _signal(**over) -> dict:
    base = {
        "interaction": "pageview",
        "url": "https://mail.google.com/mail/u/0/#inbox/X",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    base.update(over)
    return base


# ── url sanitisation ───────────────────────────────────────────────────────

def test_sanitise_url_strips_query_values_but_keeps_keys():
    """A GET form puts every field into the URL. This is the leak that matters."""
    out = sanitise_url("https://x.com/f?vendor=Kaveri+Logistics&secret=hunter2")
    assert "Kaveri" not in out
    assert "hunter2" not in out
    assert "vendor=" in out and "secret=" in out


def test_sanitise_url_keeps_a_value_free_fragment_route():
    """Gmail identifies the open message in the fragment; it is worth keeping."""
    assert sanitise_url("https://mail.google.com/mail/u/0/#inbox/FMfcgz") == (
        "https://mail.google.com/mail/u/0/#inbox/FMfcgz"
    )


def test_sanitise_url_strips_fragment_parameter_values():
    out = sanitise_url("https://x.com/a#tab=details&note=please+pay")
    assert "please" not in out
    assert "note=" in out


def test_sanitise_url_redacts_free_text_and_emails_in_the_path():
    out = sanitise_url("https://crm.com/contacts/search/john.doe@example.com")
    assert "john.doe" not in out
    assert out.endswith("/_")


# ── app and action inference ───────────────────────────────────────────────

@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://mail.google.com/mail/u/0", "gmail"),
        ("https://docs.google.com/spreadsheets/d/x/edit", "sheets"),
        ("https://docs.google.com/document/d/x/edit", "docs"),
        ("https://acme.atlassian.net/browse/FIN-1", "jira"),
        ("https://outlook.office.com/mail", "outlook"),
        ("https://t.lightning.force.com/x", "crm"),
        # Multi-label public suffixes must not name the app after the country.
        ("https://app.acme-erp.co.in/invoices/1", "acme-erp"),
        ("https://portal.northwind.com.au/po/2", "northwind"),
        # An internal tool nobody configured still gets a usable name.
        ("https://finance-tool.internal/ledger", "finance-tool"),
    ],
)
def test_app_mapping(url, expected):
    assert canonical_app_for_host(url) == expected


@pytest.mark.parametrize(
    ("interaction", "label", "expected"),
    [
        ("click", "Send reply", "send"),
        ("click", "Delete row", "delete"),
        ("click", "Save changes", "update"),
        ("click", "Add new invoice", "create"),
        ("click", "Export to CSV", "extract"),
        ("copy", "", "extract"),
        ("paste", "", "create"),
        ("submit", "", "create"),
        ("route_change", "", "navigate"),
        ("pageview", "", "read"),
    ],
)
def test_action_inference(interaction, label, expected):
    assert infer_action(RawSignal(interaction=interaction, label=label)) == expected


def test_interpret_never_includes_a_field_value():
    signal = RawSignal(
        interaction="field_edit",
        url="https://docs.google.com/spreadsheets/d/x/edit",
        field_name="amount",
    )
    result = interpret(signal, allow_values=False)
    assert result.payload["field"] == "amount"
    assert "value" not in result.payload


# ── onboarding ─────────────────────────────────────────────────────────────

async def test_capabilities_are_offered_with_honest_tradeoffs(client):
    body = (await client.get("/api/v1/sources")).json()
    kinds = {c["kind"] for c in body["capabilities"]}
    assert {"describe", "upload", "browser_extension", "api_connector", "desktop_agent"} <= kinds
    for capability in body["capabilities"]:
        # Every tier must state what it cannot see, not only what it can.
        assert capability["sees"], capability["kind"]
        assert capability["blind_to"], capability["kind"]
        assert capability["invasiveness"]
        if not capability["available"]:
            assert capability["unavailable_reason"]


async def test_unavailable_tier_is_refused_rather_than_faked(client):
    response = await client.post(
        "/api/v1/sources",
        json={"kind": "desktop_agent", "label": "agent", "user_id": "u_x", "consent": True},
    )
    assert response.status_code == 409
    assert "cannot be connected" in str(response.json())


async def test_source_without_consent_cannot_ingest(client):
    _, token = await _connect(client, consent=False)
    response = await client.post(
        "/api/v1/collect/events",
        json={"signals": [_signal()]},
        headers={"authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


async def test_unknown_token_is_rejected(client):
    response = await client.post(
        "/api/v1/collect/events",
        json={"signals": [_signal()]},
        headers={"authorization": "Bearer loop_src_nonsense"},
    )
    assert response.status_code == 401


async def test_token_is_not_retrievable_after_registration(client):
    source_id, token = await _connect(client)
    listing = (await client.get("/api/v1/sources")).json()
    serialised = str(listing)
    assert token not in serialised, "the raw token must never be readable again"
    assert source_id in serialised


# ── collection ─────────────────────────────────────────────────────────────

async def test_collector_produces_canonical_events(client):
    _, token = await _connect(client)
    headers = {"authorization": f"Bearer {token}"}
    response = await client.post(
        "/api/v1/collect/events",
        json={
            "signals": [
                _signal(url="https://mail.google.com/mail/u/0/#inbox/A", duration_ms=42000),
                _signal(
                    interaction="click",
                    url="https://mail.google.com/mail/u/0/#inbox/A",
                    label="Send reply",
                ),
            ]
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["accepted"] == 2

    events = (await client.get("/api/v1/ingest/events?limit=10")).json()["items"]
    tokens = {f"{e['app']}:{e['action']}" for e in events}
    assert "gmail:read" in tokens
    assert "gmail:send" in tokens


async def test_denylist_is_enforced_server_side(client):
    """An out-of-date collector must not be able to report an excluded domain."""
    _, token = await _connect(client)
    response = await client.post(
        "/api/v1/collect/events",
        json={
            "signals": [
                _signal(url="https://bank.example.com/accounts"),
                _signal(url="https://mail.google.com/mail/u/0"),
            ]
        },
        headers={"authorization": f"Bearer {token}"},
    )
    body = response.json()
    assert body["accepted"] == 1
    assert body["rejected"] == 1
    assert "denylist" in body["reasons"][0]


async def test_unknown_app_self_registers(client):
    """Onboarding an unanticipated internal tool is done by using it."""
    _, token = await _connect(client)
    response = await client.post(
        "/api/v1/collect/events",
        json={"signals": [_signal(url="https://finance-tool.internal/ledger/9")]},
        headers={"authorization": f"Bearer {token}"},
    )
    assert "finance-tool" in response.json()["apps_discovered"]


async def test_copy_paste_across_apps_is_linked_as_a_transfer(client):
    """The signature the brief names: moving information between systems."""
    _, token = await _connect(client)
    shared = digest("92,400.00")
    start = datetime.now(UTC) - timedelta(minutes=25)

    response = await client.post(
        "/api/v1/collect/events",
        json={
            "signals": [
                _signal(
                    interaction="copy",
                    url="https://mail.google.com/mail/u/0/#inbox/A",
                    payload_digest=shared,
                    occurred_at=start.isoformat(),
                ),
                _signal(
                    interaction="paste",
                    url="https://docs.google.com/spreadsheets/d/x/edit",
                    payload_digest=shared,
                    field_name="amount",
                    occurred_at=(start + timedelta(seconds=40)).isoformat(),
                ),
            ]
        },
        headers={"authorization": f"Bearer {token}"},
    )
    assert response.json()["transfers_linked"] == 1

    events = (await client.get("/api/v1/ingest/events?limit=10")).json()["items"]
    paste = next(e for e in events if e["action"] == "create")
    copy = next(e for e in events if e["action"] == "extract")
    assert paste["payload"]["transferred_from"] == "gmail"
    assert copy["payload"]["transferred_to"] == "sheets"
    # The transferred value itself must never be stored.
    assert "92,400.00" not in str(events)


async def test_transfer_within_one_app_is_not_a_transfer(client):
    _, token = await _connect(client)
    shared = digest("same-app")
    response = await client.post(
        "/api/v1/collect/events",
        json={
            "signals": [
                _signal(
                    interaction="copy", url="https://mail.google.com/a", payload_digest=shared
                ),
                _signal(
                    interaction="paste", url="https://mail.google.com/b", payload_digest=shared
                ),
            ]
        },
        headers={"authorization": f"Bearer {token}"},
    )
    assert response.json()["transfers_linked"] == 0


async def test_paused_source_is_told_rather_than_silently_dropped(client):
    source_id, token = await _connect(client)
    await client.patch(f"/api/v1/sources/{source_id}", json={"status": "paused"})
    response = await client.post(
        "/api/v1/collect/events",
        json={"signals": [_signal()]},
        headers={"authorization": f"Bearer {token}"},
    )
    assert response.status_code == 423


async def test_collector_config_reflects_console_changes(client):
    """The console governs the collector, so a pause needs no local action."""
    source_id, token = await _connect(client)
    headers = {"authorization": f"Bearer {token}"}

    before = (await client.get("/api/v1/collect/config", headers=headers)).json()
    assert before["status"] == "connected"
    assert before["capture_field_values"] is False
    assert before["capture_page_titles"] is False

    await client.patch(
        f"/api/v1/sources/{source_id}",
        json={"status": "paused", "denylist": ["newly-excluded.com"]},
    )
    after = (await client.get("/api/v1/collect/config", headers=headers)).json()
    assert after["status"] == "paused"
    assert after["denylist"] == ["newly-excluded.com"]


async def test_values_scope_is_opt_in(client):
    source_id, token = await _connect(client, capture_scope="with_values")
    config = (await client.get(
        "/api/v1/collect/config", headers={"authorization": f"Bearer {token}"}
    )).json()
    assert config["capture_field_values"] is True
    assert config["capture_page_titles"] is True
    assert source_id


async def test_revoking_deletes_the_events_that_source_reported(client):
    """Consent that cannot be fully withdrawn is not consent."""
    source_id, token = await _connect(client)
    await client.post(
        "/api/v1/collect/events",
        json={"signals": [_signal(), _signal(interaction="click", label="Save")]},
        headers={"authorization": f"Bearer {token}"},
    )
    before = (await client.get("/api/v1/ingest/events?limit=50")).json()["total"]
    assert before >= 2

    response = await client.delete(f"/api/v1/sources/{source_id}")
    assert response.status_code == 200
    assert response.json()["events_deleted"] >= 2

    after = (await client.get("/api/v1/ingest/events?limit=50")).json()["total"]
    assert after == before - response.json()["events_deleted"]

    # The token must stop working immediately.
    replay = await client.post(
        "/api/v1/collect/events",
        json={"signals": [_signal()]},
        headers={"authorization": f"Bearer {token}"},
    )
    assert replay.status_code == 401


async def test_coverage_reflects_the_best_connected_tier(client):
    empty = (await client.get("/api/v1/sources")).json()["coverage"]
    assert empty["estimated_coverage"] == 0.0

    await _connect(client)
    with_browser = (await client.get("/api/v1/sources")).json()["coverage"]
    assert with_browser["estimated_coverage"] == pytest.approx(0.70)
    assert with_browser["connected_sources"] == 1


async def test_detection_runs_over_collected_events(client):
    """Collected activity must feed the same detection pipeline as everything else."""
    _, token = await _connect(client)
    headers = {"authorization": f"Bearer {token}"}
    start = datetime.now(UTC) - timedelta(days=30)

    # The same four-step workflow, repeated enough to clear the support floor.
    for instance in range(20):
        base = start + timedelta(days=instance, hours=10)
        await client.post(
            "/api/v1/collect/events",
            json={
                "session_id": f"ses_{instance}",
                "signals": [
                    _signal(
                        url="https://mail.google.com/mail/u/0/#inbox/I",
                        duration_ms=40000,
                        occurred_at=base.isoformat(),
                    ),
                    _signal(
                        interaction="paste",
                        url="https://docs.google.com/spreadsheets/d/L/edit",
                        field_name="amount",
                        duration_ms=30000,
                        occurred_at=(base + timedelta(seconds=60)).isoformat(),
                    ),
                    _signal(
                        interaction="field_edit",
                        url="https://docs.google.com/spreadsheets/d/L/edit",
                        field_name="vendor",
                        duration_ms=25000,
                        occurred_at=(base + timedelta(seconds=100)).isoformat(),
                    ),
                    _signal(
                        interaction="click",
                        url="https://mail.google.com/mail/u/0/#inbox/I",
                        label="Send reply",
                        duration_ms=20000,
                        occurred_at=(base + timedelta(seconds=140)).isoformat(),
                    ),
                ],
            },
            headers=headers,
        )

    detected = (await client.post("/api/v1/ingest/redetect")).json()
    assert detected["clusters_detected"] >= 1

    clusters = (await client.get("/api/v1/clusters")).json()
    found = clusters["recommended"] + clusters["not_recommended"]
    assert found, "collected browser activity produced no detected workflow"
    signature = found[0]["signature"]
    assert any(token.startswith("gmail") for token in signature)
    assert any(token.startswith("sheets") for token in signature)


# ── screen recording ───────────────────────────────────────────────────────

async def test_recording_is_refused_honestly_without_a_vision_model(client):
    """The one tier with no deterministic fallback says so rather than faking it."""
    listing = (await client.get("/api/v1/sources")).json()
    recording = next(c for c in listing["capabilities"] if c["kind"] == "screen_recording")
    assert recording["available"] is False
    assert "vision model" in recording["unavailable_reason"]

    response = await client.post(
        "/api/v1/ingest/recording",
        json={"user_id": "u_rec", "frames": [{"image_base64": "iVBORw0KGgo" + "A" * 40}]},
    )
    assert response.status_code == 409
    detail = str(response.json())
    assert "vision model" in detail
    # It must point at something that does work rather than dead-ending.
    assert "browser extension" in detail or "describe" in detail
