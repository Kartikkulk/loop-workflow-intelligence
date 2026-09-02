"""Persisted lifecycle state for workflows observed by the browser collector."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class WorkflowCandidate(Base, TimestampMixin):
    """A live browser-derived candidate; never a synthetic seed cluster."""

    __tablename__ = "workflow_candidates"

    workflow_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    signature_tokens: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    member_signature_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    sample_instance_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    session_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distinct_users: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    apps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="observed")
    investigation_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    automation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
