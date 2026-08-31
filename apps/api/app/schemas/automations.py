"""F4/F6/F7 — automation, replay and trust-ladder models."""

from pydantic import BaseModel, Field


class StepOut(BaseModel):
    id: str
    type: str
    connector: str
    description: str = ""
    inputs: dict = Field(default_factory=dict)
    outputs: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class GuardsOut(BaseModel):
    requires_approval_if: str | None = None
    irreversible: list[str] = Field(default_factory=list)


class RuleOut(BaseModel):
    condition: str
    action: str
    source: str = "learned"
    evidence_count: int = 0
    signature_key: str | None = None


class TrustStateOut(BaseModel):
    """Everything the ladder component needs, including why it is blocked."""

    level: str
    next_level: str | None
    confidence: float
    runs_in_window: int
    runs_required: int
    average_score: float
    threshold: float
    critical_mismatches: int
    can_promote: bool
    should_demote: bool
    blockers: list[str]


class AutomationSummary(BaseModel):
    id: str
    cluster_id: str
    name: str
    description: str
    trust_level: str
    confidence: float
    shadow_run_count: int
    critical_mismatch_count: int
    replay_accuracy: float | None
    replay_total: int = 0
    replay_human_count: int = 0
    coverage: float
    generated_by: str
    annual_hours: float = 0.0
    step_count: int = 0
    created_at: str


class AutomationDetail(AutomationSummary):
    trigger: dict
    steps: list[StepOut]
    guards: GuardsOut
    rules: list[RuleOut]
    trust: TrustStateOut
    trust_history: list[dict]
    open_exception_count: int = 0
    pending_patch_count: int = 0


class AutomationList(BaseModel):
    total: int
    items: list[AutomationSummary]


class GenerateAutomationRequest(BaseModel):
    """POST /api/v1/clusters/{id}/generate-automation"""

    # A do-not-automate cluster refuses generation unless this is set, so the
    # system's own recommendation cannot be bypassed silently.
    override_do_not_automate: bool = False


class ReplayRequest(BaseModel):
    days: int = Field(default=30, ge=1, le=365)


class ReplayFailureOut(BaseModel):
    event_id: str
    reason: str
    expected: dict
    predicted: dict
    diff_fields: list[str]
    critical: bool


class ReplayReportOut(BaseModel):
    """POST /api/v1/automations/{id}/replay — failures are never hidden."""

    total: int
    correct: int
    accuracy: float
    needs_approval: int
    errored: int
    not_comparable: int = 0
    days: int
    failures: list[ReplayFailureOut]
    failure_modes: dict[str, int]


class ShadowRunOut(BaseModel):
    id: str
    sequence: int
    trigger_event_id: str | None
    predicted: dict
    observed: dict
    field_matches: dict[str, bool]
    score: float
    critical_mismatch: bool
    note: str
    created_at: str


class ShadowRunList(BaseModel):
    total: int
    items: list[ShadowRunOut]
    trust: TrustStateOut


class PromoteRequest(BaseModel):
    force: bool = Field(
        default=False,
        description="Operator override. Recorded in the audit trail as an override.",
    )


class PromoteResult(BaseModel):
    ok: bool
    level: str
    message: str
    trust: TrustStateOut


class SimulateShadowRequest(BaseModel):
    """POST /api/v1/demo/simulate-shadow-run"""

    automation_id: str
    count: int = Field(default=1, ge=1, le=20)
    force_mismatch: bool = Field(
        default=False,
        description="Deliberately pick a run the automation gets wrong, to demonstrate demotion.",
    )
