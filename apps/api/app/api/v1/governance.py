"""F8 — exception queue, patch review, ROI analytics and system status."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.registry import connector_inventory
from app.db.session import get_session
from app.llm.client import llm
from app.models.automation import Automation, TrustLevel
from app.models.cluster import Cluster
from app.models.event import Event
from app.models.execution import ShadowRun
from app.models.governance import ExceptionCase, Patch
from app.schemas.governance import (
    ApplyPatchResult,
    ConnectorOut,
    CoveragePoint,
    ExceptionList,
    ExceptionOut,
    PatchList,
    PatchOut,
    ResolveExceptionRequest,
    ResolveExceptionResult,
    RoiAutomation,
    RoiReport,
    SystemStatus,
    TrustDistribution,
)
from app.services.exception_learning import (
    apply_rule_to_flow,
    propose_rules,
    recompute_coverage,
)
from app.services.healing import apply_patch_to_flow

router = APIRouter(tags=["governance"])


async def _automation_names(session: AsyncSession) -> dict[str, str]:
    result = await session.execute(select(Automation.id, Automation.name))
    return dict(result.all())


def _exception_out(case: ExceptionCase, name: str) -> ExceptionOut:
    return ExceptionOut(
        id=case.id,
        automation_id=case.automation_id,
        automation_name=name,
        reason=case.reason,
        input_features=case.input_features or {},
        signature_key=case.signature_key,
        confidence=case.confidence,
        status=case.status,
        human_decision=case.human_decision,
        human_note=case.human_note,
        created_at=(case.created_at or datetime.now(UTC)).isoformat(),
    )


def _patch_out(patch: Patch, name: str) -> PatchOut:
    return PatchOut(
        id=patch.id,
        automation_id=patch.automation_id,
        automation_name=name,
        kind=patch.kind,
        step_id=patch.step_id,
        field=patch.field,
        from_value=patch.from_value,
        to_value=patch.to_value,
        confidence=patch.confidence,
        auto_applicable=patch.auto_applicable,
        status=patch.status,
        rationale=patch.rationale,
        rule=patch.rule,
        evidence_count=patch.evidence_count,
        proposed_by=patch.proposed_by,
        created_at=(patch.created_at or datetime.now(UTC)).isoformat(),
    )


@router.get("/exceptions", response_model=ExceptionList)
async def list_exceptions(
    status: str | None = Query(default=None, pattern="^(open|resolved)$"),
    session: AsyncSession = Depends(get_session),
) -> ExceptionList:
    """The human queue: executions the automation was not confident about."""
    query = select(ExceptionCase).order_by(ExceptionCase.created_at.desc())
    if status:
        query = query.where(ExceptionCase.status == status)
    result = await session.execute(query)
    cases = list(result.scalars().all())
    names = await _automation_names(session)

    open_count = await session.execute(
        select(func.count()).select_from(ExceptionCase).where(ExceptionCase.status == "open")
    )
    return ExceptionList(
        total=len(cases),
        open_count=int(open_count.scalar() or 0),
        items=[_exception_out(c, names.get(c.automation_id, "")) for c in cases],
    )


@router.post("/exceptions/{exception_id}/resolve", response_model=ResolveExceptionResult)
async def resolve_exception(
    exception_id: str,
    body: ResolveExceptionRequest,
    session: AsyncSession = Depends(get_session),
) -> ResolveExceptionResult:
    """Record a human decision, then look for a rule worth learning.

    The decision is the training signal: enough matching decisions on the same
    input shape and Kriyā AI proposes the branch that would have handled them.
    """
    case = await session.get(ExceptionCase, exception_id)
    if case is None:
        raise HTTPException(404, f"exception {exception_id} not found")

    case.human_decision = body.decision
    case.human_note = body.note
    case.status = "resolved"
    await session.flush()

    automation = await session.get(Automation, case.automation_id)
    proposed = 0
    if automation is not None:
        patches = await propose_rules(session, automation)
        proposed = len(patches)
        await recompute_coverage(session, automation)

    message = f"recorded '{body.decision}'"
    if proposed:
        message += f"; {proposed} branch rule(s) now have enough evidence to propose"
    return ResolveExceptionResult(ok=True, message=message, rules_proposed=proposed)


@router.get("/patches", response_model=PatchList)
async def list_patches(
    status: str | None = Query(default=None, pattern="^(proposed|applied|rejected)$"),
    session: AsyncSession = Depends(get_session),
) -> PatchList:
    """Self-healing proposals and learned rules awaiting review."""
    query = select(Patch).order_by(Patch.created_at.desc())
    if status:
        query = query.where(Patch.status == status)
    result = await session.execute(query)
    patches = list(result.scalars().all())
    names = await _automation_names(session)

    proposed = await session.execute(
        select(func.count()).select_from(Patch).where(Patch.status == "proposed")
    )
    return PatchList(
        total=len(patches),
        proposed_count=int(proposed.scalar() or 0),
        items=[_patch_out(p, names.get(p.automation_id, "")) for p in patches],
    )


@router.post("/patches/{patch_id}/apply", response_model=ApplyPatchResult)
async def apply_patch(
    patch_id: str, session: AsyncSession = Depends(get_session)
) -> ApplyPatchResult:
    """Apply a proposed patch to the flow definition."""
    patch = await session.get(Patch, patch_id)
    if patch is None:
        raise HTTPException(404, f"patch {patch_id} not found")
    if patch.status == "applied":
        raise HTTPException(409, "patch has already been applied")

    automation = await session.get(Automation, patch.automation_id)
    if automation is None:
        raise HTTPException(404, f"automation {patch.automation_id} not found")

    if patch.kind == "rule":
        changed = apply_rule_to_flow(automation, patch)
        detail = "branch rule added to the flow definition"
    else:
        changed = apply_patch_to_flow(automation, patch)
        detail = f"remapped '{patch.from_value}' to '{patch.to_value}'"

    if not changed:
        raise HTTPException(409, "patch did not change the flow definition")

    patch.status = "applied"
    await recompute_coverage(session, automation)
    await session.flush()

    names = await _automation_names(session)
    return ApplyPatchResult(
        ok=True, message=detail, patch=_patch_out(patch, names.get(patch.automation_id, ""))
    )


@router.post("/patches/{patch_id}/reject", response_model=ApplyPatchResult)
async def reject_patch(
    patch_id: str, session: AsyncSession = Depends(get_session)
) -> ApplyPatchResult:
    """Dismiss a proposal without changing the flow."""
    patch = await session.get(Patch, patch_id)
    if patch is None:
        raise HTTPException(404, f"patch {patch_id} not found")
    patch.status = "rejected"
    await session.flush()
    names = await _automation_names(session)
    return ApplyPatchResult(
        ok=True,
        message="proposal dismissed",
        patch=_patch_out(patch, names.get(patch.automation_id, "")),
    )


@router.get("/analytics/roi", response_model=RoiReport)
async def roi(session: AsyncSession = Depends(get_session)) -> RoiReport:
    """Hours saved, tax recovered, coverage trend and trust distribution.

    `projected` is what the detected workflows are worth if fully automated.
    `realised` counts only automations that have actually earned ASSIST or
    above, scaled by their measured coverage — the number that is defensible
    rather than the number that is impressive.
    """
    clusters = list((await session.execute(select(Cluster))).scalars().all())
    automations = list((await session.execute(select(Automation))).scalars().all())
    by_cluster = {c.id: c for c in clusters}

    projected = sum(c.annual_hours for c in clusters if not c.do_not_automate)
    tax_total = sum(c.interruption_tax_hours for c in clusters if not c.do_not_automate)

    realised = 0.0
    tax_recovered = 0.0
    trusted_levels = {TrustLevel.ASSIST, TrustLevel.AUTONOMOUS}
    roi_rows: list[RoiAutomation] = []

    for automation in automations:
        cluster = by_cluster.get(automation.cluster_id)
        hours = cluster.annual_hours if cluster else 0.0
        tax = cluster.interruption_tax_hours if cluster else 0.0
        if automation.trust_level in trusted_levels:
            realised += hours * automation.coverage
            tax_recovered += tax * automation.coverage
        roi_rows.append(
            RoiAutomation(
                id=automation.id,
                name=automation.name,
                trust_level=automation.trust_level.value,
                coverage=round(automation.coverage, 4),
                annual_hours=hours,
                interruption_tax_hours=tax,
                replay_accuracy=automation.replay_accuracy,
                shadow_run_count=automation.shadow_run_count,
            )
        )

    distribution = {level: 0 for level in TrustLevel}
    for automation in automations:
        distribution[automation.trust_level] += 1

    # Coverage trend, reconstructed from the shadow-run sequence: the running
    # agreement rate over time is what a rising line actually means.
    trend: list[CoveragePoint] = []
    for automation in automations:
        runs = list(
            (
                await session.execute(
                    select(ShadowRun)
                    .where(ShadowRun.automation_id == automation.id)
                    .order_by(ShadowRun.sequence)
                )
            )
            .scalars()
            .all()
        )
        running = 0.0
        for index, run in enumerate(runs, start=1):
            running += run.score
            trend.append(
                CoveragePoint(
                    automation_id=automation.id,
                    automation_name=automation.name,
                    sequence=run.sequence,
                    coverage=round(running / index, 4),
                    score=round(run.score, 4),
                )
            )

    coverages = [a.coverage for a in automations]
    return RoiReport(
        projected_annual_hours=round(projected, 1),
        realised_annual_hours=round(realised, 1),
        interruption_tax_hours=round(tax_total, 1),
        interruption_tax_recovered_hours=round(tax_recovered, 1),
        total_clusters=len(clusters),
        automatable_clusters=sum(1 for c in clusters if not c.do_not_automate),
        do_not_automate_clusters=sum(1 for c in clusters if c.do_not_automate),
        total_automations=len(automations),
        autonomous_count=distribution[TrustLevel.AUTONOMOUS],
        average_coverage=round(sum(coverages) / len(coverages), 4) if coverages else 0.0,
        trust_distribution=[
            TrustDistribution(level=level.value, count=count)
            for level, count in distribution.items()
        ],
        automations=sorted(roi_rows, key=lambda r: -r.annual_hours),
        coverage_trend=trend,
    )


@router.get("/system", response_model=SystemStatus)
async def system_status(session: AsyncSession = Depends(get_session)) -> SystemStatus:
    """Configuration and connector inventory, for the questions judges ask."""
    events = await session.execute(select(func.count()).select_from(Event))
    clusters = await session.execute(select(func.count()).select_from(Cluster))
    automations = await session.execute(select(func.count()).select_from(Automation))

    return SystemStatus(
        mock_connectors=settings.enable_mock_connectors,
        connectors=[ConnectorOut(**c) for c in connector_inventory()],
        llm_available=llm.available,
        llm_model=(
            settings.llm_description
            if llm.available
            else "none (deterministic fallback)"
        ),
        llm_calls=llm.call_count,
        llm_fallbacks=llm.fallback_count,
        llm_estimated_cost_usd=round(llm.estimated_cost_usd, 4),
        event_count=int(events.scalar() or 0),
        cluster_count=int(clusters.scalar() or 0),
        automation_count=int(automations.scalar() or 0),
        settings={
            "session_gap_minutes": settings.session_gap_minutes,
            "cluster_threshold": settings.cluster_threshold,
            "sequence_weight": settings.sequence_weight,
            "set_weight": settings.set_weight,
            "org_user_threshold": settings.org_user_threshold,
            "interruption_cost_minutes": settings.interruption_cost_minutes,
            "do_not_automate_threshold": settings.do_not_automate_threshold,
            "shadow_window": settings.shadow_window,
            "shadow_promotion_threshold": settings.shadow_promotion_threshold,
            "shadow_min_runs": settings.shadow_min_runs,
            "demotion_lookback": settings.demotion_lookback,
            "patch_auto_apply_confidence": settings.patch_auto_apply_confidence,
            "exception_rule_min_samples": settings.exception_rule_min_samples,
        },
    )
