"""Adapter: validated Agent proposal → F4 Cluster → persisted Automation.

Promotion builds an in-memory Cluster. Persistence writes that Cluster, calls
existing `generate_flow`, and stores an Automation the same way the cluster
API does. F5 is not modified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import Automation, TrustLevel
from app.models.cluster import Cluster
from app.schemas.atlas import ActivityAtlas
from app.schemas.validation import ValidatedEvidence, ValidatedProposal
from app.services.generator import generate_flow
from app.services.ids import new_id
from app.services.pipeline import cluster_id_for


class PromotionError(ValueError):
    """Raised when a proposal cannot be handed to F4 or persisted."""


@dataclass
class PromotedWorkflow:
    """In-memory F4 input plus validator-backed provenance."""

    cluster: Cluster
    core_tokens: list[str]
    optional_tokens: list[str]
    supporting_signature_ids: list[str]
    supporting_motif_ids: list[str]
    evidence: ValidatedEvidence
    validation_score: float
    agent_confidence: float
    issues: list[str] = field(default_factory=list)


@dataclass
class PersistedPromotion:
    """Cluster + Automation after F4, ready for the existing F5 engine."""

    promoted: PromotedWorkflow
    cluster: Cluster
    automation: Automation
    flow: dict
    flow_provenance: str


def _token_app(token: str) -> str:
    parts = token.split(":")
    return parts[0] if parts and parts[0] else "browser"


def _median_duration_ms(atlas: ActivityAtlas, signature_ids: list[str]) -> int:
    by_id = {row.signature_id: row for row in atlas.signature_catalog}
    durations = [
        int(by_id[sid].median_duration_ms)
        for sid in signature_ids
        if sid in by_id and by_id[sid].median_duration_ms
    ]
    if not durations:
        return 0
    return int(median(durations))


def _observed_fields(atlas: ActivityAtlas, tokens: list[str]) -> dict[str, list[str]]:
    histograms = atlas.field_name_histograms or {}
    out: dict[str, list[str]] = {}
    for token in tokens:
        names = histograms.get(token) or []
        if names:
            out[token] = list(names)
    return out


def promote_validated_proposal(
    atlas: ActivityAtlas,
    validated_proposal: ValidatedProposal,
) -> PromotedWorkflow:
    """Build the Cluster F4 expects. Rejects anything not status=validated."""
    atlas = ActivityAtlas.model_validate(atlas)
    proposal = ValidatedProposal.model_validate(validated_proposal)

    if proposal.status != "validated":
        raise PromotionError(
            f"cannot promote proposal with status={proposal.status!r}; "
            "only validated proposals may enter F4"
        )

    core_tokens = [step.token for step in proposal.validated_core_steps if step.token]
    if not core_tokens:
        raise PromotionError("validated proposal has no core steps")

    optional_tokens = [step.token for step in proposal.validated_optional_steps if step.token]
    evidence = proposal.evidence
    if evidence.source != "atlas_catalog":
        raise PromotionError("evidence must be atlas-derived, not agent-claimed")

    apps = list(dict.fromkeys(_token_app(token) for token in core_tokens))
    signature = list(core_tokens)
    cluster = Cluster(
        id=cluster_id_for(signature),
        name=proposal.proposal_name or "Observed pattern",
        description=(
            f"Promoted from validated Agent proposal {proposal.proposal_id or '(unnamed)'}. "
            f"Validator score {proposal.validation_score:.2f}; "
            f"agent confidence stored separately as {proposal.agent_confidence:.2f}."
        ),
        signature=signature,
        apps=apps,
        instance_count=evidence.instance_count,
        distinct_users=evidence.distinct_users,
        user_ids=[],
        teams=[],
        median_duration_ms=_median_duration_ms(atlas, proposal.supporting_signature_ids),
        observed_fields=_observed_fields(atlas, signature + optional_tokens),
        automatability=proposal.validation_score,
        reasoning=(
            "Source=agent_validated. "
            f"signatures={proposal.supporting_signature_ids} "
            f"motifs={proposal.supporting_motif_ids}."
        ),
        do_not_automate=False,
    )

    return PromotedWorkflow(
        cluster=cluster,
        core_tokens=signature,
        optional_tokens=optional_tokens,
        supporting_signature_ids=list(proposal.supporting_signature_ids),
        supporting_motif_ids=list(proposal.supporting_motif_ids),
        evidence=evidence,
        validation_score=proposal.validation_score,
        agent_confidence=proposal.agent_confidence,
        issues=list(proposal.issues),
    )


async def persist_promoted_cluster(
    session: AsyncSession,
    promoted: PromotedWorkflow,
) -> Cluster:
    """Insert or update the Cluster row. Does not invent events or TaskInstances."""
    if promoted.cluster is None:
        raise PromotionError("promoted workflow has no cluster")

    existing = await session.get(Cluster, promoted.cluster.id)
    if existing is None:
        session.add(promoted.cluster)
        await session.flush()
        return promoted.cluster

    # Same signature → same deterministic id. Refresh fields from the promotion.
    source = promoted.cluster
    existing.name = source.name
    existing.description = source.description
    existing.signature = list(source.signature or [])
    existing.apps = list(source.apps or [])
    existing.instance_count = source.instance_count
    existing.distinct_users = source.distinct_users
    existing.user_ids = list(source.user_ids or [])
    existing.teams = list(source.teams or [])
    existing.median_duration_ms = source.median_duration_ms
    existing.observed_fields = dict(source.observed_fields or {})
    existing.automatability = source.automatability
    existing.reasoning = source.reasoning
    existing.do_not_automate = source.do_not_automate
    await session.flush()
    promoted.cluster = existing
    return existing


async def persist_automation_from_cluster(
    session: AsyncSession,
    cluster: Cluster,
) -> tuple[Automation, dict, str]:
    """Call existing F4 `generate_flow` and persist Automation like the cluster API."""
    flow, provenance = await generate_flow(cluster)

    result = await session.execute(
        select(Automation).where(Automation.cluster_id == cluster.id)
    )
    automation = result.scalars().first()

    if automation is None:
        automation = Automation(
            id=new_id("auto"),
            cluster_id=cluster.id,
            name=flow["name"],
            description=flow["description"],
            trigger=flow["trigger"],
            steps=flow["steps"],
            guards=flow["guards"],
            rules=[],
            trust_level=TrustLevel.SUGGEST,
            generated_by=provenance,
            trust_history=[
                {
                    "level": TrustLevel.SUGGEST.value,
                    "reason": "automation generated from agent-validated cluster",
                }
            ],
        )
        session.add(automation)
    else:
        automation.name = flow["name"]
        automation.description = flow["description"]
        automation.trigger = flow["trigger"]
        automation.steps = flow["steps"]
        automation.guards = flow["guards"]
        automation.generated_by = provenance

    await session.flush()
    return automation, flow, provenance


async def persist_validated_proposal(
    session: AsyncSession,
    atlas: ActivityAtlas,
    validated_proposal: ValidatedProposal,
) -> PersistedPromotion:
    """Validated proposal → Cluster row → F4 generate_flow → Automation row."""
    promoted = promote_validated_proposal(atlas, validated_proposal)
    cluster = await persist_promoted_cluster(session, promoted)
    automation, flow, provenance = await persist_automation_from_cluster(session, cluster)
    return PersistedPromotion(
        promoted=promoted,
        cluster=cluster,
        automation=automation,
        flow=flow,
        flow_provenance=provenance,
    )
