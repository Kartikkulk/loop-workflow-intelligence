"""A personal account the user has connected.

Tokens live here, in the local database on the user's own machine. That is the
right place for a personal tool: they are never in the repository, never in the
frontend bundle, and never sent anywhere except to the provider that issued
them. Disconnecting deletes both the tokens and every event they produced.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Connection(Base, TimestampMixin):
    """One connected personal account."""

    __tablename__ = "connections"

    #: Provider key — google, microsoft, atlassian, slack.
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)

    #: Who the provider says this is. Shown so the person can see which account
    #: is connected, which matters when they have a work one and a personal one.
    account_label: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    #: Provider-specific extras — Atlassian's cloud id, Slack's team id.
    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    events_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class OAuthState(Base, TimestampMixin):
    """A pending authorisation, holding its PKCE verifier.

    Short-lived and single-use: the callback consumes it. Without this, an
    attacker could feed the callback a code of their own choosing and connect
    their account to this LOOP instance.
    """

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(300), nullable=False, default="")


class AppCredential(Base, TimestampMixin):
    """The person's own OAuth app registration.

    LOOP ships with no client secret of its own — there is no LOOP cloud to
    hold one. Each person registers a personal app with Google or Microsoft
    once and pastes the two values into the Sources page. They are stored here,
    on their machine, and read only when building a sign-in URL or exchanging a
    code. They are never returned to the browser: the API reports whether a
    secret is set, never what it is.
    """

    __tablename__ = "app_credentials"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    client_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    client_secret: Mapped[str] = mapped_column(Text, nullable=False, default="")
