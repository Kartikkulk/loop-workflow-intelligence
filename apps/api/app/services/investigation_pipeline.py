"""Small API-facing adapter for the existing investigation pipeline.

It reconstructs the privacy-bounded Activity Atlas from stored observations,
represents an already-discovered Cluster as an Agent candidate, then delegates
all semantic work and grounding to ``investigate_agent_analysis``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cluster import Cluster, TaskInstance
from app.models.event import Event
from app.schemas.agent import AgentAnalysis, CatalogEvidence, CoreStep, ProposedWorkflow
from app.schemas.investigation import ClusterInvestigationResponse, InvestigationResult
from app.schemas.validation import ValidationResult
from app.services.atlas import build_activity_atlas
from app.services.investigator import investigate_agent_analysis
from app.services.sessioniser import Instance
from app.services.validator import validate_agent_analysis


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    if not needle:
        return False
    position = 0
    for token in haystack:
        if token == needle[position]:
            position += 1
            if position == len(needle):
                return True
    return False


async def investigate_persisted_cluster(
    session: AsyncSession,
    cluster: Cluster,
    *,
    client: Any = None,
) -> ClusterInvestigationResponse:
    """Run Atlas → existing Investigator → existing Validator for one Cluster."""
    instance_result = await session.execute(
        select(TaskInstance).where(TaskInstance.cluster_id == cluster.id)
    )
    stored_instances = list(instance_result.scalars().all())
    event_ids = list(
        dict.fromkeys(
            event_id
            for stored_instance in stored_instances
            for event_id in (stored_instance.event_ids or [])
        )
    )
    event_result = await session.execute(select(Event).where(Event.id.in_(event_ids)))
    events_by_id = {event.id: event for event in event_result.scalars().all()}
    instances = [
        Instance(
            id=stored.id,
            user_id=stored.user_id,
            team=stored.team,
            events=[
                events_by_id[event_id]
                for event_id in (stored.event_ids or [])
                if event_id in events_by_id
            ],
        )
        for stored in stored_instances
    ]
    instances = [instance for instance in instances if instance.events]
    if not instances:
        return ClusterInvestigationResponse(
            cluster_id=cluster.id,
            investigation=InvestigationResult(
                status="unavailable",
                candidate_workflow_id=f"cluster_{cluster.id}",
                evidence_gaps=["no stored task-instance evidence for this cluster"],
                final_decision="insufficient_evidence",
            ),
            validation=ValidationResult(
                notes=["No stored task-instance evidence was available to validate."]
            ),
            automation_eligible=False,
        )

    atlas = build_activity_atlas(instances)

    core_tokens = list(cluster.signature or [])
    related = [
        row
        for row in atlas.signature_catalog
        if _is_subsequence(core_tokens, list(row.tokens))
        or _is_subsequence(list(row.tokens), core_tokens)
    ]
    signature_ids = [row.signature_id for row in related]
    sample_ids = list(
        dict.fromkeys(
            instance_id
            for row in related
            for instance_id in row.example_instance_ids
        )
    )[:8]

    proposal = ProposedWorkflow(
        proposal_id=f"cluster_{cluster.id}",
        name=cluster.name,
        description=cluster.description,
        supporting_signature_ids=signature_ids,
        supporting_sample_instance_ids=sample_ids,
        core_steps=[
            CoreStep(token=token, reason="persisted cluster representative signature")
            for token in core_tokens
        ],
        observed_applications=list(cluster.apps or []),
        evidence=CatalogEvidence(
            supporting_instances=sum(row.occurrence_count for row in related),
            total_occurrences=sum(row.occurrence_count for row in related),
            distinct_users=max((row.distinct_users for row in related), default=0),
        ),
        confidence=max(0.0, min(1.0, float(cluster.automatability))),
        evidence_gaps=(
            []
            if signature_ids
            else ["persisted cluster signature was not present in the bounded atlas"]
        ),
    )
    analysis = AgentAnalysis(
        status="ok",
        generated_by="fallback",
        proposed_workflows=[proposal],
        analysis_notes=[
            "Candidate reconstructed from an existing persisted Discovery cluster."
        ],
    )

    investigation_rows = await investigate_agent_analysis(atlas, analysis, client=client)
    investigation = investigation_rows[0]
    validation = validate_agent_analysis(atlas, analysis)
    validated = any(row.proposal_id == proposal.proposal_id for row in validation.validated)
    automation_eligible = (
        investigation.final_decision == "safe_to_continue" and validated
    )

    return ClusterInvestigationResponse(
        cluster_id=cluster.id,
        investigation=investigation,
        validation=validation,
        automation_eligible=automation_eligible,
    )
