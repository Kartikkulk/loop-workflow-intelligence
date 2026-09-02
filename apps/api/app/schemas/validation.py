"""Validation results for Agent workflow proposals.

The validator does not discover workflows. It only checks that an Agent
proposal is grounded in ActivityAtlas evidence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.agent import CoreStep, OptionalStep


class ValidatedEvidence(BaseModel):
    """Support figures derived from the atlas catalog, never from the Agent."""

    instance_count: int = 0
    occurrence_count: int = 0
    distinct_users: int = 0
    source: Literal["atlas_catalog"] = "atlas_catalog"


class ValidatedProposal(BaseModel):
    proposal_id: str = ""
    proposal_name: str = ""
    status: Literal["validated", "rejected"] = "rejected"
    validation_score: float = 0.0
    agent_confidence: float = 0.0
    supporting_signature_ids: list[str] = Field(default_factory=list)
    supporting_motif_ids: list[str] = Field(default_factory=list)
    validated_core_steps: list[CoreStep] = Field(default_factory=list)
    validated_optional_steps: list[OptionalStep] = Field(default_factory=list)
    dropped_optional_steps: list[str] = Field(default_factory=list)
    evidence: ValidatedEvidence = Field(default_factory=ValidatedEvidence)
    issues: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    validated: list[ValidatedProposal] = Field(default_factory=list)
    rejected: list[ValidatedProposal] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
