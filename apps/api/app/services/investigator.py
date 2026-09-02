"""Agent Investigation v1 — interpret atlas evidence for a candidate workflow.

Deterministic Python builds the evidence packet and variant statistics.
The LLM only classifies relationships from that packet. Fallback fabricates
no semantic conclusions.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from typing import Any

from app.config import settings
from app.llm.client import llm
from app.llm.tools import INVESTIGATE_WORKFLOW
from app.schemas.agent import AgentAnalysis, ProposedWorkflow
from app.schemas.atlas import ActivityAtlas, SignatureCatalogEntry
from app.schemas.investigation import (
    InvestigationConclusion,
    InvestigationEvidence,
    InvestigationPacket,
    InvestigationResult,
    RelationshipKind,
    SemanticRelationship,
    VariantStatistics,
)

logger = logging.getLogger("loop.investigator")

_RELATIONSHIPS: set[str] = {
    "same_workflow",
    "optional_step",
    "conditional_step",
    "separate_workflow",
    "insufficient_evidence",
}
_SEMANTIC_KINDS: set[str] = {
    "source_destination",
    "transformation",
    "unrelated",
    "unknown",
    "insufficient_evidence",
}

# Privacy: never put these key/substring patterns into the LLM packet.
_FORBIDDEN_KEY_RE = re.compile(
    r"(password|credential|clipboard|email_body|mail_body|body_text|"
    r"cell_value|sheet_value|payload|raw_event|inner_html|dom_html|"
    r"ground_truth)",
    re.IGNORECASE,
)

_FALLBACK_NOTE = (
    "LLM unavailable or returned unusable output; no semantic conclusions were fabricated."
)
_MAX_SAMPLES = 8
_MAX_TRANSITIONS = 20
_MAX_COMPARISONS = 8


def _token_parts(token: str) -> tuple[str, str, str]:
    parts = token.split(":")
    app = parts[0] if parts else ""
    action = parts[1] if len(parts) > 1 else ""
    obj = parts[2] if len(parts) > 2 else ""
    return app, action, obj


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    if not needle:
        return True
    i = 0
    for token in haystack:
        if token == needle[i]:
            i += 1
            if i == len(needle):
                return True
    return False


def _variant_position(base: list[str], full: list[str], extra: str) -> str:
    if extra not in full:
        return "absent"
    idx = full.index(extra)
    if idx > 0 and full[idx - 1] in base:
        return f"after:{full[idx - 1]}"
    if idx + 1 < len(full) and full[idx + 1] in base:
        return f"before:{full[idx + 1]}"
    if idx == 0:
        return "prefix"
    if idx == len(full) - 1:
        return "suffix"
    return f"index:{idx}"


def _related_signatures(
    atlas: ActivityAtlas, base_tokens: list[str]
) -> list[SignatureCatalogEntry]:
    related: list[SignatureCatalogEntry] = []
    for row in atlas.signature_catalog:
        if _is_subsequence(base_tokens, list(row.tokens)) or _is_subsequence(
            list(row.tokens), base_tokens
        ) or set(base_tokens) & set(row.tokens):
            related.append(row)
    return related


def compute_variant_statistics(
    atlas: ActivityAtlas, base_tokens: list[str]
) -> list[VariantStatistics]:
    """Deterministic base-vs-extra-step frequencies. No semantic labels."""
    if not base_tokens:
        return []

    related = [
        row
        for row in atlas.signature_catalog
        if _is_subsequence(base_tokens, list(row.tokens))
    ]
    if not related:
        return []

    base_freq = sum(r.occurrence_count for r in related)
    extra_counts: Counter[str] = Counter()
    extra_users: dict[str, set[str]] = defaultdict(set)
    extra_positions: dict[str, Counter[str]] = defaultdict(Counter)
    extra_sig_ids: dict[str, set[str]] = defaultdict(set)

    for row in related:
        extras = [t for t in row.tokens if t not in base_tokens]
        sample_users = {
            s.user_id
            for s in atlas.sample_instances
            if list(s.signature) == list(row.tokens)
        }
        for extra in extras:
            extra_counts[extra] += row.occurrence_count
            extra_sig_ids[extra].add(row.signature_id)
            extra_positions[extra][
                _variant_position(base_tokens, list(row.tokens), extra)
            ] += row.occurrence_count
            extra_users[extra].update(sample_users)

    base_only_users: set[str] = set()
    for row in related:
        if list(row.tokens) == list(base_tokens):
            base_only_users.update(
                s.user_id
                for s in atlas.sample_instances
                if list(s.signature) == list(row.tokens)
            )

    histograms = atlas.field_name_histograms or {}
    base_fields: set[str] = set()
    for token in base_tokens:
        base_fields.update(histograms.get(token) or [])

    stats: list[VariantStatistics] = []
    for i, (extra, freq) in enumerate(sorted(extra_counts.items()), start=1):
        rate = (freq / base_freq) if base_freq else 0.0
        pos_counter = extra_positions[extra]
        position = pos_counter.most_common(1)[0][0] if pos_counter else "unknown"
        variant_fields = set(histograms.get(extra) or [])
        associated = sorted(variant_fields - base_fields)
        for sid in extra_sig_ids[extra]:
            row = next((r for r in related if r.signature_id == sid), None)
            if row is None:
                continue
            for token in row.tokens:
                for name in histograms.get(token) or []:
                    if name not in base_fields and name not in associated:
                        associated.append(name)
        associated = sorted(set(associated))[:12]
        eid = f"variant_stats_{i:02d}"
        stats.append(
            VariantStatistics(
                variant_id=f"var_{i:02d}",
                base_tokens=list(base_tokens),
                variant_token=extra,
                base_pattern_frequency=base_freq,
                variant_frequency=freq,
                variant_rate=round(rate, 4),
                base_without_variant=max(0, base_freq - freq),
                users_with_variant=len(extra_users[extra]),
                users_without_variant=max(0, len(base_only_users - extra_users[extra])),
                variant_position=position,
                associated_context_keys=associated,
                evidence_id=eid,
            )
        )
    return stats


def _field_overlap_evidence(
    atlas: ActivityAtlas, tokens: list[str], start_index: int
) -> list[InvestigationEvidence]:
    histograms = atlas.field_name_histograms or {}
    items: list[InvestigationEvidence] = []
    n = 0
    for i, a in enumerate(tokens):
        for b in tokens[i + 1 :]:
            fa = set(histograms.get(a) or [])
            fb = set(histograms.get(b) or [])
            overlap = sorted(fa & fb)
            n += 1
            eid = f"field_overlap_{start_index + n:02d}"
            items.append(
                InvestigationEvidence(
                    evidence_id=eid,
                    evidence_type="field_name_overlap",
                    source="atlas_catalog",
                    description=(
                        f"Field-name overlap between {a} and {b}: "
                        f"{len(overlap)} shared name(s)."
                    ),
                    supporting_ids=[a, b],
                    facts={
                        "from_token": a,
                        "to_token": b,
                        "shared_field_names": overlap,
                        "from_field_names": sorted(fa)[:24],
                        "to_field_names": sorted(fb)[:24],
                        "overlap_count": len(overlap),
                    },
                )
            )
    return items


def _scrub_forbidden(obj: Any) -> Any:
    """Drop keys/values that look like private payloads or ground truth."""
    if isinstance(obj, dict):
        cleaned: dict[str, Any] = {}
        for key, value in obj.items():
            if _FORBIDDEN_KEY_RE.search(str(key)):
                continue
            cleaned[str(key)] = _scrub_forbidden(value)
        return cleaned
    if isinstance(obj, list):
        return [_scrub_forbidden(v) for v in obj]
    if isinstance(obj, str) and obj.lower() in {"password", "credential", "clipboard"}:
        return "[redacted]"
    return obj


def build_investigation_packet(
    atlas: ActivityAtlas,
    candidate: ProposedWorkflow,
    comparison_candidates: list[ProposedWorkflow] | None = None,
) -> InvestigationPacket:
    """Build a compact deterministic evidence packet. No raw event payloads."""
    atlas = ActivityAtlas.model_validate(atlas)
    candidate = ProposedWorkflow.model_validate(candidate)
    comparison_candidates = comparison_candidates or []

    core_tokens = [s.token for s in candidate.core_steps]
    optional_tokens = [s.token for s in candidate.optional_steps]
    apps = [_token_parts(t)[0] for t in core_tokens]
    actions = [_token_parts(t)[1] for t in core_tokens]
    objects = [_token_parts(t)[2] for t in core_tokens]

    related = _related_signatures(atlas, core_tokens)
    related_ids = {r.signature_id for r in related}
    exact = [r for r in related if list(r.tokens) == list(core_tokens)]
    durations = [r.median_duration_ms for r in related if r.median_duration_ms]
    consistent = list(core_tokens)
    all_related_tokens: Counter[str] = Counter()
    total_occ = sum(r.occurrence_count for r in related) or 1
    for row in related:
        for token in set(row.tokens):
            all_related_tokens[token] += row.occurrence_count
    subset_steps = [
        token
        for token, count in all_related_tokens.items()
        if token not in core_tokens and (count / total_occ) < 1.0
    ]

    variant_stats = compute_variant_statistics(atlas, core_tokens)

    evidence: list[InvestigationEvidence] = []
    evidence.append(
        InvestigationEvidence(
            evidence_id="candidate_01",
            evidence_type="candidate_signature",
            source="atlas_catalog",
            description="Candidate core token sequence and cited atlas ids.",
            supporting_ids=list(candidate.supporting_signature_ids)
            + list(candidate.supporting_motif_ids),
            facts={
                "core_tokens": core_tokens,
                "optional_tokens": optional_tokens,
                "supporting_signature_ids": list(candidate.supporting_signature_ids),
                "supporting_motif_ids": list(candidate.supporting_motif_ids),
                "occurrence_hint": candidate.evidence.total_occurrences,
                "instance_hint": candidate.evidence.supporting_instances,
                "distinct_users_hint": candidate.evidence.distinct_users,
            },
        )
    )

    if exact:
        evidence.append(
            InvestigationEvidence(
                evidence_id="consistency_01",
                evidence_type="step_consistency",
                source="deterministic_stats",
                description="Exact base signature frequency among related signatures.",
                supporting_ids=[r.signature_id for r in exact],
                facts={
                    "exact_match_occurrence_count": sum(r.occurrence_count for r in exact),
                    "related_signature_count": len(related),
                    "related_occurrence_count": sum(r.occurrence_count for r in related),
                },
            )
        )

    for vs in variant_stats:
        evidence.append(
            InvestigationEvidence(
                evidence_id=vs.evidence_id,
                evidence_type="variant_stats",
                source="deterministic_stats",
                description=(
                    f"Deterministic frequency of extra token {vs.variant_token} "
                    f"relative to base pattern."
                ),
                supporting_ids=[vs.variant_token],
                facts=vs.model_dump(mode="json"),
            )
        )
        if vs.associated_context_keys:
            evidence.append(
                InvestigationEvidence(
                    evidence_id=f"context_{vs.variant_id}",
                    evidence_type="context_signal",
                    source="atlas_catalog",
                    description=(
                        "Field-name keys associated with the variant token but not "
                        "present on base tokens. These are names only, not values."
                    ),
                    supporting_ids=[vs.variant_token],
                    facts={
                        "variant_token": vs.variant_token,
                        "associated_context_keys": vs.associated_context_keys,
                        "variant_rate": vs.variant_rate,
                    },
                )
            )

    evidence.extend(
        _field_overlap_evidence(atlas, core_tokens + optional_tokens, start_index=0)
    )

    for i, motif_id in enumerate(candidate.supporting_motif_ids, start=1):
        motif = next((m for m in atlas.motif_catalog if m.motif_id == motif_id), None)
        if motif is None:
            continue
        evidence.append(
            InvestigationEvidence(
                evidence_id=f"motif_{i:02d}",
                evidence_type="motif",
                source="atlas_catalog",
                description="Cited motif subsequence counts from the atlas.",
                supporting_ids=[motif.motif_id],
                facts={
                    "tokens": list(motif.tokens),
                    "instance_support": motif.instance_support,
                    "total_occurrences": motif.total_occurrences,
                    "distinct_users": motif.distinct_users,
                },
            )
        )

    comparison_summaries: list[dict[str, Any]] = []
    for i, other in enumerate(comparison_candidates[:_MAX_COMPARISONS], start=1):
        other_tokens = [s.token for s in other.core_steps]
        shared = sorted(set(core_tokens) & set(other_tokens))
        eid = f"comparison_{i:02d}"
        summary = {
            "comparison_id": eid,
            "other_proposal_id": other.proposal_id,
            "other_core_tokens": other_tokens,
            "shared_tokens": shared,
            "shared_count": len(shared),
            "other_occurrences": other.evidence.total_occurrences,
        }
        comparison_summaries.append(summary)
        evidence.append(
            InvestigationEvidence(
                evidence_id=eid,
                evidence_type="comparison_candidate",
                source="deterministic_stats",
                description=(
                    "Token overlap between the primary candidate and another "
                    "proposed recurring sequence."
                ),
                supporting_ids=list(other.supporting_signature_ids),
                facts=summary,
            )
        )

    independent = [
        row
        for row in atlas.signature_catalog
        if row.signature_id not in related_ids
        and not _is_subsequence(core_tokens, list(row.tokens))
        and not (set(core_tokens) & set(row.tokens))
    ]
    if independent:
        top = sorted(independent, key=lambda r: r.occurrence_count, reverse=True)[:3]
        evidence.append(
            InvestigationEvidence(
                evidence_id="independent_01",
                evidence_type="independent_sequence",
                source="atlas_catalog",
                description="Recurring signatures with no shared tokens vs the candidate.",
                supporting_ids=[r.signature_id for r in top],
                facts={
                    "sequences": [
                        {
                            "signature_id": r.signature_id,
                            "tokens": list(r.tokens),
                            "occurrence_count": r.occurrence_count,
                            "distinct_users": r.distinct_users,
                        }
                        for r in top
                    ]
                },
            )
        )

    transitions = [
        {"from": t.from_app, "to": t.to_app, "count": t.count}
        for t in atlas.app_transitions[:_MAX_TRANSITIONS]
    ]
    if transitions:
        evidence.append(
            InvestigationEvidence(
                evidence_id="transitions_01",
                evidence_type="app_transition",
                source="atlas_catalog",
                description="Observed application transitions (counts only).",
                supporting_ids=[],
                facts={"transitions": transitions},
            )
        )

    sample_ids = [
        s.instance_id
        for s in atlas.sample_instances
        if _is_subsequence(core_tokens, list(s.signature))
    ][:_MAX_SAMPLES]
    if not sample_ids:
        sample_ids = [s.instance_id for s in atlas.sample_instances[:_MAX_SAMPLES]]

    sample_orderings = []
    for sample in atlas.sample_instances:
        if sample.instance_id not in set(sample_ids):
            continue
        sample_orderings.append(
            {
                "instance_id": sample.instance_id,
                "signature": list(sample.signature),
                "duration_ms": sample.duration_ms,
                "user_id": sample.user_id,
                "event_count": sample.event_count,
            }
        )

    hist: dict[str, list[str]] = {}
    for token in core_tokens + optional_tokens + [vs.variant_token for vs in variant_stats]:
        names = list((atlas.field_name_histograms or {}).get(token) or [])
        if names:
            hist[token] = names[:24]

    gaps: list[str] = []
    if not variant_stats and len(related) <= 1:
        gaps.append("no variant signatures observed for this candidate")
    overlap_items = [e for e in evidence if e.evidence_type == "field_name_overlap"]
    if overlap_items and all(e.facts.get("overlap_count", 0) == 0 for e in overlap_items):
        gaps.append(
            "no overlapping field names between candidate steps; "
            "source/destination transfer is not evidenced"
        )

    packet = InvestigationPacket(
        candidate_workflow_id=candidate.proposal_id or "candidate",
        candidate_name=candidate.name,
        core_tokens=core_tokens,
        optional_tokens=optional_tokens,
        ordered_applications=apps,
        ordered_object_types=objects,
        ordered_action_types=actions,
        event_count=atlas.summary.event_count,
        instance_count=atlas.summary.instance_count,
        distinct_users=atlas.summary.distinct_users,
        duration_stats={
            "related_median_duration_ms": (
                int(sum(durations) / len(durations)) if durations else 0
            ),
            "related_signature_count": len(related),
        },
        app_transitions=transitions,
        field_name_histograms=hist,
        sample_instance_ids=sample_ids,
        sample_step_orderings=sample_orderings,
        consistent_steps=consistent,
        subset_steps=subset_steps,
        motif_ids=list(candidate.supporting_motif_ids),
        variant_statistics=variant_stats,
        comparison_summaries=comparison_summaries,
        evidence=evidence,
        evidence_gaps=gaps,
        notes=[
            "Evidence packet is deterministic and privacy-scrubbed.",
            "Field histograms contain field names only, never values.",
        ],
    )
    scrubbed = _scrub_forbidden(packet.model_dump(mode="json"))
    return InvestigationPacket.model_validate(scrubbed)


def _clip_confidence(value: Any) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, conf))


def ground_investigation_payload(
    raw: dict[str, Any],
    packet: InvestigationPacket,
) -> tuple[
    list[InvestigationConclusion],
    list[SemanticRelationship],
    list[str],
    str,
    int,
]:
    """Drop unknown evidence ids; weaken or discard ungrounded conclusions."""
    allowed = {e.evidence_id for e in packet.evidence}
    for vs in packet.variant_statistics:
        if vs.evidence_id:
            allowed.add(vs.evidence_id)

    dropped = 0
    gaps: list[str] = [str(g) for g in (raw.get("evidence_gaps") or []) if g]
    gaps.extend(packet.evidence_gaps)

    conclusions: list[InvestigationConclusion] = []
    for item in raw.get("conclusions") or []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        rel = str(item.get("relationship") or "")
        if rel not in _RELATIONSHIPS:
            dropped += 1
            continue
        cited = [str(x) for x in (item.get("evidence_ids") or []) if x]
        valid = [eid for eid in cited if eid in allowed]
        invented = [eid for eid in cited if eid not in allowed]
        dropped += len(invented)
        local_gaps = [str(g) for g in (item.get("evidence_gaps") or []) if g]
        weakened = False
        if invented:
            local_gaps.append("unknown evidence ids were removed")
            weakened = True
        if not valid:
            gaps.append(
                f"dropped ungrounded conclusion ({rel}"
                + (f"/{item.get('subject')}" if item.get("subject") else "")
                + ")"
            )
            dropped += 1
            continue
        conf = _clip_confidence(item.get("confidence"))
        if weakened:
            conf = min(conf, 0.4)
            local_gaps.append("conclusion weakened due to invented evidence ids")
        conclusions.append(
            InvestigationConclusion(
                relationship=rel,  # type: ignore[arg-type]
                confidence=conf,
                reasoning=str(item.get("reasoning") or ""),
                evidence_ids=valid,
                evidence_gaps=local_gaps,
                subject=str(item.get("subject") or ""),
                weakened=weakened,
            )
        )

    semantics: list[SemanticRelationship] = []
    for item in raw.get("semantic_relationships") or []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        kind = str(item.get("kind") or "")
        if kind not in _SEMANTIC_KINDS:
            dropped += 1
            continue
        cited = [str(x) for x in (item.get("evidence_ids") or []) if x]
        valid = [eid for eid in cited if eid in allowed]
        invented = [eid for eid in cited if eid not in allowed]
        dropped += len(invented)
        local_gaps = [str(g) for g in (item.get("evidence_gaps") or []) if g]
        weakened = bool(invented)
        if invented:
            local_gaps.append("unknown evidence ids were removed")
        if not valid:
            gaps.append(f"dropped ungrounded semantic relationship ({kind})")
            dropped += 1
            continue
        conf = _clip_confidence(item.get("confidence"))
        if weakened:
            conf = min(conf, 0.4)
            if kind not in {"insufficient_evidence", "unknown"}:
                kind = "insufficient_evidence"
                local_gaps.append(
                    "kind forced to insufficient_evidence after invalid citations"
                )
        if kind in {"source_destination", "transformation"}:
            overlap_ok = False
            for eid in valid:
                ev = next((e for e in packet.evidence if e.evidence_id == eid), None)
                if (
                    ev
                    and ev.evidence_type == "field_name_overlap"
                    and ev.facts.get("overlap_count", 0)
                ):
                    overlap_ok = True
                    break
            if not overlap_ok:
                kind = "insufficient_evidence"
                local_gaps.append(
                    "source/destination requires cited field-name overlap evidence"
                )
                conf = min(conf, 0.35)
        semantics.append(
            SemanticRelationship(
                kind=kind,  # type: ignore[arg-type]
                from_token=str(item.get("from_token") or ""),
                to_token=str(item.get("to_token") or ""),
                confidence=conf,
                evidence_ids=valid,
                evidence_gaps=local_gaps,
                weakened=weakened,
            )
        )

    decision = str(raw.get("final_decision") or "insufficient_evidence")
    if decision not in {"safe_to_continue", "insufficient_evidence"}:
        decision = "insufficient_evidence"

    if (
        not conclusions or all(c.relationship == "insufficient_evidence" for c in conclusions)
    ) and not any(s.kind in {"source_destination", "transformation"} for s in semantics):
        decision = "insufficient_evidence"

    return conclusions, semantics, gaps, decision, dropped


def packet_contains_forbidden_content(packet: InvestigationPacket) -> list[str]:
    """Return forbidden substrings found in the packet JSON (for tests)."""
    blob = json.dumps(packet.model_dump(mode="json"), default=str).lower()
    hits: list[str] = []
    for needle in (
        "email body",
        "email_body",
        "cell_value",
        "sheet cell",
        "password",
        "clipboard",
        "raw_payload",
        "ground_truth_workflow",
    ):
        if needle in blob:
            hits.append(needle)
    return hits


def _result(
    *,
    status: str,
    generated_by: str,
    packet: InvestigationPacket,
    conclusions: list[InvestigationConclusion] | None = None,
    semantics: list[SemanticRelationship] | None = None,
    gaps: list[str] | None = None,
    notes: list[str] | None = None,
    decision: str = "insufficient_evidence",
) -> InvestigationResult:
    return InvestigationResult(
        status=status,  # type: ignore[arg-type]
        generated_by=generated_by,  # type: ignore[arg-type]
        model_name=settings.llm_model if generated_by == "llm" else "",
        candidate_workflow_id=packet.candidate_workflow_id,
        conclusions=conclusions or [],
        semantic_relationships=semantics or [],
        evidence=list(packet.evidence),
        variant_statistics=list(packet.variant_statistics),
        evidence_gaps=gaps if gaps is not None else list(packet.evidence_gaps),
        investigation_notes=notes or [],
        final_decision=decision,  # type: ignore[arg-type]
        packet=packet,
    )


async def investigate_candidate(
    atlas: ActivityAtlas,
    candidate: ProposedWorkflow,
    comparison_candidates: list[ProposedWorkflow] | None = None,
    *,
    client: Any = None,
) -> InvestigationResult:
    """Investigate one candidate workflow using a compact evidence packet."""
    client = client or llm
    atlas = ActivityAtlas.model_validate(atlas)
    candidate = ProposedWorkflow.model_validate(candidate)
    packet = build_investigation_packet(atlas, candidate, comparison_candidates)

    if not getattr(client, "available", False):
        return _result(
            status="insufficient_evidence",
            generated_by="fallback",
            packet=packet,
            notes=[_FALLBACK_NOTE],
            gaps=list(packet.evidence_gaps) + ["llm unavailable"],
            decision="insufficient_evidence",
        )

    used_fallback = False

    def fallback() -> dict[str, Any]:
        nonlocal used_fallback
        used_fallback = True
        return {
            "conclusions": [],
            "semantic_relationships": [],
            "evidence_gaps": [_FALLBACK_NOTE],
            "investigation_notes": [_FALLBACK_NOTE],
            "final_decision": "insufficient_evidence",
        }

    prompt = client.load_prompt(
        "investigate_workflow",
        evidence_packet_json=json.dumps(
            _scrub_forbidden(packet.model_dump(mode="json")),
            indent=2,
            default=str,
        ),
    )

    try:
        raw = await client.structured(
            prompt=prompt,
            tool=INVESTIGATE_WORKFLOW,
            fallback=fallback,
            max_tokens=2500,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("investigator structured call failed: %s", exc)
        return _result(
            status="unavailable",
            generated_by="fallback",
            packet=packet,
            notes=[_FALLBACK_NOTE, str(exc)],
            decision="insufficient_evidence",
        )

    if used_fallback or not isinstance(raw, dict):
        return _result(
            status="insufficient_evidence",
            generated_by="fallback",
            packet=packet,
            notes=[_FALLBACK_NOTE],
            decision="insufficient_evidence",
        )

    if not isinstance(raw.get("conclusions"), list):
        return _result(
            status="invalid",
            generated_by="fallback",
            packet=packet,
            notes=[_FALLBACK_NOTE],
            decision="insufficient_evidence",
        )

    try:
        conclusions, semantics, gaps, decision, dropped = ground_investigation_payload(
            raw, packet
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("investigator grounding failed: %s", exc)
        return _result(
            status="invalid",
            generated_by="fallback",
            packet=packet,
            notes=[_FALLBACK_NOTE, str(exc)],
            decision="insufficient_evidence",
        )

    notes = [str(n) for n in (raw.get("investigation_notes") or []) if n]
    if dropped:
        notes.append(f"dropped {dropped} ungrounded claim(s)")

    status = "ok"
    if decision == "insufficient_evidence" and (
        not conclusions
        or all(c.relationship == "insufficient_evidence" for c in conclusions)
    ):
        status = "insufficient_evidence"

    return _result(
        status=status,
        generated_by="llm",
        packet=packet,
        conclusions=conclusions,
        semantics=semantics,
        gaps=gaps,
        notes=notes or ["grounded investigation conclusions"],
        decision=decision,
    )


async def investigate_agent_analysis(
    atlas: ActivityAtlas,
    analysis: AgentAnalysis,
    *,
    client: Any = None,
) -> list[InvestigationResult]:
    """Service-level integration: investigate each discovery proposal.

    Does not modify Agent discovery behavior. Callers may run this between
    discovery and validation.
    """
    analysis = AgentAnalysis.model_validate(analysis)
    proposals = list(analysis.proposed_workflows)
    results: list[InvestigationResult] = []
    for i, candidate in enumerate(proposals):
        others = [p for j, p in enumerate(proposals) if j != i]
        results.append(
            await investigate_candidate(
                atlas,
                candidate,
                comparison_candidates=others,
                client=client,
            )
        )
    return results


__all__ = [
    "RelationshipKind",
    "build_investigation_packet",
    "compute_variant_statistics",
    "ground_investigation_payload",
    "investigate_agent_analysis",
    "investigate_candidate",
    "packet_contains_forbidden_content",
]
