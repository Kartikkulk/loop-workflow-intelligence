"""Minimal generic event trigger → existing F5 engine (REPLAY only).

Matches an incoming event against persisted Automation.trigger shapes produced
by F4 (`{type, filter}`). Does not invent a second trigger schema, does not
call live connectors, and does not modify the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import Automation, TrustLevel
from app.models.execution import ExecutionMode
from app.services.engine import ExecutionResult, engine

# F4 emits these trigger.type values (see generator._TRIGGER_BY_APP / fallback).
# Aliases only normalize event vocabulary onto that existing set.
_EVENT_TYPE_ALIASES = {
    "email_received": "email_received",
    "new_email": "email_received",
    "schedule": "schedule",
    "file_created": "file_created",
    "record_updated": "record_updated",
    "manual": "manual",
}

# OBSERVE means not yet a candidate to run. Everything from SUGGEST upward may
# be exercised in REPLAY for architecture proof.
_EXECUTABLE_TRUST = {
    TrustLevel.SUGGEST,
    TrustLevel.SHADOW,
    TrustLevel.ASSIST,
    TrustLevel.AUTONOMOUS,
}


@dataclass
class TriggerEvent:
    """Generic inbound event. No Gmail/Sales business semantics."""

    source: str = ""
    event_type: str = ""
    object_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class TriggerResult:
    matched: bool
    automation_id: str | None = None
    automation_name: str | None = None
    trigger: dict[str, Any] = field(default_factory=dict)
    step_count: int = 0
    execution_mode: str = ExecutionMode.REPLAY.value
    execution: ExecutionResult | None = None
    reason: str = ""
    candidates_considered: int = 0


def normalize_event_type(raw: str | None) -> str:
    text = (raw or "").strip().lower()
    if not text:
        return ""
    return _EVENT_TYPE_ALIASES.get(text, text)


def automation_trigger_matches(trigger: dict[str, Any] | None, event: TriggerEvent) -> bool:
    """Compare event attributes to the existing F4 trigger representation."""
    trig = dict(trigger or {})
    wanted = normalize_event_type(event.event_type or trig.get("type"))
    actual = normalize_event_type(str(trig.get("type") or ""))
    if not wanted or not actual:
        return False
    if wanted != actual:
        return False

    filt = dict(trig.get("filter") or {})
    if "object_type" in filt and filt["object_type"] not in (None, ""):
        event_object = event.object_type
        if event_object is None:
            event_object = (event.metadata or {}).get("object_type")
        if event_object is None or str(event_object) != str(filt["object_type"]):
            return False
    return True


def is_automation_executable(automation: Automation) -> bool:
    return automation.trust_level in _EXECUTABLE_TRUST


async def find_matching_automations(
    session: AsyncSession,
    event: TriggerEvent,
) -> list[Automation]:
    """Return matching executable automations in deterministic id order."""
    result = await session.execute(select(Automation).order_by(Automation.id.asc()))
    automations = list(result.scalars().all())
    return [
        auto
        for auto in automations
        if is_automation_executable(auto)
        and automation_trigger_matches(auto.trigger, event)
    ]


async def trigger_event(
    session: AsyncSession,
    event: TriggerEvent,
    *,
    source_payload: dict[str, Any] | None = None,
) -> TriggerResult:
    """Match one event to a persisted Automation and run existing F5 in REPLAY.

    Always REPLAY / mock. Never live side effects in this phase.
    """
    matches = await find_matching_automations(session, event)
    if not matches:
        return TriggerResult(
            matched=False,
            reason="no matching executable automation",
            candidates_considered=0,
            execution_mode=ExecutionMode.REPLAY.value,
        )

    # Deterministic: lowest automation id wins. No ranking heuristics.
    automation = matches[0]
    payload = dict(source_payload if source_payload is not None else (event.payload or {}))
    if event.metadata:
        payload.setdefault("_event_metadata", dict(event.metadata))
    if event.source:
        payload.setdefault("_event_source", event.source)

    execution = await engine.run(
        steps=list(automation.steps or []),
        guards=dict(automation.guards or {}),
        rules=list(automation.rules or []),
        mode=ExecutionMode.REPLAY,
        trigger_payload={
            "source": event.source,
            "event_type": normalize_event_type(event.event_type),
            "object_type": event.object_type,
        },
        source_payload=payload,
    )

    return TriggerResult(
        matched=True,
        automation_id=automation.id,
        automation_name=automation.name,
        trigger=dict(automation.trigger or {}),
        step_count=len(automation.steps or []),
        execution_mode=ExecutionMode.REPLAY.value,
        execution=execution,
        reason="matched",
        candidates_considered=len(matches),
    )
