"""F5/F6/F7 — execution records and shadow-mode comparisons."""

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ExecutionMode(enum.StrEnum):
    """One engine, three modes.

    replay — mocked side effects, diffed against the historical log
    shadow — mocked side effects, diffed against live human actions
    live   — real side effects, nothing to diff against
    """

    REPLAY = "replay"
    SHADOW = "shadow"
    LIVE = "live"


class Execution(Base, TimestampMixin):
    """One run of an automation through the engine, in any mode."""

    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    automation_id: Mapped[str] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mode: Mapped[ExecutionMode] = mapped_column(
        Enum(ExecutionMode, native_enum=False, length=16), nullable=False
    )
    trigger_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    # Per-step results, including any failures and the resolved depends_on values.
    step_results: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    output: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ShadowRun(Base, TimestampMixin):
    """A prediction the automation made while a human did the task for real."""

    __tablename__ = "shadow_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    automation_id: Mapped[str] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    predicted: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    observed: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    field_matches: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Weighted agreement: critical fields count double.
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    critical_mismatch: Mapped[bool] = mapped_column(default=False, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
