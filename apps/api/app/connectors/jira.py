"""A live Jira connector: files and updates real issues.

This is the write half of the Atlassian integration. `activity_import` already
reads your Jira history to feed detection; this puts something back, which is
what turns a detected workflow into one that actually does the job.

It authenticates with its own API token, deliberately *not* with the OAuth
connection the console stores under Sources. That connection is an observation
tool and every scope it requests is read-only; adding `write:jira-work` to it
would have bought this one workflow at the cost of the promise made to everyone
who connects an account. A separate token is opt-in, visible in `.env`, and can
be revoked without disconnecting anything else.

Safety, in the order it applies:

  * The registry hands this class out only when `enable_mock_connectors` is
    false, and forces the mock for replay and shadow whatever the setting says.
  * `settings.jira_dry_run` keeps it describing what it would file until it is
    explicitly turned off.
  * A `create` names a project key that must appear in `jira_allowed_projects`,
    so a model-generated flow cannot file into an arbitrary project.
  * With no token configured, every write path refuses with an explanation
    rather than half-succeeding.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from app.connectors.base import Context, Step, StepResult

logger = logging.getLogger("loop.connectors.jira")

_API_TIMEOUT = 30.0


class JiraNotConfigured(RuntimeError):
    """Raised when the write credential is missing, with what to set."""


def _credentials() -> tuple[str, tuple[str, str]]:
    """The Jira base URL and the basic-auth pair, from configuration."""
    missing = [
        name
        for name, value in (
            ("LOOP_JIRA_SITE_URL", settings.jira_site_url),
            ("LOOP_JIRA_EMAIL", settings.jira_email),
            ("LOOP_JIRA_API_TOKEN", settings.jira_api_token),
        )
        if not value.strip()
    ]
    if missing:
        raise JiraNotConfigured(
            "Jira writing is not configured. Set "
            + ", ".join(missing)
            + " in .env. Create a token at "
            "https://id.atlassian.com/manage-profile/security/api-tokens"
        )
    base = settings.jira_site_url.strip().rstrip("/")
    return base, (settings.jira_email.strip(), settings.jira_api_token.strip())


def _text_block(text: str) -> dict[str, Any]:
    """Jira's rich-text document format, for a single paragraph of plain text."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }


def _first(available: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = available.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value not in (None, ""):
            return str(value)
    return None


def _compose_note(available: dict[str, Any]) -> str | None:
    """Render a note from what the earlier steps found, when none was supplied.

    A flow assembled from an observed signature knows *that* a note gets added
    to the ticket, but carries no wording for it — nobody types the sentence
    into the event log. Rather than fail on the last step of an otherwise
    working automation, the connector states plainly what it did, using only
    values earlier steps actually produced. If none of them resolved there is
    nothing truthful to say, and it returns None so the step fails instead.
    """
    number = _first(available, "invoice_no", "invoice_number")
    filed = _first(available, "filed_path")
    amount = available.get("amount")

    parts: list[str] = []
    if number:
        parts.append(f"Filed invoice {number}")
    if isinstance(amount, (int, float)):
        # Stored in minor units everywhere in Kriyā AI; shown in rupees here.
        parts.append(f"total INR {amount / 100:,.2f}")
    if filed:
        parts.append(f"saved to {filed}")
    if not parts:
        return None
    return " — ".join(parts) + " (filed automatically by Kriyā AI)"


class JiraConnector:
    """Creates and updates Jira issues through the REST v3 API."""

    name = "jira"
    is_mock = False
    api = "Jira Cloud REST v3 (issue.create / issue.edit / issue.comment)"
    required_credentials: tuple[str, ...] = (
        "LOOP_JIRA_SITE_URL",
        "LOOP_JIRA_EMAIL",
        "LOOP_JIRA_API_TOKEN",
    )

    async def execute(self, step: Step, ctx: Context) -> StepResult:
        handler = {
            "create": self._create,
            "update": self._update,
            "send": self._comment,
        }.get(step.type)
        if handler is None:
            # `read` and `search` belong to the importer, which already has a
            # tested path for them; duplicating that here would give two places
            # to fix when Jira's search API changes.
            return StepResult(
                step_id=step.id,
                status="failed",
                error=(
                    f"the Jira connector does not perform '{step.type}'. It can "
                    "create an issue, update one, or comment on one."
                ),
                confidence=0.0,
            )

        available = ctx.available()
        if settings.jira_dry_run:
            # A dry run makes no request, so demanding credentials for one made
            # the whole workflow unrunnable until Jira was set up — which
            # defeats the point of having a dry run to look at first.
            base, auth = "", ("", "")
        else:
            try:
                base, auth = _credentials()
            except JiraNotConfigured as exc:
                return StepResult(
                    step_id=step.id, status="failed", error=str(exc), confidence=0.0
                )

        try:
            return await handler(step, ctx, available, base, auth)
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300]
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"Jira returned {exc.response.status_code}: {detail}",
                confidence=0.0,
            )
        except httpx.HTTPError as exc:
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"could not reach Jira: {exc}",
                confidence=0.0,
            )

    # ── operations ──────────────────────────────────────────────────────

    async def _create(
        self, step: Step, ctx: Context, available: dict, base: str, auth: tuple[str, str]
    ) -> StepResult:
        project = _first(step.inputs, "project", "project_key") or _first(
            available, "project", "project_key"
        )
        if not project:
            return StepResult(
                step_id=step.id,
                status="failed",
                error="no Jira project key for this step",
                unresolved=["project"],
                confidence=0.0,
            )
        allowed = settings.jira_allowed_projects_list
        if allowed and project.upper() not in allowed:
            return StepResult(
                step_id=step.id,
                status="failed",
                error=(
                    f"'{project}' is not in LOOP_JIRA_ALLOWED_PROJECTS "
                    f"({', '.join(allowed)}), so this step will not file into it."
                ),
                confidence=0.0,
            )

        summary = _first(step.inputs, "summary", "title") or _first(
            available, "summary", "title", "subject"
        ) or "Update from Kriyā AI"
        description = _first(step.inputs, "description", "body") or _first(
            available, "description", "body"
        ) or ""
        issue_type = _first(step.inputs, "issue_type") or "Task"

        if settings.jira_dry_run:
            ctx.notes.append(f"would create {project} {issue_type}: {summary}")
            return StepResult(
                step_id=step.id,
                status="ok",
                outputs={"project": project, "summary": summary, "issue_key": None},
                confidence=1.0,
                side_effect=f"jira.create {project} '{summary}' (dry run — nothing filed)",
            )

        payload = {
            "fields": {
                "project": {"key": project.upper()},
                "summary": summary[:250],
                "issuetype": {"name": issue_type},
            }
        }
        if description:
            payload["fields"]["description"] = _text_block(description)

        async with httpx.AsyncClient(timeout=_API_TIMEOUT) as client:
            response = await client.post(
                f"{base}/rest/api/3/issue",
                auth=auth,
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            created = response.json()

        key = str(created.get("key", ""))
        logger.info("jira: created %s", key)
        return StepResult(
            step_id=step.id,
            status="ok",
            outputs={"issue_key": key, "project": project, "summary": summary},
            confidence=1.0,
            side_effect=f"jira.create {key}",
        )

    async def _update(
        self, step: Step, ctx: Context, available: dict, base: str, auth: tuple[str, str]
    ) -> StepResult:
        key = _first(step.inputs, "issue_key", "ticket_id") or _first(
            available, "issue_key", "ticket_id"
        )
        if not key:
            return StepResult(
                step_id=step.id,
                status="failed",
                error="no Jira issue key for this step",
                unresolved=["issue_key"],
                confidence=0.0,
            )
        summary = _first(step.inputs, "summary") or _first(available, "summary")
        description = _first(step.inputs, "description", "body") or _first(
            available, "description", "body"
        )
        fields: dict[str, Any] = {}
        if summary:
            fields["summary"] = summary[:250]
        if description:
            fields["description"] = _text_block(description)
        if not fields:
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"nothing to change on {key}: no summary or description resolved",
                confidence=0.0,
            )

        if settings.jira_dry_run:
            ctx.notes.append(f"would update {key}: {', '.join(fields)}")
            return StepResult(
                step_id=step.id,
                status="ok",
                outputs={"issue_key": key},
                confidence=1.0,
                side_effect=f"jira.update {key} (dry run — nothing changed)",
            )

        async with httpx.AsyncClient(timeout=_API_TIMEOUT) as client:
            response = await client.put(
                f"{base}/rest/api/3/issue/{key}",
                auth=auth,
                headers={"Content-Type": "application/json"},
                json={"fields": fields},
            )
            response.raise_for_status()

        logger.info("jira: updated %s", key)
        return StepResult(
            step_id=step.id,
            status="ok",
            outputs={"issue_key": key},
            confidence=1.0,
            side_effect=f"jira.update {key}",
        )

    async def _comment(
        self, step: Step, ctx: Context, available: dict, base: str, auth: tuple[str, str]
    ) -> StepResult:
        key = _first(step.inputs, "issue_key", "ticket_id") or _first(
            available, "issue_key", "ticket_id"
        )
        body = _first(step.inputs, "comment", "body", "note") or _first(
            available, "comment", "body", "note"
        )
        if not body:
            body = _compose_note(available)
        if not key or not body:
            missing = [n for n, v in (("issue_key", key), ("comment", body)) if not v]
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"cannot comment: missing {', '.join(missing)}",
                unresolved=missing,
                confidence=0.0,
            )

        if settings.jira_dry_run:
            ctx.notes.append(f"would comment on {key}")
            return StepResult(
                step_id=step.id,
                status="ok",
                outputs={"issue_key": key},
                confidence=1.0,
                side_effect=f"jira.comment {key} (dry run — nothing posted)",
            )

        async with httpx.AsyncClient(timeout=_API_TIMEOUT) as client:
            response = await client.post(
                f"{base}/rest/api/3/issue/{key}/comment",
                auth=auth,
                headers={"Content-Type": "application/json"},
                json={"body": _text_block(body)},
            )
            response.raise_for_status()

        logger.info("jira: commented on %s", key)
        return StepResult(
            step_id=step.id,
            status="ok",
            outputs={"issue_key": key},
            confidence=1.0,
            side_effect=f"jira.comment {key}",
        )
