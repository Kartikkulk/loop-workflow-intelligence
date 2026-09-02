"""Phase 6 API tests: browser observations through approval and replay."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.models.event import Event
from app.schemas.investigation import InvestigationConclusion, InvestigationResult


def _event(
    *,
    event_id: str,
    at: datetime,
    app_name: str,
    action: str,
    object_type: str,
    source: str = "browser_extension",
) -> Event:
    return Event(
        id=event_id,
        user_id="browser_user",
        team="operations",
        timestamp=at,
        app=app_name,
        action=action,
        object_type=object_type,
        duration_ms=1000,
        payload={"field_names": ["subject"]},
        session_id=event_id.split("_")[1],
        source=source,
    )


@pytest_asyncio.fixture
async def candidate_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
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
    start = datetime.now(UTC) - timedelta(hours=1)
    async with maker() as session:
        for run in range(2):
            base = start + timedelta(minutes=run * 20)
            session.add_all(
                [
                    _event(
                        event_id=f"evt_run{run}_1",
                        at=base,
                        app_name="gmail",
                        action="read",
                        object_type="email",
                    ),
                    _event(
                        event_id=f"evt_run{run}_2",
                        at=base + timedelta(seconds=20),
                        app_name="sheets",
                        action="update",
                        object_type="spreadsheet",
                    ),
                    _event(
                        event_id=f"evt_run{run}_3",
                        at=base + timedelta(seconds=40),
                        app_name="gmail",
                        action="send",
                        object_type="email",
                    ),
                ]
            )
        session.add(
            _event(
                event_id="evt_seed_1",
                at=start,
                app_name="erp",
                action="update",
                object_type="invoice",
                source="seed",
            )
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    app.dependency_overrides.clear()
    await engine.dispose()


async def test_browser_candidate_full_lifecycle(
    candidate_client: AsyncClient, monkeypatch
):
    from app.services import candidate_workflows

    async def grounded_investigation(atlas, analysis, *, client=None):
        proposal = analysis.proposed_workflows[0]
        return [
            InvestigationResult(
                status="ok",
                generated_by="llm",
                model_name="test-model",
                candidate_workflow_id=proposal.proposal_id,
                conclusions=[
                    InvestigationConclusion(
                        relationship="same_workflow",
                        confidence=0.9,
                    )
                ],
                final_decision="safe_to_continue",
            )
        ]

    monkeypatch.setattr(
        candidate_workflows,
        "investigate_agent_analysis",
        grounded_investigation,
    )
    monkeypatch.setattr(settings, "llm_provider", "disabled")

    listing = await candidate_client.get("/api/v1/candidates")
    assert listing.status_code == 200
    body = listing.json()
    assert body["source"] == "browser_extension"
    assert body["total"] == 1
    candidate = body["items"][0]
    assert candidate["name"] == "Gmail → Sheets → Gmail"
    assert candidate["signature_tokens"] == [
        "gmail:read:email",
        "sheets:update:spreadsheet",
        "gmail:send:email",
    ]
    assert candidate["occurrence_count"] == 2
    assert candidate["session_count"] == 2
    assert candidate["status"] == "candidate"
    assert "Invoice Email to confirmation" not in str(body)
    workflow_id = candidate["workflow_id"]

    premature = await candidate_client.post(
        f"/api/v1/candidates/{workflow_id}/validate"
    )
    assert premature.status_code == 409

    investigated = await candidate_client.post(
        f"/api/v1/candidates/{workflow_id}/investigate"
    )
    assert investigated.status_code == 200
    assert investigated.json()["candidate"]["status"] == "investigated"
    assert investigated.json()["result"]["final_decision"] == "safe_to_continue"

    validated = await candidate_client.post(
        f"/api/v1/candidates/{workflow_id}/validate"
    )
    assert validated.status_code == 200
    assert validated.json()["candidate"]["status"] == "validated"
    assert len(validated.json()["result"]["validated"]) == 1

    created = await candidate_client.post(
        f"/api/v1/candidates/{workflow_id}/automation"
    )
    assert created.status_code == 200
    automation = created.json()
    assert automation["trust_level"] == "SUGGEST"

    approved = await candidate_client.post(
        f"/api/v1/automations/{automation['automation_id']}/promote",
        json={"force": True},
    )
    assert approved.status_code == 200
    assert approved.json()["ok"] is True
    assert approved.json()["level"] == "SHADOW"

    repeated_create = await candidate_client.post(
        f"/api/v1/candidates/{workflow_id}/automation"
    )
    assert repeated_create.status_code == 200
    assert repeated_create.json()["automation_id"] == automation["automation_id"]
    assert repeated_create.json()["trust_level"] == "SHADOW"

    replay = await candidate_client.post(
        f"/api/v1/automations/{automation['automation_id']}/replay",
        json={"days": 30},
    )
    assert replay.status_code == 200
    assert replay.json()["errored"] == 0
