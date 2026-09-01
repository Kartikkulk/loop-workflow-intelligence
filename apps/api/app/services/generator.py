"""F4 — turn a detected cluster into a runnable flow definition and an SOP.

The flow definition can be produced through local LLM structured output, so the
shape is governed by a JSON schema rather than by parsing prose. The
deterministic fallback below produces a genuinely runnable flow from the
observed signature alone, which is what lets the entire product be demonstrated
without a running model.
"""

from __future__ import annotations

from typing import Any

from app.llm.client import llm
from app.llm.tools import GENERATE_FLOW
from app.models.cluster import Cluster

# What each observed step token contributes to a flow step: the fields it reads
# and the fields it produces. Derived from the canonical action vocabulary, so a
# newly observed workflow gets a sensible flow without a code change.
_OUTPUTS_BY_ACTION: dict[str, list[str]] = {
    "read": ["subject", "sender", "body"],
    "extract": ["vendor", "amount", "currency", "invoice_date", "po_number"],
    "create": ["row_id"],
    "update": ["record_id", "status"],
    "send": ["message_id"],
    "search": ["match_id"],
    "navigate": ["page_state"],
    "delete": ["deleted_id"],
}

_DEPENDS_BY_ACTION: dict[str, list[str]] = {
    "read": [],
    "extract": ["body"],
    "create": ["vendor", "amount"],
    "update": ["record_id"],
    "send": ["recipient"],
    "search": ["po_number"],
    "navigate": [],
    "delete": ["record_id"],
}

_IRREVERSIBLE_ACTIONS = {"send", "delete"}

_TRIGGER_BY_APP = {
    "gmail": "email_received",
    "outlook": "email_received",
    "sheets": "schedule",
    "drive": "file_created",
    "erp": "record_updated",
}


# Fields that exist only because a human decided something. An automation may
# produce these as predictions but must never read them as inputs.
DECISION_FIELDS = frozenset({"status", "amount_inr", "approval", "note"})


def _fallback_flow(cluster: Cluster) -> dict[str, Any]:
    """Build a runnable flow from the observed signature, with no model call.

    Step outputs come from `cluster.observed_fields` — the payload keys actually
    seen on that step in the log — rather than from a fixed action-to-field map.
    That matters for more than tidiness: if a step declares outputs the source
    systems do not have, the replay diff finds no comparable fields and reports a
    meaningless accuracy. Generating against observed reality is what makes the
    backtest a real measurement.

    Every step declares depends_on — the resolution the mock connectors perform
    and the drift detector watches — so a fallback-generated automation is a
    first-class citizen, not a degraded placeholder.
    """
    signature: list[str] = list(cluster.signature or [])
    observed: dict[str, list[str]] = dict(cluster.observed_fields or {})
    steps: list[dict[str, Any]] = []
    produced: set[str] = set()

    for index, token in enumerate(signature, start=1):
        parts = token.split(":")
        app = parts[0] if parts else "browser"
        action = parts[1] if len(parts) > 1 else "read"
        object_type = parts[2] if len(parts) > 2 else "unknown"

        seen = list(observed.get(token) or [])
        outputs = seen or list(_OUTPUTS_BY_ACTION.get(action, ["result"]))

        # Depend on fields this step is observed to use that an earlier step
        # already produced. A dependency nothing can satisfy is a bug, not drift.
        depends = [f for f in seen if f in produced and f not in DECISION_FIELDS]
        if not depends:
            depends = [
                d for d in _DEPENDS_BY_ACTION.get(action, []) if d in produced
            ]
        if index == 1:
            depends = []

        steps.append(
            {
                "id": f"s{index}",
                "type": action,
                "connector": app,
                "description": f"{action} {object_type.replace('_', ' ')} in {app}",
                "inputs": {"object_type": object_type},
                "outputs": outputs,
                "depends_on": depends,
            }
        )
        produced.update(outputs)

    first_app = signature[0].split(":")[0] if signature else "gmail"
    trigger_type = _TRIGGER_BY_APP.get(first_app, "manual")
    first_parts = signature[0].split(":") if signature else []
    first_object = first_parts[2] if len(first_parts) > 2 else ""

    irreversible = [
        s["id"] for s in steps if s["type"] in _IRREVERSIBLE_ACTIONS
    ]

    return {
        "name": cluster.name,
        "description": (
            f"Automates the {len(steps)}-step workflow observed "
            f"{cluster.instance_count} times across {cluster.distinct_users} employee(s)."
        ),
        "trigger": {"type": trigger_type, "filter": {"object_type": first_object}},
        "steps": steps,
        "guards": {
            # 10,00,000 paise = 10,000 rupees. Above this a human signs off on
            # anything irreversible.
            "requires_approval_if": "amount > 1000000",
            "irreversible": irreversible,
        },
    }


def _sanitise_flow(raw: dict[str, Any], cluster: Cluster) -> dict[str, Any]:
    """Repair a model-generated flow so the engine can always run it.

    Trust the model for naming and intent; enforce the invariants ourselves. In
    particular a step must never depend on a field that no earlier step
    produces, or the automation fails on its first run for a reason that looks
    like drift but is not.
    """
    fallback = _fallback_flow(cluster)
    steps = raw.get("steps") or fallback["steps"]

    produced: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        step = dict(step)
        step.setdefault("id", f"s{index}")
        step.setdefault("type", "read")
        step.setdefault("connector", "browser")
        outputs = list(step.get("outputs") or _OUTPUTS_BY_ACTION.get(step["type"], ["result"]))
        # Union in the fields actually observed for this step. The model names
        # steps well but cannot know the source schema; the log does.
        token_index = index - 1
        signature = list(cluster.signature or [])
        if token_index < len(signature):
            for observed_field in (cluster.observed_fields or {}).get(signature[token_index], []):
                if observed_field not in outputs:
                    outputs.append(observed_field)
        depends = [d for d in (step.get("depends_on") or []) if d.split(".")[-1] in produced]
        if index == 1:
            depends = []
        step["outputs"] = outputs
        step["depends_on"] = depends
        step["inputs"] = dict(step.get("inputs") or {})
        cleaned.append(step)
        produced.update(outputs)

    guards = dict(raw.get("guards") or {})
    guards.setdefault("requires_approval_if", fallback["guards"]["requires_approval_if"])
    declared = guards.get("irreversible") or []
    # Any step whose action is irreversible must be listed, whatever the model said.
    for step in cleaned:
        if step["type"] in _IRREVERSIBLE_ACTIONS and step["id"] not in declared:
            declared.append(step["id"])
    guards["irreversible"] = declared

    trigger = dict(raw.get("trigger") or fallback["trigger"])
    trigger.setdefault("type", fallback["trigger"]["type"])
    trigger.setdefault("filter", {})

    return {
        "name": str(raw.get("name") or cluster.name),
        "description": str(raw.get("description") or fallback["description"]),
        "trigger": trigger,
        "steps": cleaned,
        "guards": guards,
    }


async def generate_flow(cluster: Cluster) -> tuple[dict[str, Any], str]:
    """Generate a flow definition for a cluster.

    Returns (flow, provenance) where provenance is "llm" or "heuristic" — shown
    in the console so a reviewer always knows which produced what.
    """
    prompt = llm.load_prompt(
        "generate_flow",
        name=cluster.name,
        signature="\n".join(f"  {i + 1}. {s}" for i, s in enumerate(cluster.signature or [])),
        instance_count=cluster.instance_count,
        distinct_users=cluster.distinct_users,
        median_minutes=round(cluster.median_duration_ms / 60000, 1),
        automatability=round(cluster.automatability, 2),
        apps=", ".join(cluster.apps or []),
    )
    used_llm = llm.available
    raw = await llm.structured(
        prompt=prompt, tool=GENERATE_FLOW, fallback=lambda: _fallback_flow(cluster), max_tokens=3000
    )
    flow = _sanitise_flow(raw, cluster)
    return flow, ("llm" if used_llm else "heuristic")


def _fallback_sop(cluster: Cluster) -> str:
    """A genuinely useful SOP built from the observed data, with no model call."""
    steps = cluster.signature or []
    minutes = round(cluster.median_duration_ms / 60000, 1)
    apps = ", ".join(cluster.apps or [])
    lines = [
        f"# {cluster.name}",
        "",
        "## Purpose",
        f"This procedure documents a workflow observed {cluster.instance_count} times across "
        f"{cluster.distinct_users} employee(s) during the observation window. It accounts for an "
        f"estimated {cluster.annual_hours:,.0f} hours per year across the organisation, plus a "
        f"further {cluster.interruption_tax_hours:,.0f} hours of context-switching cost.",
        "",
        "## Trigger",
        f"Begins when a {(steps[0].split(':')[2] if steps else 'task')} arrives in "
        f"{(steps[0].split(':')[0] if steps else 'the source system')}.".replace("_", " "),
        "",
        "## Systems Touched",
        apps or "not recorded",
        "",
        "## Procedure",
    ]
    for index, token in enumerate(steps, start=1):
        parts = token.split(":")
        app = parts[0] if parts else "system"
        action = parts[1] if len(parts) > 1 else "review"
        obj = (parts[2] if len(parts) > 2 else "item").replace("_", " ")
        verb = {
            "read": "Open and read",
            "extract": "Extract the required fields from",
            "create": "Create a new",
            "update": "Update the",
            "send": "Send the",
            "search": "Search for the matching",
            "navigate": "Navigate to the",
            "delete": "Remove the",
        }.get(action, action.capitalize())
        lines.append(f"{index}. {verb} {obj} in {app}.")

    variance = cluster.variance_breakdown or {}
    lines += [
        "",
        "## Known Exceptions",
        f"- {variance.get('variant_count', 0)} distinct step sequences were observed; "
        f"{variance.get('dominant_variant_share', 0):.0%} of instances follow the order above.",
        f"- {variance.get('branch_count', 0)} step position(s) varied between instances and may "
        "require a judgement call.",
    ]
    if cluster.do_not_automate:
        lines.append(
            "- This workflow is **not recommended for automation**: "
            f"{cluster.reasoning}"
        )
    lines += [
        "",
        "## Owner",
        f"{(cluster.teams or ['Operations'])[0].replace('_', ' ').title()} team.",
        "",
        "## Estimated Duration",
        f"{minutes} minutes (median of {cluster.instance_count} observed instances).",
        "",
    ]
    return "\n".join(lines)


async def generate_sop(cluster: Cluster) -> str:
    """Generate a Standard Operating Procedure in Markdown for a cluster.

    Worth shipping on its own: it delivers value before any automation runs, and
    for a do-not-automate workflow it is the *only* deliverable — which is
    exactly the point of surfacing those as a first-class result.
    """
    note = (
        "this workflow varies too much between instances to automate safely"
        if cluster.do_not_automate
        else "this workflow is a strong automation candidate"
    )
    prompt = llm.load_prompt(
        "generate_sop",
        name=cluster.name,
        signature=" -> ".join(cluster.signature or []),
        distinct_users=cluster.distinct_users,
        instance_count=cluster.instance_count,
        median_minutes=round(cluster.median_duration_ms / 60000, 1),
        apps=", ".join(cluster.apps or []),
        automatability=round(cluster.automatability, 2),
        automatability_note=note,
    )
    return await llm.text(
        prompt=prompt, fallback=lambda: _fallback_sop(cluster), max_tokens=2000
    )
