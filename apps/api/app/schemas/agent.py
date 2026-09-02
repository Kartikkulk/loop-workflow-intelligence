"""Pydantic models for Workflow Discovery Agent v1.

The Agent proposes which atlas patterns may be the same repetitive work.
Counts in `evidence` are copied from the Activity Atlas catalog by Python,
never trusted from the model. A later validator will recount from instances.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CoreStep(BaseModel):
    token: str
    reason: str = ""


class OptionalStep(BaseModel):
    token: str
    frequency: float = 0.0
    reason: str = ""


class CatalogEvidence(BaseModel):
    """Support figures taken from atlas catalog rows the proposal cited."""

    supporting_instances: int = 0
    total_occurrences: int = 0
    distinct_users: int = 0
    source: Literal["atlas_catalog"] = "atlas_catalog"


class RepetitionAssessment(BaseModel):
    strength: Literal["low", "medium", "high"] = "low"
    reason: str = ""


class AutomationAssessment(BaseModel):
    deterministic_steps: list[str] = Field(default_factory=list)
    judgment_steps: list[str] = Field(default_factory=list)
    potentially_automatable: list[str] = Field(default_factory=list)
    human_approval_points: list[str] = Field(default_factory=list)


class ProposedWorkflow(BaseModel):
    proposal_id: str = ""
    name: str = ""
    description: str = ""
    supporting_signature_ids: list[str] = Field(default_factory=list)
    supporting_motif_ids: list[str] = Field(default_factory=list)
    supporting_sample_instance_ids: list[str] = Field(default_factory=list)
    core_steps: list[CoreStep] = Field(default_factory=list)
    optional_steps: list[OptionalStep] = Field(default_factory=list)
    observed_applications: list[str] = Field(default_factory=list)
    evidence: CatalogEvidence = Field(default_factory=CatalogEvidence)
    repetition_assessment: RepetitionAssessment = Field(default_factory=RepetitionAssessment)
    automation_assessment: AutomationAssessment = Field(default_factory=AutomationAssessment)
    confidence: float = 0.0
    evidence_gaps: list[str] = Field(default_factory=list)
    dropped_ungrounded_tokens: list[str] = Field(default_factory=list)


class AgentAnalysis(BaseModel):
    status: Literal["ok", "empty", "unavailable", "invalid"] = "unavailable"
    generated_by: Literal["llm", "fallback"] = "fallback"
    model_name: str = ""
    evidence_hash: str = ""
    proposed_workflows: list[ProposedWorkflow] = Field(default_factory=list)
    unrelated_patterns: list[str] = Field(default_factory=list)
    analysis_notes: list[str] = Field(default_factory=list)
