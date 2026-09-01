"""Source onboarding: registration, consent, tokens and coverage."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.event import AppRegistry, Event
from app.models.source import CaptureScope, Source, SourceKind, SourceStatus
from app.services.ids import new_id

CONSENT_TEXT = (
    "I agree to LOOP observing which applications I use and what kind of action I take "
    "in each, for the purpose of identifying repetitive work. In metadata-only mode "
    "LOOP records that a field was filled, never what was typed into it. I can pause "
    "or revoke this at any time, and revoking deletes the events this source reported."
)


@dataclass
class SourceCapability:
    """What a kind of source can and cannot observe.

    Presented during onboarding so the choice is made with open eyes: every tier
    buys coverage and costs either deployment effort or intrusiveness, and
    pretending otherwise is how these projects get switched off in month two.
    """

    kind: SourceKind
    label: str
    summary: str
    sees: list[str]
    blind_to: list[str]
    setup: str
    effort: str
    invasiveness: str
    # Rough share of a typical knowledge worker's app activity this tier covers.
    coverage_estimate: float
    available: bool
    unavailable_reason: str = ""


CAPABILITIES: list[SourceCapability] = [
    SourceCapability(
        kind=SourceKind.DESCRIBE,
        label="Describe a task",
        summary="Someone types out a recurring task in their own words.",
        sees=["The steps a person believes they take", "Rough frequency"],
        blind_to=[
            "What actually happens, as opposed to what is remembered",
            "Real durations and interruptions",
            "Variance between instances",
        ],
        setup="Nothing to install. Type a paragraph.",
        effort="seconds",
        invasiveness="none",
        coverage_estimate=0.10,
        available=True,
    ),
    SourceCapability(
        kind=SourceKind.UPLOAD,
        label="Upload an activity log",
        summary="An export from an existing tool, as CSV or JSONL.",
        sees=["Whatever the exporting system recorded"],
        blind_to=["Anything outside that one system", "Cross-application sequences"],
        setup="Export from the source system and upload the file.",
        effort="minutes",
        invasiveness="none",
        coverage_estimate=0.25,
        available=True,
    ),
    SourceCapability(
        kind=SourceKind.BROWSER_EXTENSION,
        label="Browser extension",
        summary=(
            "Observes activity across every web application in the browser, "
            "including data copied from one tool and pasted into another."
        ),
        sees=[
            "Every web app, including internal tools with no API",
            "Cross-application step sequences",
            "Copy-paste transfers between systems",
            "Real durations and context switches",
            "Field names that were filled",
        ],
        blind_to=[
            "Desktop applications: Excel, Outlook desktop, SAP GUI",
            "Anything inside a Citrix or VDI session",
            "Field values, in metadata-only mode",
        ],
        setup="Install the unpacked extension and paste the source token.",
        effort="about two minutes per person",
        invasiveness="low — metadata only, pausable, domain denylist",
        coverage_estimate=0.70,
        available=True,
    ),
    SourceCapability(
        kind=SourceKind.API_CONNECTOR,
        label="Connect an application account",
        summary=(
            "OAuth into Microsoft 365, Google Workspace, Slack or a line-of-business "
            "system and pull its audit trail."
        ),
        sees=[
            "Authoritative records of what changed in that system",
            "Tenant-wide activity, not just one person's",
            "History from before LOOP was installed",
        ],
        blind_to=[
            "How the person got there, and what else they had open",
            "Time spent, and interruptions",
            "Anything the vendor does not expose in an audit API",
        ],
        setup="OAuth consent. Tenant-wide audit APIs need an administrator.",
        effort="hours, plus an admin conversation",
        invasiveness="medium — reads real content unless scoped down",
        coverage_estimate=0.45,
        available=False,
        unavailable_reason=(
            "Requires per-provider OAuth credentials. The connector interfaces and "
            "their exact API surfaces are declared, but no live credentials are "
            "configured in this build."
        ),
    ),
    SourceCapability(
        kind=SourceKind.DESKTOP_AGENT,
        label="Desktop agent",
        summary="A background process reporting active-window and clipboard activity.",
        sees=[
            "Desktop applications the browser cannot see",
            "Application focus and switching across the whole machine",
            "The full cross-application picture",
        ],
        blind_to=["What is inside a window, without accessibility APIs or OCR"],
        setup="Signed installer, plus OS accessibility permission per machine.",
        effort="days, and an IT rollout",
        invasiveness="high — needs a serious consent conversation",
        coverage_estimate=0.95,
        available=False,
        unavailable_reason=(
            "Not built. The collector API it would post to is implemented and "
            "documented, so an agent is an independent piece of work."
        ),
    ),
    SourceCapability(
        kind=SourceKind.SCREEN_RECORDING,
        label="Screen recording",
        summary="Frames from a recorded session, read by a vision model.",
        sees=[
            "Legacy, Citrix and VDI applications with no API and no DOM",
            "Exactly what the person saw",
        ],
        blind_to=["Nothing much — which is the problem"],
        setup="Upload frames from a consented recording session.",
        effort="minutes per recording, and it does not scale",
        invasiveness="very high — captures everything on screen",
        coverage_estimate=1.00,
        # The only tier with no deterministic fallback: reading a frame requires
        # a vision model, so this one genuinely cannot run without one.
        available=settings.has_vision_llm,
        unavailable_reason=(
            ""
            if settings.has_vision_llm
            else (
                "Reading a frame needs a local vision model. Set "
                "LOOP_OLLAMA_VISION_MODEL after pulling a vision-capable Ollama model. "
                "Every other feature has a deterministic fallback; this one cannot, "
                "so it is disabled rather than faked."
            )
        ),
    ),
]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def mint_token() -> tuple[str, str]:
    """Generate a collector token. Returns (token, hash).

    The raw token is returned to the caller once and never stored, so a database
    leak cannot be replayed as a collector.
    """
    token = f"loop_src_{secrets.token_urlsafe(32)}"
    return token, hash_token(token)


async def register_source(
    session: AsyncSession,
    *,
    kind: SourceKind,
    label: str,
    user_id: str,
    team: str = "unknown",
    capture_scope: CaptureScope = CaptureScope.METADATA_ONLY,
    consent: bool = False,
    denylist: list[str] | None = None,
) -> tuple[Source, str]:
    """Register a new observation source and mint its token."""
    token, token_hash = mint_token()
    source = Source(
        id=new_id("src"),
        kind=kind,
        label=label,
        user_id=user_id,
        team=team,
        capture_scope=capture_scope,
        status=SourceStatus.CONNECTED if consent else SourceStatus.PENDING,
        consent_granted_at=func.now() if consent else None,
        consent_text=CONSENT_TEXT if consent else "",
        token_hash=token_hash,
        denylist=list(denylist or []),
    )
    session.add(source)
    await session.flush()
    return source, token


async def authenticate(session: AsyncSession, token: str) -> Source | None:
    """Resolve a bearer token to its source. Returns None if unknown."""
    if not token:
        return None
    result = await session.execute(
        select(Source).where(Source.token_hash == hash_token(token))
    )
    return result.scalars().first()


async def ensure_app_registered(session: AsyncSession, app: str) -> bool:
    """Register an app key the first time it is observed. True if newly added.

    This is why the app vocabulary is a table rather than an enum. An employee
    opening an internal tool nobody anticipated onboards it by using it — no
    code change, no migration, no configuration.
    """
    existing = await session.get(AppRegistry, app)
    if existing is not None:
        return False
    session.add(
        AppRegistry(
            key=app,
            label=app.replace("-", " ").replace("_", " ").title(),
            category="discovered",
        )
    )
    await session.flush()
    return True


def is_denied(source: Source, url: str) -> bool:
    """Whether a URL falls under this source's denylist.

    Enforced server-side as well as in the collector: an out-of-date extension
    must not be able to keep reporting a domain the person has excluded.
    """
    lowered = (url or "").lower()
    return any(
        entry.strip().lower() in lowered
        for entry in (source.denylist or [])
        if entry.strip()
    )


async def coverage_report(session: AsyncSession) -> dict:
    """What LOOP can currently see, and through what."""
    sources = list((await session.execute(select(Source))).scalars().all())
    connected = [s for s in sources if s.status is SourceStatus.CONNECTED]

    by_app = await session.execute(
        select(Event.app, func.count()).group_by(Event.app).order_by(func.count().desc())
    )
    apps = [{"app": app, "events": count} for app, count in by_app.all()]

    total_events = await session.execute(select(func.count()).select_from(Event))
    observed_events = await session.execute(
        select(func.count()).select_from(Event).where(Event.source_id.is_not(None))
    )

    # Coverage is the best single tier connected, not the sum: tiers overlap
    # heavily, so adding them would claim more than is true.
    best = max(
        (
            c.coverage_estimate
            for c in CAPABILITIES
            if any(s.kind is c.kind for s in connected)
        ),
        default=0.0,
    )

    return {
        "connected_sources": len(connected),
        "total_sources": len(sources),
        "estimated_coverage": round(best, 2),
        "apps_observed": apps,
        "distinct_apps": len(apps),
        "total_events": int(total_events.scalar() or 0),
        "observed_events": int(observed_events.scalar() or 0),
        "kinds_connected": sorted({s.kind.value for s in connected}),
    }


# ── tools LOOP can read activity out of ────────────────────────────────────
#
# Distinct from the execution connectors in app/connectors/. Those *act* on a
# system — send an email, append a row. These *read* what already happened, and
# the API surface is usually a completely different one: Gmail's execution API
# sends mail, but the activity comes from the Admin SDK Reports API.
#
# Conflating the two is an easy mistake and an expensive one, because it makes
# "we can send email" look like "we can see what you did".


@dataclass
class MonitorableTool:
    """An application whose activity LOOP knows how to read."""

    key: str
    label: str
    #: What activity this yields, in the user's words.
    reads: str
    #: The specific API the activity comes from.
    api: str
    #: Environment variables needed before it can connect.
    credentials: list[str]
    #: True when an administrator must consent, not just the individual.
    needs_admin: bool = False


MONITORABLE_TOOLS: list[MonitorableTool] = [
    MonitorableTool(
        key="google_workspace",
        label="Google Workspace",
        reads="Mail, Drive and Calendar activity across everyone in the tenant.",
        api="Admin SDK Reports API — activities.list",
        credentials=["GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"],
        needs_admin=True,
    ),
    MonitorableTool(
        key="microsoft_365",
        label="Microsoft 365",
        reads="Mail and calendar for one mailbox, without an administrator.",
        api="Microsoft Graph — /me/messages/delta, /me/events/delta",
        credentials=["MS_CLIENT_ID", "MS_CLIENT_SECRET"],
    ),
    MonitorableTool(
        key="microsoft_365_tenant",
        label="Microsoft 365 — whole tenant",
        reads="Every action across Exchange, SharePoint and Teams. The richest source there is.",
        api="Office 365 Management Activity API",
        credentials=["MS_CLIENT_ID", "MS_CLIENT_SECRET", "MS_TENANT_ID"],
        needs_admin=True,
    ),
    MonitorableTool(
        key="slack",
        label="Slack",
        reads="Who did what in which channel.",
        api="Audit Logs API (Enterprise Grid) or the Events API",
        credentials=["SLACK_BOT_TOKEN"],
        needs_admin=True,
    ),
    MonitorableTool(
        key="jira",
        label="Jira",
        reads="Issue transitions, comments and field edits.",
        api="Webhooks plus the audit log",
        credentials=["ATLASSIAN_SITE", "ATLASSIAN_API_TOKEN"],
    ),
    MonitorableTool(
        key="salesforce",
        label="Salesforce",
        reads="Record views, edits and reports run.",
        api="EventLogFile",
        credentials=["SF_CLIENT_ID", "SF_CLIENT_SECRET", "SF_INSTANCE_URL"],
        needs_admin=True,
    ),
    MonitorableTool(
        key="erp",
        label="Your ERP",
        reads="Document changes and postings.",
        api="Tenant REST API, or SAP change documents",
        credentials=["ERP_BASE_URL", "ERP_API_TOKEN"],
    ),
]


def tool_inventory() -> list[dict]:
    """Every monitorable tool, with whether its credentials are configured.

    Honest by construction: a tool reports connected only when the environment
    actually holds every variable it needs, so this cannot claim a connection
    that does not exist.
    """
    import os

    out = []
    for tool in MONITORABLE_TOOLS:
        missing = [name for name in tool.credentials if not os.environ.get(name)]
        out.append(
            {
                "key": tool.key,
                "label": tool.label,
                "reads": tool.reads,
                "api": tool.api,
                "credentials": tool.credentials,
                "missing_credentials": missing,
                "needs_admin": tool.needs_admin,
                "connected": not missing,
            }
        )
    return out
