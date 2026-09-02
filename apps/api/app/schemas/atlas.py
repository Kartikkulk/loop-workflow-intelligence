"""Activity Atlas — compressed evidence for a future Workflow Agent.

The atlas is not a discovery decision. It does not assert that a pattern is a
repetitive workflow. Motifs are repeated token subsequences (counts only).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TimeWindow(BaseModel):
    start: datetime | None = None
    end: datetime | None = None


class AtlasSummary(BaseModel):
    event_count: int = 0
    instance_count: int = 0
    distinct_users: int = 0
    distinct_sessions: int = 0


class SignatureCatalogEntry(BaseModel):
    signature_id: str
    tokens: list[str]
    occurrence_count: int = 0
    distinct_users: int = 0
    median_duration_ms: int = 0
    example_instance_ids: list[str] = Field(default_factory=list)


class CandidateGroup(BaseModel):
    """A clustering hypothesis, including groups below the Discovery floor."""

    candidate_id: str
    occurrence_count: int = 0
    medoid_signature: list[str] = Field(default_factory=list)
    member_signature_ids: list[str] = Field(default_factory=list)


class MotifCatalogEntry(BaseModel):
    """A repeated token subsequence observed inside and across instances."""

    motif_id: str
    tokens: list[str] = Field(default_factory=list)
    length: int = 0
    instance_support: int = 0
    total_occurrences: int = 0
    distinct_users: int = 0
    example_instance_ids: list[str] = Field(default_factory=list)


class AppTransition(BaseModel):
    from_app: str = Field(alias="from")
    to_app: str = Field(alias="to")
    count: int = 0

    model_config = {"populate_by_name": True}


class SampleInstance(BaseModel):
    instance_id: str
    signature: list[str]
    duration_ms: int
    user_id: str
    started_at: datetime
    event_count: int


class ActivityAtlas(BaseModel):
    """Compact JSON evidence derived from task instances."""

    time_window: TimeWindow = Field(default_factory=TimeWindow)
    summary: AtlasSummary = Field(default_factory=AtlasSummary)
    signature_catalog: list[SignatureCatalogEntry] = Field(default_factory=list)
    candidate_groups: list[CandidateGroup] = Field(default_factory=list)
    motif_catalog: list[MotifCatalogEntry] = Field(default_factory=list)
    app_transitions: list[AppTransition] = Field(default_factory=list)
    field_name_histograms: dict[str, list[str]] = Field(default_factory=dict)
    sample_instances: list[SampleInstance] = Field(default_factory=list)
    evidence_notes: list[str] = Field(default_factory=list)
