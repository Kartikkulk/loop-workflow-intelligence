"""Source onboarding and collector request/response models."""

from pydantic import BaseModel, Field


class CapabilityOut(BaseModel):
    """What a tier of source can observe, shown during onboarding."""

    kind: str
    label: str
    summary: str
    sees: list[str]
    blind_to: list[str]
    setup: str
    effort: str
    invasiveness: str
    coverage_estimate: float
    available: bool
    unavailable_reason: str = ""


class SourceOut(BaseModel):
    id: str
    kind: str
    label: str
    user_id: str
    team: str
    status: str
    capture_scope: str
    consent_granted: bool
    denylist: list[str]
    event_count: int
    rejected_count: int
    last_event_at: str | None
    created_at: str


class SourceList(BaseModel):
    total: int
    items: list[SourceOut]
    capabilities: list[CapabilityOut]
    coverage: dict


class RegisterSourceRequest(BaseModel):
    """POST /api/v1/sources"""

    kind: str = Field(description="One of the kinds listed in capabilities.")
    label: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=64)
    team: str = Field(default="unknown", max_length=64)
    capture_scope: str = Field(
        default="metadata_only",
        description="metadata_only records that a field was filled, never its value.",
    )
    consent: bool = Field(
        default=False,
        description="Must be true before the source can send anything.",
    )
    denylist: list[str] = Field(
        default_factory=list,
        description="Hostnames or substrings never to report, enforced server-side too.",
    )


class RegisterSourceResult(BaseModel):
    """The token is returned once, here, and is never retrievable again."""

    source: SourceOut
    token: str
    consent_text: str
    collector_config: dict


class UpdateSourceRequest(BaseModel):
    status: str | None = Field(default=None, description="connected | paused | revoked")
    capture_scope: str | None = None
    denylist: list[str] | None = None


class RawSignalIn(BaseModel):
    """One observation from a collector.

    Deliberately close to raw. Interpretation happens server-side so the rules
    can improve without reinstalling anything.
    """

    interaction: str = Field(max_length=32)
    url: str = Field(default="", max_length=2048)
    title: str = Field(default="", max_length=300)
    label: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=64)
    field_name: str = Field(default="", max_length=100)
    duration_ms: int = Field(default=0, ge=0, le=86_400_000)
    payload_digest: str = Field(
        default="",
        max_length=64,
        description="Hash of transferred text. Never the text itself.",
    )
    occurred_at: str = Field(default="", max_length=64)
    tab_id: str = Field(default="", max_length=64)


class CollectBatch(BaseModel):
    """POST /api/v1/collect/events — authenticated by the source's bearer token."""

    signals: list[RawSignalIn] = Field(min_length=1, max_length=500)
    # The collector's own session grouping. Respected by the sessioniser.
    session_id: str | None = Field(default=None, max_length=64)


class CollectResult(BaseModel):
    ok: bool
    accepted: int
    rejected: int
    reasons: list[str]
    transfers_linked: int
    apps_discovered: list[str]
    # Set when enough new activity has arrived to be worth re-running detection.
    detection_suggested: bool


class CollectorConfig(BaseModel):
    """GET /api/v1/collect/config — what the collector should and should not do."""

    source_id: str
    status: str
    capture_scope: str
    denylist: list[str]
    batch_interval_seconds: int
    max_batch_size: int
    capture_field_values: bool
    capture_page_titles: bool
    consent_text: str


class RecordingFrameIn(BaseModel):
    """One frame from a consented screen recording."""

    # Base64 PNG or JPEG. Kept out of the database: frames are read and dropped.
    image_base64: str = Field(min_length=32)
    offset_seconds: float = Field(default=0.0, ge=0)


class RecordingIngestRequest(BaseModel):
    """POST /api/v1/ingest/recording"""

    user_id: str = Field(default="u_recorded", max_length=64)
    team: str = Field(default="unknown", max_length=64)
    frames: list[RecordingFrameIn] = Field(min_length=1, max_length=40)
    repeat_instances: int = Field(
        default=12,
        ge=1,
        le=200,
        description=(
            "A single recording is one instance. Repeat it so the detected pattern "
            "clears the minimum-support floor."
        ),
    )


class ToolStatus(BaseModel):
    """One application a domain needs watched, and whether it is being watched."""

    app: str
    observed: bool
    events: int


class DomainOut(BaseModel):
    """A team, the work they repeat, and the tools that work happens in.

    Deliberately carries no developer name. Who on the project owns a domain
    pack is repository metadata; putting it on screen makes the product look
    like a status report about the team rather than about the customer's work.
    """

    key: str
    label: str
    summary: str
    team: str
    people: int
    workflow_name: str
    step_count: int
    tools: list[ToolStatus]
    is_template: bool
    #: Share of this domain's tools that have produced observed activity.
    tool_coverage: float

    # ── what automating this domain would give back ─────────────────────
    #: Hours per year currently spent on this domain's repetitive work.
    annual_hours: float
    #: Hours per year lost to context switching on top of that.
    interruption_hours: float
    #: Hours per year that could plausibly be handed over — task time plus
    #: interruption tax, scaled by how automatable the work actually is.
    reclaimable_hours: float
    #: Share of this domain's total burden that is reclaimable.
    effort_reduction: float
    #: True when the detector recommends against automating this domain.
    do_not_automate: bool


class DomainList(BaseModel):
    """GET /api/v1/domains"""

    total: int
    items: list[DomainOut]
    #: Every tool across every domain that nothing is currently watching.
    unwatched_tools: list[str]


class MonitorableToolOut(BaseModel):
    """An application Kriyā AI knows how to read activity out of."""

    key: str
    label: str
    reads: str
    api: str
    credentials: list[str]
    missing_credentials: list[str]
    needs_admin: bool
    connected: bool


class ToolInventory(BaseModel):
    """GET /api/v1/tools"""

    total: int
    connected: int
    items: list[MonitorableToolOut]
