"""Workflow Discovery Agent v1 — reason over an Activity Atlas.

The Agent proposes which observed patterns may be the same repetitive work.
Python still owns counting (via atlas catalog rows) and drops ungrounded
claims. This module does not promote Cluster/Discovery rows and does not
execute automations.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm.client import llm
from app.llm.tools import DISCOVER_WORKFLOWS
from app.models.agent_analysis import WorkflowAgentAnalysis
from app.schemas.agent import (
    AgentAnalysis,
    AutomationAssessment,
    CatalogEvidence,
    CoreStep,
    OptionalStep,
    ProposedWorkflow,
    RepetitionAssessment,
)
from app.schemas.atlas import ActivityAtlas
from app.services.atlas import atlas_as_jsonable
from app.services.ids import new_id

logger = logging.getLogger("loop.agent")

_FALLBACK_NOTE = (
    "LLM unavailable or returned unusable output; no agent discoveries were fabricated."
)
_EMPTY_NOTE = "Activity Atlas contained no signatures or motifs; no workflows were proposed."
_MIN_CORE_STEPS = 3


def atlas_fingerprint(atlas: ActivityAtlas) -> str:
    blob = json.dumps(atlas_as_jsonable(atlas), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _empty_llm_payload() -> dict[str, Any]:
    return {
        "proposed_workflows": [],
        "unrelated_patterns": [],
        "analysis_notes": [_FALLBACK_NOTE],
    }


def _token_app(token: str) -> str:
    return token.split(":")[0] if token else ""


def _atlas_allowlists(atlas: ActivityAtlas) -> dict[str, set[str]]:
    tokens: set[str] = set()
    sig_ids = {row.signature_id for row in atlas.signature_catalog}
    motif_ids = {row.motif_id for row in atlas.motif_catalog}
    cand_ids = {row.candidate_id for row in atlas.candidate_groups}
    sample_ids = {row.instance_id for row in atlas.sample_instances}
    for row in atlas.signature_catalog:
        tokens.update(row.tokens)
    for row in atlas.motif_catalog:
        tokens.update(row.tokens)
    for row in atlas.candidate_groups:
        tokens.update(row.medoid_signature)
    for row in atlas.sample_instances:
        tokens.update(row.signature)
    apps = {_token_app(t) for t in tokens if _token_app(t)}
    for row in atlas.app_transitions:
        apps.add(row.from_app)
        apps.add(row.to_app)
    return {
        "tokens": tokens,
        "signature_ids": sig_ids,
        "motif_ids": motif_ids,
        "candidate_ids": cand_ids,
        "sample_ids": sample_ids,
        "apps": apps,
        "pattern_ids": sig_ids | motif_ids | cand_ids,
    }


def _catalog_evidence(atlas: ActivityAtlas, sig_ids: list[str], motif_ids: list[str]) -> CatalogEvidence:
    """Read support from cited atlas rows. Not an instance-level recount."""
    sigs = [s for s in atlas.signature_catalog if s.signature_id in set(sig_ids)]
    motifs = [m for m in atlas.motif_catalog if m.motif_id in set(motif_ids)]
    sig_occ = sum(s.occurrence_count for s in sigs)
    motif_occ = sum(m.total_occurrences for m in motifs)
    users = [s.distinct_users for s in sigs] + [m.distinct_users for m in motifs]
    instances = sig_occ if sigs else sum(m.instance_support for m in motifs)
    return CatalogEvidence(
        supporting_instances=instances,
        total_occurrences=max(sig_occ, motif_occ),
        distinct_users=max(users) if users else 0,
        source="atlas_catalog",
    )


def _clip_token_list(values: list[str], allowed: set[str]) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for token in values:
        if token in allowed and token not in seen:
            kept.append(token)
            seen.add(token)
        elif token not in allowed:
            dropped.append(token)
    return kept, dropped


def _proposal_id(sig_ids: list[str], motif_ids: list[str]) -> str:
    digest = hashlib.sha256("|".join(sorted(sig_ids + motif_ids)).encode()).hexdigest()
    return f"proposal_{digest[:12]}"


def _generic_name(core_steps: list[CoreStep]) -> str:
    if not core_steps:
        return "Observed pattern"
    first = core_steps[0].token.split(":")
    last = core_steps[-1].token.split(":")
    start = first[2].replace("_", " ") if len(first) > 2 else first[0]
    end = last[2].replace("_", " ") if len(last) > 2 else last[0]
    if start == end:
        return f"{start} handling"
    return f"{start} to {end}"


def ground_agent_payload(raw: dict[str, Any], atlas: ActivityAtlas) -> tuple[list[ProposedWorkflow], list[str], int]:
    """Drop invented ids/tokens/apps. Fill evidence from the atlas catalog."""
    allow = _atlas_allowlists(atlas)
    dropped_total = 0
    proposals: list[ProposedWorkflow] = []

    for item in raw.get("proposed_workflows") or []:
        if not isinstance(item, dict):
            dropped_total += 1
            continue
        sig_ids = [
            sid
            for sid in (item.get("supporting_signature_ids") or [])
            if sid in allow["signature_ids"]
        ]
        motif_ids = [
            mid
            for mid in (item.get("supporting_motif_ids") or [])
            if mid in allow["motif_ids"]
        ]
        sample_ids = [
            iid
            for iid in (item.get("supporting_sample_instance_ids") or [])
            if iid in allow["sample_ids"]
        ]
        dropped_total += len(item.get("supporting_signature_ids") or []) - len(sig_ids)
        dropped_total += len(item.get("supporting_motif_ids") or []) - len(motif_ids)

        core: list[CoreStep] = []
        dropped_tokens: list[str] = []
        for step in item.get("core_steps") or []:
            if not isinstance(step, dict):
                continue
            token = str(step.get("token") or "")
            if token in allow["tokens"]:
                core.append(CoreStep(token=token, reason=str(step.get("reason") or "")))
            elif token:
                dropped_tokens.append(token)
        optional: list[OptionalStep] = []
        for step in item.get("optional_steps") or []:
            if not isinstance(step, dict):
                continue
            token = str(step.get("token") or "")
            if token in allow["tokens"]:
                freq = step.get("frequency")
                try:
                    frequency = float(freq) if freq is not None else 0.0
                except (TypeError, ValueError):
                    frequency = 0.0
                optional.append(
                    OptionalStep(
                        token=token,
                        frequency=max(0.0, min(1.0, frequency)),
                        reason=str(step.get("reason") or ""),
                    )
                )
            elif token:
                dropped_tokens.append(token)

        apps_kept, apps_dropped = _clip_token_list(
            [str(a) for a in (item.get("observed_applications") or [])],
            allow["apps"],
        )
        dropped_tokens.extend(apps_dropped)

        auto_raw = item.get("automation_assessment") or {}
        if not isinstance(auto_raw, dict):
            auto_raw = {}
        det, d1 = _clip_token_list(list(auto_raw.get("deterministic_steps") or []), allow["tokens"])
        jud, d2 = _clip_token_list(list(auto_raw.get("judgment_steps") or []), allow["tokens"])
        pot, d3 = _clip_token_list(
            list(auto_raw.get("potentially_automatable") or []), allow["tokens"]
        )
        hum, d4 = _clip_token_list(
            list(auto_raw.get("human_approval_points") or []), allow["tokens"]
        )
        dropped_tokens.extend(d1 + d2 + d3 + d4)
        dropped_total += len(dropped_tokens)

        if not sig_ids and not motif_ids:
            dropped_total += 1
            continue
        if len(core) < _MIN_CORE_STEPS:
            # Keep the proposal but force low confidence and a gap.
            pass

        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        gaps = [str(g) for g in (item.get("evidence_gaps") or []) if g]
        if dropped_tokens:
            gaps.append("ungrounded tokens were dropped")
            confidence = min(confidence, 0.4)
        if len(core) < _MIN_CORE_STEPS:
            gaps.append("fewer than 3 grounded core steps")
            confidence = min(confidence, 0.35)

        rep_raw = item.get("repetition_assessment") or {}
        if not isinstance(rep_raw, dict):
            rep_raw = {}
        strength = rep_raw.get("strength")
        if strength not in {"low", "medium", "high"}:
            strength = "low"
        if confidence <= 0.4:
            strength = "low"

        name = str(item.get("name") or "").strip() or _generic_name(core)
        evidence = _catalog_evidence(atlas, sig_ids, motif_ids)

        proposals.append(
            ProposedWorkflow(
                proposal_id=_proposal_id(sig_ids, motif_ids),
                name=name,
                description=str(item.get("description") or ""),
                supporting_signature_ids=sig_ids,
                supporting_motif_ids=motif_ids,
                supporting_sample_instance_ids=sample_ids,
                core_steps=core,
                optional_steps=optional,
                observed_applications=apps_kept,
                evidence=evidence,
                repetition_assessment=RepetitionAssessment(
                    strength=strength,
                    reason=str(rep_raw.get("reason") or ""),
                ),
                automation_assessment=AutomationAssessment(
                    deterministic_steps=det,
                    judgment_steps=jud,
                    potentially_automatable=pot,
                    human_approval_points=hum,
                ),
                confidence=confidence,
                evidence_gaps=gaps,
                dropped_ungrounded_tokens=dropped_tokens,
            )
        )

    unrelated = [
        str(p)
        for p in (raw.get("unrelated_patterns") or [])
        if str(p) in allow["pattern_ids"]
    ]
    return proposals, unrelated, dropped_total


def _analysis(
    *,
    status: str,
    generated_by: str,
    atlas: ActivityAtlas,
    proposals: list[ProposedWorkflow] | None = None,
    unrelated: list[str] | None = None,
    notes: list[str] | None = None,
    error: str | None = None,
) -> AgentAnalysis:
    extra = list(notes or [])
    if error:
        extra.append(error)
    return AgentAnalysis(
        status=status,  # type: ignore[arg-type]
        generated_by=generated_by,  # type: ignore[arg-type]
        model_name=settings.llm_model if generated_by == "llm" else "",
        evidence_hash=atlas_fingerprint(atlas),
        proposed_workflows=proposals or [],
        unrelated_patterns=unrelated or [],
        analysis_notes=extra,
    )


async def _persist(
    session: AsyncSession | None,
    analysis: AgentAnalysis,
    error: str | None = None,
) -> None:
    if session is None:
        return
    session.add(
        WorkflowAgentAnalysis(
            id=new_id("agan"),
            evidence_hash=analysis.evidence_hash,
            model_name=analysis.model_name,
            status=analysis.status,
            generated_by=analysis.generated_by,
            result=analysis.model_dump(mode="json"),
            error=error,
        )
    )
    await session.flush()


def _atlas_is_empty(atlas: ActivityAtlas) -> bool:
    return not atlas.signature_catalog and not atlas.motif_catalog


async def analyze_activity_atlas(
    atlas: ActivityAtlas,
    *,
    session: AsyncSession | None = None,
    client: Any = None,
) -> AgentAnalysis:
    """Run Agent v1 over an Activity Atlas. Does not write Cluster rows."""
    client = client or llm
    atlas = ActivityAtlas.model_validate(atlas)

    if _atlas_is_empty(atlas):
        analysis = _analysis(
            status="empty",
            generated_by="fallback",
            atlas=atlas,
            notes=[_EMPTY_NOTE],
        )
        await _persist(session, analysis)
        return analysis

    used_fallback = False

    def fallback() -> dict[str, Any]:
        nonlocal used_fallback
        used_fallback = True
        return _empty_llm_payload()

    prompt = client.load_prompt(
        "discover_workflows",
        atlas_json=json.dumps(atlas_as_jsonable(atlas), indent=2, default=str),
    )

    if not getattr(client, "available", False):
        analysis = _analysis(
            status="unavailable",
            generated_by="fallback",
            atlas=atlas,
            notes=[_FALLBACK_NOTE],
        )
        await _persist(session, analysis)
        return analysis

    try:
        raw = await client.structured(
            prompt=prompt,
            tool=DISCOVER_WORKFLOWS,
            fallback=fallback,
            max_tokens=3000,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("agent structured call failed: %s", exc)
        analysis = _analysis(
            status="unavailable",
            generated_by="fallback",
            atlas=atlas,
            notes=[_FALLBACK_NOTE],
            error=str(exc),
        )
        await _persist(session, analysis, error=str(exc))
        return analysis

    if used_fallback or not isinstance(raw, dict):
        analysis = _analysis(
            status="unavailable" if used_fallback else "invalid",
            generated_by="fallback",
            atlas=atlas,
            notes=[_FALLBACK_NOTE],
        )
        await _persist(session, analysis)
        return analysis

    if not isinstance(raw.get("proposed_workflows"), list) or not isinstance(
        raw.get("unrelated_patterns"), list
    ):
        analysis = _analysis(
            status="invalid",
            generated_by="fallback",
            atlas=atlas,
            notes=[_FALLBACK_NOTE],
        )
        await _persist(session, analysis)
        return analysis

    try:
        proposals, unrelated, dropped = ground_agent_payload(raw, atlas)
    except Exception as exc:  # noqa: BLE001
        logger.error("agent grounding failed: %s", exc)
        analysis = _analysis(
            status="invalid",
            generated_by="fallback",
            atlas=atlas,
            notes=[_FALLBACK_NOTE],
            error=str(exc),
        )
        await _persist(session, analysis, error=str(exc))
        return analysis

    notes = [str(n) for n in (raw.get("analysis_notes") or []) if n]
    if dropped:
        notes.append(f"dropped {dropped} ungrounded claim(s)")
    analysis = _analysis(
        status="ok",
        generated_by="llm",
        atlas=atlas,
        proposals=proposals,
        unrelated=unrelated,
        notes=notes or ["grounded agent proposals"],
    )
    await _persist(session, analysis)
    return analysis
