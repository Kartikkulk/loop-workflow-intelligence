"""F1 — the canonical event stream, plus the source-agnostic app/action registry."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AppRegistry(Base, TimestampMixin):
    """Known source applications.

    Deliberately a table rather than a Python enum: onboarding a new source
    (outlook, teams, sap, jira) must not require a code change or a migration
    that touches every service.
    """

    __tablename__ = "app_registry"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="other")


class ActionRegistry(Base, TimestampMixin):
    """Known verbs. Same rationale as AppRegistry."""

    __tablename__ = "action_registry"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    # Destructive/irreversible actions can never be auto-patched or run
    # autonomously without an explicit guard.
    irreversible: Mapped[bool] = mapped_column(default=False, nullable=False)


class Event(Base, TimestampMixin):
    """One observed user action, normalised from any ingestion adapter."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_user_ts", "user_id", "timestamp"),
        Index("ix_events_session", "session_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    team: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    app: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Set only by the seed generator, and only so tests can assert that
    # detection recovered the truth. Never read by any detection service.
    ground_truth_workflow: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="upload")
    # Which onboarded source reported this. Nullable because seed and upload
    # events predate any source registration.
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def step_token(self) -> str:
        """The value-stripped token used to build a workflow signature."""
        return f"{self.app}:{self.action}:{self.object_type}"
