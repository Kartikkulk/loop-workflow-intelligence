"""F1 — ingestion endpoints: file upload and the plain-English fallback path."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.llm.client import llm
from app.llm.tools import ACTIONS, APPS, SYNTHESISE_EVENTS
from app.models.event import Event
from app.schemas.ingest import (
    DescribeRequest,
    DiscoveredWorkflow,
    EventOut,
    EventPage,
    IngestResult,
    SourceFacet,
)
from app.services.ids import new_id
from app.services.normaliser import NormalisedEvent, normalise_upload
from app.services.pipeline import run_detection

router = APIRouter(prefix="/ingest", tags=["ingest"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


async def _persist(session: AsyncSession, events: list[NormalisedEvent]) -> int:
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
                source=event.source,
                notes=event.notes,
            )
        )
    await session.flush()
    return len(events)


def _summarise(clusters: list) -> list[DiscoveredWorkflow]:
    """The discoveries, ordered so the strongest opportunity is first."""
    ranked = sorted(clusters, key=lambda c: (-(c.annual_hours or 0), -(c.instance_count or 0)))
    return [
        DiscoveredWorkflow(
            id=c.id,
            name=c.name,
            occurrences=c.instance_count,
            apps=list(c.apps or []),
            annual_hours=round(c.annual_hours or 0.0, 1),
            automatability=round(c.automatability or 0.0, 2),
        )
        for c in ranked
    ]

@router.post("/upload", response_model=IngestResult)
async def upload_events(
    file: UploadFile = File(..., description="Activity log as CSV or JSONL."),
    run_detection_after: bool = Query(default=True),
    session: AsyncSession = Depends(get_session),
) -> IngestResult:
    """Ingest an activity log, normalise it, and re-run detection."""
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(400, f"file is not valid UTF-8: {exc}") from exc

    events, errors = normalise_upload(file.filename or "upload.csv", text, source="upload")
    if not events:
        raise HTTPException(
            400,
            {
                "message": "no valid events found in upload",
                "errors": errors[:20],
            },
        )

    ingested = await _persist(session, events)
    clusters = await run_detection(session) if run_detection_after else []

    return IngestResult(
        ok=True,
        events_ingested=ingested,
        events_rejected=len(errors),
        errors=errors[:20],
        source="upload",
        clusters_detected=len(clusters),
        sessions=len({e.session_id for e in events if e.session_id}),
        applications=len({e.app for e in events}),
        workflows=_summarise(clusters),
    )


@router.get("/template.csv")
async def activity_template() -> FileResponse:
    """A working example of the activity CSV, downloadable from the console.

    The shipped demo fixture rather than a hand-written sample of it: a template
    that has drifted from what the parser accepts is worse than none, and this
    one is exercised by the test suite on every run.
    """
    path = Path(__file__).resolve().parents[3] / "fixtures" / "support-escalation-demo.csv"
    if not path.is_file():
        raise HTTPException(404, "the activity template is missing from this build")
    return FileResponse(
        path,
        media_type="text/csv",
        filename="loop-activity-template.csv",
    )

@router.post("/describe", response_model=IngestResult)
async def describe_workflow(
    body: DescribeRequest,
    session: AsyncSession = Depends(get_session),
) -> IngestResult:
    """Synthesise an event stream from prose.

    The fallback demo path: if a log upload misbehaves on stage, a spoken
    description of the task still produces detectable events. It is also the
    honest answer to "what if the customer has no activity logs at all?".
    """
    def fallback() -> dict:
        """Derive a step sequence from keywords in the description."""
        text = body.description.lower()
        steps: list[dict] = []
        # Ordered so the emitted sequence follows the order the words appear.
        signals = [
            (("email", "inbox", "mail", "outlook"), "gmail", "read", "email"),
            (("attachment", "pdf", "invoice", "extract", "scan"), "pdf", "extract", "fields"),
            (("download", "export"), "drive", "extract", "export_file"),
            (("filter", "look up", "search", "find", "match"), "sheets", "search", "rows"),
            (("spreadsheet", "sheet", "excel", "log", "record"), "sheets", "create", "row"),
            (("erp", "sap", "system", "ledger", "post"), "erp", "update", "record"),
            (("report", "summarise", "summarize", "aggregate"), "sheets", "update", "report"),
            (
                ("send", "email finance", "notify", "reply", "forward"),
                "gmail",
                "send",
                "notification",
            ),
            (("slack", "message the team"), "slack", "send", "message"),
        ]
        positions = []
        for keywords, app, action, object_type in signals:
            hit = min((text.find(k) for k in keywords if k in text), default=-1)
            if hit >= 0:
                positions.append((hit, app, action, object_type))
        positions.sort()
        durations = {
            "read": 45, "extract": 120, "create": 60,
            "update": 90, "send": 40, "search": 80,
        }
        for _, app, action, object_type in positions:
            steps.append(
                {
                    "app": app,
                    "action": action,
                    "object_type": object_type,
                    "duration_seconds": durations.get(action, 60),
                }
            )
        if len(steps) < 2:
            steps = [
                {"app": "gmail", "action": "read", "object_type": "email", "duration_seconds": 45},
                {"app": "sheets", "action": "create", "object_type": "row", "duration_seconds": 60},
            ]

        per_week = 5.0
        for token, value in (("daily", 5.0), ("every day", 5.0), ("weekly", 1.0),
                             ("every monday", 1.0), ("monthly", 0.25), ("twice a day", 10.0)):
            if token in text:
                per_week = value
                break
        return {
            "workflow_name": body.description.strip().split(".")[0][:80] or "Described workflow",
            "steps": steps,
            "per_week": per_week,
            "likely_users": 1,
        }

    synthesised = await llm.structured(
        prompt=llm.load_prompt(
            "describe_workflow",
            description=body.description,
            apps=", ".join(APPS),
            actions=", ".join(ACTIONS),
        ),
        tool=SYNTHESISE_EVENTS,
        fallback=fallback,
    )

    steps = list(synthesised.get("steps") or [])
    if not steps:
        raise HTTPException(422, "could not derive any workflow steps from that description")

    per_week = max(0.25, float(synthesised.get("per_week", 5.0)))
    users = max(1, min(6, int(synthesised.get("likely_users", 1))))
    workflow_name = str(synthesised.get("workflow_name") or "Described workflow")[:200]

    # Synthesise enough instances to clear the detection floor, otherwise the
    # described workflow is ingested and then invisible — the worst outcome.
    rng = random.Random(len(body.description))
    user_ids = [body.user_id] + [f"{body.user_id}_{i}" for i in range(1, users)]
    instances_needed = max(12, int(per_week * body.weeks))
    start = datetime.now(UTC) - timedelta(weeks=body.weeks)

    generated: list[NormalisedEvent] = []
    for index in range(instances_needed):
        user_id = user_ids[index % len(user_ids)]
        cursor = start + timedelta(
            days=(index / max(instances_needed, 1)) * body.weeks * 7,
            hours=rng.randrange(9, 17),
            minutes=rng.randrange(0, 60),
        )
        session_id = new_id("ses")
        for step in steps:
            seconds = max(5, int(rng.gauss(float(step.get("duration_seconds", 60)), 12)))
            generated.append(
                NormalisedEvent(
                    id=new_id("evt"),
                    user_id=user_id,
                    team=body.team,
                    timestamp=cursor,
                    app=str(step.get("app", "browser")),
                    action=str(step.get("action", "read")),
                    object_type=str(step.get("object_type", "item")),
                    object_id=new_id("obj"),
                    duration_ms=seconds * 1000,
                    payload={"described": True, "workflow_hint": workflow_name},
                    session_id=session_id,
                    source="describe",
                    notes=step.get("note"),
                )
            )
            cursor += timedelta(seconds=seconds + rng.randrange(3, 30))

    ingested = await _persist(session, generated)
    clusters = await run_detection(session)

    return IngestResult(
        ok=True,
        events_ingested=ingested,
        events_rejected=0,
        errors=[],
        source="describe" if llm.available else "describe (heuristic)",
        clusters_detected=len(clusters),
        workflow_name=workflow_name,
    )


@router.post("/redetect", response_model=IngestResult)
async def redetect(session: AsyncSession = Depends(get_session)) -> IngestResult:
    """Re-run detection over the stored events without ingesting anything new."""
    clusters = await run_detection(session)
    return IngestResult(
        ok=True,
        events_ingested=0,
        events_rejected=0,
        errors=[],
        source="redetect",
        clusters_detected=len(clusters),
        workflow_name=None,
    )


@router.get("/events", response_model=EventPage)
async def list_events(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    source: str | None = Query(
        default=None,
        description="Only events from this source, e.g. 'upload' or 'browser_extension'.",
    ),
    app: str | None = Query(default=None, description="Only events in this application."),
    session: AsyncSession = Depends(get_session),
) -> EventPage:
    """Browse the canonical event stream, optionally filtered.

    Filtering happens in the query rather than in the browser. The stream is the
    whole event log — hundreds of thousands of rows on a real deployment — and a
    filter applied to whichever page happened to load would silently only search
    the most recent fifty events.
    """
    filters = []
    if source:
        filters.append(Event.source == source)
    if app:
        filters.append(Event.app == app)

    total = await session.execute(select(func.count()).select_from(Event).where(*filters))
    result = await session.execute(
        select(Event)
        .where(*filters)
        .order_by(Event.timestamp.desc())
        .limit(limit)
        .offset(offset)
    )

    # Facets are counted across the entire log, unfiltered, so selecting one
    # source does not make every other source disappear from the picker.
    source_rows = await session.execute(
        select(Event.source, func.count()).group_by(Event.source).order_by(func.count().desc())
    )
    app_rows = await session.execute(
        select(Event.app, func.count()).group_by(Event.app).order_by(func.count().desc())
    )

    return EventPage(
        total=int(total.scalar() or 0),
        sources=[SourceFacet(value=v or "unknown", count=c) for v, c in source_rows],
        apps=[SourceFacet(value=v or "unknown", count=c) for v, c in app_rows],
        items=[
            EventOut(
                id=e.id,
                user_id=e.user_id,
                team=e.team,
                timestamp=e.timestamp.isoformat(),
                app=e.app,
                action=e.action,
                object_type=e.object_type,
                duration_ms=e.duration_ms,
                payload=e.payload or {},
                session_id=e.session_id,
                source=e.source or "",
            )
            for e in result.scalars().all()
        ],
    )
