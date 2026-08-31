"""F4/F6/F7 — automation detail, replay, promotion and the SSE trust stream."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.db.session import SessionLocal, get_session
from app.models.automation import Automation
from app.models.cluster import Cluster
from app.models.execution import ShadowRun
from app.models.governance import ExceptionCase, Patch
from app.schemas.automations import (
    AutomationDetail,
    AutomationList,
    AutomationSummary,
    GuardsOut,
    PromoteRequest,
    PromoteResult,
    ReplayReportOut,
    ReplayRequest,
    RuleOut,
    ShadowRunList,
    ShadowRunOut,
    StepOut,
    TrustStateOut,
)
from app.services import trust
from app.services.exception_learning import recompute_coverage
from app.services.replay import run_replay
from app.services.shadow import run_as_dict

router = APIRouter(prefix="/automations", tags=["automations"])

# How often the SSE stream re-reads promotion state. Fast enough that the
# confidence bar animates the moment a run lands, cheap enough to leave open.
_STREAM_INTERVAL_SECONDS = 1.0


async def _get_automation(session: AsyncSession, automation_id: str) -> Automation:
    automation = await session.get(Automation, automation_id)
    if automation is None:
        raise HTTPException(404, f"automation {automation_id} not found")
    return automation


async def _cluster_hours(session: AsyncSession, cluster_id: str) -> float:
    cluster = await session.get(Cluster, cluster_id)
    return cluster.annual_hours if cluster else 0.0


def _to_summary(automation: Automation, annual_hours: float) -> AutomationSummary:
    return AutomationSummary(
        id=automation.id,
        cluster_id=automation.cluster_id,
        name=automation.name,
        description=automation.description,
        trust_level=automation.trust_level.value,
        confidence=round(automation.confidence, 4),
        shadow_run_count=automation.shadow_run_count,
        critical_mismatch_count=automation.critical_mismatch_count,
        replay_accuracy=automation.replay_accuracy,
        replay_total=automation.replay_total,
        replay_human_count=automation.replay_human_count,
        coverage=round(automation.coverage, 4),
        generated_by=automation.generated_by,
        annual_hours=annual_hours,
        step_count=len(automation.steps or []),
        created_at=(automation.created_at or datetime.now(UTC)).isoformat(),
    )


async def build_automation_detail(
    session: AsyncSession, automation: Automation
) -> AutomationDetail:
    """Assemble the full automation payload, including live trust state."""
    state = await trust.evaluate(session, automation)
    annual_hours = await _cluster_hours(session, automation.cluster_id)

    open_exceptions = await session.execute(
        select(func.count())
        .select_from(ExceptionCase)
        .where(ExceptionCase.automation_id == automation.id, ExceptionCase.status == "open")
    )
    pending_patches = await session.execute(
        select(func.count())
        .select_from(Patch)
        .where(Patch.automation_id == automation.id, Patch.status == "proposed")
    )

    summary = _to_summary(automation, annual_hours)
    guards = automation.guards or {}
    return AutomationDetail(
        **summary.model_dump(),
        trigger=automation.trigger or {},
        steps=[StepOut(**s) for s in (automation.steps or [])],
        guards=GuardsOut(
            requires_approval_if=guards.get("requires_approval_if"),
            irreversible=list(guards.get("irreversible") or []),
        ),
        rules=[RuleOut(**r) for r in (automation.rules or [])],
        trust=TrustStateOut(**state.as_dict()),
        trust_history=list(automation.trust_history or []),
        open_exception_count=int(open_exceptions.scalar() or 0),
        pending_patch_count=int(pending_patches.scalar() or 0),
    )


@router.get("", response_model=AutomationList)
async def list_automations(session: AsyncSession = Depends(get_session)) -> AutomationList:
    """Every generated automation, most trusted first."""
    result = await session.execute(select(Automation))
    automations = list(result.scalars().all())
    items = []
    for automation in automations:
        items.append(_to_summary(automation, await _cluster_hours(session, automation.cluster_id)))
    items.sort(key=lambda a: (-a.confidence, a.name))
    return AutomationList(total=len(items), items=items)


@router.get("/{automation_id}", response_model=AutomationDetail)
async def get_automation(
    automation_id: str, session: AsyncSession = Depends(get_session)
) -> AutomationDetail:
    """One automation, with its flow definition and current trust state."""
    automation = await _get_automation(session, automation_id)
    return await build_automation_detail(session, automation)


@router.post("/{automation_id}/replay", response_model=ReplayReportOut)
async def replay_automation(
    automation_id: str,
    body: ReplayRequest = ReplayRequest(),
    session: AsyncSession = Depends(get_session),
) -> ReplayReportOut:
    """Backtest the automation against the historical log."""
    automation = await _get_automation(session, automation_id)
    report = await run_replay(session, automation, days=body.days)
    automation.replay_accuracy = report.accuracy
    automation.replay_total = report.total
    # A guard hold and a failed step both mean a person had to be involved.
    automation.replay_human_count = report.needs_approval + report.errored
    await recompute_coverage(session, automation)
    await session.flush()

    return ReplayReportOut(
        total=report.total,
        correct=report.correct,
        accuracy=report.accuracy,
        needs_approval=report.needs_approval,
        errored=report.errored,
        not_comparable=report.not_comparable,
        days=report.days,
        # Capped for payload size; failure_modes carries the full tally so no
        # failure disappears from the count.
        failures=[
            {
                "event_id": f.event_id,
                "reason": f.reason,
                "expected": f.expected,
                "predicted": f.predicted,
                "diff_fields": f.diff_fields,
                "critical": f.critical,
            }
            for f in report.failures[:25]
        ],
        failure_modes=dict(
            sorted(report.failure_modes.items(), key=lambda kv: -kv[1])
        ),
    )


@router.get("/{automation_id}/shadow-runs", response_model=ShadowRunList)
async def list_shadow_runs(
    automation_id: str, session: AsyncSession = Depends(get_session)
) -> ShadowRunList:
    """Shadow-run history with per-field agreement."""
    automation = await _get_automation(session, automation_id)
    result = await session.execute(
        select(ShadowRun)
        .where(ShadowRun.automation_id == automation_id)
        .order_by(ShadowRun.sequence.desc())
    )
    runs = list(result.scalars().all())
    state = await trust.evaluate(session, automation)
    return ShadowRunList(
        total=len(runs),
        items=[ShadowRunOut(**run_as_dict(r)) for r in runs],
        trust=TrustStateOut(**state.as_dict()),
    )


@router.post("/{automation_id}/promote", response_model=PromoteResult)
async def promote(
    automation_id: str,
    body: PromoteRequest = PromoteRequest(),
    session: AsyncSession = Depends(get_session),
) -> PromoteResult:
    """Promote one rung, if the policy allows it."""
    automation = await _get_automation(session, automation_id)
    ok, message = await trust.apply_promotion(session, automation, force=body.force)
    state = await trust.evaluate(session, automation)
    return PromoteResult(
        ok=ok,
        level=automation.trust_level.value,
        message=message,
        trust=TrustStateOut(**state.as_dict()),
    )


@router.post("/{automation_id}/demote", response_model=PromoteResult)
async def demote(
    automation_id: str, session: AsyncSession = Depends(get_session)
) -> PromoteResult:
    """Drop one rung."""
    automation = await _get_automation(session, automation_id)
    ok, message = await trust.apply_demotion(session, automation, "manual demotion by operator")
    state = await trust.evaluate(session, automation)
    return PromoteResult(
        ok=ok,
        level=automation.trust_level.value,
        message=message,
        trust=TrustStateOut(**state.as_dict()),
    )


@router.get("/{automation_id}/stream")
async def stream_trust(automation_id: str, request: Request) -> EventSourceResponse:
    """Server-sent events carrying live promotion state.

    This is what makes the confidence bar animate as shadow runs land, and it is
    the moment the demo turns on. Uses its own short-lived sessions rather than
    the request-scoped dependency, because a streaming response outlives the
    transaction the dependency would hold open.
    """

    async def publisher():
        last_payload: str | None = None
        while True:
            if await request.is_disconnected():
                break
            async with SessionLocal() as session:
                automation = await session.get(Automation, automation_id)
                if automation is None:
                    yield {
                        "event": "error",
                        "data": json.dumps({"message": f"automation {automation_id} not found"}),
                    }
                    break
                # Demotion is enforced here too, so a critical mismatch is
                # reflected on screen without waiting for a page refresh.
                state = await trust.enforce_policy(session, automation)
                await session.commit()

                payload = json.dumps(
                    {
                        "automation_id": automation.id,
                        "name": automation.name,
                        "trust": state.as_dict(),
                        "shadow_run_count": automation.shadow_run_count,
                        "coverage": round(automation.coverage, 4),
                        "replay_accuracy": automation.replay_accuracy,
                        "at": datetime.now(UTC).isoformat(),
                    }
                )

            # Only emit on change, plus a periodic keepalive.
            if payload != last_payload:
                last_payload = payload
                yield {"event": "trust", "data": payload}
            else:
                yield {"event": "ping", "data": "{}"}

            await asyncio.sleep(_STREAM_INTERVAL_SECONDS)

    return EventSourceResponse(publisher())
