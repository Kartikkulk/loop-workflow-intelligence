"""F2/F3 — sessionised task instances and the mined workflow clusters."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TaskInstance(Base, TimestampMixin):
    """One contiguous run of a task by one user, produced by the sessioniser."""

    __tablename__ = "task_instances"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    team: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Ordered list of value-stripped step tokens — the instance's signature.
    signature: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    signature_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    context_switches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cluster_id: Mapped[str | None] = mapped_column(
        ForeignKey("clusters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ground_truth_workflow: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Cluster(Base, TimestampMixin):
    """A repetitive workflow discovered across one or more employees."""

    __tablename__ = "clusters"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The cluster's representative (medoid) signature.
    signature: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    apps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Aggregates (F2 step 4)
    instance_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distinct_users: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    teams: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    median_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    instances_per_user_per_week: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    annual_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_organisational: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Scoring (F3)
    context_switches_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    interruption_tax_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    automatability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # The four components behind the automatability score, kept so the UI can
    # explain the number instead of just asserting it.
    variance_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    build_effort: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    priority: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    do_not_automate: Mapped[bool] = mapped_column(default=False, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Payload keys actually observed for each step token, e.g.
    # {"pdf:extract:fields": ["amount", "currency", "vendor"]}. The flow
    # generator reads this so a generated automation's outputs are fields that
    # genuinely exist in the source systems, which is what makes a replay diff
    # meaningful rather than vacuous.
    observed_fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    sop_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
