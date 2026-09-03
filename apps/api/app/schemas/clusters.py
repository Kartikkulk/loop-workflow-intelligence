"""F2/F3 — cluster response models."""

from pydantic import BaseModel, Field


class VarianceOut(BaseModel):
    """The measured components behind an automatability score."""

    step_order_entropy: float = 0.0
    parameter_spread: float = 0.0
    branch_count: int = 0
    judgement_ratio: float = 0.0
    variant_count: int = 0
    dominant_variant_share: float = 0.0
    #: Mean similarity of the observed runs to each other, 0–1. High even
    #: when the *number* of distinct orders is high, which is the normal
    #: shape of a workflow with a couple of optional steps.
    sequence_similarity: float = 0.0


class ClusterSummary(BaseModel):
    """A detected workflow, as shown on the discovery screen."""

    id: str
    name: str
    description: str
    signature: list[str]
    apps: list[str]
    instance_count: int
    distinct_users: int
    user_ids: list[str]
    teams: list[str]
    median_duration_ms: int
    instances_per_user_per_week: float
    annual_hours: float
    is_organisational: bool
    context_switches_total: int
    interruption_tax_hours: float
    automatability: float
    #: Automation Potential, 0-100. A ranking heuristic, not a prediction.
    potential: int = 0
    #: One row per factor: what was measured, its weight, points contributed.
    potential_factors: list[dict] = []
    variance_breakdown: VarianceOut
    build_effort: int
    priority: float
    do_not_automate: bool
    reasoning: str
    #: Strength of the evidence that this is a real repetitive workflow:
    #: "early", "moderate" or "strong". Lets the console distinguish a
    #: two-occurrence demo candidate from a proven workflow.
    evidence_level: str = "strong"
    #: True while the case rests on few observations — the UI recommends
    #: watching more before acting, and never auto-executes.
    requires_more_observation: bool = False
    #: Rejected on the Discovery screen. Hidden from the recommended list.
    dismissed: bool = False
    has_automation: bool = False
    automation_id: str | None = None


class ClusterDetail(ClusterSummary):
    """A workflow with its per-user breakdown and step graph."""

    users: list["ClusterUser"]
    step_graph: list["StepNode"]
    variants: list["SignatureVariant"]
    #: Fields the automation must take as inputs, with sample observed values.
    variables: list["ObservedVariable"] = Field(default_factory=list)
    #: Fields that held one value on every run — the evidence behind a guard.
    constants: list["ObservedConstant"] = Field(default_factory=list)


class ClusterUser(BaseModel):
    user_id: str
    team: str
    instance_count: int
    median_duration_ms: int
    annual_hours: float


class StepNode(BaseModel):
    index: int
    app: str
    action: str
    object_type: str
    label: str
    median_duration_ms: int
    alternatives: list[str]


class SignatureVariant(BaseModel):
    """One distinct step order observed within the cluster."""

    signature: list[str]
    count: int
    share: float


class ClusterList(BaseModel):
    """GET /api/v1/clusters"""

    total: int
    recommended: list[ClusterSummary]
    not_recommended: list[ClusterSummary]
    total_annual_hours: float
    total_interruption_tax_hours: float


class SopOut(BaseModel):
    """GET /api/v1/clusters/{id}/sop"""

    cluster_id: str
    name: str
    markdown: str
    generated_by: str


class DismissResult(BaseModel):
    """POST /api/v1/clusters/{id}/dismiss and /restore"""

    id: str
    dismissed: bool
    message: str

class ObservedVariable(BaseModel):
    """A field whose value changed run to run, so the automation parameterises it."""

    name: str
    placeholder: str = Field(description="e.g. {{customer}}")
    step_token: str
    key: str
    samples: list[str] = Field(default_factory=list)
    distinct_count: int = 0
    occurrences: int = 0


class ObservedConstant(BaseModel):
    """A field that held the same value on every observed run."""

    name: str
    step_token: str
    key: str
    value: str
    occurrences: int = 0



ClusterDetail.model_rebuild()
