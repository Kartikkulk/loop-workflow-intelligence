"""Tell the parts of a workflow that change from the parts that do not.

Two escalations differ in the customer and the issue; they do not differ in the
fact that a Jira issue gets created at High priority. That distinction is the
whole difference between an automation and a recording:

  * a field whose value is different almost every run is an **input**. The
    automation must take it as a parameter, because baking one observed value
    into the generated code produces something that files every future ticket
    under "ABC".
  * a field whose value is the same every run is a **constant**, and a constant
    on a decision-shaped field is where a guard comes from. Five escalations
    that were all `priority = High` are evidence that this workflow is for
    high-priority tickets — not evidence that priority can be ignored.

Both conclusions come from the observed values and nothing else. No model is
asked, because a model cannot know whether `High` was a coincidence of the
sample or the point of the task, and the counts can.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Payload keys that never describe the work itself. `value` is the collector's
#: generic column and is renamed after the step it appeared on, so it is not
#: excluded here — it is the single most informative key in a UI activity log.
METADATA_KEYS = frozenset(
    {"interaction", "tab", "control", "transfer_digest", "domain", "workflow_hint"}
)

#: Alias kept for readability inside this module.
_IGNORED_KEYS = METADATA_KEYS

#: Below this share of distinct values a field is not varying enough to be an
#: input. Two runs out of five sharing a value is normal; five runs sharing one
#: value is a constant.
_VARIABLE_DISTINCT_RATIO = 0.6

#: A field must be present on at least this share of runs to be either. A key
#: seen once in five runs is an anomaly, and templating on it would produce an
#: automation that stalls waiting for a value four runs in five never had.
_MIN_PRESENCE = 0.6


@dataclass
class Observed:
    """One payload field, and every value it took across the runs."""

    step_token: str
    key: str
    values: list[str] = field(default_factory=list)
    #: How many runs carried this field at all.
    present_in: int = 0

    @property
    def distinct(self) -> list[str]:
        return list(dict.fromkeys(self.values))


@dataclass
class Variable:
    """A field the automation must take as an input rather than hard-code."""

    #: Template name, e.g. `customer`. Unique within a workflow.
    name: str
    #: The step it is read on, so the generator knows where it comes from.
    step_token: str
    key: str
    #: A few real values, for the reviewer to recognise the field by.
    samples: list[str]
    distinct_count: int
    occurrences: int

    @property
    def placeholder(self) -> str:
        return "{{" + self.name + "}}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "placeholder": self.placeholder,
            "step_token": self.step_token,
            "key": self.key,
            "samples": list(self.samples),
            "distinct_count": self.distinct_count,
            "occurrences": self.occurrences,
        }


@dataclass
class Constant:
    """A field that held the same value every run. A guard candidate."""

    name: str
    step_token: str
    key: str
    value: str
    occurrences: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "step_token": self.step_token,
            "key": self.key,
            "value": self.value,
            "occurrences": self.occurrences,
        }


def _variable_name(step_token: str, key: str, taken: set[str]) -> str:
    """Name a field after what it is, not after the column it arrived in.

    A UI collector labels almost everything `value`, so naming by key alone
    gives `value`, `value_2`, `value_3` — accurate and useless to a reviewer.
    The step's object type is the real name: the `value` read on
    `browser:read:customer` is the customer.
    """
    parts = step_token.split(":")
    object_type = parts[2] if len(parts) > 2 else ""
    base = object_type if key in ("value", "target", "") else key
    base = re.sub(r"[^a-z0-9_]+", "_", str(base).lower()).strip("_") or "field"

    name = base
    suffix = 2
    while name in taken:
        name = f"{base}_{suffix}"
        suffix += 1
    taken.add(name)
    return name


def collect_observed(instances: list) -> dict[tuple[str, str], Observed]:
    """Gather every payload field seen per step, with its values, across runs.

    Keyed by (step token, payload key) rather than by position: a run that
    skipped an optional step would otherwise shift every later field onto the
    wrong column.
    """
    collected: dict[tuple[str, str], Observed] = {}
    for instance in instances:
        seen_here: set[tuple[str, str]] = set()
        for event in instance.events:
            token = event.step_token
            for key, value in (event.payload or {}).items():
                if key in _IGNORED_KEYS or value in (None, ""):
                    continue
                entry = collected.setdefault(
                    (token, key), Observed(step_token=token, key=key)
                )
                entry.values.append(str(value))
                if (token, key) not in seen_here:
                    entry.present_in += 1
                    seen_here.add((token, key))
    return collected


def detect(instances: list) -> tuple[list[Variable], list[Constant]]:
    """Split every observed field into workflow inputs and workflow constants.

    Returns (variables, constants). Ordered by the step they appear on, so the
    reviewer reads them in the order the work happens.
    """
    runs = len(instances)
    if runs == 0:
        return [], []

    observed = collect_observed(instances)
    # Step order, so the reviewer sees the fields in the order they are read.
    order = {
        event.step_token: index
        for index, event in enumerate(instances[0].events)
    }

    variables: list[Variable] = []
    constants: list[Constant] = []
    taken: set[str] = set()
    for (token, key), entry in sorted(
        observed.items(), key=lambda kv: (order.get(kv[0][0], 999), kv[0][1])
    ):
        if entry.present_in / runs < _MIN_PRESENCE:
            continue
        distinct = entry.distinct
        if len(distinct) == 1:
            constants.append(
                Constant(
                    name=_variable_name(token, key, taken),
                    step_token=token,
                    key=key,
                    value=distinct[0],
                    occurrences=entry.present_in,
                )
            )
            continue
        if len(distinct) / max(1, len(entry.values)) >= _VARIABLE_DISTINCT_RATIO:
            variables.append(
                Variable(
                    name=_variable_name(token, key, taken),
                    step_token=token,
                    key=key,
                    samples=distinct[:5],
                    distinct_count=len(distinct),
                    occurrences=entry.present_in,
                )
            )
    return variables, constants


def templatise(text: str, variables: list[Variable], *, exclude: str = "") -> str:
    """Replace observed values in a string with the placeholders that produced them.

    Used on step descriptions and on generated summaries, so a reviewer reading
    "Summary = {{customer}} - {{issue}}" can see the automation is parameterised
    rather than a transcript of the first run. Longest values first, so a value
    that contains another one is not half-replaced.

    `exclude` drops one variable from the substitution — pass the field being
    rendered. Without it a composed field collapses into its own placeholder
    (`Summary = {{summary}}`), which is true but hides the very thing worth
    seeing: that the summary is built out of two other observed fields.
    """
    if not text:
        return text
    replacements: list[tuple[str, str]] = []
    for variable in variables:
        if variable.name == exclude:
            continue
        replacements.extend((sample, variable.placeholder) for sample in variable.samples)
    for sample, placeholder in sorted(replacements, key=lambda p: -len(p[0])):
        if sample and sample in text:
            text = text.replace(sample, placeholder)
    return text


#: Fields whose value is a decision rather than a datum. A constant on one of
#: these is the reason the observed runs were the ones worth automating; a
#: constant on a name or an id is a coincidence of a small sample.
_DECISION_FIELDS = (
    "priority", "status", "state", "severity", "category", "type",
    "approval", "decision", "tier", "urgency",
)


def guard_from_constants(constants: list[Constant]) -> str:
    """Derive the guard the observed runs imply, in the engine's own polarity.

    Every recorded escalation had `priority = High`. That is evidence the
    workflow is *for* high-priority tickets — so the automation must stop on
    anything else rather than escalate it.

    The engine holds a step when `requires_approval_if` is true, so the
    condition emitted is the negation: `priority != High`. A run that looks like
    the observed ones proceeds; one that does not goes to a person. Writing it
    the other way round would hold every single run, which reads as caution and
    is really just a broken automation.
    """
    for field_name in _DECISION_FIELDS:
        for constant in constants:
            base = constant.name.rstrip("_0123456789")
            if base == field_name and constant.value:
                return f"{base} != {constant.value}"
    return ""
