"""Agent Investigation v1 tests. Mocked LLM only — no live Ollama."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from app.llm.client import LLMClient
from app.schemas.agent import (
    CatalogEvidence,
    CoreStep,
    ProposedWorkflow,
)
from app.schemas.atlas import (
    ActivityAtlas,
    AppTransition,
    AtlasSummary,
    SampleInstance,
    SignatureCatalogEntry,
    TimeWindow,
)
from app.services import investigator as investigator_mod
from app.services.investigator import (
    build_investigation_packet,
    compute_variant_statistics,
    ground_investigation_payload,
    investigate_candidate,
    packet_contains_forbidden_content,
)

A = "app_a:source_action:record"
B = "app_b:transform_action:record"
C = "app_c:destination_action:record"
D = "app_d:followup_action:record"
E = "app_e:other_action:record"
F = "app_f:other_action:record"


class FakeLLM:
    def __init__(self, payload, *, available: bool = True, raise_exc: bool = False):
        self.payload = payload
        self.available = available
        self.raise_exc = raise_exc
        self.calls = 0
        self.last_prompt = ""
        self.last_tool = None

    def load_prompt(self, template: str, /, **kwargs):
        return LLMClient.load_prompt(template, **kwargs)

    async def structured(self, *, prompt, tool, fallback, max_tokens=2048):
        self.calls += 1
        self.last_prompt = prompt
        self.last_tool = tool
        if self.raise_exc:
            raise RuntimeError("ollama timeout")
        if not self.available:
            return fallback()
        if callable(self.payload):
            return self.payload()
        return self.payload


def _candidate(
    tokens: list[str], *, proposal_id: str = "proposal_core", **kwargs
) -> ProposedWorkflow:
    body = {
        "proposal_id": proposal_id,
        "name": "observed pattern",
        "supporting_signature_ids": kwargs.pop("supporting_signature_ids", ["sig_base"]),
        "core_steps": [CoreStep(token=t) for t in tokens],
        "confidence": 0.7,
        "evidence": CatalogEvidence(
            supporting_instances=kwargs.pop("instances", 80),
            total_occurrences=kwargs.pop("occurrences", 80),
            distinct_users=kwargs.pop("users", 6),
        ),
    }
    body.update(kwargs)
    return ProposedWorkflow(**body)


def _atlas_simple_abc() -> ActivityAtlas:
    return ActivityAtlas(
        time_window=TimeWindow(
            start=datetime(2026, 4, 1, tzinfo=UTC),
            end=datetime(2026, 4, 8, tzinfo=UTC),
        ),
        summary=AtlasSummary(
            event_count=240,
            instance_count=80,
            distinct_users=6,
            distinct_sessions=80,
        ),
        signature_catalog=[
            SignatureCatalogEntry(
                signature_id="sig_base",
                tokens=[A, B, C],
                occurrence_count=80,
                distinct_users=6,
                median_duration_ms=120000,
                example_instance_ids=["ti_001", "ti_002"],
            )
        ],
        app_transitions=[
            AppTransition(**{"from": "app_a", "to": "app_b", "count": 80}),
            AppTransition(**{"from": "app_b", "to": "app_c", "count": 80}),
        ],
        field_name_histograms={
            A: ["name", "amount", "date"],
            B: ["name", "amount", "date"],
            C: ["name", "amount", "date"],
        },
        sample_instances=[
            SampleInstance(
                instance_id="ti_001",
                signature=[A, B, C],
                duration_ms=100000,
                user_id="u1",
                started_at=datetime(2026, 4, 1, 10, tzinfo=UTC),
                event_count=3,
            )
        ],
    )


def _atlas_variant_abc_d(*, with_context: bool = False) -> ActivityAtlas:
    hist = {
        A: ["name", "amount"],
        B: ["name", "amount"],
        C: ["name", "amount"],
        D: ["status_flag"] if with_context else [],
    }
    if with_context:
        hist[D] = ["needs_followup"]
    return ActivityAtlas(
        time_window=TimeWindow(
            start=datetime(2026, 4, 1, tzinfo=UTC),
            end=datetime(2026, 4, 8, tzinfo=UTC),
        ),
        summary=AtlasSummary(
            event_count=340,
            instance_count=100,
            distinct_users=10,
            distinct_sessions=100,
        ),
        signature_catalog=[
            SignatureCatalogEntry(
                signature_id="sig_base",
                tokens=[A, B, C],
                occurrence_count=80,
                distinct_users=6,
                median_duration_ms=120000,
                example_instance_ids=["ti_001"],
            ),
            SignatureCatalogEntry(
                signature_id="sig_variant",
                tokens=[A, B, C, D],
                occurrence_count=20,
                distinct_users=4,
                median_duration_ms=150000,
                example_instance_ids=["ti_020"],
            ),
        ],
        app_transitions=[
            AppTransition(**{"from": "app_a", "to": "app_b", "count": 100}),
            AppTransition(**{"from": "app_b", "to": "app_c", "count": 100}),
            AppTransition(**{"from": "app_c", "to": "app_d", "count": 20}),
        ],
        field_name_histograms=hist,
        sample_instances=[
            SampleInstance(
                instance_id="ti_001",
                signature=[A, B, C],
                duration_ms=100000,
                user_id="u1",
                started_at=datetime(2026, 4, 1, 10, tzinfo=UTC),
                event_count=3,
            ),
            SampleInstance(
                instance_id="ti_020",
                signature=[A, B, C, D],
                duration_ms=140000,
                user_id="u7",
                started_at=datetime(2026, 4, 2, 10, tzinfo=UTC),
                event_count=4,
            ),
        ],
    )


def _atlas_separate() -> ActivityAtlas:
    return ActivityAtlas(
        summary=AtlasSummary(event_count=200, instance_count=50, distinct_users=4),
        signature_catalog=[
            SignatureCatalogEntry(
                signature_id="sig_base",
                tokens=[A, B, C],
                occurrence_count=30,
                distinct_users=3,
                median_duration_ms=100000,
                example_instance_ids=["ti_a"],
            ),
            SignatureCatalogEntry(
                signature_id="sig_other",
                tokens=[D, E, F],
                occurrence_count=20,
                distinct_users=2,
                median_duration_ms=90000,
                example_instance_ids=["ti_b"],
            ),
        ],
        sample_instances=[
            SampleInstance(
                instance_id="ti_a",
                signature=[A, B, C],
                duration_ms=100000,
                user_id="u1",
                started_at=datetime(2026, 4, 1, 10, tzinfo=UTC),
                event_count=3,
            ),
            SampleInstance(
                instance_id="ti_b",
                signature=[D, E, F],
                duration_ms=90000,
                user_id="u2",
                started_at=datetime(2026, 4, 1, 11, tzinfo=UTC),
                event_count=3,
            ),
        ],
    )


def _atlas_open_update_no_meta() -> ActivityAtlas:
    open_tok = "app_doc:open_document:file"
    update_tok = "app_sheet:update_spreadsheet:row"
    return ActivityAtlas(
        summary=AtlasSummary(event_count=40, instance_count=20, distinct_users=2),
        signature_catalog=[
            SignatureCatalogEntry(
                signature_id="sig_open_update",
                tokens=[open_tok, update_tok],
                occurrence_count=20,
                distinct_users=2,
                median_duration_ms=60000,
                example_instance_ids=["ti_1"],
            )
        ],
        field_name_histograms={
            # No overlapping field names — sequence alone is not transfer proof.
            open_tok: [],
            update_tok: [],
        },
        sample_instances=[
            SampleInstance(
                instance_id="ti_1",
                signature=[open_tok, update_tok],
                duration_ms=60000,
                user_id="u1",
                started_at=datetime(2026, 4, 1, 10, tzinfo=UTC),
                event_count=2,
            )
        ],
    )


# ---------------------------------------------------------------------------
# TEST 1 — simple repeated workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simple_repeated_workflow_same_workflow():
    atlas = _atlas_simple_abc()
    candidate = _candidate([A, B, C])
    payload = {
        "conclusions": [
            {
                "relationship": "same_workflow",
                "confidence": 0.82,
                "reasoning": "Single repeated signature with consistent steps.",
                "evidence_ids": ["candidate_01", "consistency_01"],
                "subject": "core",
            }
        ],
        "semantic_relationships": [
            {
                "kind": "source_destination",
                "from_token": A,
                "to_token": C,
                "confidence": 0.7,
                "evidence_ids": ["field_overlap_01"],
            }
        ],
        "evidence_gaps": [],
        "investigation_notes": ["consistent A→B→C"],
        "final_decision": "safe_to_continue",
    }
    result = await investigate_candidate(atlas, candidate, client=FakeLLM(payload))
    assert result.generated_by == "llm"
    assert result.status == "ok"
    assert result.conclusions
    assert result.conclusions[0].relationship == "same_workflow"
    assert "candidate_01" in result.conclusions[0].evidence_ids
    assert result.final_decision == "safe_to_continue"


# ---------------------------------------------------------------------------
# TEST 2 — variant statistics are deterministic (not hardcoded optional)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_variant_statistics_are_deterministic():
    atlas = _atlas_variant_abc_d()
    candidate = _candidate([A, B, C], supporting_signature_ids=["sig_base", "sig_variant"])
    stats = compute_variant_statistics(atlas, [A, B, C])
    assert len(stats) == 1
    vs = stats[0]
    assert vs.variant_token == D
    assert vs.base_pattern_frequency == 100
    assert vs.variant_frequency == 20
    assert vs.variant_rate == 0.2
    assert vs.base_without_variant == 80
    assert vs.variant_position == f"after:{C}"

    # Packet exposes facts; classification is not hardcoded by Python.
    packet = build_investigation_packet(atlas, candidate)
    assert packet.variant_statistics
    assert packet.variant_statistics[0].variant_rate == 0.2
    assert any(e.evidence_type == "variant_stats" for e in packet.evidence)

    # LLM may classify variously; we only assert facts reached the model path.
    payload = {
        "conclusions": [
            {
                "relationship": "insufficient_evidence",
                "confidence": 0.55,
                "reasoning": "D occurs in 20% of instances; no condition evidenced.",
                "evidence_ids": ["variant_stats_01"],
                "subject": D,
            }
        ],
        "semantic_relationships": [],
        "evidence_gaps": ["no observable condition for D"],
        "investigation_notes": ["frequency only"],
        "final_decision": "insufficient_evidence",
    }
    result = await investigate_candidate(atlas, candidate, client=FakeLLM(payload))
    assert result.variant_statistics[0].variant_rate == 0.2
    # Must NOT hardcode optional_step in the service for this case.
    assert result.conclusions[0].relationship == "insufficient_evidence"


# ---------------------------------------------------------------------------
# TEST 3 — conditional only when context evidence exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conditional_requires_context_evidence():
    atlas = _atlas_variant_abc_d(with_context=True)
    candidate = _candidate([A, B, C], supporting_signature_ids=["sig_base", "sig_variant"])
    packet = build_investigation_packet(atlas, candidate)
    context_ids = [
        e.evidence_id for e in packet.evidence if e.evidence_type == "context_signal"
    ]
    assert context_ids, "expected context_signal evidence from associated field names"

    payload = {
        "conclusions": [
            {
                "relationship": "conditional_step",
                "confidence": 0.78,
                "reasoning": "D co-occurs with an observable context field-name key.",
                "evidence_ids": ["variant_stats_01", context_ids[0]],
                "subject": D,
            }
        ],
        "semantic_relationships": [],
        "evidence_gaps": [],
        "investigation_notes": ["context-linked variant"],
        "final_decision": "safe_to_continue",
    }
    result = await investigate_candidate(atlas, candidate, client=FakeLLM(payload))
    assert result.conclusions[0].relationship == "conditional_step"
    assert context_ids[0] in result.conclusions[0].evidence_ids


# ---------------------------------------------------------------------------
# TEST 4 — separate workflow when sequences do not overlap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_separate_workflow_when_independent_sequence():
    atlas = _atlas_separate()
    primary = _candidate([A, B, C], proposal_id="proposal_a")
    other = _candidate(
        [D, E, F],
        proposal_id="proposal_b",
        supporting_signature_ids=["sig_other"],
        instances=20,
        occurrences=20,
        users=2,
    )
    packet = build_investigation_packet(atlas, primary, [other])
    assert any(e.evidence_id == "comparison_01" for e in packet.evidence)
    assert any(e.evidence_type == "independent_sequence" for e in packet.evidence)

    payload = {
        "conclusions": [
            {
                "relationship": "separate_workflow",
                "confidence": 0.88,
                "reasoning": "No shared tokens with independently recurring DEF sequence.",
                "evidence_ids": ["comparison_01", "independent_01"],
                "subject": other.proposal_id,
            }
        ],
        "semantic_relationships": [],
        "evidence_gaps": [],
        "investigation_notes": ["distinct objectives"],
        "final_decision": "safe_to_continue",
    }
    result = await investigate_candidate(
        atlas, primary, comparison_candidates=[other], client=FakeLLM(payload)
    )
    assert result.conclusions[0].relationship == "separate_workflow"


# ---------------------------------------------------------------------------
# TEST 5 — insufficient semantic evidence for source/destination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insufficient_semantic_evidence_for_transfer():
    atlas = _atlas_open_update_no_meta()
    open_tok = "app_doc:open_document:file"
    update_tok = "app_sheet:update_spreadsheet:row"
    candidate = _candidate(
        [open_tok, update_tok],
        supporting_signature_ids=["sig_open_update"],
        instances=20,
        occurrences=20,
    )
    packet = build_investigation_packet(atlas, candidate)
    assert any(
        "source/destination transfer is not evidenced" in g for g in packet.evidence_gaps
    )

    # LLM invents a transfer without overlap evidence → grounding rejects kind.
    payload = {
        "conclusions": [
            {
                "relationship": "insufficient_evidence",
                "confidence": 0.6,
                "reasoning": "Sequence alone does not prove data transfer.",
                "evidence_ids": ["candidate_01"],
            }
        ],
        "semantic_relationships": [
            {
                "kind": "source_destination",
                "from_token": open_tok,
                "to_token": update_tok,
                "confidence": 0.9,
                "evidence_ids": ["candidate_01"],
            }
        ],
        "evidence_gaps": [],
        "investigation_notes": [],
        "final_decision": "insufficient_evidence",
    }
    result = await investigate_candidate(atlas, candidate, client=FakeLLM(payload))
    assert result.final_decision == "insufficient_evidence"
    assert result.semantic_relationships
    assert result.semantic_relationships[0].kind == "insufficient_evidence"


# ---------------------------------------------------------------------------
# TEST 6 — invented evidence IDs rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invented_evidence_ids_rejected():
    atlas = _atlas_simple_abc()
    candidate = _candidate([A, B, C])
    payload = {
        "conclusions": [
            {
                "relationship": "optional_step",
                "confidence": 0.95,
                "reasoning": "Invented citation.",
                "evidence_ids": ["invented_evidence_99"],
                "subject": D,
            },
            {
                "relationship": "same_workflow",
                "confidence": 0.8,
                "reasoning": "Valid citation retained.",
                "evidence_ids": ["candidate_01", "invented_extra"],
            },
        ],
        "semantic_relationships": [],
        "evidence_gaps": [],
        "investigation_notes": [],
        "final_decision": "safe_to_continue",
    }
    result = await investigate_candidate(atlas, candidate, client=FakeLLM(payload))
    # Fully invented conclusion dropped.
    assert all(c.relationship != "optional_step" for c in result.conclusions)
    # Partially invented conclusion kept but weakened.
    kept = [c for c in result.conclusions if c.relationship == "same_workflow"]
    assert len(kept) == 1
    assert kept[0].evidence_ids == ["candidate_01"]
    assert kept[0].weakened is True
    assert "invented_evidence_99" not in {
        eid for c in result.conclusions for eid in c.evidence_ids
    }


def test_grounding_drops_conclusion_with_zero_valid_ids():
    atlas = _atlas_simple_abc()
    packet = build_investigation_packet(atlas, _candidate([A, B, C]))
    conclusions, _, gaps, _, dropped = ground_investigation_payload(
        {
            "conclusions": [
                {
                    "relationship": "conditional_step",
                    "confidence": 0.9,
                    "evidence_ids": ["does_not_exist"],
                }
            ],
            "semantic_relationships": [],
            "final_decision": "safe_to_continue",
        },
        packet,
    )
    assert conclusions == []
    assert dropped >= 1
    assert any("ungrounded conclusion" in g for g in gaps)


# ---------------------------------------------------------------------------
# TEST 7 — privacy
# ---------------------------------------------------------------------------


def test_investigation_packet_has_no_private_payloads():
    atlas = _atlas_simple_abc()
    # Attempt to smuggle private keys through histogram / notes.
    atlas.field_name_histograms[A] = ["name", "password", "clipboard"]
    candidate = _candidate([A, B, C])
    packet = build_investigation_packet(atlas, candidate)
    hits = packet_contains_forbidden_content(packet)
    assert hits == []
    blob = str(packet.model_dump(mode="json")).lower()
    assert "email_body" not in blob
    assert "cell_value" not in blob
    assert "raw_payload" not in blob
    # Scrubber removes forbidden histogram keys.
    for names in packet.field_name_histograms.values():
        assert "password" not in [n.lower() for n in names]
        assert "clipboard" not in [n.lower() for n in names]


# ---------------------------------------------------------------------------
# TEST 8 — no ground_truth leakage
# ---------------------------------------------------------------------------


def test_investigator_does_not_access_ground_truth():
    src = inspect.getsource(investigator_mod)
    # Must not read seed/domain labels from events or clusters.
    assert "event.ground_truth_workflow" not in src
    assert "Instance.ground_truth" not in src
    assert "cluster.ground_truth" not in src
    assert ".ground_truth_workflow" not in src.replace(
        '"ground_truth_workflow"', ""
    ).replace("'ground_truth_workflow'", "")

    atlas = _atlas_simple_abc()
    atlas.evidence_notes.append("ground_truth_workflow=secret_recipe")
    packet = build_investigation_packet(atlas, _candidate([A, B, C]))
    blob = str(packet.model_dump(mode="json")).lower()
    assert "ground_truth_workflow" not in blob
    assert "secret_recipe" not in blob
    assert packet_contains_forbidden_content(packet) == []


@pytest.mark.asyncio
async def test_fallback_does_not_fabricate_semantics():
    atlas = _atlas_variant_abc_d()
    candidate = _candidate([A, B, C], supporting_signature_ids=["sig_base", "sig_variant"])
    result = await investigate_candidate(
        atlas, candidate, client=FakeLLM({}, available=False)
    )
    assert result.generated_by == "fallback"
    assert result.status == "insufficient_evidence"
    assert result.conclusions == []
    assert result.final_decision == "insufficient_evidence"
    # Deterministic facts still present for callers.
    assert result.variant_statistics
