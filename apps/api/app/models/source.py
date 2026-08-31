"""Onboarded observation sources.

A source is *a thing that watches*: a browser extension on someone's laptop, an
OAuth connection to a tenant's Microsoft 365, a desktop agent, an uploaded log.

Sources are first-class rows rather than a string on each event because three
things have to be true per-source and are meaningless globally: consent has to
be granted and revocable, capture has to be pausable by the person being
observed, and coverage has to be reportable so an operator knows what LOOP can
and cannot currently see.
"""

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SourceKind(enum.StrEnum):
    """How a source observes.

    Ordered roughly by coverage: later kinds see more, and cost more to deploy.
    """

    UPLOAD = "upload"
    DESCRIBE = "describe"
    BROWSER_EXTENSION = "browser_extension"
    API_CONNECTOR = "api_connector"
    DESKTOP_AGENT = "desktop_agent"
    SCREEN_RECORDING = "screen_recording"


class SourceStatus(enum.StrEnum):
    PENDING = "pending"
    CONNECTED = "connected"
    PAUSED = "paused"
    REVOKED = "revoked"


class CaptureScope(enum.StrEnum):
    """How much of what it sees a source is permitted to transmit.

    `metadata_only` is the default and is what makes this deployable: the
    collector reports that a field called `amount` was filled, never what was
    typed into it. Detection works on the shape of activity, not its content, so
    the default costs almost nothing in capability.
    """

    METADATA_ONLY = "metadata_only"
    WITH_VALUES = "with_values"


class Source(Base, TimestampMixin):
    """One onboarded observation source."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[SourceKind] = mapped_column(
        Enum(SourceKind, native_enum=False, length=32), nullable=False
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    # Who this source observes. A browser extension watches one person; an
    # API connector may watch a whole tenant.
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    team: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")

    status: Mapped[SourceStatus] = mapped_column(
        Enum(SourceStatus, native_enum=False, length=16),
        nullable=False,
        default=SourceStatus.PENDING,
    )
    capture_scope: Mapped[CaptureScope] = mapped_column(
        Enum(CaptureScope, native_enum=False, length=32),
        nullable=False,
        default=CaptureScope.METADATA_ONLY,
    )

    # Consent is recorded, not assumed. A source with no consent timestamp
    # cannot ingest.
    consent_granted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consent_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # SHA-256 of the collector's bearer token. The token itself is shown once at
    # registration and never stored.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Hostnames or application names the person has excluded. Honoured by the
    # collector locally *and* enforced server-side, so a stale collector cannot
    # keep sending an excluded domain.
    denylist: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    last_event_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    @property
    def can_ingest(self) -> bool:
        """A source may only send events while connected and consented."""
        return self.status is SourceStatus.CONNECTED and self.consent_granted_at is not None
