"""Deterministic validator tests. Generic tokens only — no domain packs."""

from __future__ import annotations

from pathlib import Path

from app.schemas.agent import (
    AgentAnalysis,
    CatalogEvidence,
    CoreStep,
    OptionalStep,
    ProposedWorkflow,
)
from app.schemas.atlas import ActivityAtlas, SignatureCatalogEntry
from app.services.validator import validate_agent_analysis, validate_proposal

FIXTURE = Path(__file__).parent / "fixtures" / "activity_atlas_generic.json"

A = "app_a:read:item"
B = "app_b:update:item"
C = "app_c:send:item"
X = "app_x:search:item"
INVENTED = "app_z:delete:secret"


def load_fixture() -> ActivityAtlas:
    return ActivityAtlas.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _proposal(**overrides) -> ProposedWorkflow:
    base = ProposedWorkflow(
        proposal_id="proposal_test",
        name="item to item",
        supporting_signature_ids=["sig_core"],
        supporting_motif_ids=["motif_core"],
        core_steps=[
            CoreStep(token=A, reason="observed"),
            CoreStep(token=B, reason="observed"),
            CoreStep(token=C, reason="observed"),
        ],
        optional_steps=[],
        confidence=0.8,
        evidence=CatalogEvidence(
            supporting_instances=999,
            total_occurrences=999,
            distinct_users=999,
        ),
    )
    return base.model_copy(update=overrides)


def test_valid_proposal_with_signature_evidence():
    atlas = load_fixture()
    analysis = AgentAnalysis(
        status="ok",
        generated_by="llm",
        proposed_workflows=[_proposal()],
    )
    result = validate_agent_analysis(atlas, analysis)
    assert len(result.validated) == 1
    assert result.rejected == []
    row = result.validated[0]
    assert row.status == "validated"
    assert row.validation_score >= 0.7
    assert row.supporting_signature_ids == ["sig_core"]
    assert [s.token for s in row.validated_core_steps] == [A, B, C]
    # Counts come from the atlas, not the Agent's 999 claims.
    assert row.evidence.instance_count == 10
    assert row.evidence.occurrence_count == 10
    assert row.evidence.distinct_users == 2
    assert row.evidence.source == "atlas_catalog"


def test_nonexistent_signature_is_rejected():
    atlas = load_fixture()
    proposal = _proposal(supporting_signature_ids=["sig_invented"], supporting_motif_ids=[])
    result = validate_proposal(atlas, proposal)
    assert result.status == "rejected"
    assert any("unknown supporting_signature_ids" in i for i in result.issues)


def test_invented_core_step_is_rejected():
    atlas = load_fixture()
    proposal = _proposal(
        core_steps=[
            CoreStep(token=A),
            CoreStep(token=B),
            CoreStep(token=C),
            CoreStep(token=INVENTED, reason="made up"),
        ]
    )
    result = validate_proposal(atlas, proposal)
    assert result.status == "rejected"
    assert any("ungrounded core steps" in i for i in result.issues)
    assert INVENTED in " ".join(result.issues)


def test_unsupported_optional_step_is_dropped_but_core_validates():
    atlas = load_fixture()
    proposal = _proposal(
        supporting_signature_ids=["sig_core", "sig_optional"],
        optional_steps=[
            OptionalStep(token=X, frequency=0.33, reason="in sig_optional"),
            OptionalStep(token=INVENTED, frequency=0.1, reason="fake"),
        ],
    )
    result = validate_proposal(atlas, proposal)
    assert result.status == "validated"
    assert [s.token for s in result.validated_optional_steps] == [X]
    assert INVENTED in result.dropped_optional_steps
    assert any("dropped unsupported optional step" in i for i in result.issues)
    # Atlas-derived: 10 + 5 from the two signatures.
    assert result.evidence.instance_count == 15
    assert result.evidence.occurrence_count == 15


def test_no_repetition_evidence_is_rejected():
    atlas = ActivityAtlas(
        signature_catalog=[
            SignatureCatalogEntry(
                signature_id="sig_once",
                tokens=[A, B, C],
                occurrence_count=1,
                distinct_users=1,
            )
        ],
        motif_catalog=[],
        candidate_groups=[],
    )
    proposal = ProposedWorkflow(
        proposal_id="proposal_once",
        name="one-off",
        supporting_signature_ids=["sig_once"],
        core_steps=[CoreStep(token=A), CoreStep(token=B), CoreStep(token=C)],
        confidence=0.9,
    )
    result = validate_proposal(atlas, proposal)
    assert result.status == "rejected"
    assert any("insufficient repetition" in i for i in result.issues)


def test_fixture_grounded_proposal_derives_counts_from_atlas():
    atlas = load_fixture()
    proposal = _proposal(
        supporting_signature_ids=["sig_core", "sig_optional"],
        supporting_motif_ids=["motif_core"],
        optional_steps=[OptionalStep(token=X, frequency=0.33)],
        evidence=CatalogEvidence(
            supporting_instances=999,
            total_occurrences=999,
            distinct_users=999,
        ),
    )
    analysis = AgentAnalysis(
        status="ok",
        generated_by="llm",
        proposed_workflows=[proposal],
    )
    result = validate_agent_analysis(atlas, analysis)
    assert len(result.validated) == 1
    row = result.validated[0]
    assert row.status == "validated"
    assert set(row.supporting_signature_ids) == {"sig_core", "sig_optional"}
    assert row.supporting_motif_ids == ["motif_core"]
    assert [s.token for s in row.validated_core_steps] == [A, B, C]
    assert [s.token for s in row.validated_optional_steps] == [X]
    assert row.evidence.instance_count == 15
    assert row.evidence.occurrence_count == 15
    assert row.evidence.distinct_users == 2
    assert 999 not in (
        row.evidence.instance_count,
        row.evidence.occurrence_count,
        row.evidence.distinct_users,
    )


def test_motif_only_citation_can_validate():
    atlas = load_fixture()
    proposal = ProposedWorkflow(
        proposal_id="proposal_motif",
        name="motif pattern",
        supporting_signature_ids=[],
        supporting_motif_ids=["motif_core"],
        core_steps=[CoreStep(token=A), CoreStep(token=B), CoreStep(token=C)],
        confidence=0.6,
    )
    result = validate_proposal(atlas, proposal)
    assert result.status == "validated"
    assert result.evidence.occurrence_count == 3
    assert result.evidence.instance_count == 2
    assert result.evidence.distinct_users == 2
