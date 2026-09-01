"""Pull a connected account's activity and turn it into canonical events.

Every fetcher below asks for *metadata* and nothing more. Gmail is read with
`format=metadata` and an explicit header allow-list, so the body is never even
transmitted; Graph selects named fields rather than the whole message. That is
not politeness — a personal tool that quietly downloads the contents of your
inbox is one you would be right to uninstall.

What comes back is the same `Event` shape the browser collector produces, so
detection, scoring and everything downstream cannot tell the difference.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.services.ids import new_id
from app.services.normaliser import NormalisedEvent, as_utc
from app.services.oauth import OAuthError, valid_token
from app.services.oauth_providers import OAuthProvider

logger = logging.getLogger("loop.import")

#: How far back a first sync reaches.
DEFAULT_WINDOW_DAYS = 60

#: Ceiling per sync. Enough to detect a pattern, small enough to stay quick.
MAX_ITEMS = 400


def _iso(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def _get(client: httpx.AsyncClient, url: str, token: str, **params):
    response = await client.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params=params or None,
    )
    if response.status_code == 401:
        raise OAuthError("The provider rejected the token. Reconnect the account.")
    response.raise_for_status()
    return response.json()


# ── Google ──────────────────────────────────────────────────────────────────

async def _fetch_google(token: str, user_id: str, since: datetime) -> list[NormalisedEvent]:
    """Gmail activity, metadata only.

    `format=metadata` with an explicit header allow-list means the API does not
    return the body at all — we are not choosing to discard it, we never receive
    it.
    """
    events: list[NormalisedEvent] = []
    after = int(since.timestamp())

    async with httpx.AsyncClient(timeout=30) as client:
        listing = await _get(
            client,
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            token,
            q=f"after:{after}",
            maxResults=min(MAX_ITEMS, 200),
        )
        for stub in (listing.get("messages") or [])[:MAX_ITEMS]:
            detail = await _get(
                client,
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{stub['id']}",
                token,
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            )
            headers = {
                h["name"].lower(): h["value"]
                for h in (detail.get("payload", {}).get("headers") or [])
            }
            labels = detail.get("labelIds") or []
            sent = "SENT" in labels
            when = datetime.fromtimestamp(int(detail.get("internalDate", 0)) / 1000, UTC)

            events.append(
                NormalisedEvent(
                    id=new_id("evt"),
                    user_id=user_id,
                    team="personal",
                    timestamp=when,
                    app="gmail",
                    action="send" if sent else "read",
                    object_type="email_with_attachment"
                    if "attachment" in str(detail.get("payload", {}).get("mimeType", ""))
                    else "email",
                    object_id=str(detail.get("threadId") or stub["id"])[:128],
                    duration_ms=45_000,
                    payload={
                        # Counterparty domain, not the address: enough to see
                        # "the same vendor every week", not enough to be a
                        # contact list.
                        "counterparty": (headers.get("from" if not sent else "to", "")
                                         .split("@")[-1].strip(">").strip())[:64],
                        "has_attachment": bool(detail.get("payload", {}).get("parts")),
                    },
                    session_id=None,
                    source="api_connector",
                )
            )
    return events


# ── Microsoft ───────────────────────────────────────────────────────────────

async def _fetch_microsoft(token: str, user_id: str, since: datetime) -> list[NormalisedEvent]:
    """Outlook mail and calendar, selected fields only."""
    events: list[NormalisedEvent] = []
    stamp = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    async with httpx.AsyncClient(timeout=30) as client:
        mail = await _get(
            client,
            "https://graph.microsoft.com/v1.0/me/messages",
            token,
            **{
                "$select": "id,receivedDateTime,sentDateTime,hasAttachments"
                           ",from,toRecipients,conversationId",
                "$filter": f"receivedDateTime ge {stamp}",
                "$top": min(MAX_ITEMS, 200),
                "$orderby": "receivedDateTime desc",
            },
        )
        for item in (mail.get("value") or [])[:MAX_ITEMS]:
            sender = (item.get("from") or {}).get("emailAddress", {}).get("address", "")
            events.append(
                NormalisedEvent(
                    id=new_id("evt"),
                    user_id=user_id,
                    team="personal",
                    timestamp=_iso(item.get("receivedDateTime")),
                    app="outlook",
                    action="read",
                    object_type="email_with_attachment"
                    if item.get("hasAttachments")
                    else "email",
                    object_id=str(item.get("conversationId") or item.get("id"))[:128],
                    duration_ms=45_000,
                    payload={
                        "counterparty": sender.split("@")[-1][:64],
                        "has_attachment": bool(item.get("hasAttachments")),
                    },
                    session_id=None,
                    source="api_connector",
                )
            )

        events_response = await _get(
            client,
            "https://graph.microsoft.com/v1.0/me/events",
            token,
            **{"$select": "id,subject,start,end,organizer", "$top": 100},
        )
        for item in (events_response.get("value") or [])[:100]:
            start = _iso((item.get("start") or {}).get("dateTime"))
            if start < since:
                continue
            events.append(
                NormalisedEvent(
                    id=new_id("evt"),
                    user_id=user_id,
                    team="personal",
                    timestamp=start,
                    app="calendar",
                    action="read",
                    object_type="meeting",
                    object_id=str(item.get("id"))[:128],
                    duration_ms=1_800_000,
                    payload={},
                    session_id=None,
                    source="api_connector",
                )
            )
    return events


# ── Jira ────────────────────────────────────────────────────────────────────

async def _fetch_atlassian(
    token: str, user_id: str, since: datetime, cloud_id: str
) -> list[NormalisedEvent]:
    """Issues the person touched, and what they did to them."""
    if not cloud_id:
        raise OAuthError("Jira did not report a site. Reconnect the account.")

    events: list[NormalisedEvent] = []
    jql = f"assignee = currentUser() AND updated >= -{DEFAULT_WINDOW_DAYS}d ORDER BY updated DESC"

    async with httpx.AsyncClient(timeout=30) as client:
        found = await _get(
            client,
            f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search",
            token,
            jql=jql,
            maxResults=min(MAX_ITEMS, 100),
            fields="updated,status,issuetype,project",
        )
        for issue in (found.get("issues") or [])[:MAX_ITEMS]:
            fields = issue.get("fields") or {}
            events.append(
                NormalisedEvent(
                    id=new_id("evt"),
                    user_id=user_id,
                    team="personal",
                    timestamp=_iso(fields.get("updated")),
                    app="jira",
                    action="update",
                    object_type=str(
                        (fields.get("issuetype") or {}).get("name", "issue")
                    ).lower().replace(" ", "_")[:40],
                    object_id=str(issue.get("key"))[:128],
                    duration_ms=120_000,
                    payload={
                        "project": str((fields.get("project") or {}).get("key", ""))[:32],
                        "status": str((fields.get("status") or {}).get("name", ""))[:32],
                    },
                    session_id=None,
                    source="api_connector",
                )
            )
    return events


# ── Slack ───────────────────────────────────────────────────────────────────

async def _fetch_slack(token: str, user_id: str, since: datetime) -> list[NormalisedEvent]:
    """The person's own messages, found through search rather than by reading channels."""
    events: list[NormalisedEvent] = []
    async with httpx.AsyncClient(timeout=30) as client:
        found = await _get(
            client,
            "https://slack.com/api/search.messages",
            token,
            query=f"from:me after:{since.strftime('%Y-%m-%d')}",
            count=min(MAX_ITEMS, 100),
        )
        if not found.get("ok"):
            raise OAuthError(f"Slack said: {found.get('error', 'unknown error')}")
        for match in ((found.get("messages") or {}).get("matches") or [])[:MAX_ITEMS]:
            events.append(
                NormalisedEvent(
                    id=new_id("evt"),
                    user_id=user_id,
                    team="personal",
                    timestamp=datetime.fromtimestamp(float(match.get("ts", 0)), UTC),
                    app="slack",
                    action="send",
                    object_type="message",
                    object_id=str(match.get("iid") or "")[:128],
                    duration_ms=40_000,
                    payload={"channel": str((match.get("channel") or {}).get("name", ""))[:64]},
                    session_id=None,
                    source="api_connector",
                )
            )
    return events


# ── entry point ─────────────────────────────────────────────────────────────

async def fetch_activity(
    session: AsyncSession,
    provider: OAuthProvider,
    connection: Connection,
    user_id: str = "u_me",
) -> list[NormalisedEvent]:
    """Pull everything new since the last sync, as canonical events."""
    token = await valid_token(session, provider, connection)
    since = (
        as_utc(connection.last_sync_at)
        if connection.last_sync_at
        else datetime.now(UTC) - timedelta(days=DEFAULT_WINDOW_DAYS)
    )

    if provider.key == "google":
        return await _fetch_google(token, user_id, since)
    if provider.key == "microsoft":
        return await _fetch_microsoft(token, user_id, since)
    if provider.key == "atlassian":
        cloud_id = str((connection.extra or {}).get("cloud_id", ""))
        return await _fetch_atlassian(token, user_id, since, cloud_id)
    if provider.key == "slack":
        return await _fetch_slack(token, user_id, since)

    raise OAuthError(f"No importer written for {provider.label} yet.")
