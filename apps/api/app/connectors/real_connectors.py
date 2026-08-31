"""Real connector implementations.

These are the classes a production deployment swaps in by setting
`LOOP_ENABLE_MOCK_CONNECTORS=false`. Each one declares the credentials and the
API surface it needs, and raises a precise error until those are configured, so
the boundary between "demonstrated" and "wired to production" is explicit rather
than blurred by a stub that silently returns success.

The interface is identical to the mocks, so the engine is unchanged either way.
"""

from __future__ import annotations

from app.connectors.base import Connector, ConnectorError, Context, Step, StepResult


class RealConnector:
    """Base for a live-system connector."""

    name = "real"
    is_mock = False
    #: Environment variables that must be present before this can run.
    required_credentials: tuple[str, ...] = ()
    #: The upstream API this would call, documented for reviewers.
    api: str = ""

    async def execute(self, step: Step, ctx: Context) -> StepResult:
        raise ConnectorError(
            f"{self.name} live connector is not configured. It requires "
            f"{', '.join(self.required_credentials) or 'credentials'} and calls {self.api}. "
            "Set LOOP_ENABLE_MOCK_CONNECTORS=true to run against mocks instead."
        )


class GmailConnector(RealConnector):
    name = "gmail"
    required_credentials = ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET")
    api = "Gmail API v1 (users.messages.list / .get / .send)"


class OutlookConnector(RealConnector):
    name = "outlook"
    required_credentials = ("MS_CLIENT_ID", "MS_CLIENT_SECRET", "MS_TENANT_ID")
    api = "Microsoft Graph v1.0 (/me/messages/delta, /me/sendMail)"


class SheetsConnector(RealConnector):
    name = "sheets"
    required_credentials = ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET")
    api = "Google Sheets API v4 (spreadsheets.values.append / .get)"


class PdfConnector(RealConnector):
    name = "pdf"
    required_credentials = ()
    api = "local extraction (pdfplumber) — no external credentials needed"


class ErpConnector(RealConnector):
    name = "erp"
    required_credentials = ("ERP_BASE_URL", "ERP_API_TOKEN")
    api = "tenant ERP REST API"


class DriveConnector(RealConnector):
    name = "drive"
    required_credentials = ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET")
    api = "Google Drive API v3 (files.create / .get)"


class SlackConnector(RealConnector):
    name = "slack"
    required_credentials = ("SLACK_BOT_TOKEN",)
    api = "Slack Web API (chat.postMessage)"


class BrowserConnector(RealConnector):
    name = "browser"
    required_credentials = ()
    api = "Playwright — drives a real browser for systems with no API"


REAL_REGISTRY: dict[str, Connector] = {
    "gmail": GmailConnector(),
    "outlook": OutlookConnector(),
    "sheets": SheetsConnector(),
    "pdf": PdfConnector(),
    "erp": ErpConnector(),
    "drive": DriveConnector(),
    "slack": SlackConnector(),
    "browser": BrowserConnector(),
}
