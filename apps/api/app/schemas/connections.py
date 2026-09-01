"""Connecting a personal account: request and response models.

One rule runs through every model here: a client secret goes *in* and never
comes back out. `CredentialStatus` reports whether a secret is set, never what
it is, so a screenshot of the Sources page cannot leak one.
"""

from pydantic import BaseModel, Field


class ProviderOut(BaseModel):
    """One sign-in button, and everything the page needs to draw it."""

    key: str
    label: str
    #: What LOOP reads once connected, in the person's own words.
    reads: str
    scopes: list[str]

    #: True once the person has supplied their own client id and secret.
    configured: bool
    #: Where they register a personal app, and how.
    setup_url: str
    setup_steps: list[str]
    #: The exact value to paste into the provider's redirect-URI field.
    redirect_uri: str
    #: Present so the person can put them in a .env file instead of the UI.
    client_id_env: str
    client_secret_env: str

    #: Whether a client id has been saved, and its first characters so they can
    #: tell which app it is. The secret is never echoed in any form.
    client_id_hint: str = ""
    has_secret: bool = False

    connected: bool = False
    account_label: str = ""
    last_sync_at: str | None = None
    events_imported: int = 0
    last_error: str | None = None


class ProviderList(BaseModel):
    items: list[ProviderOut]
    connected_count: int


class SaveCredentialsRequest(BaseModel):
    """The two values the provider gave the person when they registered an app."""

    client_id: str = Field(min_length=1, max_length=500)
    client_secret: str = Field(min_length=1, max_length=500)


class StartOut(BaseModel):
    """Where to send the browser to sign in."""

    authorize_url: str


class SyncResult(BaseModel):
    """What one sync pulled in, and what detection made of it."""

    provider: str
    events_imported: int
    total_events: int
    clusters_found: int
    message: str
