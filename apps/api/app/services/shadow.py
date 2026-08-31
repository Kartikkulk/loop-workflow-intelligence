"""F7 support — producing a shadow run.

A shadow run pairs a prediction with a real human outcome. During the demo the
"live human action" is drawn from the historical log, which is the same
comparison a genuine deployment would make against a live observation — the only
difference is where the observation comes from.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import Automation
from app.models.event import Event
from app.models.execution import ExecutionMode, ShadowRun
from app.services.diffing import compare, explain_failure
from app.services.engine import engine
from app.services.ids import new_id
from app.services.replay import observed_outcome, source_payload, trigger_payload
from app.services.sessioniser import sessionise

# Upper bound on instances evaluated when searching for a specific outcome.
MAX_SEARCH = 200


async def _next_sequence(session: AsyncSession, automation_id: str) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(ShadowRun.sequence), 0)).where(
            ShadowRun.automation_id == automation_id
        )
    )
    return int(result.scalar() or 0) + 1


async def _candidate_instances(session: AsyncSession, automation: Automation) -> list:
    """Historical task instances that match this automation's trigger."""
    wanted = ((automation.trigger or {}).get("filter") or {}).get("object_type")
    result = await session.execute(select(Event).order_by(Event.timestamp))
    instances = sessionise(list(result.scalars().all()))
    if not wanted:
        return instances
    return [i for i in instances if i.events[0].object_type == wanted] or instances


async def simulate_shadow_run(
    session: AsyncSession,
    automation: Automation,
    *,
    force_mismatch: bool = False,
    seed: int | None = None,
) -> ShadowRun:
    """Execute one shadow run and persist the comparison.

    `force_mismatch` deliberately selects an instance the automation gets wrong.
    It exists so demotion can be demonstrated on cue — a ladder that only ever
    goes up in front of an audience proves nothing about safety.
    """
    rng = random.Random(seed)
    instances = await _candidate_instances(session, automation)
    if not instances:
        raise ValueError("no historical instances match this automation's trigger")

    chosen = None
    outcome = None
    diff = None

    # Scan for an instance of the requested kind.
    #
    # The bound is deliberately generous. Only about 8% of invoices are the
    # foreign-currency cases that produce a genuine critical mismatch, so a
    # 25-instance sample would come up empty roughly one time in eight — and
    # silently return a *matching* run instead. That turns the most dramatic
    # button in the demo into a coin flip. Scanning up to 200 makes the miss
    # probability negligible, and each evaluation is a mocked in-process run.
    pool = list(instances)
    rng.shuffle(pool)
    for instance in pool[:MAX_SEARCH]:
        candidate_outcome = await engine.run(
            steps=automation.steps,
            guards=automation.guards or {},
            rules=automation.rules or [],
            mode=ExecutionMode.SHADOW,
            trigger_payload=trigger_payload(instance.events),
            source_payload=source_payload(instance.events),
        )
        expected = observed_outcome(instance.events)
        candidate_diff = compare(candidate_outcome.output, expected)

        # "Mismatch" means specifically a critical field disagreement — the
        # thing that actually forces a demotion. A guard hold is deliberately
        # excluded: withholding an irreversible step is the automation behaving
        # correctly, and it is recorded below as agreement. Counting it here
        # would select a run that then reports `critical_mismatch: false`.
        is_mismatch = (
            candidate_outcome.status != "needs_approval" and candidate_diff.critical_mismatch
        )
        if is_mismatch == force_mismatch:
            chosen, outcome, diff = instance, candidate_outcome, candidate_diff
            break
        if chosen is None:
            chosen, outcome, diff = instance, candidate_outcome, candidate_diff

    if chosen is None or outcome is None or diff is None:
        raise ValueError("no historical instances match this automation's trigger")

    # Be explicit rather than quietly substituting the wrong kind of run: a
    # caller that asked for a mismatch and got agreement would draw exactly the
    # wrong conclusion.
    produced_mismatch = outcome.status != "needs_approval" and diff.critical_mismatch
    if force_mismatch and not produced_mismatch:
        raise ValueError(
            f"searched {min(len(pool), MAX_SEARCH)} historical instances and found none "
            "this automation gets wrong. It may have been healed or patched since; "
            "run a replay to see whether any failures remain."
        )

    expected = observed_outcome(chosen.events)

    note = ""
    if outcome.status == "needs_approval":
        note = f"withheld for approval: {outcome.approval_reason}"
    elif outcome.status == "failed":
        note = f"execution failed: {outcome.error}"
    elif diff.diff_fields:
        note = explain_failure(diff, outcome.output, expected)
    else:
        note = f"agreed with the human on all {diff.compared} compared field(s)"

    # A run held back by a guard is not a disagreement; the automation behaved
    # exactly as designed, so it scores as agreement.
    if outcome.status == "needs_approval":
        score, critical = 1.0, False
        field_matches: dict = {}
    else:
        score, critical = diff.score, diff.critical_mismatch
        field_matches = diff.field_matches

    run = ShadowRun(
        id=new_id("shr"),
        automation_id=automation.id,
        trigger_event_id=chosen.events[0].id,
        predicted={k: outcome.output.get(k) for k in (field_matches or outcome.output)},
        observed={k: expected.get(k) for k in (field_matches or expected)},
        field_matches=field_matches,
        score=score,
        critical_mismatch=critical,
        sequence=await _next_sequence(session, automation.id),
        note=note,
    )
    session.add(run)

    automation.shadow_run_count = (automation.shadow_run_count or 0) + 1
    if critical:
        automation.critical_mismatch_count = (automation.critical_mismatch_count or 0) + 1
    await session.flush()
    return run


def run_as_dict(run: ShadowRun) -> dict:
    return {
        "id": run.id,
        "sequence": run.sequence,
        "trigger_event_id": run.trigger_event_id,
        "predicted": run.predicted,
        "observed": run.observed,
        "field_matches": run.field_matches,
        "score": round(run.score, 4),
        "critical_mismatch": run.critical_mismatch,
        "note": run.note,
        "created_at": (run.created_at or datetime.now(UTC)).isoformat(),
    }
