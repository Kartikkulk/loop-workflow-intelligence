"""F4/F6/F7 — automation detail, replay, promotion and the SSE trust stream."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.db.session import SessionLocal, get_session
from app.models.automation import Automation
from app.models.cluster import Cluster
from app.models.event import Event
from app.models.execution import ShadowRun
from app.models.governance import ExceptionCase, Patch
from app.schemas.automations import (
    AutomationDetail,
    AutomationList,
    AutomationSummary,
    GuardsOut,
    N8nExport,
    N8nPushResult,
    N8nRun,
    N8nRunList,
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
from app.services.n8n_export import SCHEDULES, to_n8n_workflow
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
        n8n_workflow_id=automation.n8n_workflow_id or "",
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


async def _observed_constants(
    session: AsyncSession, cluster_id: str
) -> dict[str, object]:
    """Payload fields the log shows exactly one value for, across every run.

    These are the facts a generated workflow can safely hard-code. A field that
    varied would be wrong to fix in place; a field that never varied is not
    really an input at all, and leaving it as an expression produces a node
    that resolves to undefined on its first run.
    """
    rows = await session.execute(
        select(Event.payload).where(Event.session_id.isnot(None)).limit(2000)
    )
    seen: dict[str, set[str]] = {}
    for (payload,) in rows:
        for key, value in (payload or {}).items():
            if key == "workflow_hint" or value in (None, ""):
                continue
            seen.setdefault(key, set()).add(str(value))
    return {key: next(iter(values)) for key, values in seen.items() if len(values) == 1}


#: n8n node types that cannot run until somebody picks an account for them.
_NEEDS_ACCOUNT = (
    "gmail", "microsoftOutlook", "jira", "slack", "googleSheets",
    "googleDrive", "github", "jenkins",
)


@router.get("/{automation_id}/n8n", response_model=N8nExport)
async def export_to_n8n(
    automation_id: str,
    schedule: str = Query(
        default="manual",
        description="How often the exported workflow should run: "
        + ", ".join(SCHEDULES),
    ),
    session: AsyncSession = Depends(get_session),
) -> N8nExport:
    """This automation as an importable n8n workflow.

    LOOP decides what is worth automating and whether it has earned the right
    to act; n8n has the connectors and the credential handling to carry it out.
    No credential is ever written into the exported workflow — every node that
    needs an account is listed in `needs_credentials` for a person to wire up
    in n8n itself.
    """
    if schedule not in SCHEDULES:
        raise HTTPException(
            422, f"unknown schedule {schedule!r}; expected one of {', '.join(SCHEDULES)}"
        )
    automation = await _get_automation(session, automation_id)
    detail = await build_automation_detail(session, automation)
    constants = await _observed_constants(session, automation.cluster_id)
    workflow = to_n8n_workflow(
        detail.model_dump(), schedule=schedule, constants=constants
    )
    notes = list(workflow.pop("_loop_notes", []))
    needs = [
        node["name"]
        for node in workflow["nodes"]
        if any(node["type"].endswith(suffix) for suffix in _NEEDS_ACCOUNT)
    ]
    return N8nExport(workflow=workflow, notes=notes, needs_credentials=needs)


@router.post("/{automation_id}/n8n", response_model=N8nPushResult)
async def push_to_n8n(
    automation_id: str,
    schedule: str = Query(default="hourly", description="How often it should run."),
    session: AsyncSession = Depends(get_session),
) -> N8nPushResult:
    """Approve this automation by creating it in n8n, and say where to finish it.

    Approving does not start anything. The workflow is created **inactive and
    without credentials**, so the person still has to choose which account each
    node uses and switch it on inside n8n. That is the boundary that matters:
    LOOP can decide a workflow is worth running, but it cannot connect itself
    to somebody's Jira.

    Failure here is reported rather than swallowed. A button that says "approved"
    while nothing was created is worse than one that says why it could not be.
    """
    if schedule not in SCHEDULES:
        raise HTTPException(
            422, f"unknown schedule {schedule!r}; expected one of {', '.join(SCHEDULES)}"
        )
    automation = await _get_automation(session, automation_id)
    detail = await build_automation_detail(session, automation)
    constants = await _observed_constants(session, automation.cluster_id)
    workflow = to_n8n_workflow(
        detail.model_dump(), schedule=schedule, constants=constants
    )
    notes = list(workflow.pop("_loop_notes", []))
    needs = [
        node["name"]
        for node in workflow["nodes"]
        if any(node["type"].endswith(suffix) for suffix in _NEEDS_ACCOUNT)
    ]

    base = settings.n8n_base_url.rstrip("/")
    if not settings.n8n_api_key.strip():
        return N8nPushResult(
            ok=False,
            needs_credentials=needs,
            notes=notes,
            message=(
                f"No n8n API key is set. Open {base}, then Settings > n8n API, "
                "create a key, and put it in .env as LOOP_N8N_API_KEY."
            ),
        )

    payload = {
        "name": workflow["name"],
        "nodes": workflow["nodes"],
        "connections": workflow["connections"],
        "settings": workflow["settings"],
    }
    headers = {
        "X-N8N-API-KEY": settings.n8n_api_key.strip(),
        "Content-Type": "application/json",
    }
    existing = (automation.n8n_workflow_id or "").strip()
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            if not existing:
                # Resetting the demo clears the automations table, so the link
                # to n8n is lost even though the workflow is still sitting
                # there. Without this, every reset-and-approve left another
                # copy behind and the person had to guess which of five
                # identically-named workflows to configure.
                found = await client.get(
                    f"{base}/api/v1/workflows", headers=headers, params={"limit": 100}
                )
                if found.status_code == 200:
                    for candidate in found.json().get("data") or []:
                        if str(candidate.get("name")) == workflow["name"]:
                            existing = str(candidate.get("id", ""))
                            break
            # Approving twice must not leave two workflows behind. n8n happily
            # accepts duplicate names, so without this every click of the button
            # added another copy and the person had to work out which one they
            # were supposed to configure.
            if existing:
                update = await client.put(
                    f"{base}/api/v1/workflows/{existing}", headers=headers, json=payload
                )
                if update.status_code == 404:
                    existing = ""  # deleted in n8n; fall through and recreate
                else:
                    update.raise_for_status()
                    created = update.json()
            if not existing:
                response = await client.post(
                    f"{base}/api/v1/workflows", headers=headers, json=payload
                )
                response.raise_for_status()
                created = response.json()
    except httpx.HTTPStatusError as exc:
        return N8nPushResult(
            ok=False,
            needs_credentials=needs,
            notes=notes,
            message=f"n8n rejected the workflow ({exc.response.status_code}): "
            f"{exc.response.text[:200]}",
        )
    except httpx.HTTPError as exc:
        return N8nPushResult(
            ok=False,
            needs_credentials=needs,
            notes=notes,
            message=f"Could not reach n8n at {base}: {exc}. Is the container running?",
        )

    workflow_id = str(created.get("id", ""))
    # Recording this is what makes approval mean something in LOOP rather than
    # being a button that fires and forgets: the automation now points at the
    # thing that will run it, and the console can follow how it gets on.
    automation.n8n_workflow_id = workflow_id
    await session.flush()
    await session.commit()

    return N8nPushResult(
        ok=True,
        workflow_id=workflow_id,
        configure_url=f"{base}/workflow/{workflow_id}",
        needs_credentials=needs,
        notes=notes,
        message=(
            ("Updated in n8n. " if existing else "Created in n8n, switched off. ")
            + (
                "Choose the accounts for " + ", ".join(needs) + ", then turn it on."
                if needs
                else "Turn it on when you are ready."
            )
        ),
    )


@router.get("/{automation_id}/n8n/runs", response_model=N8nRunList)
async def n8n_runs(
    automation_id: str, session: AsyncSession = Depends(get_session)
) -> N8nRunList:
    """How the exported workflow is actually getting on inside n8n.

    Exporting a workflow and then losing sight of it is the failure mode worth
    designing against: the person is left switching between two tools to find
    out whether the thing LOOP recommended works. So LOOP asks n8n and reports
    what it says, naming the node that failed rather than only that something
    did.
    """
    automation = await _get_automation(session, automation_id)
    workflow_id = automation.n8n_workflow_id
    base = settings.n8n_base_url.rstrip("/")

    if not workflow_id:
        return N8nRunList(
            ok=False, message="Not exported yet. Approve it to build it in n8n."
        )
    configure_url = f"{base}/workflow/{workflow_id}"
    if not settings.n8n_api_key.strip():
        return N8nRunList(
            ok=False,
            workflow_id=workflow_id,
            configure_url=configure_url,
            message="No n8n API key is set, so LOOP cannot read its run history.",
        )

    headers = {"X-N8N-API-KEY": settings.n8n_api_key.strip()}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            workflow = await client.get(
                f"{base}/api/v1/workflows/{workflow_id}", headers=headers
            )
            workflow.raise_for_status()
            active = bool(workflow.json().get("active"))

            runs = await client.get(
                f"{base}/api/v1/executions",
                headers=headers,
                params={"workflowId": workflow_id, "limit": 20, "includeData": "false"},
            )
            runs.raise_for_status()
            data = runs.json()
    except httpx.HTTPStatusError as exc:
        return N8nRunList(
            ok=False,
            workflow_id=workflow_id,
            configure_url=configure_url,
            message=f"n8n returned {exc.response.status_code}: {exc.response.text[:160]}",
        )
    except httpx.HTTPError as exc:
        return N8nRunList(
            ok=False,
            workflow_id=workflow_id,
            configure_url=configure_url,
            message=f"Could not reach n8n at {base}: {exc}",
        )

    items: list[N8nRun] = []
    for row in data.get("data") or []:
        # n8n reports the outcome as `status`; older builds only set `finished`.
        status = str(row.get("status") or ("success" if row.get("finished") else "unknown"))
        items.append(
            N8nRun(
                id=str(row.get("id", "")),
                status=status,
                started_at=str(row.get("startedAt") or ""),
                finished_at=str(row.get("stoppedAt") or ""),
                failed_node=str(row.get("lastNodeExecuted") or ""),
                error=str(row.get("error") or "")[:300],
            )
        )

    succeeded = sum(1 for run in items if run.status == "success")
    failed = sum(1 for run in items if run.status in ("error", "crashed", "failed"))
    if not items:
        message = (
            "Switched on, waiting for its first run."
            if active
            else "Not switched on in n8n yet. Choose its accounts, then activate it."
        )
    elif failed:
        message = f"{failed} of the last {len(items)} runs failed."
    else:
        message = f"All of the last {len(items)} runs succeeded."

    return N8nRunList(
        ok=True,
        workflow_id=workflow_id,
        configure_url=configure_url,
        active=active,
        total=len(items),
        succeeded=succeeded,
        failed=failed,
        items=items,
        message=message,
    )


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
