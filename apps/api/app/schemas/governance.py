"""F8 — exception queue, patches and ROI models."""

from pydantic import BaseModel, Field


class ExceptionOut(BaseModel):
    id: str
    automation_id: str
    automation_name: str = ""
    reason: str
    input_features: dict
    signature_key: str
    confidence: float
    status: str
    human_decision: str | None
    human_note: str | None
    created_at: str


class ExceptionList(BaseModel):
    total: int
    open_count: int
    items: list[ExceptionOut]


class ResolveExceptionRequest(BaseModel):
    decision: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=1000)


class ResolveExceptionResult(BaseModel):
    ok: bool
    message: str
    rules_proposed: int


class PatchOut(BaseModel):
    id: str
    automation_id: str
    automation_name: str = ""
    kind: str
    step_id: str | None
    field: str | None
    from_value: str | None
    to_value: str | None
    confidence: float
    auto_applicable: bool
    status: str
    rationale: str
    rule: dict | None
    evidence_count: int
    proposed_by: str
    created_at: str


class PatchList(BaseModel):
    total: int
    proposed_count: int
    items: list[PatchOut]


class ApplyPatchResult(BaseModel):
    ok: bool
    message: str
    patch: PatchOut


class BreakSchemaRequest(BaseModel):
    """POST /api/v1/demo/break-schema — renames a field in the stored events.

    `app` is optional. Left unset the rename propagates through every system
    carrying the field, which is what a real schema migration does — and is what
    actually breaks a dependency, since an automation usually reads a field from
    one system and writes it to another.
    """

    app: str | None = None
    from_field: str = "Supplier Name"
    to_field: str = "Vendor Legal Name"


class BreakSchemaResult(BaseModel):
    ok: bool
    events_updated: int
    message: str
    patches_proposed: int
    automations_affected: list[str]


class RoiAutomation(BaseModel):
    id: str
    name: str
    trust_level: str
    coverage: float
    annual_hours: float
    interruption_tax_hours: float
    replay_accuracy: float | None
    shadow_run_count: int


class TrustDistribution(BaseModel):
    level: str
    count: int


class CoveragePoint(BaseModel):
    automation_id: str
    automation_name: str
    sequence: int
    coverage: float
    score: float


class RoiReport(BaseModel):
    """GET /api/v1/analytics/roi"""

    projected_annual_hours: float
    realised_annual_hours: float
    interruption_tax_hours: float
    interruption_tax_recovered_hours: float
    total_clusters: int
    automatable_clusters: int
    do_not_automate_clusters: int
    total_automations: int
    autonomous_count: int
    average_coverage: float
    trust_distribution: list[TrustDistribution]
    automations: list[RoiAutomation]
    coverage_trend: list[CoveragePoint]


class ConnectorOut(BaseModel):
    name: str
    mock_available: bool
    live_available: bool
    required_credentials: list[str]
    api: str
    active: str


class SystemStatus(BaseModel):
    """GET /api/v1/system — what a judge asks about, answered on one screen."""

    mock_connectors: bool
    connectors: list[ConnectorOut]
    llm_available: bool
    llm_model: str
    llm_calls: int
    llm_fallbacks: int
    llm_estimated_cost_usd: float
    event_count: int
    cluster_count: int
    automation_count: int
    settings: dict
