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
    #: n8n's id, once a review draft has been built there. Empty until then.
    n8n_workflow_id: str = ""
    #: The final human sign-off, after reviewing (and maybe editing) the draft
    #: in n8n. A draft can exist (n8n_workflow_id set) while this is still False.
    approved: bool = False


class ExecutionPlanOut(BaseModel):
    """Which runtime was chosen to execute an automation, and why."""

    method: str = Field(description="n8n, playwright or python.")
    rationale: str = ""
    confidence: float = 0.0
    #: "llm" or "heuristic", so a reviewer knows what made the call.
    decided_by: str = ""
    #: What the connector rules would have chosen instead, when they disagree.
    #: Empty when both agree. Shown at the approval gate rather than resolved
    #: silently, because either choice has a real cost.
    alternative_method: str = ""
    alternative_rationale: str = ""
    #: One line per observation behind the choice.
    factors: list[str] = Field(default_factory=list)


class AutomationDetail(AutomationSummary):
    trigger: dict
    steps: list[StepOut]
    guards: GuardsOut
    rules: list[RuleOut]
    trust: TrustStateOut
    trust_history: list[dict]
    open_exception_count: int = 0
    pending_patch_count: int = 0
    execution: ExecutionPlanOut | None = None


class GeneratedCodeOut(BaseModel):
    """GET /api/v1/automations/{id}/code"""

    method: str
    filename: str
    source: str = Field(description="The complete file, ready to write to disk and run.")
    #: What has to exist before this will run.
    requirements: list[str] = Field(default_factory=list)
    #: Steps that could not be fully generated, and why. Empty means the file
    #: is complete as it stands.
    caveats: list[str] = Field(default_factory=list)
    line_count: int = 0


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


class N8nPushResult(BaseModel):
    """POST /api/v1/automations/{id}/n8n"""

    ok: bool
    #: n8n's id for the created workflow.
    workflow_id: str = ""
    #: Where to open it and wire up the accounts. This is the whole point of
    #: the response: approving is only useful if you land on the thing to do next.
    configure_url: str = ""
    #: Node names that need an account chosen before the workflow can run.
    needs_credentials: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    message: str = ""


class N8nRun(BaseModel):
    """One execution n8n has recorded for an exported workflow."""

    id: str
    #: n8n's own words: success, error, waiting, running, canceled.
    status: str
    started_at: str = ""
    finished_at: str = ""
    #: The node that failed, when one did. This is the whole reason Kriyā AI shows
    #: these at all: "it failed" is not actionable, "the Jira node failed" is.
    failed_node: str = ""
    error: str = ""


class N8nRunList(BaseModel):
    """GET /api/v1/automations/{id}/n8n/runs"""

    #: False when the workflow has never been exported, or n8n is unreachable.
    ok: bool
    workflow_id: str = ""
    configure_url: str = ""
    #: True once the workflow has been switched on inside n8n.
    active: bool = False
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    items: list[N8nRun] = Field(default_factory=list)
    message: str = ""


class N8nExport(BaseModel):
    """GET /api/v1/automations/{id}/n8n"""

    workflow: dict = Field(
        description="An importable n8n workflow: nodes, connections and settings."
    )
    #: What did not survive the translation. Empty means everything mapped.
    notes: list[str] = Field(default_factory=list)
    #: Nodes that will need an account chosen inside n8n before they can run.
    needs_credentials: list[str] = Field(default_factory=list)


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

class ValidationFindingOut(BaseModel):
    """One thing wrong with a generated automation."""

    check: str
    detail: str
    step_id: str = ""
    blocking: bool = True


class ValidationReportOut(BaseModel):
    """POST /api/v1/automations/{id}/validate"""

    ok: bool = Field(
        description="True only when nothing blocking was found. Never approximated."
    )
    passed: list[str] = Field(default_factory=list)
    findings: list[ValidationFindingOut] = Field(default_factory=list)
    blocking_count: int = 0


class DryRunStepOut(BaseModel):
    """What one step did during a dry run."""

    step_id: str
    connector: str = ""
    action: str = ""
    status: str
    outputs: dict = Field(default_factory=dict)
    error: str | None = None


class DryRunResult(BaseModel):
    """POST /api/v1/automations/{id}/dry-run

    Every connector is forced to its mock during a dry run, by the engine rather
    than by this endpoint, so no step can reach a real system however it is
    configured.
    """

    status: str = Field(description="ok, needs_approval or failed.")
    steps: list[DryRunStepOut] = Field(default_factory=list)
    #: Side effects that a live run *would* have produced, and did not.
    would_have: list[str] = Field(default_factory=list)
    held_by_guard: bool = False
    guard_reason: str | None = None
    #: Restates the safety property in the response itself.
    side_effects_performed: int = 0


class RunStepOut(BaseModel):
    """What one step did during a live run."""

    step_id: str
    connector: str = ""
    action: str = ""
    status: str
    detail: str = ""


class RunItemOut(BaseModel):
    """One item the automation processed."""

    item: str
    status: str = Field(description="done, held or failed.")
    detail: str = ""
    steps: list[RunStepOut] = Field(default_factory=list)


class RunResult(BaseModel):
    """POST /api/v1/automations/{id}/run — a real execution."""

    ok: bool
    processed: int = 0
    completed: int = 0
    held: int = 0
    failed: int = 0
    #: What actually changed on disk, so the result can be checked rather than
    #: believed.
    side_effects: list[str] = Field(default_factory=list)
    items: list[RunItemOut] = Field(default_factory=list)
    message: str = ""
    #: True when the connector was rehearsing rather than acting. Reported
    #: rather than inferred: a rehearsed step and a real one look the same.
    dry_run: bool = False

