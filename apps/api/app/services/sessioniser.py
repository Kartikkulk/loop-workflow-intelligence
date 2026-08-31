"""F2 step 1 + step 2 — sessionise events into task instances, then sign them.

Sessionising is the step that decides what counts as "one task". Get it wrong
and no amount of clever clustering recovers: too coarse and every task merges
into one blob, too fine and a single workflow shatters into fragments.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.config import settings
from app.models.event import Event
from app.services.ids import new_id

# An (app, action) pair treated as a hard context reset: the user has
# demonstrably left the previous task. Reading Slack or browsing an unrelated
# page is ambient activity, not a workflow step.
#
# Note what is *not* here: `browser:search` and `slack:send` are genuine steps in
# real workflows (looking up contract terms, flagging a mismatch to a channel),
# so treating them as boundaries would shatter those workflows.
_RESET_TOKENS = {("slack", "read"), ("browser", "navigate"), ("browser", "read")}


@dataclass
class Instance:
    """A sessionised task instance, before persistence."""

    user_id: str
    team: str
    events: list[Event]
    id: str = field(default_factory=lambda: new_id("ti"))

    @property
    def started_at(self) -> datetime:
        return self.events[0].timestamp

    @property
    def ended_at(self) -> datetime:
        last = self.events[-1]
        return last.timestamp + timedelta(milliseconds=last.duration_ms)

    @property
    def duration_ms(self) -> int:
        """Wall-clock span of the instance, floored at the sum of step durations."""
        span = int((self.ended_at - self.started_at).total_seconds() * 1000)
        return max(span, sum(e.duration_ms for e in self.events))

    @property
    def raw_signature(self) -> list[str]:
        """Every observed step token, interruptions included. Kept for audit."""
        return [e.step_token for e in self.events]

    @property
    def signature(self) -> list[str]:
        """The workflow's identity: raw steps with interruption bounces removed."""
        return collapse_interruptions(self.raw_signature)

    @property
    def event_ids(self) -> list[str]:
        return [e.id for e in self.events]

    @property
    def context_switches(self) -> int:
        """Interruption bounces inside this instance. Feeds the Interruption Tax."""
        return count_context_switches(self.events)

    @property
    def ground_truth_workflow(self) -> str | None:
        """Majority ground-truth label, for test assertions only."""
        labels = [e.ground_truth_workflow for e in self.events if e.ground_truth_workflow]
        if not labels:
            return None
        return max(set(labels), key=labels.count)


def collapse_interruptions(tokens: Sequence[str]) -> list[str]:
    """Remove interruption artefacts from a step sequence.

    Two patterns are stripped: an immediately repeated step, and an `A -> B -> A`
    bounce where the user left a step and came straight back to it.

    This matters because a workflow's *identity* should not change just because
    somebody glanced at the ERP halfway through. Without this collapse the same
    task fragments into dozens of near-identical clusters, one per place an
    interruption happened to land. The interruptions themselves are not
    discarded — `count_context_switches` reads them straight off the events, so
    the Interruption Tax still charges for every one.
    """
    result = list(tokens)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(result) - 2:
            if result[i] == result[i + 2] and result[i] != result[i + 1]:
                del result[i + 1 : i + 3]
                changed = True
                continue
            i += 1
        i = 0
        while i < len(result) - 1:
            if result[i] == result[i + 1]:
                del result[i + 1]
                changed = True
                continue
            i += 1
    return result


def signature_hash(signature: Sequence[str]) -> str:
    """Stable hash of an exact step sequence. Backs the fast clustering pass."""
    return hashlib.sha1("|".join(signature).encode()).hexdigest()[:16]


def signature_text(signature: Sequence[str]) -> str:
    """Human- and embedding-friendly rendering of a signature."""
    return " -> ".join(signature)


def count_context_switches(
    events: Sequence[Event], window_minutes: int | None = None
) -> int:
    """Count A -> B -> A application bounces within the configured window.

    This is the raw material for the Interruption Tax. A simple count of app
    changes would badly overcount: moving from email to a spreadsheet once, on
    purpose, is not an interruption. A bounce back to what you were doing is.
    """
    window = timedelta(minutes=window_minutes or settings.context_switch_window_minutes)
    switches = 0
    for i in range(len(events) - 2):
        a, b, c = events[i], events[i + 1], events[i + 2]
        if a.app != b.app and a.app == c.app and (c.timestamp - a.timestamp) <= window:
            switches += 1
    return switches


def sessionise(events: Iterable[Event], gap_minutes: int | None = None) -> list[Instance]:
    """Group a user's events into task instances.

    Splits on an idle gap longer than `gap_minutes`, on a hard context reset, or
    on an explicit session_id change when the source supplied one.
    """
    gap = timedelta(minutes=gap_minutes or settings.session_gap_minutes)
    by_user: dict[str, list[Event]] = {}
    for event in events:
        by_user.setdefault(event.user_id, []).append(event)

    instances: list[Instance] = []
    for user_id, user_events in by_user.items():
        ordered = sorted(user_events, key=lambda e: e.timestamp)
        current: list[Event] = []
        for event in ordered:
            # Checked before anything else: a resetting event belongs to no task,
            # including the one about to start. Testing it only when `current` is
            # non-empty let a reset become the *first* step of the next instance,
            # which polluted signatures with ambient noise.
            if (event.app, event.action) in _RESET_TOKENS:
                if current:
                    instances.append(
                        Instance(user_id=user_id, team=current[0].team, events=current)
                    )
                    current = []
                continue

            if current:
                previous = current[-1]
                previous_end = previous.timestamp + timedelta(milliseconds=previous.duration_ms)
                idle_too_long = (event.timestamp - previous_end) > gap
                explicit_split = (
                    event.session_id is not None
                    and previous.session_id is not None
                    and event.session_id != previous.session_id
                )
                if idle_too_long or explicit_split:
                    instances.append(
                        Instance(user_id=user_id, team=current[0].team, events=current)
                    )
                    current = []
            current.append(event)
        if current:
            instances.append(Instance(user_id=user_id, team=current[0].team, events=current))

    # A single observed action is not a workflow.
    return [i for i in instances if len(i.events) >= 2]
