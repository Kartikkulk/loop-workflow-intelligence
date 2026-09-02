"""Generic trigger → F5 REPLAY tests. No Gmail/Sales hardcoding, no live Ollama."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.automation import Automation, TrustLevel
from app.models.cluster import Cluster
from app.models.execution import ExecutionMode
from app.schemas.agent import (
    AgentAnalysis,
    CatalogEvidence,
    CoreStep,
    OptionalStep,
    ProposedWorkflow,
)
from app.schemas.atlas import ActivityAtlas
from app.services.promotion import persist_validated_proposal
from app.services.trigger import (
    TriggerEvent,
    automation_trigger_matches,
    find_matching_automations,
    trigger_event,
)
from app.services.validator import validate_agent_analysis

FIXTURE = Path(__file__).parent / "fixtures" / "activity_atlas_generic.json"

A = "app_a:read:item"
B = "app_b:update:item"
C = "app_c:send:item"
X = "app_x:search:item"


def load_fixture() -> ActivityAtlas:
    return ActivityAtlas.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _agent_proposal() -> ProposedWorkflow:
    return ProposedWorkflow(
        proposal_id="proposal_test",
        name="item to item",
        supporting_signature_ids=["sig_core", "sig_optional"],
        supporting_motif_ids=["motif_core"],
        core_steps=[
            CoreStep(token=A, reason="observed"),
            CoreStep(token=B, reason="observed"),
            CoreStep(token=C, reason="observed"),
        ],
        optional_steps=[OptionalStep(token=X, frequency=0.33)],
        confidence=0.72,
        evidence=CatalogEvidence(
            supporting_instances=999,
            total_occurrences=999,
            distinct_users=999,
        ),
    )


@pytest_asyncio.fixture
async def db_session():
    engine_ = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine_.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine_, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine_.dispose()


@pytest.fixture
def force_heuristic_flow(monkeypatch):
    async def _structured(*, prompt, tool, fallback, max_tokens=2048):
        return fallback()

    monkeypatch.setattr("app.services.generator.llm.structured", _structured)


async def _persist_fixture_automation(session, force_heuristic_flow):
    atlas = load_fixture()
    analysis = AgentAnalysis(
        status="ok",
        generated_by="llm",
        proposed_workflows=[_agent_proposal()],
    )
    validation = validate_agent_analysis(atlas, analysis)
    assert len(validation.validated) == 1
    return await persist_validated_proposal(session, atlas, validation.validated[0])


def _matching_event_for(automation: Automation) -> TriggerEvent:
    trig = dict(automation.trigger or {})
    filt = dict(trig.get("filter") or {})
    return TriggerEvent(
        source="app_a",
        event_type=str(trig.get("type") or "manual"),
        object_type=filt.get("object_type"),
        metadata={},
        payload={"title": "demo", "status_flag": "open"},
    )


def test_matcher_accepts_matching_type_and_object():
    trigger = {"type": "manual", "filter": {"object_type": "item"}}
    event = TriggerEvent(source="app_a", event_type="manual", object_type="item")
    assert automation_trigger_matches(trigger, event)


def test_matcher_rejects_unrelated_event():
    trigger = {"type": "manual", "filter": {"object_type": "item"}}
    event = TriggerEvent(source="calendar", event_type="new_event", object_type="event")
    assert not automation_trigger_matches(trigger, event)


@pytest.mark.asyncio
async def test_matching_event_finds_persisted_automation(db_session, force_heuristic_flow):
    persisted = await _persist_fixture_automation(db_session, force_heuristic_flow)
    event = _matching_event_for(persisted.automation)
    matches = await find_matching_automations(db_session, event)
    assert len(matches) == 1
    assert matches[0].id == persisted.automation.id


@pytest.mark.asyncio
async def test_non_matching_event_executes_nothing(db_session, force_heuristic_flow, monkeypatch):
    await _persist_fixture_automation(db_session, force_heuristic_flow)
    called = {"n": 0}

    async def _boom(**kwargs):
        called["n"] += 1
        raise AssertionError("engine must not run")

    monkeypatch.setattr("app.services.trigger.engine.run", _boom)
    result = await trigger_event(
        db_session,
        TriggerEvent(source="calendar", event_type="new_event", object_type="event"),
    )
    assert result.matched is False
    assert result.execution is None
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_matching_event_calls_existing_f5(db_session, force_heuristic_flow, monkeypatch):
    persisted = await _persist_fixture_automation(db_session, force_heuristic_flow)
    seen: dict = {}

    from app.services.engine import engine as real_engine

    real_run = real_engine.run

    async def _wrap(**kwargs):
        seen.update(kwargs)
        return await real_run(**kwargs)

    monkeypatch.setattr("app.services.trigger.engine.run", _wrap)
    event = _matching_event_for(persisted.automation)
    result = await trigger_event(db_session, event)
    assert result.matched is True
    assert seen["mode"] == ExecutionMode.REPLAY
    assert seen["steps"] == list(persisted.automation.steps or [])
    assert seen["guards"] == dict(persisted.automation.guards or {})
    assert result.execution is not None
    assert result.execution_mode == ExecutionMode.REPLAY.value


@pytest.mark.asyncio
async def test_f5_receives_persisted_steps_and_guards(db_session, force_heuristic_flow):
    persisted = await _persist_fixture_automation(db_session, force_heuristic_flow)
    result = await trigger_event(db_session, _matching_event_for(persisted.automation))
    assert result.matched
    assert result.step_count == len(persisted.automation.steps or [])
    assert result.trigger == dict(persisted.automation.trigger or {})
    assert result.execution is not None
    assert len(result.execution.step_results) >= 1


@pytest.mark.asyncio
async def test_observe_automation_is_not_executed(db_session, force_heuristic_flow, monkeypatch):
    persisted = await _persist_fixture_automation(db_session, force_heuristic_flow)
    auto = await db_session.get(Automation, persisted.automation.id)
    auto.trust_level = TrustLevel.OBSERVE
    await db_session.flush()

    called = {"n": 0}

    async def _boom(**kwargs):
        called["n"] += 1
        raise AssertionError("OBSERVE must not execute")

    monkeypatch.setattr("app.services.trigger.engine.run", _boom)
    result = await trigger_event(db_session, _matching_event_for(auto))
    assert result.matched is False
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_multiple_matches_pick_lowest_id(db_session, force_heuristic_flow):
    persisted = await _persist_fixture_automation(db_session, force_heuristic_flow)
    first = persisted.automation
    twin = Automation(
        id="auto_000000000000",
        cluster_id=first.cluster_id,
        name="twin",
        description="",
        trigger=dict(first.trigger or {}),
        steps=list(first.steps or []),
        guards=dict(first.guards or {}),
        rules=[],
        trust_level=TrustLevel.SUGGEST,
        generated_by="heuristic",
        trust_history=[],
    )
    db_session.add(twin)
    await db_session.flush()

    result = await trigger_event(db_session, _matching_event_for(first))
    assert result.matched
    assert result.automation_id == "auto_000000000000"
    assert result.candidates_considered == 2


@pytest.mark.asyncio
async def test_end_to_end_trigger_replay(db_session, force_heuristic_flow):
    atlas = load_fixture()
    analysis = AgentAnalysis(
        status="ok",
        generated_by="llm",
        proposed_workflows=[_agent_proposal()],
    )
    validation = validate_agent_analysis(atlas, analysis)
    persisted = await persist_validated_proposal(
        db_session, atlas, validation.validated[0]
    )
    assert await db_session.get(Cluster, persisted.cluster.id) is not None

    event = _matching_event_for(persisted.automation)
    result = await trigger_event(db_session, event)
    assert result.matched is True
    assert result.automation_id == persisted.automation.id
    assert result.execution_mode == ExecutionMode.REPLAY.value
    assert result.execution is not None
    assert result.execution.status in {"ok", "needs_approval", "failed"}
    assert len(result.execution.step_results) >= 1
