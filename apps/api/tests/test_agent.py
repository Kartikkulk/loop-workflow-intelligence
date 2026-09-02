"""Workflow Discovery Agent v1 tests. Mocked LLM only — no live Ollama."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.llm.client import LLMClient
from app.models.agent_analysis import WorkflowAgentAnalysis
from app.models.cluster import Cluster
from app.schemas.atlas import ActivityAtlas
from app.services.agent import analyze_activity_atlas, atlas_fingerprint, ground_agent_payload

FIXTURE = Path(__file__).parent / "fixtures" / "activity_atlas_generic.json"

A = "app_a:read:item"
B = "app_b:update:item"
C = "app_c:send:item"
X = "app_x:search:item"


def load_fixture_atlas() -> ActivityAtlas:
    return ActivityAtlas.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


class FakeLLM:
    def __init__(self, payload, *, available: bool = True, raise_exc: bool = False):
        self.payload = payload
        self.available = available
        self.raise_exc = raise_exc
        self.calls = 0

    def load_prompt(self, template: str, /, **kwargs):
        return LLMClient.load_prompt(template, **kwargs)

    async def structured(self, *, prompt, tool, fallback, max_tokens=2048):
        self.calls += 1
        if self.raise_exc:
            raise RuntimeError("ollama timeout")
        if not self.available:
            return fallback()
        if callable(self.payload):
            return self.payload()
        return self.payload


def _good_payload(**overrides) -> dict:
    body = {
        "proposed_workflows": [
            {
                "name": "item to item",
                "description": "Observed app_a then app_b then app_c, sometimes with app_x.",
                "supporting_signature_ids": ["sig_core", "sig_optional"],
                "supporting_motif_ids": ["motif_core"],
                "supporting_sample_instance_ids": ["ti_001"],
                "core_steps": [
                    {"token": A, "reason": "present in both cited signatures"},
                    {"token": B, "reason": "present in both cited signatures"},
                    {"token": C, "reason": "present in both cited signatures"},
                ],
                "optional_steps": [
                    {
                        "token": X,
                        "frequency": 0.33,
                        "reason": "present only in sig_optional",
                    }
                ],
                "observed_applications": ["app_a", "app_b", "app_c", "app_x"],
                "repetition_assessment": {
                    "strength": "medium",
                    "reason": "two related signatures plus a shared motif",
                },
                "automation_assessment": {
                    "deterministic_steps": [A, B],
                    "judgment_steps": [X],
                    "potentially_automatable": [A, B, C],
                    "human_approval_points": [C],
                },
                "confidence": 0.72,
                "evidence_gaps": ["object types are generic item tokens"],
            }
        ],
        "unrelated_patterns": [],
        "analysis_notes": ["grouped by shared subsequence"],
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_valid_generic_atlas_yields_valid_agent_output():
    atlas = load_fixture_atlas()
    analysis = await analyze_activity_atlas(atlas, client=FakeLLM(_good_payload()))
    assert analysis.status == "ok"
    assert analysis.generated_by == "llm"
    assert analysis.proposed_workflows
    proposal = analysis.proposed_workflows[0]
    assert [s.token for s in proposal.core_steps] == [A, B, C]
    assert proposal.optional_steps[0].token == X
    assert proposal.evidence.source == "atlas_catalog"
    assert analysis.evidence_hash == atlas_fingerprint(atlas)


@pytest.mark.asyncio
async def test_no_hardcoded_sales_or_gmail_assumptions():
    atlas = load_fixture_atlas()
    analysis = await analyze_activity_atlas(atlas, client=FakeLLM(_good_payload()))
    blob = json.dumps(analysis.model_dump(mode="json"))
    for banned in ("sales", "gmail", "sheets", "enquiry", "lead", "invoice", "acknowledgement"):
        assert banned not in blob.lower()


@pytest.mark.asyncio
async def test_agent_references_valid_signature_ids():
    atlas = load_fixture_atlas()
    analysis = await analyze_activity_atlas(atlas, client=FakeLLM(_good_payload()))
    known = {row.signature_id for row in atlas.signature_catalog}
    for proposal in analysis.proposed_workflows:
        assert proposal.supporting_signature_ids
        assert set(proposal.supporting_signature_ids) <= known


@pytest.mark.asyncio
async def test_agent_references_valid_motif_ids():
    atlas = load_fixture_atlas()
    analysis = await analyze_activity_atlas(atlas, client=FakeLLM(_good_payload()))
    known = {row.motif_id for row in atlas.motif_catalog}
    for proposal in analysis.proposed_workflows:
        assert set(proposal.supporting_motif_ids) <= known
        assert "motif_core" in proposal.supporting_motif_ids


@pytest.mark.asyncio
async def test_malformed_llm_json_is_handled():
    atlas = load_fixture_atlas()
    analysis = await analyze_activity_atlas(atlas, client=FakeLLM("not-json-object"))
    assert analysis.status == "invalid"
    assert analysis.proposed_workflows == []
    assert analysis.generated_by == "fallback"


@pytest.mark.asyncio
async def test_schema_validation_failure_is_handled():
    atlas = load_fixture_atlas()
    analysis = await analyze_activity_atlas(
        atlas, client=FakeLLM({"proposed_workflows": "nope", "unrelated_patterns": []})
    )
    assert analysis.status == "invalid"
    assert analysis.proposed_workflows == []


@pytest.mark.asyncio
async def test_ollama_unavailable_safe_fallback():
    atlas = load_fixture_atlas()
    client = FakeLLM(_good_payload(), available=False)
    analysis = await analyze_activity_atlas(atlas, client=client)
    assert client.calls == 0
    assert analysis.status == "unavailable"
    assert analysis.generated_by == "fallback"
    assert analysis.proposed_workflows == []
    assert any("fabricated" in n.lower() for n in analysis.analysis_notes)


@pytest.mark.asyncio
async def test_empty_atlas_does_not_fabricate_workflows():
    atlas = ActivityAtlas()
    client = FakeLLM(_good_payload())
    analysis = await analyze_activity_atlas(atlas, client=client)
    assert client.calls == 0
    assert analysis.status == "empty"
    assert analysis.proposed_workflows == []


@pytest.mark.asyncio
async def test_unsupported_meaning_low_confidence_and_gaps():
    atlas = load_fixture_atlas()
    payload = _good_payload()
    payload["proposed_workflows"][0]["core_steps"].append(
        {"token": "crm:create:deal", "reason": "must be a sales pipeline"}
    )
    payload["proposed_workflows"][0]["confidence"] = 0.95
    analysis = await analyze_activity_atlas(atlas, client=FakeLLM(payload))
    proposal = analysis.proposed_workflows[0]
    assert all(s.token != "crm:create:deal" for s in proposal.core_steps)
    assert proposal.confidence <= 0.4
    assert proposal.evidence_gaps
    assert "crm:create:deal" in proposal.dropped_ungrounded_tokens


@pytest.mark.asyncio
async def test_agent_does_not_invent_applications():
    atlas = load_fixture_atlas()
    payload = _good_payload()
    payload["proposed_workflows"][0]["observed_applications"] = ["app_a", "salesforce", "crm"]
    analysis = await analyze_activity_atlas(atlas, client=FakeLLM(payload))
    apps = analysis.proposed_workflows[0].observed_applications
    assert "app_a" in apps
    assert "salesforce" not in apps
    assert "crm" not in apps


@pytest.mark.asyncio
async def test_agent_does_not_invent_steps():
    atlas = load_fixture_atlas()
    payload = _good_payload()
    payload["proposed_workflows"][0]["core_steps"] = [
        {"token": A, "reason": "observed"},
        {"token": B, "reason": "observed"},
        {"token": C, "reason": "observed"},
        {"token": "app_z:delete:secret", "reason": "invented"},
    ]
    analysis = await analyze_activity_atlas(atlas, client=FakeLLM(payload))
    tokens = [s.token for s in analysis.proposed_workflows[0].core_steps]
    assert tokens == [A, B, C]
    assert "app_z:delete:secret" in analysis.proposed_workflows[0].dropped_ungrounded_tokens


@pytest.mark.asyncio
async def test_agent_does_not_invent_occurrence_counts():
    atlas = load_fixture_atlas()
    payload = _good_payload()
    payload["proposed_workflows"][0]["evidence"] = {
        "supporting_instances": 999,
        "total_occurrences": 999,
        "distinct_users": 999,
    }
    analysis = await analyze_activity_atlas(atlas, client=FakeLLM(payload))
    evidence = analysis.proposed_workflows[0].evidence
    assert evidence.source == "atlas_catalog"
    assert evidence.supporting_instances == 15  # 10 + 5 from cited signatures
    assert evidence.total_occurrences == 15
    assert evidence.distinct_users == 2
    assert 999 not in (evidence.supporting_instances, evidence.total_occurrences, evidence.distinct_users)


@pytest.mark.asyncio
async def test_fixture_produces_a_reasonable_proposed_workflow():
    atlas = load_fixture_atlas()
    analysis = await analyze_activity_atlas(atlas, client=FakeLLM(_good_payload()))
    proposal = analysis.proposed_workflows[0]
    assert set(proposal.supporting_signature_ids) == {"sig_core", "sig_optional"}
    assert proposal.optional_steps[0].token == X
    assert {s.token for s in proposal.core_steps} == {A, B, C}
    assert proposal.proposal_id.startswith("proposal_")


@pytest.mark.asyncio
async def test_analysis_does_not_modify_cluster_rows():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add(
            Cluster(
                id="clu_keep",
                name="existing",
                description="",
                signature=[A, B, C],
                apps=["app_a"],
            )
        )
        await session.flush()
        before = (await session.execute(select(func.count()).select_from(Cluster))).scalar_one()
        atlas = load_fixture_atlas()
        await analyze_activity_atlas(atlas, session=session, client=FakeLLM(_good_payload()))
        after = (await session.execute(select(func.count()).select_from(Cluster))).scalar_one()
        names = list((await session.execute(select(Cluster.id, Cluster.name))).all())
        stored = list((await session.execute(select(WorkflowAgentAnalysis))).scalars().all())
        assert before == after == 1
        assert names == [("clu_keep", "existing")]
        assert len(stored) == 1
        assert stored[0].status == "ok"
    await engine.dispose()


def test_grounding_drops_unknown_signature_ids():
    atlas = load_fixture_atlas()
    raw = _good_payload()
    raw["proposed_workflows"][0]["supporting_signature_ids"] = ["sig_core", "sig_invented"]
    proposals, _, dropped = ground_agent_payload(raw, atlas)
    assert proposals[0].supporting_signature_ids == ["sig_core"]
    assert dropped >= 1


@pytest.mark.asyncio
async def test_structured_exception_is_safe():
    atlas = load_fixture_atlas()
    analysis = await analyze_activity_atlas(
        atlas, client=FakeLLM(_good_payload(), raise_exc=True)
    )
    assert analysis.status == "unavailable"
    assert analysis.proposed_workflows == []
