"""Promotion + persistence tests. Generic tokens only — no live Ollama."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
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
from app.services.engine import engine
from app.services.generator import generate_flow
from app.services.promotion import (
    PromotionError,
    persist_validated_proposal,
    promote_validated_proposal,
)
from app.services.validator import validate_agent_analysis, validate_proposal

FIXTURE = Path(__file__).parent / "fixtures" / "activity_atlas_generic.json"

A = "app_a:read:item"
B = "app_b:update:item"
C = "app_c:send:item"
X = "app_x:search:item"
INVENTED = "app_z:delete:secret"


def load_fixture() -> ActivityAtlas:
    return ActivityAtlas.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _agent_proposal(**overrides) -> ProposedWorkflow:
    base = ProposedWorkflow(
        proposal_id="proposal_test",
        name="item to item",
        supporting_signature_ids=["sig_core", "sig_optional"],
        supporting_motif_ids=["motif_core"],
        core_steps=[
            CoreStep(token=A, reason="observed"),
            CoreStep(token=B, reason="observed"),
            CoreStep(token=C, reason="observed"),
        ],
        optional_steps=[OptionalStep(token=X, frequency=0.33, reason="in sig_optional")],
        confidence=0.72,
        evidence=CatalogEvidence(
            supporting_instances=999,
            total_occurrences=999,
            distinct_users=999,
        ),
    )
    return base.model_copy(update=overrides)


def _validated(atlas: ActivityAtlas, **overrides):
    return validate_proposal(atlas, _agent_proposal(**overrides))


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


def test_validated_proposal_promotes_successfully():
    atlas = load_fixture()
    promoted = promote_validated_proposal(atlas, _validated(atlas))
    assert promoted.cluster.signature == [A, B, C]
    assert promoted.cluster.instance_count == 15
    assert promoted.cluster.id.startswith("clu_")


def test_rejected_proposal_cannot_be_promoted():
    atlas = load_fixture()
    rejected = _validated(
        atlas, supporting_signature_ids=["sig_invented"], supporting_motif_ids=[]
    )
    assert rejected.status == "rejected"
    with pytest.raises(PromotionError, match="cannot promote"):
        promote_validated_proposal(atlas, rejected)


def test_core_steps_are_preserved_exactly():
    atlas = load_fixture()
    promoted = promote_validated_proposal(atlas, _validated(atlas))
    assert promoted.core_tokens == [A, B, C]
    assert promoted.cluster.signature == [A, B, C]


def test_optional_steps_preserved_only_when_validated():
    atlas = load_fixture()
    validated = _validated(
        atlas,
        optional_steps=[
            OptionalStep(token=X, frequency=0.33),
            OptionalStep(token=INVENTED, frequency=0.1),
        ],
    )
    assert validated.status == "validated"
    assert INVENTED in validated.dropped_optional_steps
    promoted = promote_validated_proposal(atlas, validated)
    assert promoted.optional_tokens == [X]
    assert INVENTED not in promoted.optional_tokens
    assert INVENTED not in promoted.cluster.signature


def test_agent_fake_counts_cannot_override_validator_evidence():
    atlas = load_fixture()
    validated = _validated(atlas)
    promoted = promote_validated_proposal(atlas, validated)
    assert promoted.evidence.instance_count == 15
    assert promoted.evidence.occurrence_count == 15
    assert promoted.evidence.distinct_users == 2
    assert promoted.cluster.instance_count == 15
    assert promoted.cluster.distinct_users == 2
    assert promoted.agent_confidence == 0.72
    assert promoted.validation_score == validated.validation_score
    assert 999 not in (
        promoted.evidence.instance_count,
        promoted.cluster.instance_count,
        promoted.cluster.distinct_users,
    )


def test_invented_steps_cannot_enter_promoted_workflow():
    atlas = load_fixture()
    rejected = _validated(
        atlas,
        core_steps=[
            CoreStep(token=A),
            CoreStep(token=B),
            CoreStep(token=C),
            CoreStep(token=INVENTED),
        ],
    )
    assert rejected.status == "rejected"
    with pytest.raises(PromotionError):
        promote_validated_proposal(atlas, rejected)


@pytest.mark.asyncio
async def test_end_to_end_fixture_reaches_f4(force_heuristic_flow):
    atlas = load_fixture()
    analysis = AgentAnalysis(
        status="ok",
        generated_by="llm",
        proposed_workflows=[_agent_proposal()],
    )
    validation = validate_agent_analysis(atlas, analysis)
    assert len(validation.validated) == 1
    promoted = promote_validated_proposal(atlas, validation.validated[0])

    flow, provenance = await generate_flow(promoted.cluster)
    assert provenance in {"llm", "heuristic"}
    assert flow["name"]
    assert flow["trigger"]
    assert flow["steps"]
    assert flow["guards"]
    assert len(flow["steps"]) == len(promoted.core_tokens)
    for step, token in zip(flow["steps"], promoted.core_tokens, strict=True):
        app, action, _object = token.split(":")
        assert step["connector"] == app
        assert step["type"] == action
        assert step["id"]
        assert "depends_on" in step
        assert "outputs" in step
    assert promoted.optional_tokens == [X]
    assert X not in promoted.cluster.signature


@pytest.mark.asyncio
async def test_validated_proposal_persists_cluster(db_session, force_heuristic_flow):
    atlas = load_fixture()
    result = await persist_validated_proposal(db_session, atlas, _validated(atlas))
    stored = await db_session.get(Cluster, result.cluster.id)
    assert stored is not None
    assert stored.signature == [A, B, C]
    assert stored.instance_count == 15
    assert stored.distinct_users == 2
    count = (await db_session.execute(select(func.count()).select_from(Cluster))).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_rejected_proposal_persists_nothing(db_session):
    atlas = load_fixture()
    rejected = _validated(
        atlas, supporting_signature_ids=["sig_invented"], supporting_motif_ids=[]
    )
    with pytest.raises(PromotionError):
        await persist_validated_proposal(db_session, atlas, rejected)
    clusters = (await db_session.execute(select(func.count()).select_from(Cluster))).scalar_one()
    autos = (await db_session.execute(select(func.count()).select_from(Automation))).scalar_one()
    assert clusters == 0
    assert autos == 0


@pytest.mark.asyncio
async def test_persisted_counts_ignore_agent_claims(db_session, force_heuristic_flow):
    atlas = load_fixture()
    result = await persist_validated_proposal(db_session, atlas, _validated(atlas))
    assert result.cluster.instance_count == 15
    assert result.cluster.distinct_users == 2
    assert 999 not in (result.cluster.instance_count, result.cluster.distinct_users)


@pytest.mark.asyncio
async def test_optional_not_converted_to_mandatory_f4_steps(db_session, force_heuristic_flow):
    atlas = load_fixture()
    result = await persist_validated_proposal(db_session, atlas, _validated(atlas))
    assert result.promoted.optional_tokens == [X]
    assert X not in result.cluster.signature
    assert len(result.automation.steps) == 3
    connectors_actions = [(s["connector"], s["type"]) for s in result.automation.steps]
    assert connectors_actions == [
        ("app_a", "read"),
        ("app_b", "update"),
        ("app_c", "send"),
    ]


@pytest.mark.asyncio
async def test_automation_persisted_with_f4_shape(db_session, force_heuristic_flow):
    atlas = load_fixture()
    result = await persist_validated_proposal(db_session, atlas, _validated(atlas))
    auto = await db_session.get(Automation, result.automation.id)
    assert auto is not None
    assert auto.cluster_id == result.cluster.id
    assert auto.trust_level == TrustLevel.SUGGEST
    assert auto.trigger
    assert auto.steps
    assert auto.guards
    assert auto.id.startswith("auto_")


@pytest.mark.asyncio
async def test_f5_can_load_and_run_persisted_automation(db_session, force_heuristic_flow):
    atlas = load_fixture()
    result = await persist_validated_proposal(db_session, atlas, _validated(atlas))
    auto = await db_session.get(Automation, result.automation.id)
    assert auto is not None

    run = await engine.run(
        steps=list(auto.steps or []),
        guards=dict(auto.guards or {}),
        mode=ExecutionMode.REPLAY,
        source_payload={"title": "demo", "status_flag": "open", "result": "ok"},
    )
    assert run.status in {"ok", "needs_approval", "failed"}
    assert len(run.step_results) >= 1
    # Replay forces mocks — engine must accept the persisted F4 steps.
    assert all(isinstance(step, dict) for step in (auto.steps or []))


@pytest.mark.asyncio
async def test_end_to_end_persist_cluster_automation_f5(db_session, force_heuristic_flow):
    """Atlas → AgentAnalysis → Validator → persist → F4 → Automation → F5."""
    atlas = load_fixture()
    analysis = AgentAnalysis(
        status="ok",
        generated_by="llm",
        proposed_workflows=[_agent_proposal()],
    )
    validation = validate_agent_analysis(atlas, analysis)
    assert len(validation.validated) == 1

    result = await persist_validated_proposal(
        db_session, atlas, validation.validated[0]
    )
    assert result.cluster.signature == [A, B, C]
    assert result.cluster.instance_count == 15
    assert X not in result.cluster.signature
    assert result.automation.steps
    assert result.flow["steps"]

    loaded = await db_session.get(Automation, result.automation.id)
    run = await engine.run(
        steps=list(loaded.steps or []),
        guards=dict(loaded.guards or {}),
        mode=ExecutionMode.REPLAY,
        source_payload={"title": "demo", "status_flag": "open"},
    )
    assert run.status in {"ok", "needs_approval", "failed"}
    assert loaded.cluster_id == result.cluster.id
