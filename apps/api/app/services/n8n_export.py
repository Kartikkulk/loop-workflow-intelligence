"""Translate a Kriyā AI automation into an n8n workflow.

The argument for doing this at all: Kriyā AI's contribution is working out *what*
repeats and whether it is safe to hand over. Executing it needs a connector per
system, each with its own OAuth dance — and n8n already has several hundred of
those, with credential handling its users already trust. Writing a twelfth
connector by hand is worse than emitting a workflow into a tool that has them.

Two things this deliberately does not do:

  * It does not invent credentials. Every node that needs an account is emitted
    without one, so n8n shows it as unconfigured and the person picks the
    account in n8n's own UI. A workflow that arrived pre-wired to somebody's
    mailbox would be alarming, and rightly so.
  * It does not silently drop a step it cannot map. An unmapped connector
    becomes a NoOp node named after what it was supposed to do, so the shape of
    the workflow survives and the gap is visible in the canvas rather than
    hidden in a log.

The guard travels too. `requires_approval_if` becomes an IF node in front of
the irreversible steps, so the hold that Kriyā AI measured is still enforced by the
thing actually doing the work.
"""

from __future__ import annotations

import re
from typing import Any

from app.config import settings

#: Node types per Kriyā AI connector, chosen so an imported workflow lands on a
#: real node the person can configure rather than a placeholder.
_NODE_TYPES: dict[str, tuple[str, float]] = {
    "files": ("n8n-nodes-base.readWriteFile", 1),
    "pdf": ("n8n-nodes-base.extractFromFile", 1),
    "gmail": ("n8n-nodes-base.gmail", 2.1),
    "outlook": ("n8n-nodes-base.microsoftOutlook", 2),
    "jira": ("n8n-nodes-base.jira", 1),
    "slack": ("n8n-nodes-base.slack", 2.2),
    "sheets": ("n8n-nodes-base.googleSheets", 4.5),
    "drive": ("n8n-nodes-base.googleDrive", 3),
    "github": ("n8n-nodes-base.github", 1),
    "confluence": ("n8n-nodes-base.httpRequest", 4.2),
    "okta": ("n8n-nodes-base.httpRequest", 4.2),
    "erp": ("n8n-nodes-base.httpRequest", 4.2),
    "crm": ("n8n-nodes-base.httpRequest", 4.2),
    "hrms": ("n8n-nodes-base.httpRequest", 4.2),
    "jenkins": ("n8n-nodes-base.jenkins", 1),
    # There is no git node; running the command is how n8n does this, and it
    # is a real node rather than a placeholder.
    "git": ("n8n-nodes-base.executeCommand", 1),
}

_NO_OP = ("n8n-nodes-base.noOp", 1)


def node_type_for(connector: str) -> tuple[str, float] | None:
    """The n8n node backing a Kriyā AI connector, or None when nothing maps.

    Public because the execution planner needs the same answer to decide
    whether n8n could run a whole flow. Two copies of this table would drift,
    and the planner would start recommending a backend that cannot run a step.
    """
    return _NODE_TYPES.get(connector)


#: How often the workflow should wake up, per Kriyā AI trigger type. A workflow
#: nobody triggers does nothing, so a trigger is always emitted.
_SCHEDULE_BY_TRIGGER = {
    "email_received": "hours",
    "file_created": "hours",
    "schedule": "days",
    "manual": None,
}

_CONDITION = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_. ]*?)\s*(>=|<=|==|!=|>|<)\s*(.+?)\s*$"
)

_N8N_OPERATORS = {
    ">": "gt",
    "<": "lt",
    ">=": "gte",
    "<=": "lte",
    "==": "equals",
    "!=": "notEquals",
}


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", text).strip()
    return cleaned or "Step"


def _node_name(step: dict[str, Any]) -> str:
    """A human name for the canvas, from the step's own description."""
    description = str(step.get("description") or "").strip()
    if description:
        return _slug(description).title()[:60]
    return f"{str(step.get('connector', 'step')).title()} {step.get('id', '')}".strip()


def _parameters_for(
    step: dict[str, Any], *, mount: str, constants: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Node parameters that are safe to prefill.

    Only values Kriyā AI genuinely observed are set. Anything that would amount to
    guessing at somebody's project key, channel or spreadsheet is left empty for
    them to fill in, because a wrong prefilled target is harder to notice than
    an empty one.

    `mount` is where the document root appears *inside the n8n container*. The
    paths Kriyā AI observed are host paths, and a host path in a file node resolves
    to nothing on the other side of the container boundary — so the first run
    fails with "no such file" and looks like a Kriyā AI bug rather than a mapping
    one.
    """
    connector = str(step.get("connector", ""))
    action = str(step.get("type", ""))
    known = constants or {}

    if connector == "files":
        if action in ("read", "extract"):
            # A glob, not a single path: the schedule trigger carries no data,
            # so something has to go and find the work. Without this the first
            # node reads an empty expression and the run ends immediately.
            return {
                "operation": "read",
                "fileSelector": f"{mount}/Inbox/*.pdf",
                "options": {"dataPropertyName": "data"},
            }
        return {
            "operation": "write",
            "fileName": (
                f"={{{{ '{mount}/' + "
                "($json.invoice_date || '').slice(0,4) + '/' + "
                "($json.invoice_date || '').slice(5,7) + '/' + "
                # Not an f-string, so these braces are literal: the expression
                # needs exactly two to close.
                "($binary.data.fileName || 'document.pdf') }}"
            ),
            "dataPropertyName": "data",
        }
    if connector == "pdf":
        return {"operation": "pdf", "binaryPropertyName": "data"}
    if connector == "git":
        # Prefilled because it is the command that was actually observed, and
        # it only reads. A reviewer can see exactly what would run.
        return {
            "command": "git -C {{ $json.repo_path }} log --since=1.day "
            "--pretty=format:'%h %an %s'"
        }
    if connector == "jira":
        if action == "send":
            # The key and the wording come from what earlier steps produced.
            # Leaving them blank made the node import cleanly and then fail on
            # every run with nothing to post and nowhere to post it.
            # A field the log shows the same value for every single time is a
            # constant, not something flowing between steps. Emitting it as an
            # expression meant the node looked configured and then resolved to
            # undefined, because nothing upstream in n8n produces it.
            ticket = known.get("ticket_id") or known.get("issue_key")
            return {
                "resource": "issueComment",
                "operation": "create",
                "issueKey": str(ticket) if ticket else "={{ $json.ticket_id }}",
                "comment": (
                    "={{ 'Filed ' + ($json.invoice_no || $binary.data.fileName) "
                    "+ ' — total INR ' + (($json.amount || 0) / 100).toFixed(2) "
                    "+ ' (filed automatically by Kriyā AI)' }}"
                ),
            }
        if action == "create":
            return {"resource": "issue", "operation": "create"}
        return {"resource": "issue", "operation": "update"}
    if connector in ("gmail", "outlook"):
        if action == "send":
            return {"resource": "message", "operation": "send"}
        return {"resource": "message", "operation": "getAll"}
    if connector == "slack":
        return {"resource": "message", "operation": "post"}
    if connector == "sheets":
        return {"operation": "append" if action == "create" else "read"}
    if connector in ("erp", "crm", "hrms", "okta", "confluence"):
        # An HTTP node with no URL imports cleanly and shows as incomplete,
        # which is the honest state: Kriyā AI knows the system was touched but not
        # which endpoint does it.
        return {"method": "GET" if action in ("read", "search") else "POST"}
    return {}


def _guard_node(expression: str, position: list[int]) -> dict[str, Any] | None:
    """An IF node enforcing Kriyā AI's approval guard, or None if unparseable.

    Failing closed matters here as much as it does in Kriyā AI's own engine: a guard
    that cannot be translated must not become an IF node that always passes.
    Returning None means the caller leaves the guard out entirely and says so,
    rather than shipping a workflow that looks guarded and is not.
    """
    match = _CONDITION.match(expression)
    if not match:
        return None
    field, operator, literal = match.groups()
    n8n_operator = _N8N_OPERATORS.get(operator)
    if n8n_operator is None:
        return None

    try:
        value: Any = float(literal)
        value = int(value) if value.is_integer() else value
        kind = "number"
    except ValueError:
        value = literal.strip("'\"")
        kind = "string"

    # The condition is inverted on purpose. Kriyā AI's guard says "hold when this is
    # true", and what the workflow needs is "continue when it is not".
    negated = {
        "gt": "lte", "lte": "gt", "lt": "gte", "gte": "lt",
        "equals": "notEquals", "notEquals": "equals",
    }[n8n_operator]

    return {
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "typeValidation": "loose"},
                "conditions": [
                    {
                        "leftValue": f"={{{{ $json.{field.strip()} }}}}",
                        "rightValue": value,
                        "operator": {"type": kind, "operation": negated},
                    }
                ],
                "combinator": "and",
            }
        },
        "id": "guard",
        "name": "Within policy limit",
        "type": "n8n-nodes-base.if",
        "typeVersion": 2,
        "position": position,
    }


#: Cadences a caller may ask for, mapped to n8n's schedule-trigger field.
SCHEDULES = {"hourly": "hours", "daily": "days", "weekly": "weeks", "manual": None}


def to_n8n_workflow(
    automation: dict[str, Any],
    *,
    schedule: str | None = None,
    mount: str | None = None,
    constants: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an importable n8n workflow from a Kriyā AI automation.

    `automation` is the shape the detail endpoint returns: name, trigger, steps
    and guards. `schedule` overrides how often it runs — the observed trigger
    says what set the work off for a human, which is not always how you want a
    machine to wake up.
    """
    files_mount = (mount or settings.n8n_files_mount).rstrip("/")
    steps: list[dict[str, Any]] = list(automation.get("steps") or [])
    guards: dict[str, Any] = dict(automation.get("guards") or {})
    trigger = dict(automation.get("trigger") or {})
    irreversible = set(guards.get("irreversible") or [])

    nodes: list[dict[str, Any]] = []
    notes: list[str] = []
    x, y = 260, 300

    if schedule is not None:
        if schedule not in SCHEDULES:
            raise ValueError(
                f"unknown schedule {schedule!r}; expected one of {', '.join(SCHEDULES)}"
            )
        cadence = SCHEDULES[schedule]
    else:
        cadence = _SCHEDULE_BY_TRIGGER.get(str(trigger.get("type", "manual")))
    if cadence:
        nodes.append(
            {
                "parameters": {
                    "rule": {"interval": [{"field": cadence}]},
                },
                "id": "trigger",
                "name": {
                    "hours": "Every hour",
                    "days": "Every day",
                    "weeks": "Every week",
                }.get(cadence, "On a schedule"),
                "type": "n8n-nodes-base.scheduleTrigger",
                "typeVersion": 1.2,
                "position": [x, y],
            }
        )
    else:
        nodes.append(
            {
                "parameters": {},
                "id": "trigger",
                "name": "When run manually",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "position": [x, y],
            }
        )

    guard_expression = str(guards.get("requires_approval_if") or "").strip()
    first_irreversible = next(
        (index for index, s in enumerate(steps) if str(s.get("id")) in irreversible),
        None,
    )

    for index, step in enumerate(steps):
        x += 220
        if (
            guard_expression
            and first_irreversible is not None
            and index == first_irreversible
        ):
            guard = _guard_node(guard_expression, [x, y])
            if guard is None:
                notes.append(
                    f"guard {guard_expression!r} could not be translated and was "
                    "left out — add the check by hand before enabling this"
                )
            else:
                nodes.append(guard)
                x += 220

        connector = str(step.get("connector", ""))
        node_type, version = node_type_for(connector) or _NO_OP
        if node_type == _NO_OP[0]:
            notes.append(
                f"no n8n node is mapped for '{connector}'; step {step.get('id')} "
                "imported as a placeholder"
            )
        nodes.append(
            {
                "parameters": _parameters_for(step, mount=files_mount, constants=constants),
                "id": str(step.get("id", f"s{index + 1}")),
                "name": _node_name(step),
                "type": node_type,
                "typeVersion": version,
                "position": [x, y],
            }
        )

    connections: dict[str, Any] = {}
    for previous, current in zip(nodes, nodes[1:], strict=False):
        # An IF node's first output is the true branch, which is the one that
        # carries on. Anything on the false branch is being held, and is left
        # unconnected so it visibly stops there.
        connections[previous["name"]] = {
            "main": [[{"node": current["name"], "type": "main", "index": 0}]]
        }

    return {
        "name": str(automation.get("name") or "Kriyā AI workflow"),
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
        # Not part of n8n's schema; carried alongside so the caller can tell the
        # person what did not survive the translation.
        "_loop_notes": notes,
    }
