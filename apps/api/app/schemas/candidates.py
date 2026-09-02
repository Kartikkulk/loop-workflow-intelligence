"""API contracts for browser-extension workflow candidates."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.investigation import InvestigationResult
from app.schemas.validation import ValidationResult

CandidateStatus = Literal["observed", "candidate", "investigated", "validated"]


class CandidateWorkflowOut(BaseModel):
    workflow_id: str
    name: str
    signature_tokens: list[str] = Field(default_factory=list)
    session_count: int = 0
    occurrence_count: int = 0
    distinct_users: int = 0
    apps: list[str] = Field(default_factory=list)
    first_seen: datetime
    last_seen: datetime
    confidence: float = 0.0
    status: CandidateStatus = "observed"
    investigation: InvestigationResult | None = None
    validation: ValidationResult | None = None
    automation_id: str | None = None
    automation_trust_level: str | None = None


class CandidateWorkflowList(BaseModel):
    source: Literal["browser_extension"] = "browser_extension"
    total: int = 0
    items: list[CandidateWorkflowOut] = Field(default_factory=list)


class CandidateInvestigationResponse(BaseModel):
    candidate: CandidateWorkflowOut
    result: InvestigationResult


class CandidateValidationResponse(BaseModel):
    candidate: CandidateWorkflowOut
    result: ValidationResult


class CandidateAutomationResponse(BaseModel):
    workflow_id: str
    cluster_id: str
    automation_id: str
    trust_level: str
    generated_by: str
