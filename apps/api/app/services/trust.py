"""F7 — the trust ladder and shadow mode. The centrepiece.

OBSERVE -> SUGGEST -> SHADOW -> ASSIST -> AUTONOMOUS

The premise: an automation should not demand blind trust on day one. In SHADOW,
every time a trigger fires the automation records what it *would* have done
while the human does the task for real. Agreement over a rolling window is what
buys the next rung.

Demotion matters as much as promotion. A ladder you can only climb is not a
safety mechanism, it is a progress bar — so a single critical mismatch drops the
automation back down a rung immediately, regardless of how good its average is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.automation import Automation, TrustLevel
from app.models.execution import ShadowRun


@dataclass
class PromotionState:
    """Everything the console needs to render the ladder honestly.

    `blockers` exists so the disabled Promote button can say exactly what is
    still required — "needs 2 more runs above 90%" — rather than being mutely
    greyed out.
    """

    level: TrustLevel
    next_level: TrustLevel | None
    confidence: float
    runs_in_window: int
    runs_required: int
    average_score: float
    threshold: float
    critical_mismatches: int
    can_promote: bool
    should_demote: bool
    blockers: list[str]

    def as_dict(self) -> dict:
        return {
            "level": self.level.value,
            "next_level": self.next_level.value if self.next_level else None,
            "confidence": round(self.confidence, 4),
            "runs_in_window": self.runs_in_window,
            "runs_required": self.runs_required,
            "average_score": round(self.average_score, 4),
            "threshold": self.threshold,
            "critical_mismatches": self.critical_mismatches,
            "can_promote": self.can_promote,
            "should_demote": self.should_demote,
            "blockers": self.blockers,
        }


async def recent_runs(
    session: AsyncSession, automation_id: str, limit: int | None = None
) -> list[ShadowRun]:
    """The most recent shadow runs, newest first."""
    window = limit or settings.shadow_window
    result = await session.execute(
        select(ShadowRun)
        .where(ShadowRun.automation_id == automation_id)
        .order_by(desc(ShadowRun.sequence))
        .limit(window)
    )
    return list(result.scalars().all())


async def evaluate(session: AsyncSession, automation: Automation) -> PromotionState:
    """Compute the automation's promotion state from its shadow-run history."""
    window_runs = await recent_runs(session, automation.id, settings.shadow_window)
    lookback_runs = window_runs[: settings.demotion_lookback]

    scores = [r.score for r in window_runs]
    average = sum(scores) / len(scores) if scores else 0.0
    criticals_in_window = sum(1 for r in window_runs if r.critical_mismatch)
    criticals_in_lookback = sum(1 for r in lookback_runs if r.critical_mismatch)

    runs = len(window_runs)
    required = settings.shadow_min_runs
    threshold = settings.shadow_promotion_threshold

    blockers: list[str] = []
    if runs < required:
        blockers.append(f"needs {required - runs} more shadow run(s)")
    if average < threshold:
        blockers.append(
            f"rolling average is {average:.0%}, needs {threshold:.0%}"
        )
    if criticals_in_window:
        blockers.append(
            f"{criticals_in_window} critical field mismatch(es) in the last {runs} run(s)"
        )

    next_level = automation.trust_level.next_level()
    if next_level is None:
        blockers = ["already at the top of the ladder"]

    can_promote = not blockers and next_level is not None
    should_demote = criticals_in_lookback > 0 and automation.trust_level.rank > 0

    # Confidence is the rolling average, floored to zero while the window is
    # still filling so the bar does not read as high confidence on one run.
    confidence = average * min(1.0, runs / required) if required else average

    return PromotionState(
        level=automation.trust_level,
        next_level=next_level,
        confidence=confidence,
        runs_in_window=runs,
        runs_required=required,
        average_score=average,
        threshold=threshold,
        critical_mismatches=criticals_in_window,
        can_promote=can_promote,
        should_demote=should_demote,
        blockers=blockers,
    )


def _record_history(automation: Automation, level: TrustLevel, reason: str) -> None:
    """Append to the audit trail. Reassigned, not mutated, so SQLAlchemy sees it."""
    history = list(automation.trust_history or [])
    history.append(
        {
            "level": level.value,
            "reason": reason,
            "at": datetime.now(UTC).isoformat(),
        }
    )
    automation.trust_history = history


async def apply_promotion(
    session: AsyncSession, automation: Automation, *, force: bool = False
) -> tuple[bool, str]:
    """Promote one rung if the policy allows it.

    `force` is for the operator's explicit override and is recorded as such in
    the audit trail — an override that leaves no trace would defeat the point of
    having a ladder.
    """
    state = await evaluate(session, automation)
    target = automation.trust_level.next_level()
    if target is None:
        return False, "already at AUTONOMOUS"
    if not state.can_promote and not force:
        return False, "; ".join(state.blockers)

    automation.trust_level = target
    automation.confidence = state.confidence
    reason = (
        f"manual override by operator (average {state.average_score:.0%} over "
        f"{state.runs_in_window} run(s))"
        if force and not state.can_promote
        else (
            f"policy satisfied: {state.average_score:.0%} average over "
            f"{state.runs_in_window} run(s), no critical mismatches"
        )
    )
    _record_history(automation, target, reason)
    await session.flush()
    return True, reason


async def apply_demotion(
    session: AsyncSession, automation: Automation, reason: str | None = None
) -> tuple[bool, str]:
    """Drop one rung."""
    target = automation.trust_level.previous_level()
    if target is None:
        return False, "already at OBSERVE"
    automation.trust_level = target
    explanation = reason or "critical field mismatch detected"
    _record_history(automation, target, explanation)
    await session.flush()
    return True, explanation


async def enforce_policy(session: AsyncSession, automation: Automation) -> PromotionState:
    """Apply automatic demotion, then return the resulting state.

    Promotion is never automatic: the operator presses the button. Demotion is
    always automatic, because a system that waits for permission to become safer
    is not a safety mechanism.
    """
    state = await evaluate(session, automation)
    if state.should_demote:
        await apply_demotion(
            session,
            automation,
            f"critical field mismatch within the last {settings.demotion_lookback} run(s)",
        )
        state = await evaluate(session, automation)
    automation.confidence = state.confidence
    await session.flush()
    return state
