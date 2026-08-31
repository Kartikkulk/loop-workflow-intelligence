"""Shared response models."""

from pydantic import BaseModel, Field


class Health(BaseModel):
    """GET /health"""

    status: str
    database: str
    llm: str
    connectors: str
    version: str


class Message(BaseModel):
    """Generic acknowledgement."""

    ok: bool = True
    message: str


class LlmUsage(BaseModel):
    """Running LLM cost, surfaced so the operator can see it during a demo."""

    available: bool
    model: str
    calls: int
    fallbacks: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float = Field(description="Approximate, based on list pricing.")
