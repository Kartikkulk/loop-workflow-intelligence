"""Rebuilds the demo to a known-good starting state.

Shared by `make demo`, `make seed` and POST /api/v1/demo/reset so all three
produce exactly the same state — a demo that resets differently depending on how
you reset it is worse than no reset at all.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.automation import Automation, TrustLevel
from app.models.cluster import Cluster, TaskInstance
from app.models.event import ActionRegistry, AppRegistry, Event
from app.models.execution import Execution, ShadowRun
from app.models.governance import ExceptionCase, Patch
from app.services.generator import generate_flow
from app.services.generator_seed import generate_events
from app.services.ids import new_id
from app.services.pipeline import run_detection

logger = logging.getLogger("loop.demo")

_APPS = [
    ("gmail", "Gmail", "email"),
    ("outlook", "Microsoft Outlook", "email"),
    ("sheets", "Spreadsheets", "data"),
    ("erp", "ERP", "system_of_record"),
    ("drive", "File storage", "documents"),
    ("slack", "Slack", "chat"),
    ("browser", "Web browser", "other"),
    ("pdf", "Document extraction", "documents"),
]

_ACTIONS = [
    ("read", "Read", False),
    ("create", "Create", False),
    ("update", "Update", False),
    ("delete", "Delete", True),
    ("send", "Send", True),
    ("extract", "Extract", False),
    ("search", "Search", False),
    ("navigate", "Navigate", False),
]


async def seed_registries(session: AsyncSession) -> None:
    """Populate the app/action registries if they are empty."""
    existing = await session.execute(select(AppRegistry.key))
    if not set(existing.scalars().all()):
        for key, label, category in _APPS:
            session.add(AppRegistry(key=key, label=label, category=category))
    existing_actions = await session.execute(select(ActionRegistry.key))
    if not set(existing_actions.scalars().all()):
        for key, label, irreversible in _ACTIONS:
            session.add(ActionRegistry(key=key, label=label, irreversible=irreversible))
    await session.flush()


async def clear_all(session: AsyncSession) -> None:
    """Truncate every table, children first."""
    for model in (
        ShadowRun,
        Execution,
        ExceptionCase,
        Patch,
        Automation,
        TaskInstance,
        Cluster,
        Event,
    ):
        await session.execute(delete(model))
    await session.flush()


async def seed_events(session: AsyncSession) -> int:
    """Generate and persist the synthetic activity log."""
    events = generate_events(seed=settings.seed, days=settings.seed_days)
    for event in events:
        session.add(
            Event(
                id=event.id,
                user_id=event.user_id,
                team=event.team,
                timestamp=event.timestamp,
                app=event.app,
                action=event.action,
                object_type=event.object_type,
                object_id=event.object_id,
                duration_ms=event.duration_ms,
                payload=event.payload,
                session_id=event.session_id,
                ground_truth_workflow=event.ground_truth_workflow,
                source="seed",
            )
        )
    await session.flush()
    return len(events)


async def generate_starting_automations(session: AsyncSession, limit: int = 3) -> list[str]:
    """Generate automations for the highest-priority automatable clusters.

    Each starts at SUGGEST — nothing begins trusted — except the hero workflow,
    which is placed in SHADOW so the demo can open on a ladder mid-climb rather
    than spend its first minute pressing buttons to get there.
    """
    result = await session.execute(
        select(Cluster)
        .where(Cluster.do_not_automate.is_(False))
        .order_by(Cluster.priority.desc())
        .limit(limit)
    )
    clusters = list(result.scalars().all())

    created: list[str] = []
    for index, cluster in enumerate(clusters):
        flow, provenance = await generate_flow(cluster)
        level = TrustLevel.SHADOW if index == 0 else TrustLevel.SUGGEST
        automation = Automation(
            id=new_id("auto"),
            cluster_id=cluster.id,
            name=flow["name"],
            description=flow["description"],
            trigger=flow["trigger"],
            steps=flow["steps"],
            guards=flow["guards"],
            rules=[],
            trust_level=level,
            generated_by=provenance,
            trust_history=[
                {"level": TrustLevel.SUGGEST.value, "reason": "generated from detected cluster"},
            ]
            + (
                [
                    {
                        "level": TrustLevel.SHADOW.value,
                        "reason": "placed in shadow mode for observation",
                    }
                ]
                if level is TrustLevel.SHADOW
                else []
            ),
        )
        session.add(automation)
        created.append(automation.id)

    await session.flush()
    return created


async def rebuild_demo_state(session: AsyncSession) -> str:
    """Full reset: registries, events, detection, starting automations."""
    await clear_all(session)
    await seed_registries(session)
    event_count = await seed_events(session)
    clusters = await run_detection(session)
    automations = await generate_starting_automations(session)

    do_not_automate = sum(1 for c in clusters if c.do_not_automate)
    hours = sum(c.annual_hours for c in clusters if not c.do_not_automate)

    summary = (
        f"{event_count} events, {len(clusters)} workflows detected "
        f"({do_not_automate} flagged do-not-automate), "
        f"{hours:,.0f} projected annual hours, "
        f"{len(automations)} automation(s) generated."
    )
    logger.info("demo state rebuilt: %s", summary)
    return summary
