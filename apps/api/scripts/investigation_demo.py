"""Development demo: deterministic evidence packet + Agent Investigation v1.

Uses generic action names only (no invoice/email/sales/finance labels).

Mock (default, no Ollama required):
    .venv\\Scripts\\python.exe scripts\\investigation_demo.py

Real Ollama:
    .venv\\Scripts\\python.exe scripts\\investigation_demo.py --real

Real Gemini Developer API (gitignored LOOP_GEMINI_API_KEY, not Ollama):
    .venv\\Scripts\\python.exe scripts\\investigation_demo.py --gemini
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.llm.client import LLMClient, llm
from app.schemas.agent import CatalogEvidence, CoreStep, ProposedWorkflow
from app.schemas.atlas import (
    ActivityAtlas,
    AppTransition,
    AtlasSummary,
    SampleInstance,
    SignatureCatalogEntry,
    TimeWindow,
)
from app.schemas.investigation import InvestigationPacket, InvestigationResult
from app.services.investigator import build_investigation_packet, investigate_candidate

A = "app_a:source_action:record"
B = "app_b:transform_action:record"
C = "app_c:destination_action:record"
D = "app_d:followup_action:record"

# Words that would indicate invented domain/business semantics.
_INVENTED_DOMAIN_RE = re.compile(
    r"\b(invoice|customer|sales|finance|lead|gmail|pdf|spreadsheet|"
    r"new customer|when the customer|because the user wants)\b",
    re.IGNORECASE,
)


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.available = True

    def load_prompt(self, template: str, /, **kwargs):
        return LLMClient.load_prompt(template, **kwargs)

    async def structured(self, *, prompt, tool, fallback, max_tokens=2048):
        return self.payload


def _demo_atlas() -> ActivityAtlas:
    """Generic Pattern A (80) vs Pattern B (20) plus field-name overlap."""
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
        field_name_histograms={
            A: ["entity_name", "amount", "date"],
            B: ["entity_name", "amount", "date"],
            C: ["entity_name", "amount", "date"],
            D: ["needs_followup"],
        },
        sample_instances=[
            SampleInstance(
                instance_id="ti_001",
                signature=[A, B, C],
                duration_ms=110000,
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
        evidence_notes=["Synthetic generic atlas for investigation demo only."],
    )


def _candidate() -> ProposedWorkflow:
    return ProposedWorkflow(
        proposal_id="proposal_demo_core",
        name="source_action to destination_action",
        supporting_signature_ids=["sig_base", "sig_variant"],
        core_steps=[CoreStep(token=A), CoreStep(token=B), CoreStep(token=C)],
        confidence=0.7,
        evidence=CatalogEvidence(
            supporting_instances=100,
            total_occurrences=100,
            distinct_users=10,
        ),
    )


def _mock_payload(packet: InvestigationPacket) -> dict:
    context_ids = [
        e.evidence_id for e in packet.evidence if e.evidence_type == "context_signal"
    ]
    variant_ids = [
        e.evidence_id for e in packet.evidence if e.evidence_type == "variant_stats"
    ]
    overlap_ids = [
        e.evidence_id
        for e in packet.evidence
        if e.evidence_type == "field_name_overlap" and e.facts.get("overlap_count", 0) > 0
    ]
    return {
        "conclusions": [
            {
                "relationship": "conditional_step",
                "confidence": 0.74,
                "reasoning": (
                    "followup_action occurs in 20% of base-pattern instances and is "
                    "associated with an observable field-name context key. "
                    "No invented business condition."
                ),
                "evidence_ids": variant_ids[:1] + context_ids[:1],
                "subject": D,
                "evidence_gaps": [],
            }
        ],
        "semantic_relationships": [
            {
                "kind": "source_destination",
                "from_token": A,
                "to_token": C,
                "confidence": 0.7,
                "evidence_ids": overlap_ids[:1],
            }
        ],
        "evidence_gaps": [],
        "investigation_notes": [
            "Demo uses a mocked LLM response grounded on deterministic evidence."
        ],
        "final_decision": "safe_to_continue",
    }


def _allowed_evidence_ids(packet: InvestigationPacket) -> set[str]:
    allowed = {e.evidence_id for e in packet.evidence}
    for vs in packet.variant_statistics:
        if vs.evidence_id:
            allowed.add(vs.evidence_id)
    return allowed


def _inspect_grounding(result: InvestigationResult, packet: InvestigationPacket) -> None:
    """Report whether citations and reasoning stay inside the evidence packet."""
    allowed = _allowed_evidence_ids(packet)
    print("\n9. GROUNDING INSPECTION (honest, not forced)")
    if result.generated_by != "llm":
        print("   generated_by is not llm; model grounding cannot be assessed.")
        return

    if not result.conclusions and not result.semantic_relationships:
        print("   No semantic conclusions survived grounding (or the model returned none).")
        print("   insufficient_evidence is acceptable.")
        return

    for c in result.conclusions:
        invalid = [eid for eid in c.evidence_ids if eid not in allowed]
        print(f"   conclusion {c.relationship}:")
        print(f"     cited ids: {c.evidence_ids}")
        print(f"     all cited ids in packet: {not invalid}")
        if invalid:
            print(f"     INVALID ids (should have been stripped): {invalid}")
        if c.weakened:
            print("     weakened by investigator grounding (unknown ids removed)")
        invented = _INVENTED_DOMAIN_RE.findall(c.reasoning or "")
        if invented:
            print(f"     LIMITATION: reasoning invents domain terms not in packet: {invented}")
            print(f"     reasoning: {c.reasoning}")
        else:
            print("     reasoning does not introduce invoice/sales/customer-style labels")

    for s in result.semantic_relationships:
        invalid = [eid for eid in s.evidence_ids if eid not in allowed]
        print(f"   semantic {s.kind} {s.from_token} -> {s.to_token}:")
        print(f"     cited ids: {s.evidence_ids}")
        print(f"     all cited ids in packet: {not invalid}")
        if s.weakened:
            print("     weakened by investigator grounding")
        if s.kind in {"source_destination", "transformation"}:
            overlap = [
                e
                for e in packet.evidence
                if e.evidence_id in s.evidence_ids
                and e.evidence_type == "field_name_overlap"
                and e.facts.get("overlap_count", 0) > 0
            ]
            print(f"     cites field-name overlap evidence: {bool(overlap)}")


def _print_packet_and_stats(candidate: ProposedWorkflow, packet: InvestigationPacket) -> None:
    print("\n1. CANDIDATE WORKFLOW")
    print(f"   id:    {candidate.proposal_id}")
    print(f"   name:  {candidate.name}")
    print(f"   core:  {' -> '.join(t.token for t in candidate.core_steps)}")

    print("\n2. EVIDENCE PACKET (compact)")
    overlap = [
        {
            "evidence_id": e.evidence_id,
            "from": e.facts.get("from_token"),
            "to": e.facts.get("to_token"),
            "shared_field_names": e.facts.get("shared_field_names"),
            "overlap_count": e.facts.get("overlap_count"),
        }
        for e in packet.evidence
        if e.evidence_type == "field_name_overlap"
    ]
    print(
        json.dumps(
            {
                "candidate_workflow_id": packet.candidate_workflow_id,
                "core_tokens": packet.core_tokens,
                "instance_count": packet.instance_count,
                "distinct_users": packet.distinct_users,
                "subset_steps": packet.subset_steps,
                "field_name_histograms": packet.field_name_histograms,
                "evidence_ids": [e.evidence_id for e in packet.evidence],
                "field_name_overlap": overlap,
                "evidence_gaps": packet.evidence_gaps,
            },
            indent=2,
        )
    )

    print("\n3. VARIANT STATISTICS (deterministic)")
    for vs in packet.variant_statistics:
        print(
            json.dumps(
                {
                    "variant_token": vs.variant_token,
                    "base_pattern_frequency": vs.base_pattern_frequency,
                    "variant_frequency": vs.variant_frequency,
                    "variant_rate": vs.variant_rate,
                    "base_without_variant": vs.base_without_variant,
                    "users_with_variant": vs.users_with_variant,
                    "users_without_variant": vs.users_without_variant,
                    "variant_position": vs.variant_position,
                    "associated_context_keys": vs.associated_context_keys,
                    "evidence_id": vs.evidence_id,
                },
                indent=2,
            )
        )


def _print_result(
    result: InvestigationResult,
    *,
    mode: str,
    elapsed_s: float | None,
) -> None:
    print("\n4. AGENT INVESTIGATION RESULT")
    print(f"   mode:         {mode}")
    print(f"   status:       {result.status}")
    print(f"   generated_by: {result.generated_by}")
    print(f"   model_name:   {result.model_name or '(none)'}")
    if elapsed_s is not None:
        print(f"   elapsed_s:    {elapsed_s:.2f}")
    if mode == "real":
        print(f"   llm.available:{llm.available}")
        print(f"   llm.calls:    {llm.call_count}")
        print(f"   llm.fallback: {llm.fallback_count}")
        print(f"   ollama:       {settings.ollama_base_url.rstrip('/')}/api/chat")
        print(f"   configured:   {settings.llm_model}")

    print("\n5. RELATIONSHIP CLASSIFICATION")
    if not result.conclusions:
        print("   (none)")
    for c in result.conclusions:
        print(f"   - {c.relationship} (confidence={c.confidence:.2f})")
        print(f"     subject:   {c.subject or '-'}")
        print(f"     reasoning: {c.reasoning}")

    print("\n5b. SOURCE/DESTINATION SEMANTIC RELATIONSHIPS")
    if not result.semantic_relationships:
        print("   (none)")
    for s in result.semantic_relationships:
        print(f"   - {s.kind} (confidence={s.confidence:.2f})")
        print(f"     from: {s.from_token or '-'}")
        print(f"     to:   {s.to_token or '-'}")
        print(f"     evidence_ids: {s.evidence_ids}")
        if s.evidence_gaps:
            print(f"     gaps: {s.evidence_gaps}")

    print("\n6. EVIDENCE IDS SUPPORTING CONCLUSIONS")
    if not result.conclusions:
        print("   (none)")
    for c in result.conclusions:
        print(f"   {c.relationship}: {c.evidence_ids}")

    print("\n7. EVIDENCE GAPS")
    if result.evidence_gaps:
        for g in result.evidence_gaps:
            print(f"   - {g}")
    else:
        print("   (none)")

    print("\n8. FINAL DECISION")
    print(f"   {result.final_decision}")
    if result.final_decision == "safe_to_continue":
        print("   -> safe to continue toward validation / promotion")
    else:
        print("   -> insufficient evidence - do not invent semantics")


def _print_summary(
    result: InvestigationResult,
    packet: InvestigationPacket,
    *,
    elapsed_s: float | None,
) -> None:
    allowed = _allowed_evidence_ids(packet)
    classes = [c.relationship for c in result.conclusions] or ["(none)"]
    confs = [f"{c.confidence:.2f}" for c in result.conclusions] or ["n/a"]
    eids = [eid for c in result.conclusions for eid in c.evidence_ids]
    invalid = [eid for eid in eids if eid not in allowed]
    src = result.semantic_relationships
    src_txt = "(none)"
    if src:
        src_txt = "; ".join(
            f"{s.kind} {s.from_token or '-'}->{s.to_token or '-'} "
            f"conf={s.confidence:.2f} ids={s.evidence_ids}"
            for s in src
        )
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Provider: {settings.llm_provider}")
    print(f"Model: {result.model_name or settings.llm_model}")
    print(f"Latency: {elapsed_s:.2f}s" if elapsed_s is not None else "Latency: n/a")
    print(f"Status: {result.status}")
    print(f"Generated by: {result.generated_by}")
    print(f"Classification: {', '.join(classes)}")
    print(f"Confidence: {', '.join(confs)}")
    print(f"Evidence IDs: {eids or '(none)'}")
    grounding = "n/a"
    if eids:
        grounding = "valid" if not invalid else f"invalid ids {invalid}"
    print(f"Evidence grounding: {grounding}")
    print(f"Source/destination result: {src_txt}")
    print(f"Validation result: {result.final_decision}")
    print(f"Evidence gaps: {result.evidence_gaps or '(none)'}")
    print(f"Fallbacks: {llm.fallback_count}")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 5C investigation demo")
    parser.add_argument(
        "--real",
        action="store_true",
        help="Call the existing Ollama LLM via investigate_candidate(); do not mock.",
    )
    parser.add_argument(
        "--gemini",
        action="store_true",
        help="Call Gemini 2.5 Flash via llm.structured() (LOOP_GEMINI_API_KEY).",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Override LOOP_LLM_MODEL for this process only.",
    )
    args = parser.parse_args(argv)
    if args.gemini:
        settings.llm_provider = "gemini"
        settings.llm_model = args.model.strip() or "gemini-2.5-flash"
        settings.llm_cache = False
        llm._cache.clear()
        llm.call_count = 0
        llm.fallback_count = 0
    elif args.model.strip():
        settings.llm_model = args.model.strip()
    if args.real:
        settings.llm_cache = False
        llm._cache.clear()
        llm.call_count = 0
        llm.fallback_count = 0

    atlas = _demo_atlas()
    candidate = _candidate()
    packet = build_investigation_packet(atlas, candidate)

    live = args.real or args.gemini
    if args.gemini:
        mode_label = "REAL GEMINI"
    elif args.real:
        mode_label = "REAL OLLAMA"
    else:
        mode_label = "MOCK"

    print("=" * 60)
    print("PHASE 5C - AGENT INVESTIGATION DEMO")
    print("=" * 60)
    print(f"mode: {mode_label}")
    _print_packet_and_stats(candidate, packet)

    elapsed_s: float | None = None
    if live:
        if args.gemini and not llm.available:
            print("\nGemini is not configured (LOOP_GEMINI_API_KEY missing).")
            print("Skipping real call. This demo is not a CI failure.")
            return 2
        if args.real and not llm.available:
            print("\nOllama is not configured (LOOP_LLM_PROVIDER / LOOP_LLM_MODEL).")
            print("Skipping real call. This demo is not a CI failure.")
            return 2
        print("\ncalling investigate_candidate() with the default LLM client")
        print(f"LOOP_LLM_PROVIDER={settings.llm_provider}")
        print(f"LOOP_LLM_MODEL={settings.llm_model}")
        print(f"llm_cache={settings.llm_cache}")
        t0 = time.perf_counter()
        result = await investigate_candidate(atlas, candidate)
        elapsed_s = time.perf_counter() - t0
        mode = "real"
    else:
        result = await investigate_candidate(
            atlas, candidate, client=FakeLLM(_mock_payload(packet))
        )
        mode = "mock"

    _print_result(result, mode=mode, elapsed_s=elapsed_s)
    _inspect_grounding(result, packet)
    _print_summary(result, packet, elapsed_s=elapsed_s)

    if mode == "mock":
        print("\nNOTE: Mock LLM response; evidence packet is real/deterministic.")
    elif result.generated_by == "llm":
        print("\nNOTE: Real LLM call through investigator.py. Classification is not hardcoded.")
    else:
        print("\nNOTE: Real path fell back; no fabricated semantics.")
    return 0 if (not live or result.generated_by == "llm") else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

