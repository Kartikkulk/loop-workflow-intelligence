"""Phase 6 — browser-only discovery candidate lifecycle."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.automation import Automation
from app.schemas.candidates import (
    CandidateAutomationResponse,
    CandidateInvestigationResponse,
    CandidateValidationResponse,
    CandidateWorkflowList,
)
from app.services.candidate_workflows import (
    CandidateArtifact,
    CandidateStateError,
    automate_browser_candidate,
    candidate_out,
    get_browser_candidate,
    investigate_browser_candidate,
    refresh_browser_candidates,
    validate_browser_candidate,
)

router = APIRouter(prefix="/candidates", tags=["candidates"])


async def _artifact_or_404(
    session: AsyncSession, workflow_id: str
) -> CandidateArtifact:
    artifact = await get_browser_candidate(session, workflow_id)
    if artifact is None:
        raise HTTPException(404, f"browser workflow candidate {workflow_id} not found")
    return artifact


@router.get("", response_model=CandidateWorkflowList)
async def list_candidates(
    session: AsyncSession = Depends(get_session),
) -> CandidateWorkflowList:
    """Discover workflows exclusively from source=browser_extension events."""
    artifacts = await refresh_browser_candidates(session)
    return CandidateWorkflowList(
        total=len(artifacts),
        items=[
            await candidate_out(session, artifact.candidate)
            for artifact in artifacts
        ],
    )


@router.post(
    "/{workflow_id}/investigate",
    response_model=CandidateInvestigationResponse,
)
async def investigate_candidate(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
) -> CandidateInvestigationResponse:
    artifact = await _artifact_or_404(session, workflow_id)
    result = await investigate_browser_candidate(session, artifact)
    return CandidateInvestigationResponse(
        candidate=await candidate_out(session, artifact.candidate),
        result=result,
    )


@router.post(
    "/{workflow_id}/validate",
    response_model=CandidateValidationResponse,
)
async def validate_candidate(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
) -> CandidateValidationResponse:
    artifact = await _artifact_or_404(session, workflow_id)
    try:
        result = await validate_browser_candidate(session, artifact)
    except CandidateStateError as exc:
        raise HTTPException(409, str(exc)) from exc
    return CandidateValidationResponse(
        candidate=await candidate_out(session, artifact.candidate),
        result=result,
    )


@router.post(
    "/{workflow_id}/automation",
    response_model=CandidateAutomationResponse,
)
async def create_candidate_automation(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
) -> CandidateAutomationResponse:
    artifact = await _artifact_or_404(session, workflow_id)
    if artifact.candidate.automation_id:
        existing = await session.get(Automation, artifact.candidate.automation_id)
        if existing is not None:
            return CandidateAutomationResponse(
                workflow_id=workflow_id,
                cluster_id=existing.cluster_id,
                automation_id=existing.id,
                trust_level=existing.trust_level.value,
                generated_by=existing.generated_by,
            )
    try:
        persisted = await automate_browser_candidate(session, artifact)
    except CandidateStateError as exc:
        raise HTTPException(409, str(exc)) from exc
    automation = persisted.automation
    return CandidateAutomationResponse(
        workflow_id=workflow_id,
        cluster_id=persisted.cluster.id,
        automation_id=automation.id,
        trust_level=automation.trust_level.value,
        generated_by=persisted.flow_provenance,
    )
