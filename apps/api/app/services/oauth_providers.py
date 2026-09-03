"""Personal OAuth providers.

Kriyā AI is a personal tool: one employee, their own laptop, their own accounts.
Every scope below is a *delegated, read-only, personal* scope — nothing here
needs an administrator to approve it, and nothing here can see a colleague's
activity. That is a deliberate constraint, not a limitation we have not got
round to: a tool that needs IT to enable it never gets tried.

What Kriyā AI cannot do without the person's own consent, it does not do.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class OAuthProvider:
    """One sign-in button."""

    key: str
    label: str
    #: What Kriyā AI reads once connected, in the user's words.
    reads: str

    authorize_url: str
    token_url: str
    #: Read-only personal scopes. No admin consent, no tenant-wide access.
    scopes: list[str]

    #: Environment variables holding the app registration. These belong to the
    #: person running Kriyā AI, not to us — see `setup_steps`.
    client_id_env: str
    client_secret_env: str

    #: Where the person registers their own OAuth app, once.
    setup_url: str
    setup_steps: list[str] = field(default_factory=list)

    #: Extra params some providers require on the authorize call.
    extra_authorize_params: dict[str, str] = field(default_factory=dict)

    @property
    def client_id(self) -> str:
        return _resolve(self.key, "client_id", self.client_id_env)

    @property
    def client_secret(self) -> str:
        return _resolve(self.key, "client_secret", self.client_secret_env)

    @property
    def configured(self) -> bool:
        """True once the person has registered an app and supplied both values."""
        return bool(self.client_id and self.client_secret)


#: Credentials the person typed into the Sources page, loaded from the database
#: at startup and updated whenever they save. Kriyā AI is a single-process personal
#: tool on one laptop, so a module-level cache is the whole story — there is no
#: second worker to fall out of sync with. It exists because the provider
#: properties are read from synchronous code that has no database session to
#: hand; `refresh_credentials` is the only thing that writes to it.
_SAVED: dict[str, dict[str, str]] = {}


def refresh_credentials(rows: dict[str, dict[str, str]]) -> None:
    """Replace the cached credentials with what is stored on disk."""
    _SAVED.clear()
    _SAVED.update(rows)


def _resolve(provider_key: str, field: str, env_name: str) -> str:
    """What the person typed, else what they exported, else nothing.

    The UI wins over the environment so that saving a corrected client id in
    the browser actually takes effect without editing a file and restarting.
    """
    typed = (_SAVED.get(provider_key) or {}).get(field, "")
    if typed.strip():
        return typed.strip()

    from app.config import settings

    attr = env_name.removeprefix("LOOP_").lower()
    return str(getattr(settings, attr, "") or os.environ.get(env_name, "")).strip()


PROVIDERS: list[OAuthProvider] = [
    OAuthProvider(
        key="google",
        label="Google",
        reads=(
            "Your Gmail activity — who you mail, how often, with what attached. "
            "Metadata only; message bodies are never requested."
        ),
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=[
            # Readonly, and only ever used with format=metadata.
            "https://www.googleapis.com/auth/gmail.metadata",
            "https://www.googleapis.com/auth/drive.metadata.readonly",
        ],
        client_id_env="LOOP_GOOGLE_CLIENT_ID",
        client_secret_env="LOOP_GOOGLE_CLIENT_SECRET",
        setup_url="https://console.cloud.google.com/apis/credentials",
        setup_steps=[
            "Open the Google Cloud console and create a project, or pick one you have.",
            "Enable the Gmail API and the Drive API for it.",
            "Under Credentials, create an OAuth client ID of type 'Web application'.",
            "Paste the redirect URI below into 'Authorised redirect URIs'.",
            "Copy the client ID and secret back here and press Save.",
        ],
        # offline + consent so a refresh token actually comes back.
        extra_authorize_params={"access_type": "offline", "prompt": "consent"},
    ),
    OAuthProvider(
        key="microsoft",
        label="Microsoft",
        reads=(
            "Your Outlook mail and calendar activity. Delegated to you alone — it "
            "cannot see anybody else's mailbox."
        ),
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        scopes=["offline_access", "Mail.ReadBasic", "Calendars.Read", "User.Read"],
        client_id_env="LOOP_MS_CLIENT_ID",
        client_secret_env="LOOP_MS_CLIENT_SECRET",
        setup_url="https://portal.azure.com",
        setup_steps=[
            "Open Azure Portal, then Microsoft Entra ID, then App registrations, "
            "then New registration.",
            "Choose 'Accounts in any organizational directory and personal "
            "Microsoft accounts'.",
            "Set the redirect URI (type Web) to the value below.",
            "Under Certificates & secrets, create a client secret.",
            "Copy the Application (client) ID and the secret back here and press Save.",
        ],
    ),
    OAuthProvider(
        key="atlassian",
        label="Jira",
        reads="Issues you worked on, and the transitions and comments you made.",
        authorize_url="https://auth.atlassian.com/authorize",
        token_url="https://auth.atlassian.com/oauth/token",
        scopes=["read:jira-work", "read:jira-user", "offline_access"],
        client_id_env="LOOP_ATLASSIAN_CLIENT_ID",
        client_secret_env="LOOP_ATLASSIAN_CLIENT_SECRET",
        setup_url="https://developer.atlassian.com/console/myapps/",
        setup_steps=[
            "Open the Atlassian developer console and create an OAuth 2.0 (3LO) integration.",
            "Add the Jira API with the read:jira-work and read:jira-user scopes.",
            "Set the callback URL to the value below.",
            "Copy the client ID and secret back here and press Save.",
        ],
        extra_authorize_params={"audience": "api.atlassian.com", "prompt": "consent"},
    ),
    OAuthProvider(
        key="slack",
        label="Slack",
        reads=(
            "Channels you post in and how often — your own messages, not the "
            "whole workspace."
        ),
        authorize_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        scopes=["users:read", "channels:history", "search:read"],
        client_id_env="LOOP_SLACK_CLIENT_ID",
        client_secret_env="LOOP_SLACK_CLIENT_SECRET",
        setup_url="https://api.slack.com/apps",
        setup_steps=[
            "Open api.slack.com/apps and create a new app from scratch.",
            "Under OAuth & Permissions, add the user token scopes users:read, "
            "channels:history and search:read.",
            "Add the redirect URL below.",
            "Copy the client ID and secret back here and press Save.",
        ],
        # Slack puts personal scopes on user_scope, not scope.
        extra_authorize_params={},
    ),
]

PROVIDERS_BY_KEY: dict[str, OAuthProvider] = {p.key: p for p in PROVIDERS}


def redirect_uri(provider_key: str, base: str) -> str:
    """The callback this provider must be registered against."""
    return f"{base.rstrip('/')}/api/v1/connect/{provider_key}/callback"
