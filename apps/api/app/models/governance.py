"""F8 — the human-in-the-loop queue and the self-healing patch stream."""

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ExceptionCase(Base, TimestampMixin):
    """A low-confidence execution routed to a human, with the reason stated."""

    __tablename__ = "exception_cases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    automation_id: Mapped[str] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The input features that made this uncertain — the left half of the
    # (features -> decision) pair the rule learner trains on.
    input_features: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    human_decision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    human_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    # Groups similar exceptions so a rule can be proposed after N samples.
    signature_key: Mapped[str] = mapped_column(String(128), nullable=False, default="", index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class Patch(Base, TimestampMixin):
    """A proposed change to a flow definition.

    Two origins: drift (a depends_on field no longer resolves) and rule (a
    branch learned from repeated human decisions on the exception queue).
    """

    __tablename__ = "patches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    automation_id: Mapped[str] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="drift")
    step_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    from_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    auto_applicable: Mapped[bool] = mapped_column(default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # For rule patches: the branch condition and action to splice into the flow.
    rule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proposed_by: Mapped[str] = mapped_column(String(32), nullable=False, default="heuristic")
