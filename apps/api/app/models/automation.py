"""F4/F7 — generated automations and their position on the trust ladder."""

import enum

from sqlalchemy import JSON, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TrustLevel(enum.StrEnum):
    """The five rungs. Promotion is earned by measured agreement, never asserted."""

    OBSERVE = "OBSERVE"
    SUGGEST = "SUGGEST"
    SHADOW = "SHADOW"
    ASSIST = "ASSIST"
    AUTONOMOUS = "AUTONOMOUS"

    @property
    def rank(self) -> int:
        return _LADDER.index(self)

    def next_level(self) -> "TrustLevel | None":
        i = self.rank
        return _LADDER[i + 1] if i + 1 < len(_LADDER) else None

    def previous_level(self) -> "TrustLevel | None":
        i = self.rank
        return _LADDER[i - 1] if i > 0 else None


_LADDER: list[TrustLevel] = [
    TrustLevel.OBSERVE,
    TrustLevel.SUGGEST,
    TrustLevel.SHADOW,
    TrustLevel.ASSIST,
    TrustLevel.AUTONOMOUS,
]


class Automation(Base, TimestampMixin):
    """A runnable flow definition generated from a cluster."""

    __tablename__ = "automations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cluster_id: Mapped[str] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # The flow definition: {trigger, steps[], guards}. Steps carry depends_on,
    # which F8 self-healing relies on entirely.
    trigger: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    guards: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Branch rules accepted from the exception queue (F8).
    rules: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    trust_level: Mapped[TrustLevel] = mapped_column(
        Enum(TrustLevel, native_enum=False, length=16),
        nullable=False,
        default=TrustLevel.SUGGEST,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    shadow_run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    critical_mismatch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    replay_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Sample size and human-involvement count from the last backtest. Coverage
    # is measured from these when available: a replay over hundreds of real
    # triggers is far better evidence than a handful of shadow runs.
    replay_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    replay_human_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    generated_by: Mapped[str] = mapped_column(String(32), nullable=False, default="heuristic")

    #: n8n's id for this workflow, once it has been approved and exported.
    #: Its presence is what "approved" means: LOOP decided the work was worth
    #: automating and handed it to the thing that will run it. Empty until then.
    n8n_workflow_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    trust_history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
