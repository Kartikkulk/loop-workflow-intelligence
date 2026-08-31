"""Source onboarding and the collector ingest endpoint.

This is how LOOP gets to *observe* rather than merely be fed. A collector — a
browser extension, a desktop agent, an API poller — registers once, receives a
bearer token, and posts batches of raw signals here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.domains import DOMAINS
from app.llm.client import llm
from app.llm.tools import ACTIONS, APPS, READ_FRAMES
from app.models.event import Event
from app.models.source import CaptureScope, Source, SourceKind, SourceStatus
from app.schemas.sources import (
    CapabilityOut,
    CollectBatch,
    CollectorConfig,
    CollectResult,
    DomainList,
    DomainOut,
    RecordingIngestRequest,
    RegisterSourceRequest,
    RegisterSourceResult,
    SourceList,
    SourceOut,
    ToolStatus,
    UpdateSourceRequest,
)
from app.services import sources as source_service
from app.services.ids import new_id
from app.services.normaliser import parse_timestamp
from app.services.web_activity import RawSignal, interpret

router = APIRouter(tags=["sources"])

# A copy in one application and a paste in another within this window is treated
# as one transfer. Long enough to cover a real tab switch, short enough that two
# unrelated copies of the same value do not get linked.
TRANSFER_WINDOW = timedelta(minutes=10)

BATCH_INTERVAL_SECONDS = 20
MAX_BATCH_SIZE = 200


def _source_out(source: Source) -> SourceOut:
    return SourceOut(
        id=source.id,
        kind=source.kind.value,
        label=source.label,
        user_id=source.user_id,
        team=source.team,
        status=source.status.value,
        capture_scope=source.capture_scope.value,
        consent_granted=source.consent_granted_at is not None,
        denylist=list(source.denylist or []),
        event_count=source.event_count,
        rejected_count=source.rejected_count,
        last_event_at=source.last_event_at.isoformat() if source.last_event_at else None,
        created_at=(source.created_at or datetime.now(UTC)).isoformat(),
    )


def _collector_config(source: Source) -> CollectorConfig:
    return CollectorConfig(
        source_id=source.id,
        status=source.status.value,
        capture_scope=source.capture_scope.value,
        denylist=list(source.denylist or []),
        batch_interval_seconds=BATCH_INTERVAL_SECONDS,
        max_batch_size=MAX_BATCH_SIZE,
        capture_field_values=source.capture_scope is CaptureScope.WITH_VALUES,
        capture_page_titles=source.capture_scope is CaptureScope.WITH_VALUES,
        consent_text=source.consent_text or source_service.CONSENT_TEXT,
    )


# ── onboarding ─────────────────────────────────────────────────────────────

@router.get("/sources", response_model=SourceList)
async def list_sources(session: AsyncSession = Depends(get_session)) -> SourceList:
    """Every onboarded source, the available tiers, and current coverage."""
    result = await session.execute(select(Source).order_by(Source.created_at.desc()))
    items = [_source_out(s) for s in result.scalars().all()]
    return SourceList(
        total=len(items),
        items=items,
        capabilities=[
            CapabilityOut(
                kind=c.kind.value,
                label=c.label,
                summary=c.summary,
                sees=c.sees,
                blind_to=c.blind_to,
                setup=c.setup,
                effort=c.effort,
                invasiveness=c.invasiveness,
                coverage_estimate=c.coverage_estimate,
                available=c.available,
                unavailable_reason=c.unavailable_reason,
            )
            for c in source_service.CAPABILITIES
        ],
        coverage=await source_service.coverage_report(session),
    )


@router.post("/sources", response_model=RegisterSourceResult, status_code=201)
async def register_source(
    body: RegisterSourceRequest, session: AsyncSession = Depends(get_session)
) -> RegisterSourceResult:
    """Onboard a source and mint its collector token.

    The token is returned here and nowhere else: only its hash is stored, so a
    database leak cannot be replayed as a collector.
    """
    try:
        kind = SourceKind(body.kind)
        scope = CaptureScope(body.capture_scope)
    except ValueError as exc:
        raise HTTPException(422, f"unknown kind or capture_scope: {exc}") from exc

    capability = next((c for c in source_service.CAPABILITIES if c.kind is kind), None)
    if capability is not None and not capability.available:
        raise HTTPException(
            409,
            {
                "message": f"{capability.label} cannot be connected in this build",
                "reason": capability.unavailable_reason,
            },
        )

    source, token = await source_service.register_source(
        session,
        kind=kind,
        label=body.label,
        user_id=body.user_id,
        team=body.team,
        capture_scope=scope,
        consent=body.consent,
        denylist=body.denylist,
    )
    await session.flush()
    await session.refresh(source)

    return RegisterSourceResult(
        source=_source_out(source),
        token=token,
        consent_text=source_service.CONSENT_TEXT,
        collector_config=_collector_config(source).model_dump(),
    )


@router.patch("/sources/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: str,
    body: UpdateSourceRequest,
    session: AsyncSession = Depends(get_session),
) -> SourceOut:
    """Pause, resume, revoke, or change what a source may capture."""
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(404, f"source {source_id} not found")

    if body.status is not None:
        try:
            target = SourceStatus(body.status)
        except ValueError as exc:
            raise HTTPException(422, f"unknown status: {body.status}") from exc
        if target is SourceStatus.CONNECTED and source.consent_granted_at is None:
            raise HTTPException(409, "cannot connect a source that has not granted consent")
        source.status = target

    if body.capture_scope is not None:
        try:
            source.capture_scope = CaptureScope(body.capture_scope)
        except ValueError as exc:
            raise HTTPException(422, f"unknown capture_scope: {body.capture_scope}") from exc

    if body.denylist is not None:
        source.denylist = list(body.denylist)

    await session.flush()
    return _source_out(source)


@router.delete("/sources/{source_id}")
async def revoke_source(
    source_id: str,
    delete_events: bool = Query(
        default=True,
        description="Delete the events this source reported. The default, deliberately.",
    ),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Revoke a source.

    Deleting the reported events is the default rather than an option buried
    behind a flag. Consent that cannot be withdrawn in full is not consent.
    """
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(404, f"source {source_id} not found")

    removed = 0
    if delete_events:
        counted = await session.execute(
            select(func.count()).select_from(Event).where(Event.source_id == source_id)
        )
        removed = int(counted.scalar() or 0)
        await session.execute(delete(Event).where(Event.source_id == source_id))

    source.status = SourceStatus.REVOKED
    source.token_hash = "revoked"
    await session.flush()
    return {
        "ok": True,
        "message": (
            f"Source revoked and its token invalidated. {removed} reported event(s) deleted."
            if delete_events
            else "Source revoked. Reported events retained."
        ),
        "events_deleted": removed,
    }


# ── collector ──────────────────────────────────────────────────────────────

async def _authenticated_source(
    session: AsyncSession, authorization: str | None
) -> Source:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    source = await source_service.authenticate(session, token)
    if source is None:
        raise HTTPException(401, "unknown or revoked collector token")
    if source.status is SourceStatus.REVOKED:
        raise HTTPException(403, "this source has been revoked")
    return source


@router.get("/collect/config", response_model=CollectorConfig)
async def collector_config(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> CollectorConfig:
    """What the collector should capture right now.

    Polled by the collector, so a pause or a denylist change from the console
    takes effect without the person touching the extension.
    """
    source = await _authenticated_source(session, authorization)
    return _collector_config(source)


@router.post("/collect/events", response_model=CollectResult)
async def collect_events(
    body: CollectBatch,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> CollectResult:
    """Ingest a batch of raw signals from a collector."""
    source = await _authenticated_source(session, authorization)

    if source.status is SourceStatus.PAUSED:
        # Not an error: the collector is behaving correctly and will re-poll
        # config. Silently dropping would hide a pause that failed to propagate.
        raise HTTPException(423, "capture is paused for this source")
    if not source.can_ingest:
        raise HTTPException(403, "this source has not granted consent")

    allow_values = source.capture_scope is CaptureScope.WITH_VALUES
    session_id = body.session_id or new_id("ses")

    accepted = 0
    reasons: list[str] = []
    discovered: list[str] = []
    pending: list[Event] = []
    latest: datetime | None = None
    # Apps already checked in this batch, so a 200-signal flush from one app does
    # not issue 200 identical registry lookups.
    known_apps: set[str] = set()

    for index, raw in enumerate(body.signals):
        if source_service.is_denied(source, raw.url):
            reasons.append(f"signal {index}: excluded by denylist")
            continue

        signal = RawSignal(
            interaction=raw.interaction,
            url=raw.url,
            title=raw.title,
            label=raw.label,
            role=raw.role,
            field_name=raw.field_name,
            duration_ms=raw.duration_ms,
            payload_digest=raw.payload_digest,
            occurred_at=raw.occurred_at,
            tab_id=raw.tab_id,
        )
        try:
            occurred = (
                parse_timestamp(raw.occurred_at) if raw.occurred_at else datetime.now(UTC)
            )
        except Exception:  # noqa: BLE001 — a bad clock must not drop the batch
            occurred = datetime.now(UTC)

        interpreted = interpret(signal, allow_values=allow_values)

        if interpreted.app not in known_apps:
            known_apps.add(interpreted.app)
            if await source_service.ensure_app_registered(session, interpreted.app):
                discovered.append(interpreted.app)

        payload = dict(interpreted.payload)
        payload["interaction"] = raw.interaction
        if raw.tab_id:
            payload["tab"] = raw.tab_id

        pending.append(
            Event(
                id=new_id("evt"),
                user_id=source.user_id,
                team=source.team,
                timestamp=occurred,
                app=interpreted.app,
                action=interpreted.action,
                object_type=interpreted.object_type,
                object_id=interpreted.object_id,
                duration_ms=raw.duration_ms,
                payload=payload,
                session_id=session_id,
                source=source.kind.value,
                source_id=source.id,
            )
        )
        accepted += 1
        latest = occurred if latest is None or occurred > latest else latest

    for event in pending:
        session.add(event)
    await session.flush()

    transfers = await _link_transfers(session, source, pending)

    source.event_count = (source.event_count or 0) + accepted
    source.rejected_count = (source.rejected_count or 0) + len(reasons)
    if latest is not None:
        source.last_event_at = latest
    await session.flush()

    # Detection is not run per batch: it is a full pass over the log and would
    # be wasteful on every 20-second flush. The console decides when to re-run.
    total_from_source = source.event_count
    return CollectResult(
        ok=True,
        accepted=accepted,
        rejected=len(reasons),
        reasons=reasons[:20],
        transfers_linked=transfers,
        apps_discovered=sorted(set(discovered)),
        detection_suggested=total_from_source >= 30,
    )


async def _link_transfers(
    session: AsyncSession, source: Source, batch: list[Event]
) -> int:
    """Match copies against pastes to detect data moving between systems.

    This is the signature the brief names directly — "moving information between
    systems" — and it is the single most valuable thing a browser collector can
    see. Matching is on a hash of the transferred text, so LOOP can prove that
    the same value moved from app A to app B without ever holding the value.
    """
    digests = {
        event.payload.get("transfer_digest")
        for event in batch
        if event.payload.get("transfer_digest")
    }
    if not digests:
        return 0

    # The window is anchored to the batch's own earliest event, not to
    # wall-clock now. A collector queues offline and may flush activity from
    # twenty minutes ago; anchoring to now silently dropped every transfer in
    # such a batch.
    earliest = min(event.timestamp for event in batch)
    cutoff = earliest - TRANSFER_WINDOW
    result = await session.execute(
        select(Event).where(
            Event.source_id == source.id,
            Event.timestamp >= cutoff,
            Event.action.in_(("extract", "create")),
        )
    )
    candidates = [
        event
        for event in result.scalars().all()
        if (event.payload or {}).get("transfer_digest") in digests
    ]

    by_digest: dict[str, list[Event]] = {}
    for event in candidates:
        by_digest.setdefault(str(event.payload["transfer_digest"]), []).append(event)

    linked = 0
    for digest_value, events in by_digest.items():
        events.sort(key=lambda e: e.timestamp)
        copies = [e for e in events if e.action == "extract"]
        pastes = [e for e in events if e.action == "create"]
        if not copies or not pastes:
            continue
        for paste in pastes:
            origin = next(
                (c for c in reversed(copies) if c.timestamp <= paste.timestamp), None
            )
            if origin is None or origin.app == paste.app:
                continue
            # Two unrelated copies of the same value, hours apart, are not a
            # transfer. The window is enforced between the pair itself.
            if paste.timestamp - origin.timestamp > TRANSFER_WINDOW:
                continue
            # Reassigned, not mutated, so SQLAlchemy persists the JSON change.
            payload = dict(paste.payload or {})
            payload["transferred_from"] = origin.app
            payload["transfer_id"] = digest_value
            paste.payload = payload

            origin_payload = dict(origin.payload or {})
            origin_payload["transferred_to"] = paste.app
            origin_payload["transfer_id"] = digest_value
            origin.payload = origin_payload
            linked += 1

    await session.flush()
    return linked


# ── screen recording ───────────────────────────────────────────────────────

@router.post("/ingest/recording", response_model=CollectResult)
async def ingest_recording(
    body: RecordingIngestRequest, session: AsyncSession = Depends(get_session)
) -> CollectResult:
    """Read a consented screen recording into canonical events.

    The third input the brief names, and the only one with no deterministic
    fallback: identifying what an application is from a picture of it requires a
    vision model. Rather than fake it, this returns a precise error when no key
    is configured.

    Frames are read and discarded. Nothing image-derived is persisted beyond the
    application, the verb and the object type — the prompt explicitly forbids
    transcribing any visible text, so a recording does not become a durable copy
    of whatever was on screen.
    """
    if not llm.available:
        raise HTTPException(
            409,
            {
                "message": "screen-recording ingestion needs a vision model",
                "reason": (
                    "No ANTHROPIC_API_KEY is configured. Every other feature has a "
                    "deterministic fallback; reading a frame cannot have one."
                ),
                "hint": "Use the browser extension, or describe the task in prose.",
            },
        )

    source, _token = await source_service.register_source(
        session,
        kind=SourceKind.SCREEN_RECORDING,
        label=f"Recording — {body.user_id}",
        user_id=body.user_id,
        team=body.team,
        consent=True,
    )

    content: list[dict] = [
        {
            "type": "text",
            "text": llm.load_prompt(
                "read_frames",
                apps=", ".join(APPS),
                actions=", ".join(ACTIONS),
            ),
        }
    ]
    for frame in body.frames:
        media_type = "image/png" if frame.image_base64[:20].startswith("iVBOR") else "image/jpeg"
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": frame.image_base64,
                },
            }
        )

    read = await llm.structured_multimodal(
        content=content,
        tool=READ_FRAMES,
        fallback=lambda: {"workflow_name": "", "frames": []},
        max_tokens=2000,
    )

    steps = [f for f in (read.get("frames") or []) if not f.get("skip")]
    if not steps:
        raise HTTPException(
            422,
            "could not identify any distinct application actions in those frames",
        )

    workflow_name = str(read.get("workflow_name") or "Recorded workflow")[:200]

    # One recording is one instance, which cannot clear the minimum-support
    # floor on its own. Repeating it makes the observed pattern detectable,
    # and the multiplier is explicit in the request rather than hidden here.
    start = datetime.now(UTC) - timedelta(weeks=12)
    accepted = 0
    known_apps: set[str] = set()
    discovered: list[str] = []

    for instance in range(body.repeat_instances):
        cursor = start + timedelta(
            days=(instance / max(body.repeat_instances, 1)) * 84,
            hours=10,
            minutes=instance % 47,
        )
        session_key = new_id("ses")
        for index, step in enumerate(steps):
            app = str(step.get("app", "browser"))
            if app not in known_apps:
                known_apps.add(app)
                if await source_service.ensure_app_registered(session, app):
                    discovered.append(app)
            duration = 45 + (index * 7) % 60
            session.add(
                Event(
                    id=new_id("evt"),
                    user_id=body.user_id,
                    team=body.team,
                    timestamp=cursor,
                    app=app,
                    action=str(step.get("action", "read")),
                    object_type=str(step.get("object_type", "screen"))[:64],
                    object_id=None,
                    duration_ms=duration * 1000,
                    payload={"workflow_hint": workflow_name, "from_recording": True},
                    session_id=session_key,
                    source=SourceKind.SCREEN_RECORDING.value,
                    source_id=source.id,
                )
            )
            accepted += 1
            cursor += timedelta(seconds=duration + 12)

    source.event_count = accepted
    source.last_event_at = datetime.now(UTC)
    await session.flush()

    return CollectResult(
        ok=True,
        accepted=accepted,
        rejected=0,
        reasons=[],
        transfers_linked=0,
        apps_discovered=sorted(set(discovered)),
        detection_suggested=True,
    )


# ── domains ────────────────────────────────────────────────────────────────

@router.get("/domains", response_model=DomainList)
async def list_domains(session: AsyncSession = Depends(get_session)) -> DomainList:
    """The teams LOOP knows about, and whether their tools are being watched.

    This is the honest answer to "what do I need to onboard?". A domain whose
    tools have produced no events is a domain LOOP is blind to, however good the
    detection is — so the gap is reported per tool rather than as one number.
    """
    counted = await session.execute(
        select(Event.app, func.count()).group_by(Event.app)
    )
    events_by_app = {app: count for app, count in counted.all()}

    items: list[DomainOut] = []
    unwatched: set[str] = set()

    for domain in DOMAINS:
        tools = []
        for app in domain.tools:
            events = int(events_by_app.get(app, 0))
            if events == 0:
                unwatched.add(app)
            tools.append(ToolStatus(app=app, observed=events > 0, events=events))

        watched = sum(1 for t in tools if t.observed)
        items.append(
            DomainOut(
                key=domain.key,
                label=domain.label,
                owner=domain.owner,
                summary=domain.summary,
                team=domain.team,
                people=len(domain.people),
                workflow_name=domain.workflow_name,
                step_count=len(domain.steps),
                tools=tools,
                is_template=domain.is_template,
                tool_coverage=round(watched / len(tools), 3) if tools else 0.0,
            )
        )

    return DomainList(
        total=len(items),
        items=items,
        unwatched_tools=sorted(unwatched),
    )
