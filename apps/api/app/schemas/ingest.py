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


class IngestResult(BaseModel):
    """Outcome of any ingestion, whatever the source."""

    ok: bool
    events_ingested: int
    events_rejected: int
    errors: list[str]
    source: str
    clusters_detected: int
    workflow_name: str | None = None


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


class EventPage(BaseModel):
    """Paged event listing."""

    total: int
    items: list[EventOut]
