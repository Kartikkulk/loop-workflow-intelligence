"""F2/F3 — cluster response models."""

from pydantic import BaseModel


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
    has_automation: bool = False
    automation_id: str | None = None


class ClusterDetail(ClusterSummary):
    """A workflow with its per-user breakdown and step graph."""

    users: list["ClusterUser"]
    step_graph: list["StepNode"]
    variants: list["SignatureVariant"]


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


ClusterDetail.model_rebuild()
