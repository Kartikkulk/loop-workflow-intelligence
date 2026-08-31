"""Demo control endpoints — the ones triggered live on stage.

Every one of these drives the *real* code path. `break-schema` genuinely renames
a column in the stored events and the drift detector genuinely rediscovers it;
nothing here fakes an outcome for the audience.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.automation import Automation
from app.models.event import Event
from app.models.execution import ExecutionMode
from app.schemas.automations import (
    ShadowRunOut,
    SimulateShadowRequest,
    TrustStateOut,
)
from app.schemas.common import Message
from app.schemas.governance import BreakSchemaRequest, BreakSchemaResult
from app.services import trust
from app.services.engine import engine
from app.services.exception_learning import recompute_coverage, record_exception
from app.services.healing import detect_and_heal
from app.services.replay import source_payload, trigger_payload
from app.services.sessioniser import sessionise
from app.services.shadow import run_as_dict, simulate_shadow_run

router = APIRouter(prefix="/demo", tags=["demo"])

# Upper bound on self-healing iterations per automation, so a pathological flow
# cannot spin here.
MAX_HEAL_PASSES = 8


class _ShadowResponse(ShadowRunOut):
    pass


@router.post("/simulate-shadow-run")
async def simulate_shadow(
    body: SimulateShadowRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """Fire one or more shadow runs on cue.

    In a real deployment these arrive when a human happens to do the task. On
    stage they need to arrive when the presenter presses a key, so the trust bar
    fills while the audience is watching it.
    """
    automation = await session.get(Automation, body.automation_id)
    if automation is None:
        raise HTTPException(404, f"automation {body.automation_id} not found")

    runs = []
    for index in range(body.count):
        run = await simulate_shadow_run(
            session,
            automation,
            force_mismatch=body.force_mismatch,
            seed=index,
        )
        runs.append(run)

    # Demotion is enforced immediately, so a forced mismatch drops the rung in
    # the same request the audience just watched.
    state = await trust.enforce_policy(session, automation)
    await recompute_coverage(session, automation)

    return {
        "ok": True,
        "runs": [ShadowRunOut(**run_as_dict(r)).model_dump() for r in runs],
        "trust": TrustStateOut(**state.as_dict()).model_dump(),
        "level": automation.trust_level.value,
    }


@router.post("/break-schema", response_model=BreakSchemaResult)
async def break_schema(
    body: BreakSchemaRequest = BreakSchemaRequest(),
    session: AsyncSession = Depends(get_session),
) -> BreakSchemaResult:
    """Rename a column in the stored events, then let self-healing find it.

    This is a genuine mutation of the data, not a scripted animation. The rename
    lands, the next execution's `depends_on` stops resolving, and F8 proposes the
    remapping from the schema it observes — which is why it works on any field,
    not just the one the demo script names.
    """
    query = select(Event)
    if body.app:
        query = query.where(Event.app == body.app)
    result = await session.execute(query)
    events = list(result.scalars().all())

    updated = 0
    for event in events:
        payload = dict(event.payload or {})
        if body.from_field in payload:
            payload[body.to_field] = payload.pop(body.from_field)
            # Reassigned, not mutated, so SQLAlchemy persists the JSON change.
            event.payload = payload
            updated += 1

    if updated == 0:
        raise HTTPException(
            409,
            {
                "message": (
                    f"no {body.app or 'stored'} events carry a "
                    f"'{body.from_field}' field"
                ),
                "hint": "check GET /api/v1/system for the current event counts",
            },
        )
    await session.flush()

    # Now run every automation once so the broken dependency actually surfaces.
    automations = list((await session.execute(select(Automation))).scalars().all())
    result = await session.execute(select(Event).order_by(Event.timestamp))
    all_events = list(result.scalars().all())
    instances = sessionise(all_events)

    patches_proposed = 0
    affected: list[str] = []

    for automation in automations:
        wanted = ((automation.trigger or {}).get("filter") or {}).get("object_type")
        candidates = [
            i for i in instances if not wanted or i.events[0].object_type == wanted
        ]
        if not candidates:
            continue

        # Use the most recent instance: the rename only affects recent data.
        instance = max(candidates, key=lambda i: i.started_at)
        trigger = trigger_payload(instance.events)
        source = source_payload(instance.events)

        # The engine halts at the first hard failure, so one pass only reveals
        # the first broken step. Loop until the flow either runs clean or stops
        # yielding new patches — a rename usually breaks several steps, and
        # healing one of them is not healing the automation.
        first_failing_step: str | None = None
        healed_any = False
        for _ in range(MAX_HEAL_PASSES):
            outcome = await engine.run(
                steps=automation.steps,
                guards=automation.guards or {},
                rules=automation.rules or [],
                mode=ExecutionMode.SHADOW,
                trigger_payload=trigger,
                source_payload=source,
            )
            unresolved = outcome.unresolved_fields
            if not unresolved:
                break

            failing_step = next(
                (r.step_id for r in outcome.step_results if r.unresolved), None
            )
            first_failing_step = first_failing_step or failing_step
            patches = await detect_and_heal(session, automation, unresolved, failing_step)
            if not patches:
                break
            patches_proposed += len(patches)
            healed_any = True
            if not any(p.status == "applied" for p in patches):
                # Everything left needs a human, so further passes cannot progress.
                break

        if not healed_any and first_failing_step is None:
            continue

        affected.append(automation.id)

        # A broken step is also a genuine exception for the human queue.
        await record_exception(
            session,
            automation,
            reason=(
                f"Step {first_failing_step} could not resolve its source field — "
                f"the '{body.from_field}' field was renamed to '{body.to_field}'."
            ),
            features={"unresolved": True, "renamed_field": body.from_field},
            confidence=0.0,
        )

    await session.flush()
    return BreakSchemaResult(
        ok=True,
        events_updated=updated,
        message=(
            f"Renamed '{body.from_field}' to '{body.to_field}' across {updated} "
            f"{body.app or 'stored'} event(s). {patches_proposed} patch(es) "
            f"proposed by drift detection."
        ),
        patches_proposed=patches_proposed,
        automations_affected=affected,
    )


@router.post("/seed-exceptions", response_model=Message)
async def seed_exceptions(
    automation_id: str,
    count: int = 4,
    session: AsyncSession = Depends(get_session),
) -> Message:
    """Generate genuine high-value exceptions so rule learning has evidence.

    Runs the automation against real historical instances and queues the ones
    its guard actually held back. The rule LOOP later proposes is therefore
    learned from real decisions, not seeded with a pre-written answer.
    """
    automation = await session.get(Automation, automation_id)
    if automation is None:
        raise HTTPException(404, f"automation {automation_id} not found")

    all_events = list(
        (await session.execute(select(Event).order_by(Event.timestamp))).scalars().all()
    )
    instances = sessionise(all_events)
    wanted = ((automation.trigger or {}).get("filter") or {}).get("object_type")
    candidates = [i for i in instances if not wanted or i.events[0].object_type == wanted]

    created = 0
    for instance in candidates:
        if created >= count:
            break
        payload = source_payload(instance.events)
        outcome = await engine.run(
            steps=automation.steps,
            guards=automation.guards or {},
            rules=automation.rules or [],
            mode=ExecutionMode.SHADOW,
            trigger_payload=trigger_payload(instance.events),
            source_payload=payload,
        )
        if outcome.status != "needs_approval":
            continue
        await record_exception(
            session,
            automation,
            reason=outcome.approval_reason or "guard held execution",
            features={
                "amount": payload.get("amount"),
                "currency": payload.get("currency"),
                "vendor": payload.get("vendor"),
            },
            confidence=outcome.confidence,
        )
        created += 1

    await session.flush()
    return Message(
        ok=True,
        message=(
            f"{created} exception(s) queued from real guard holds. Resolve at least "
            f"3 with the same decision to trigger a branch-rule proposal."
        ),
    )


@router.post("/reset", response_model=Message)
async def reset(session: AsyncSession = Depends(get_session)) -> Message:
    """Reset to a known-good demo state: reseed, redetect, regenerate.

    Backs `make demo`. Everything downstream of the event log is derived, so a
    reset is a truncate plus a re-run rather than a restore.
    """
    from app.services.demo_state import rebuild_demo_state

    summary = await rebuild_demo_state(session)
    return Message(ok=True, message=summary)
