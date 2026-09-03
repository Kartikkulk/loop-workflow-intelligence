"""F1 — ingestion request/response models."""

from pydantic import BaseModel, Field


class DescribeRequest(BaseModel):
    """POST /api/v1/ingest/describe — the plain-English fallback input path."""

    description: str = Field(
        min_length=10,
        max_length=4000,
        description="A recurring task in the employee's own words.",
    )
    user_id: str = Field(default="u_described", max_length=64)
    team: str = Field(default="unknown", max_length=64)
    weeks: int = Field(default=12, ge=1, le=52, description="Weeks of history to synthesise.")


class DiscoveredWorkflow(BaseModel):
    """A workflow detection found, summarised for the upload response."""

    id: str
    name: str
    occurrences: int
    apps: list[str] = Field(default_factory=list)
    annual_hours: float = 0.0
    automatability: float = 0.0


class IngestResult(BaseModel):
    """Outcome of any ingestion, whatever the source."""

    ok: bool
    events_ingested: int
    events_rejected: int
    errors: list[str]
    source: str
    clusters_detected: int
    workflow_name: str | None = None
    #: What was found, returned with the upload itself. Without this the console
    #: had to re-fetch and the person who just uploaded a file was told only a
    #: count — "3 workflows detected" — with no way to see them without
    #: navigating away and hunting.
    workflows: list["DiscoveredWorkflow"] = Field(default_factory=list)
    #: How many events, sessions, applications and sources arrived, so the
    #: upload can be sanity-checked before anyone trusts what was detected.
    sessions: int = 0
    applications: int = 0


class EventOut(BaseModel):
    """One canonical event."""

    id: str
    user_id: str
    team: str
    timestamp: str
    app: str
    action: str
    object_type: str
    duration_ms: int
    payload: dict
    session_id: str | None = None
    #: Where the event came from — "upload" for a CSV/JSONL, "browser_extension"
    #: for a live collector, or the connector that synced it. Detection treats
    #: them identically; this exists so a person can see what they are looking at.
    source: str = ""


class SourceFacet(BaseModel):
    """One value a stream can be filtered by, with how many events carry it."""

    value: str
    count: int


class EventPage(BaseModel):
    """Paged event listing."""

    total: int
    items: list[EventOut]
    #: Every source present in the whole log, not just this page — a filter
    #: built from one page of results would hide the sources further down it.
    sources: list[SourceFacet] = Field(default_factory=list)
    #: The same, per application.
    apps: list[SourceFacet] = Field(default_factory=list)
