"""Deterministic validator for Agent workflow proposals.

The Agent proposes which atlas patterns may be the same repetitive work.
This module only checks that those claims match ActivityAtlas evidence.
It does not discover workflows and does not invent evidence.
"""

from __future__ import annotations

from app.schemas.agent import AgentAnalysis, CoreStep, OptionalStep, ProposedWorkflow
from app.schemas.atlas import ActivityAtlas
from app.schemas.validation import (
    ValidatedEvidence,
    ValidatedProposal,
    ValidationResult,
)

# A single observation is not repetition.
_MIN_REPETITION = 2


def _normalize_token(token: str) -> str:
    """Canonical form for step tokens. Exact observed ids only; no fuzzy matching."""
    return token.strip()


def _atlas_indexes(atlas: ActivityAtlas) -> tuple[dict[str, object], dict[str, object]]:
    signatures = {row.signature_id: row for row in atlas.signature_catalog}
    motifs = {row.motif_id: row for row in atlas.motif_catalog}
    return signatures, motifs


def _cited_tokens(
    atlas: ActivityAtlas,
    signature_ids: list[str],
    motif_ids: list[str],
) -> set[str]:
    tokens: set[str] = set()
    by_sig, by_motif = _atlas_indexes(atlas)
    for sid in signature_ids:
        row = by_sig.get(sid)
        if row is not None:
            tokens.update(_normalize_token(t) for t in row.tokens)
    for mid in motif_ids:
        row = by_motif.get(mid)
        if row is not None:
            tokens.update(_normalize_token(t) for t in row.tokens)
    return tokens


def _derive_evidence(
    atlas: ActivityAtlas,
    signature_ids: list[str],
    motif_ids: list[str],
) -> ValidatedEvidence:
    """Recount support from cited atlas rows. Ignore Agent-reported counts."""
    by_sig, by_motif = _atlas_indexes(atlas)
    sigs = [by_sig[sid] for sid in signature_ids if sid in by_sig]
    motifs = [by_motif[mid] for mid in motif_ids if mid in by_motif]

    sig_occ = sum(int(s.occurrence_count) for s in sigs)
    motif_occ = sum(int(m.total_occurrences) for m in motifs)
    motif_instances = sum(int(m.instance_support) for m in motifs)
    users = [int(s.distinct_users) for s in sigs] + [int(m.distinct_users) for m in motifs]

    # Prefer signature occurrence totals as instance support when signatures
    # were cited; otherwise fall back to motif instance_support.
    instance_count = sig_occ if sigs else motif_instances
    occurrence_count = max(sig_occ, motif_occ)

    # A candidate group whose members exactly match the cited signatures can
    # supply an aggregate count. Partial membership must not inflate support.
    cited = set(signature_ids)
    if cited:
        for group in atlas.candidate_groups:
            members = set(group.member_signature_ids or [])
            if cited == members:
                occurrence_count = max(occurrence_count, int(group.occurrence_count))
                instance_count = max(instance_count, int(group.occurrence_count))
                break

    return ValidatedEvidence(
        instance_count=instance_count,
        occurrence_count=occurrence_count,
        distinct_users=max(users) if users else 0,
        source="atlas_catalog",
    )


def _validation_score(
    *,
    citations_ok: bool,
    core_ok: bool,
    repetition_ok: bool,
    optional_clean: bool,
    evidence: ValidatedEvidence,
) -> float:
    """Simple evidence-backed score in [0, 1]. Not a probability."""
    score = 0.0
    if citations_ok:
        score += 0.25
    if core_ok:
        score += 0.35
    if repetition_ok:
        score += 0.25
    if optional_clean:
        score += 0.05
    if evidence.distinct_users >= 1:
        score += 0.05
    if evidence.occurrence_count >= 5 or evidence.instance_count >= 5:
        score += 0.05
    return round(min(1.0, score), 2)


def validate_proposal(
    atlas: ActivityAtlas,
    proposal: ProposedWorkflow,
) -> ValidatedProposal:
    """Validate one Agent proposal against atlas evidence."""
    issues: list[str] = []
    by_sig, by_motif = _atlas_indexes(atlas)

    known_sig_ids = [
        sid for sid in proposal.supporting_signature_ids if sid in by_sig
    ]
    unknown_sigs = [
        sid for sid in proposal.supporting_signature_ids if sid not in by_sig
    ]
    known_motif_ids = [
        mid for mid in proposal.supporting_motif_ids if mid in by_motif
    ]
    unknown_motifs = [
        mid for mid in proposal.supporting_motif_ids if mid not in by_motif
    ]

    if unknown_sigs:
        issues.append(f"unknown supporting_signature_ids: {unknown_sigs}")
    if unknown_motifs:
        issues.append(f"unknown supporting_motif_ids: {unknown_motifs}")

    citations_ok = not unknown_sigs and not unknown_motifs
    has_citation = bool(known_sig_ids or known_motif_ids)
    if not has_citation:
        issues.append("no supporting signature or motif cited")

    allowed = _cited_tokens(atlas, known_sig_ids, known_motif_ids)

    validated_core: list[CoreStep] = []
    invented_core: list[str] = []
    for step in proposal.core_steps:
        token = _normalize_token(step.token)
        if token and token in allowed:
            validated_core.append(CoreStep(token=token, reason=step.reason))
        elif token:
            invented_core.append(token)
    if invented_core:
        issues.append(f"ungrounded core steps: {invented_core}")
    if not validated_core:
        issues.append("no grounded core steps")

    validated_optional: list[OptionalStep] = []
    dropped_optional: list[str] = []
    for step in proposal.optional_steps:
        token = _normalize_token(step.token)
        if token and token in allowed:
            validated_optional.append(
                OptionalStep(token=token, frequency=step.frequency, reason=step.reason)
            )
        elif token:
            dropped_optional.append(token)
            issues.append(f"dropped unsupported optional step: {token}")

    evidence = _derive_evidence(atlas, known_sig_ids, known_motif_ids)
    repetition_ok = (
        evidence.occurrence_count >= _MIN_REPETITION
        or evidence.instance_count >= _MIN_REPETITION
    )
    if not repetition_ok:
        issues.append(
            f"insufficient repetition evidence "
            f"(occurrence_count={evidence.occurrence_count}, "
            f"instance_count={evidence.instance_count}; need >= {_MIN_REPETITION})"
        )

    core_ok = bool(validated_core) and not invented_core
    optional_clean = not dropped_optional
    score = _validation_score(
        citations_ok=citations_ok and has_citation,
        core_ok=core_ok,
        repetition_ok=repetition_ok,
        optional_clean=optional_clean,
        evidence=evidence,
    )

    is_valid = (
        citations_ok
        and has_citation
        and core_ok
        and repetition_ok
    )
    return ValidatedProposal(
        proposal_id=proposal.proposal_id,
        proposal_name=proposal.name,
        status="validated" if is_valid else "rejected",
        validation_score=score if is_valid else min(score, 0.4),
        agent_confidence=proposal.confidence,
        supporting_signature_ids=(
            known_sig_ids if is_valid else list(proposal.supporting_signature_ids)
        ),
        supporting_motif_ids=(
            known_motif_ids if is_valid else list(proposal.supporting_motif_ids)
        ),
        validated_core_steps=validated_core,
        validated_optional_steps=validated_optional if is_valid else [],
        dropped_optional_steps=dropped_optional,
        evidence=evidence,
        issues=issues,
    )


def validate_agent_analysis(
    atlas: ActivityAtlas,
    analysis: AgentAnalysis,
) -> ValidationResult:
    """Validate every proposal in an AgentAnalysis against the ActivityAtlas."""
    atlas = ActivityAtlas.model_validate(atlas)
    analysis = AgentAnalysis.model_validate(analysis)

    validated: list[ValidatedProposal] = []
    rejected: list[ValidatedProposal] = []
    for proposal in analysis.proposed_workflows:
        result = validate_proposal(atlas, proposal)
        if result.status == "validated":
            validated.append(result)
        else:
            rejected.append(result)

    notes = [
        "Validator checks Agent claims against ActivityAtlas evidence only.",
        "Evidence counts are derived from the atlas catalog, not from the Agent.",
    ]
    if not analysis.proposed_workflows:
        notes.append("no proposals to validate")

    return ValidationResult(validated=validated, rejected=rejected, notes=notes)
