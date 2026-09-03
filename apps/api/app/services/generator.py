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

# The same restricted comparator the engine evaluates guards with, so the
# generator rejects exactly the expressions the engine would refuse to run.
from app.services.engine import _CONDITION
from app.services.variables import Constant, guard_from_constants

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

#: Connectors whose effects stay on this machine. Creating a row in a local
#: spreadsheet is undoable; creating a Jira issue is a notification to other
#: people and an id that now exists in a system of record.
_LOCAL_CONNECTORS = frozenset({"files", "pdf", "git", "desktop", "browser"})


def _is_irreversible(step: dict[str, Any]) -> bool:
    """Whether a step's effect can be taken back.

    `send` and `delete` always count. `create` counts too when it lands in a
    system other people can see — which is the case that matters here, because
    an automation that files tickets into a shared tracker unsupervised is
    exactly what the guard exists to hold.
    """
    action = str(step.get("type") or "")
    connector = str(step.get("connector") or "")
    if action in _IRREVERSIBLE_ACTIONS:
        return True
    return action == "create" and connector not in _LOCAL_CONNECTORS

#: Payload keys that carry a monetary value, in minor units.
#:
#: `amount_inr` is deliberately absent even though invoices produce it. It is a
#: decision field, so `source_payload` withholds it from the automation at run
#: time; a guard naming it would parse, display, and never once fire. The guard
#: has to name a value the automation can actually read while it is running.
#: `value` is deliberately absent. It is what a UI collector calls *every*
#: field it captures, so treating it as money produced `value > 1000000` on a
#: support workflow that has no money in it — a spend limit on a ticket, which
#: displays convincingly and can never fire.
_MONEY_FIELDS = ("amount", "total", "amount_due", "grand_total")


def _money_field(produced: set[str]) -> str | None:
    """The money key this workflow actually produces, if it produces one.

    A guard naming a field the workflow never sets — or one the engine hides
    from the automation at run time — can never fire, and `evaluate_condition`
    returns False for an unknown key. That is the worst
    kind of safety mechanism: the console displays a spend limit, and every
    irreversible step sails past it. An access-request or build-report workflow
    has no money in it, so it gets no money guard — its irreversible steps are
    still held at ASSIST, which is the protection that actually applies.
    """
    for field_name in _MONEY_FIELDS:
        if field_name in produced:
            return field_name
    return None

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


def _guard_names_a_produced_field(expression: str, produced: set[str]) -> bool:
    """True when a guard's left-hand side is a field this workflow sets."""
    match = _CONDITION.match(expression)
    if not match:
        return False
    key = match.group(1).strip()
    return key in produced or key.split(".")[-1] in produced


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

    irreversible = [s["id"] for s in steps if _is_irreversible(s)]
    guards: dict[str, Any] = {"irreversible": irreversible}
    approval_field = _money_field(produced)
    if approval_field:
        # 10,00,000 paise = 10,000 rupees. Above this a human signs off on
        # anything irreversible.
        guards["requires_approval_if"] = f"{approval_field} > 1000000"
    else:
        # No money in this workflow, but a field that held one value on every
        # observed run is a condition the work was performed *under*. Five
        # escalations all at `priority = High` say this automation is for
        # high-priority tickets; anything else goes to a person.
        observed_guard = guard_from_constants(
            [
                Constant(
                    name=str(c.get("name", "")),
                    step_token=str(c.get("step_token", "")),
                    key=str(c.get("key", "")),
                    value=str(c.get("value", "")),
                    occurrences=int(c.get("occurrences", 0) or 0),
                )
                for c in (cluster.constants or [])
            ]
        )
        if observed_guard:
            guards["requires_approval_if"] = observed_guard

    return {
        "name": cluster.name,
        "description": (
            f"Automates the {len(steps)}-step workflow observed "
            f"{cluster.instance_count} times across {cluster.distinct_users} employee(s)."
        ),
        "trigger": {"type": trigger_type, "filter": {"object_type": first_object}},
        "steps": steps,
        "guards": guards,
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

    signature = list(cluster.signature or [])
    #: Every field name the event log actually carries, across all steps.
    observed_vocabulary = {
        field_name
        for fields in (cluster.observed_fields or {}).values()
        for field_name in fields
    }
    produced: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        step = dict(step)
        token_index = index - 1

        # Ids are positional, always. A model asked for a step id will often
        # echo the signature token back — `jira:send:billing_note` — and that
        # id then appears in `guards.irreversible` while the engine looks up a
        # step called `s4`. The guard matches nothing and the hold silently
        # stops applying, which is the worst way for a safety mechanism to fail.
        step["id"] = f"s{index}"
        step.setdefault("type", "read")

        # *Which system* a step touches is a fact from the event log, not an
        # opinion the model is entitled to. A smaller model will cheerfully
        # rewrite `files` as `drive` and `jira` as `slack` because they are the
        # same kind of thing — and the runtime choice, the credentials needed
        # and the backtest are then all reasoning about a workflow nobody
        # performed. The verb is left to the model, which reads intent well;
        # the system it acts on comes from what was observed.
        if token_index < len(signature):
            parts = signature[token_index].split(":")
            step["connector"] = parts[0] if parts else "browser"
        else:
            step.setdefault("connector", "browser")

        outputs = list(step.get("outputs") or _OUTPUTS_BY_ACTION.get(step["type"], ["result"]))
        # Union in the fields actually observed for this step. The model names
        # steps well but cannot know the source schema; the log does.
        if token_index < len(signature):
            for observed_field in (cluster.observed_fields or {}).get(signature[token_index], []):
                if observed_field not in outputs:
                    outputs.append(observed_field)
        # A dependency has to name a field the *log* contains, not merely one an
        # earlier step declared. Models name outputs descriptively — a step that
        # was observed reading a portal becomes `support_portal_data` — and a
        # later step then depends on it. That passes an internal-consistency
        # check and fails on every real run, because no source system has a
        # field by that name and nothing can ever produce a value for it. The
        # invented names are harmless as labels; they are not allowed to carry
        # data.
        depends = [
            d
            for d in (step.get("depends_on") or [])
            if d.split(".")[-1] in produced and d.split(".")[-1] in observed_vocabulary
        ]
        # A step with no dependencies is not a smaller automation, it is an
        # unhealable one: F8 detects drift by watching which declared
        # dependency stopped resolving, so a flow that declares none can never
        # report drift and never proposes a patch. Smaller models routinely
        # return `depends_on: []` for every step. Where the model offers
        # nothing usable, take what the observed field log implies instead —
        # which is what the deterministic path would have produced anyway.
        if not depends and index - 1 < len(fallback["steps"]):
            depends = [
                d
                for d in (fallback["steps"][index - 1].get("depends_on") or [])
                if d.split(".")[-1] in produced
            ]
        if index == 1:
            depends = []
        step["outputs"] = outputs
        step["depends_on"] = depends
        step["inputs"] = dict(step.get("inputs") or {})
        cleaned.append(step)
        produced.update(outputs)

    guards = dict(raw.get("guards") or {})
    fallback_approval = fallback["guards"].get("requires_approval_if")
    model_approval = str(guards.get("requires_approval_if") or "").strip()
    if model_approval and not _guard_names_a_produced_field(model_approval, produced):
        # The model invents plausible-looking guards on fields that do not
        # exist here. Silently keeping one would show a limit in the console
        # that nothing can ever trip.
        guards.pop("requires_approval_if", None)
    # An empty string is not a guard, it is the absence of one. Models routinely
    # emit `"requires_approval_if": ""` to satisfy the schema, and `setdefault`
    # treats that key as already set — so the guard the observation earned was
    # dropped without a word, and the automation shipped with a hold that
    # protected nothing. Cleared here so "no guard" is genuinely absent.
    if not str(guards.get("requires_approval_if") or "").strip():
        guards.pop("requires_approval_if", None)

    if fallback_approval:
        # `setdefault`, not an override. A model guard that named a real field
        # survived the check above, and it is usually a *tighter* threshold than
        # the default — overriding it would loosen the automation in the name of
        # protecting it. A guard the model dropped entirely is caught by
        # validation, which compares against what the observation implied.
        guards.setdefault("requires_approval_if", fallback_approval)
    else:
        guards.pop("requires_approval_if", None)
    # Rebuilt from the steps rather than merged with what the model declared.
    # A model-supplied id that matches no step is not a harmless extra entry:
    # the engine checks membership by id, so a guard listing `jira:send:note`
    # while the step is called `s4` protects nothing at all.
    valid_ids = {step["id"] for step in cleaned}
    declared = [str(i) for i in (guards.get("irreversible") or []) if str(i) in valid_ids]
    for step in cleaned:
        if _is_irreversible(step) and step["id"] not in declared:
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
