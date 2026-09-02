"""Agent analysis runs. Not Discovery/Cluster rows — proposals only."""

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class WorkflowAgentAnalysis(Base, TimestampMixin):
    """One Agent pass over an Activity Atlas. Never writes Cluster rows."""

    __tablename__ = "workflow_agent_analyses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unavailable")
    generated_by: Mapped[str] = mapped_column(String(32), nullable=False, default="fallback")
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
