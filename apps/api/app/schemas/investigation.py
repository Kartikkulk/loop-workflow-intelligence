"""Agent Investigation v1 — semantic relationship analysis over atlas evidence.

The Investigator does not discover workflows. It reasons over a compact,
deterministic evidence packet built from an ActivityAtlas and a candidate
proposal. It must not invent business conditions or private payloads.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.agent import ProposedWorkflow
from app.schemas.atlas import ActivityAtlas
from app.schemas.validation import ValidationResult

RelationshipKind = Literal[
    "same_workflow",
    "optional_step",
    "conditional_step",
    "separate_workflow",
    "insufficient_evidence",
]

FinalDecision = Literal["safe_to_continue", "insufficient_evidence"]


class InvestigationRequest(BaseModel):
    """Inputs for one investigation run."""

    candidate: ProposedWorkflow
    atlas: ActivityAtlas
    comparison_candidates: list[ProposedWorkflow] = Field(default_factory=list)


class InvestigationEvidence(BaseModel):
    """One grounded evidence item in the deterministic packet."""

    evidence_id: str
    evidence_type: str
    source: Literal["atlas_catalog", "deterministic_stats"] = "deterministic_stats"
    description: str = ""
    supporting_ids: list[str] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)


class VariantStatistics(BaseModel):
    """Deterministic frequency facts about a base pattern vs an extra step."""

    variant_id: str
    base_tokens: list[str] = Field(default_factory=list)
    variant_token: str = ""
    base_pattern_frequency: int = 0
    variant_frequency: int = 0
    variant_rate: float = 0.0
    base_without_variant: int = 0
    users_with_variant: int = 0
    users_without_variant: int = 0
    variant_position: str = ""
    associated_context_keys: list[str] = Field(default_factory=list)
    evidence_id: str = ""


class InvestigationConclusion(BaseModel):
    relationship: RelationshipKind = "insufficient_evidence"
    confidence: float = 0.0
    reasoning: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    subject: str = ""
    weakened: bool = False


class SemanticRelationship(BaseModel):
    """Possible source → destination style link, only when evidence supports it."""

    kind: Literal[
        "source_destination",
        "transformation",
        "unrelated",
        "unknown",
        "insufficient_evidence",
    ] = "insufficient_evidence"
    from_token: str = ""
    to_token: str = ""
    confidence: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    weakened: bool = False


class InvestigationPacket(BaseModel):
    """Compact deterministic packet sent to the LLM (no raw payloads)."""

    candidate_workflow_id: str = ""
    candidate_name: str = ""
    core_tokens: list[str] = Field(default_factory=list)
    optional_tokens: list[str] = Field(default_factory=list)
    ordered_applications: list[str] = Field(default_factory=list)
    ordered_object_types: list[str] = Field(default_factory=list)
    ordered_action_types: list[str] = Field(default_factory=list)
    event_count: int = 0
    instance_count: int = 0
    distinct_users: int = 0
    duration_stats: dict[str, Any] = Field(default_factory=dict)
    app_transitions: list[dict[str, Any]] = Field(default_factory=list)
    field_name_histograms: dict[str, list[str]] = Field(default_factory=dict)
    sample_instance_ids: list[str] = Field(default_factory=list)
    sample_step_orderings: list[dict[str, Any]] = Field(default_factory=list)
    consistent_steps: list[str] = Field(default_factory=list)
    subset_steps: list[str] = Field(default_factory=list)
    motif_ids: list[str] = Field(default_factory=list)
    variant_statistics: list[VariantStatistics] = Field(default_factory=list)
    comparison_summaries: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[InvestigationEvidence] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class InvestigationResult(BaseModel):
    status: Literal["ok", "insufficient_evidence", "unavailable", "invalid"] = (
        "insufficient_evidence"
    )
    generated_by: Literal["llm", "fallback"] = "fallback"
    model_name: str = ""
    candidate_workflow_id: str = ""
    conclusions: list[InvestigationConclusion] = Field(default_factory=list)
    semantic_relationships: list[SemanticRelationship] = Field(default_factory=list)
    evidence: list[InvestigationEvidence] = Field(default_factory=list)
    variant_statistics: list[VariantStatistics] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    investigation_notes: list[str] = Field(default_factory=list)
    final_decision: FinalDecision = "insufficient_evidence"
    packet: InvestigationPacket | None = None


class ClusterInvestigationResponse(BaseModel):
    """One persisted cluster investigated and validated against its atlas."""

    cluster_id: str
    investigation: InvestigationResult
    validation: ValidationResult
    automation_eligible: bool = False
