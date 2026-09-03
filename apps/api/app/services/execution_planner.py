"""Choose which runtime should execute an approved automation.

LOOP works out *what* repeats and whether handing it over is safe. That is a
separate question from *how* it should run, and the answer is not the same for
every workflow: a chain of SaaS API calls belongs in n8n, which already owns the
connectors and the OAuth; a workflow that has to click through a system with no
API can only be driven by a real browser; and local file and document work is a
plain script, which needs no credentials and is the easiest thing to test.

Picking one backend for everything would mean writing Playwright against systems
that have a perfectly good API, or writing n8n nodes for a system that has none.
So the choice is made per automation, from the connectors its steps touch.

The model is asked, because the trade-off is a judgement call and it reads the
step descriptions. It is not trusted: a choice that cannot physically reach one
of the steps is overruled below. The deterministic path produces a usable answer
on its own, so the routing works with no model installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from app.llm.client import llm
from app.llm.tools import CHOOSE_EXECUTOR, EXECUTION_METHODS
from app.services.n8n_export import node_type_for

#: Systems with no usable API, where driving the browser is the only way in.
#: A step on one of these forces Playwright whatever else the flow contains,
#: because no other runtime can reach it at all.
NO_API_CONNECTORS = frozenset({"browser", "desktop"})

#: Local file, document and repository work. A script does this directly; a node
#: graph would wrap the same few lines in six nodes and a credential it does not
#: need.
LOCAL_WORK_CONNECTORS = frozenset({"files", "pdf", "git"})

DEFAULT_METHOD = "python"


@dataclass
class ExecutionPlan:
    """The chosen runtime, and why."""

    method: str
    rationale: str
    confidence: float
    #: True when the model's answer was overruled because it could not have run.
    overruled: bool = False
    #: "llm" or "heuristic", shown in the console beside the choice.
    decided_by: str = "heuristic"
    #: What the connector-based rules would have chosen, when that differs from
    #: what was chosen. Surfaced rather than silently resolved: picking a
    #: runtime is a judgement call with a real cost either way, and the approval
    #: gate is the right place for a person to see that the two disagreed.
    alternative_method: str = ""
    alternative_rationale: str = ""
    #: The observations behind the choice, one per line, for the reviewer. A
    #: recommendation with no visible reasoning is indistinguishable from a
    #: guess, and the reviewer is the person who has to stand behind it.
    factors: list[str] = dataclass_field(default_factory=list)
    #: For `hybrid` only: which connectors each half drives. Empty otherwise.
    browser_connectors: list[str] = dataclass_field(default_factory=list)
    api_connectors: list[str] = dataclass_field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "method": self.method,
            "rationale": self.rationale,
            "confidence": round(self.confidence, 3),
            "overruled": self.overruled,
            "decided_by": self.decided_by,
            "alternative_method": self.alternative_method,
            "alternative_rationale": self.alternative_rationale,
            "factors": list(self.factors),
            "browser_connectors": list(self.browser_connectors),
            "api_connectors": list(self.api_connectors),
        }


def _connectors(steps: list[dict]) -> list[str]:
    return [str(step.get("connector") or "browser") for step in steps]


def _partition(steps: list[dict]) -> tuple[list[str], list[str], list[str]]:
    """Split step ids into no-API, local-work and n8n-mappable buckets."""
    no_api: list[str] = []
    local: list[str] = []
    n8n_ready: list[str] = []
    for step in steps:
        connector = str(step.get("connector") or "browser")
        step_id = str(step.get("id") or "?")
        if connector in NO_API_CONNECTORS:
            no_api.append(step_id)
        elif connector in LOCAL_WORK_CONNECTORS:
            local.append(step_id)
        if node_type_for(connector) is not None:
            n8n_ready.append(step_id)
    return no_api, local, n8n_ready


def _api_connectors(steps: list[dict]) -> list[str]:
    """Connectors reachable through an API rather than a browser."""
    return sorted(
        {
            str(step.get("connector") or "")
            for step in steps
            if str(step.get("connector") or "") not in NO_API_CONNECTORS
            and node_type_for(str(step.get("connector") or "")) is not None
        }
    )


def _browser_connectors(steps: list[dict]) -> list[str]:
    return sorted(
        {
            str(step.get("connector") or "")
            for step in steps
            if str(step.get("connector") or "") in NO_API_CONNECTORS
        }
    )


def feasibility(method: str, steps: list[dict]) -> tuple[bool, str]:
    """Whether a runtime could actually execute this flow, and why not if not.

    Called when a person overrides the recommendation. An override is their
    call to make, but silently generating an automation that cannot run is not
    respecting the choice — it is deferring the failure to run time.
    """
    no_api, local, n8n_ready = _partition(steps)
    if method == "n8n" and no_api:
        return False, (
            f"n8n has no browser executor, and steps {', '.join(no_api)} interact with "
            "a system that has no usable API. Choose Browser or Hybrid."
        )
    if method == "python" and no_api:
        return False, (
            f"A plain script cannot drive the UI that steps {', '.join(no_api)} rely on. "
            "Choose Browser or Hybrid."
        )
    if method == "hybrid" and not no_api:
        return False, (
            "Hybrid exists to pair a browser with an API. No step here needs a browser, "
            "so one runtime covers the whole flow."
        )
    if method == "hybrid" and not _api_connectors(steps):
        return False, (
            "Hybrid needs an API half. Every step here is browser-only, so Browser "
            "automation covers it on its own."
        )
    if method == "n8n" and len(n8n_ready) < len(steps):
        missing = len(steps) - len(n8n_ready)
        return False, (
            f"{missing} step(s) map to no n8n node, so n8n cannot run the whole flow."
        )
    if method not in EXECUTION_METHODS:
        return False, f"'{method}' is not a runtime LOOP can generate."
    return True, ""


def choose_method_deterministically(steps: list[dict]) -> ExecutionPlan:
    """Pick a runtime from the connectors alone, with no model call.

    Ordered by what is *possible* before what is convenient. A system with no
    API cannot be reached by n8n or by a script however tidy that would be, so
    that test comes first and is decisive. Where a flow spans both kinds of
    system, splitting it is better than forcing one runtime to do work it is bad
    at: driving Jira by clicking its UI is slower and breaks on every redesign,
    when Jira has a perfectly good REST API.
    """
    if not steps:
        return ExecutionPlan(
            method=DEFAULT_METHOD,
            rationale="No steps to run; defaulting to a script.",
            confidence=0.3,
            factors=["No steps were observed."],
        )

    no_api, local, n8n_ready = _partition(steps)
    total = len(steps)
    browser_side = _browser_connectors(steps)
    api_side = _api_connectors(steps)

    factors = [
        f"Browser interaction required: {'yes' if no_api else 'no'}"
        + (f" ({', '.join(browser_side)})" if browser_side else ""),
        f"Reachable through an API: {', '.join(api_side) if api_side else 'none'}",
        f"Local file or document work: {len(local)} of {total} steps",
    ]

    if no_api and api_side:
        return ExecutionPlan(
            method="hybrid",
            rationale=(
                f"{', '.join(browser_side)} has no usable API so it must be driven through "
                f"the browser, while {', '.join(api_side)} has one. Splitting the flow keeps "
                "browser automation to the system that needs it."
            ),
            confidence=0.87,
            factors=factors
            + [
                "Browser automation is confined to the source system.",
                "The API half is more reliable than clicking the same screens.",
            ],
            browser_connectors=browser_side,
            api_connectors=api_side,
        )

    if no_api:
        return ExecutionPlan(
            method="playwright",
            rationale=(
                f"{len(no_api)} of {total} steps touch a system with no usable API "
                f"({', '.join(no_api)}), so driving the browser is the only way in."
            ),
            confidence=0.9,
            factors=factors,
            browser_connectors=browser_side,
        )

    if len(local) * 2 >= total:
        return ExecutionPlan(
            method="python",
            rationale=(
                f"{len(local)} of {total} steps are local file or document work, "
                "which a script does directly and can run with no credentials."
            ),
            confidence=0.85,
            factors=factors,
            api_connectors=api_side,
        )

    if len(n8n_ready) == total:
        return ExecutionPlan(
            method="n8n",
            rationale=(
                f"All {total} steps map to maintained n8n nodes, so n8n supplies the "
                "connectors and the credential handling."
            ),
            confidence=0.88,
            factors=factors,
            api_connectors=api_side,
        )

    unmapped = total - len(n8n_ready)
    return ExecutionPlan(
        method="python",
        rationale=(
            f"{unmapped} of {total} steps have no n8n node, so a script is the only "
            "runtime that can cover the whole flow."
        ),
        confidence=0.7,
        factors=factors,
        api_connectors=api_side,
    )


async def choose_execution_method(
    *, name: str, steps: list[dict]
) -> ExecutionPlan:
    """Choose the runtime for an automation, asking the model first.

    Returns the deterministic choice unchanged when no model is running, and
    overrules the model whenever its answer could not physically execute a step.
    """
    fallback_plan = choose_method_deterministically(steps)
    if not steps:
        return fallback_plan

    no_api, local, n8n_ready = _partition(steps)
    prompt = llm.load_prompt(
        "choose_executor",
        name=name,
        steps="\n".join(
            f"  {i}. {s.get('id')}: {s.get('type')} via {s.get('connector')}"
            f" — {s.get('description') or s.get('type')}"
            for i, s in enumerate(steps, start=1)
        ),
        connectors=", ".join(dict.fromkeys(_connectors(steps))),
        no_api_steps=", ".join(no_api) or "none",
        local_steps=", ".join(local) or "none",
        n8n_steps=", ".join(n8n_ready) or "none",
    )

    # Availability before the call is not the same as an answer after it. The
    # client degrades to the caller's fallback on failure, so asking only
    # `llm.available` credited the model with a choice it never made — and the
    # deterministic reasoning was then discarded in favour of an empty echo.
    before = llm.fallback_count
    raw = await llm.structured(
        prompt=prompt,
        tool=CHOOSE_EXECUTOR,
        fallback=lambda: {
            "method": fallback_plan.method,
            "rationale": fallback_plan.rationale,
            "confidence": fallback_plan.confidence,
        },
        max_tokens=400,
    )
    if llm.fallback_count != before:
        return fallback_plan

    method = str(raw.get("method") or "").strip().lower()
    if method not in EXECUTION_METHODS:
        return fallback_plan

    rationale = str(raw.get("rationale") or fallback_plan.rationale).strip()
    try:
        confidence = min(1.0, max(0.0, float(raw.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5

    # The one thing the model does not get to be wrong about. Neither n8n nor a
    # plain script can reach a system that has no API, so a choice that leaves
    # such a step unrunnable is replaced rather than displayed with a caveat.
    if no_api and method not in ("playwright", "hybrid"):
        return ExecutionPlan(
            method="playwright",
            rationale=(
                f"{fallback_plan.rationale} (Model suggested {method}, which cannot "
                f"reach steps {', '.join(no_api)}.)"
            ),
            confidence=fallback_plan.confidence,
            overruled=True,
            decided_by="llm",
        )

    return ExecutionPlan(
        method=method,
        rationale=rationale,
        confidence=confidence,
        decided_by="llm",
        factors=list(fallback_plan.factors),
        browser_connectors=list(fallback_plan.browser_connectors),
        api_connectors=list(fallback_plan.api_connectors),
        alternative_method=(
            fallback_plan.method if fallback_plan.method != method else ""
        ),
        alternative_rationale=(
            fallback_plan.rationale if fallback_plan.method != method else ""
        ),
    )
