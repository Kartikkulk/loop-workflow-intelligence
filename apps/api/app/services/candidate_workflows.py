"""Live workflow candidates derived only from browser-extension observations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import Automation
from app.models.candidate import WorkflowCandidate
from app.models.event import Event
from app.models.source import SourceKind
from app.schemas.agent import AgentAnalysis, CatalogEvidence, CoreStep, ProposedWorkflow
from app.schemas.atlas import ActivityAtlas
from app.schemas.candidates import CandidateWorkflowOut
from app.schemas.investigation import InvestigationResult
from app.schemas.validation import ValidatedProposal, ValidationResult
from app.services.atlas import build_activity_atlas, signature_id_for
from app.services.clustering import ClusterResult, cluster_instances
from app.services.investigator import investigate_agent_analysis
from app.services.promotion import PersistedPromotion, persist_validated_proposal
from app.services.sessioniser import sessionise
from app.services.validator import validate_agent_analysis

_STATUS_RANK = {
    "observed": 0,
    "candidate": 1,
    "investigated": 2,
    "validated": 3,
}


class CandidateStateError(ValueError):
    """The requested lifecycle transition is not currently safe."""


@dataclass
class CandidateArtifact:
    candidate: WorkflowCandidate
    atlas: ActivityAtlas
    proposal: ProposedWorkflow


def _ordered_apps(tokens: list[str]) -> list[str]:
    apps: list[str] = []
    for token in tokens:
        app = token.split(":", 1)[0].strip() or "browser"
        if not apps or apps[-1] != app:
            apps.append(app)
    return apps


def _workflow_name(tokens: list[str]) -> str:
    apps = _ordered_apps(tokens)
    for period in range(1, len(apps) // 2 + 1):
        if all(app == apps[index % period] for index, app in enumerate(apps)):
            apps = apps[:period] + ([apps[0]] if apps[-1] == apps[0] else [])
            break
    labels = [
        "Browser" if app == "0" else app.replace("_", " ").title()
        for app in apps
    ]
    return " → ".join(labels) if labels else "Observed browser workflow"


def _display_signature(group: ClusterResult) -> list[str]:
    """Use one actually observed path, preferring informative cross-app work."""
    counts: dict[tuple[str, ...], int] = {}
    for instance in group.instances:
        key = tuple(instance.signature)
        counts[key] = counts.get(key, 0) + 1
    best = max(
        counts,
        key=lambda signature: (
            len(
                {
                    app
                    for app in _ordered_apps(list(signature))
                    if app not in {"0", "browser", "google"}
                }
            ),
            counts[signature],
            -len(signature),
            signature,
        ),
    )
    return list(best)


def _workflow_id(group: ClusterResult) -> str:
    signature_ids = sorted({signature_id_for(instance.signature) for instance in group.instances})
    digest = hashlib.sha256("|".join(signature_ids).encode()).hexdigest()
    return f"cand_{digest[:12]}"


def _confidence(occurrences: int, distinct_users: int, app_count: int) -> float:
    """Evidence confidence, not an LLM probability."""
    score = 0.25 + min(occurrences, 5) * 0.12
    if distinct_users > 1:
        score += 0.05
    if app_count > 1:
        score += 0.05
    return round(min(score, 0.95), 2)


def _proposal(candidate: WorkflowCandidate, atlas: ActivityAtlas) -> ProposedWorkflow:
    signature_ids = [
        signature_id
        for signature_id in (candidate.member_signature_ids or [])
        if any(row.signature_id == signature_id for row in atlas.signature_catalog)
    ]
    catalog = [
        row for row in atlas.signature_catalog if row.signature_id in set(signature_ids)
    ]
    sample_ids = [
        instance_id
        for instance_id in (candidate.sample_instance_ids or [])
        if any(row.instance_id == instance_id for row in atlas.sample_instances)
    ]
    return ProposedWorkflow(
        proposal_id=f"proposal_{candidate.workflow_id}",
        name=candidate.name,
        description=(
            "Observed from browser-extension activity and grouped by the existing "
            "sessioniser and workflow clustering service."
        ),
        supporting_signature_ids=signature_ids,
        supporting_sample_instance_ids=sample_ids,
        core_steps=[
            CoreStep(token=token, reason="observed browser workflow path")
            for token in (candidate.signature_tokens or [])
        ],
        observed_applications=list(candidate.apps or []),
        evidence=CatalogEvidence(
            supporting_instances=sum(row.occurrence_count for row in catalog),
            total_occurrences=sum(row.occurrence_count for row in catalog),
            distinct_users=max((row.distinct_users for row in catalog), default=0),
        ),
        confidence=candidate.confidence,
        evidence_gaps=[] if signature_ids else ["candidate signatures are outside atlas bounds"],
    )


async def refresh_browser_candidates(
    session: AsyncSession,
) -> list[CandidateArtifact]:
    """Recompute browser-only candidates and upsert their lifecycle records."""
    result = await session.execute(
        select(Event)
        .where(Event.source == SourceKind.BROWSER_EXTENSION.value)
        .order_by(Event.timestamp)
    )
    events = list(result.scalars().all())
    instances = sessionise(events)
    groups = cluster_instances(instances)
    atlas = build_activity_atlas(instances)

    existing_result = await session.execute(select(WorkflowCandidate))
    existing = {
        row.workflow_id: row for row in existing_result.scalars().all()
    }
    artifacts: list[CandidateArtifact] = []

    for group in groups:
        workflow_id = _workflow_id(group)
        signature = _display_signature(group)
        member_signature_ids = sorted(
            {signature_id_for(instance.signature) for instance in group.instances}
        )
        sample_ids = [instance.id for instance in group.instances[:8]]
        session_ids = {
            event.session_id
            for instance in group.instances
            for event in instance.events
            if event.session_id
        }
        users = {instance.user_id for instance in group.instances}
        first_seen = min(instance.started_at for instance in group.instances)
        last_seen = max(instance.ended_at for instance in group.instances)
        all_apps = list(dict.fromkeys(_ordered_apps(signature)))
        base_status = "candidate" if group.size >= 2 else "observed"
        row = existing.get(workflow_id)
        if row is None:
            row = WorkflowCandidate(
                workflow_id=workflow_id,
                name=_workflow_name(signature),
                signature_tokens=signature,
                member_signature_ids=member_signature_ids,
                sample_instance_ids=sample_ids,
                session_count=len(session_ids) or group.size,
                occurrence_count=group.size,
                distinct_users=len(users),
                apps=all_apps,
                first_seen=first_seen,
                last_seen=last_seen,
                confidence=_confidence(group.size, len(users), len(all_apps)),
                status=base_status,
            )
            session.add(row)
        else:
            row.name = _workflow_name(signature)
            row.signature_tokens = signature
            row.member_signature_ids = member_signature_ids
            row.sample_instance_ids = sample_ids
            row.session_count = len(session_ids) or group.size
            row.occurrence_count = group.size
            row.distinct_users = len(users)
            row.apps = all_apps
            row.first_seen = first_seen
            row.last_seen = last_seen
            row.confidence = _confidence(group.size, len(users), len(all_apps))
            if _STATUS_RANK.get(row.status, 0) < _STATUS_RANK[base_status]:
                row.status = base_status

        artifacts.append(
            CandidateArtifact(candidate=row, atlas=atlas, proposal=_proposal(row, atlas))
        )

    await session.flush()
    artifacts.sort(
        key=lambda item: (
            -_STATUS_RANK.get(item.candidate.status, 0),
            -item.candidate.occurrence_count,
            item.candidate.name,
        )
    )
    return artifacts


async def get_browser_candidate(
    session: AsyncSession, workflow_id: str
) -> CandidateArtifact | None:
    artifacts = await refresh_browser_candidates(session)
    return next(
        (artifact for artifact in artifacts if artifact.candidate.workflow_id == workflow_id),
        None,
    )


async def candidate_out(
    session: AsyncSession, candidate: WorkflowCandidate
) -> CandidateWorkflowOut:
    automation = (
        await session.get(Automation, candidate.automation_id)
        if candidate.automation_id
        else None
    )
    return CandidateWorkflowOut(
        workflow_id=candidate.workflow_id,
        name=candidate.name,
        signature_tokens=list(candidate.signature_tokens or []),
        session_count=candidate.session_count,
        occurrence_count=candidate.occurrence_count,
        distinct_users=candidate.distinct_users,
        apps=list(candidate.apps or []),
        first_seen=candidate.first_seen,
        last_seen=candidate.last_seen,
        confidence=candidate.confidence,
        status=candidate.status,
        investigation=(
            InvestigationResult.model_validate(candidate.investigation_result)
            if candidate.investigation_result
            else None
        ),
        validation=(
            ValidationResult.model_validate(candidate.validation_result)
            if candidate.validation_result
            else None
        ),
        automation_id=candidate.automation_id,
        automation_trust_level=(
            automation.trust_level.value if automation is not None else None
        ),
    )


async def investigate_browser_candidate(
    session: AsyncSession, artifact: CandidateArtifact
) -> InvestigationResult:
    analysis = AgentAnalysis(
        status="ok",
        generated_by="fallback",
        proposed_workflows=[artifact.proposal],
        analysis_notes=["Candidate deterministically derived from browser-extension events."],
    )
    results = await investigate_agent_analysis(artifact.atlas, analysis)
    result = results[0]
    artifact.candidate.investigation_result = result.model_dump(mode="json")
    artifact.candidate.status = "investigated"
    artifact.candidate.validation_result = None
    await session.flush()
    return result


async def validate_browser_candidate(
    session: AsyncSession, artifact: CandidateArtifact
) -> ValidationResult:
    stored = artifact.candidate.investigation_result
    if not stored:
        raise CandidateStateError("investigate this workflow before validation")
    investigation = InvestigationResult.model_validate(stored)
    if (
        investigation.status != "ok"
        or investigation.final_decision != "safe_to_continue"
    ):
        raise CandidateStateError(
            "investigation did not produce a safe-to-continue result"
        )

    analysis = AgentAnalysis(
        status="ok",
        generated_by="fallback",
        proposed_workflows=[artifact.proposal],
    )
    result = validate_agent_analysis(artifact.atlas, analysis)
    artifact.candidate.validation_result = result.model_dump(mode="json")
    artifact.candidate.status = "validated" if result.validated else "investigated"
    await session.flush()
    return result


async def automate_browser_candidate(
    session: AsyncSession, artifact: CandidateArtifact
) -> PersistedPromotion:
    if artifact.candidate.status != "validated":
        raise CandidateStateError("validate this workflow before creating automation")
    analysis = AgentAnalysis(
        status="ok",
        generated_by="fallback",
        proposed_workflows=[artifact.proposal],
    )
    validation = validate_agent_analysis(artifact.atlas, analysis)
    validated: ValidatedProposal | None = next(
        (
            item
            for item in validation.validated
            if item.proposal_id == artifact.proposal.proposal_id
        ),
        None,
    )
    if validated is None:
        artifact.candidate.status = "investigated"
        artifact.candidate.validation_result = validation.model_dump(mode="json")
        await session.flush()
        raise CandidateStateError("candidate no longer passes grounded validation")

    persisted = await persist_validated_proposal(session, artifact.atlas, validated)
    artifact.candidate.automation_id = persisted.automation.id
    artifact.candidate.validation_result = validation.model_dump(mode="json")
    await session.flush()
    return persisted
