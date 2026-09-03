"""Check a generated automation against the activity that was actually observed.

The flow definition is partly written by a language model, and a model asked to
describe a support escalation will happily produce a tidy one — with a Slack
notification nobody sent, a Salesforce lookup nobody performed, and a step id
that matches nothing. Each of those reads as an improvement and is a fabrication.

So the event log is the authority and this module is where that is enforced. It
answers one question in several parts: *is every element of this automation
traceable to something a person was observed doing?* Anything that is not gets
named, with the step it came from, and the automation is held back from the
approval screen until it is repaired.

Presenting an automation as ready when it did not pass would be the single most
damaging thing this product could do, because approval is the moment a human
transfers their judgement to the machine on the strength of that word.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

from app.services.execution_planner import feasibility

#: Runtimes whose artefact is Python source, and so can be parsed to prove it.
_PYTHON_METHODS = frozenset({"python", "playwright", "hybrid"})


@dataclass
class Finding:
    """One thing wrong with a generated automation."""

    #: Machine-readable check name, e.g. "connector_not_observed".
    check: str
    #: What is wrong, in the words a reviewer needs.
    detail: str
    #: The step it concerns, when it concerns one.
    step_id: str = ""
    #: True when this must be fixed before approval; False for a warning.
    blocking: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "detail": self.detail,
            "step_id": self.step_id,
            "blocking": self.blocking,
        }


@dataclass
class ValidationReport:
    """The outcome of every check, passed and failed alike."""

    passed_checks: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.blocking]

    @property
    def ok(self) -> bool:
        """True only when nothing blocking was found. Never inferred loosely."""
        return not self.blocking

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "passed": list(self.passed_checks),
            "findings": [f.as_dict() for f in self.findings],
            "blocking_count": len(self.blocking),
        }


def _observed_connectors(signature: list[str]) -> set[str]:
    return {token.split(":")[0] for token in signature if token}


def _observed_actions(signature: list[str]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for token in signature:
        parts = token.split(":")
        if len(parts) >= 2:
            out.add((parts[0], parts[1]))
    return out


def validate(
    *,
    steps: list[dict[str, Any]],
    guards: dict[str, Any],
    signature: list[str],
    method: str,
    variables: list[dict[str, Any]] | None = None,
    source: str = "",
    expected_guard: str = "",
) -> ValidationReport:
    """Validate a generated automation against the observed signature.

    `signature` is the cluster's observed step sequence and is the source of
    truth. `source` is the generated artefact, checked for syntactic validity
    when the runtime produces Python.
    """
    report = ValidationReport()
    variables = list(variables or [])

    # ── the automation has a body at all ──────────────────────────────────
    if not steps:
        report.findings.append(
            Finding("schema", "The automation has no steps.", blocking=True)
        )
        return report
    report.passed_checks.append("Schema valid")

    # ── every step is well formed ─────────────────────────────────────────
    ids: list[str] = []
    malformed = False
    for index, step in enumerate(steps, start=1):
        step_id = str(step.get("id") or "")
        if not step_id:
            report.findings.append(
                Finding("schema", f"Step {index} has no id.", blocking=True)
            )
            malformed = True
            continue
        if not step.get("connector") or not step.get("type"):
            report.findings.append(
                Finding(
                    "schema",
                    f"Step {step_id} is missing a connector or an action.",
                    step_id=step_id,
                )
            )
            malformed = True
        ids.append(step_id)
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        report.findings.append(
            Finding("schema", f"Duplicate step ids: {', '.join(sorted(duplicates))}.")
        )
        malformed = True
    if not malformed:
        report.passed_checks.append("All steps well formed")

    # ── source of truth: no invented systems ──────────────────────────────
    observed_connectors = _observed_connectors(signature)
    observed_actions = _observed_actions(signature)
    invented = False
    for step in steps:
        connector = str(step.get("connector") or "")
        action = str(step.get("type") or "")
        step_id = str(step.get("id") or "?")
        if observed_connectors and connector not in observed_connectors:
            report.findings.append(
                Finding(
                    "connector_not_observed",
                    f"Step {step_id} uses '{connector}', which does not appear in the "
                    f"observed activity ({', '.join(sorted(observed_connectors))}).",
                    step_id=step_id,
                )
            )
            invented = True
        elif observed_actions and (connector, action) not in observed_actions:
            report.findings.append(
                Finding(
                    "action_not_observed",
                    f"Step {step_id} performs '{connector}:{action}', which was never "
                    "observed. Nobody was seen doing this.",
                    step_id=step_id,
                    blocking=False,
                )
            )
    if not invented:
        report.passed_checks.append("Connectors all observed in the activity log")

    # ── dependencies resolve ──────────────────────────────────────────────
    produced: set[str] = set()
    unresolved = False
    for step in steps:
        for dependency in step.get("depends_on") or []:
            if str(dependency).split(".")[-1] not in produced:
                report.findings.append(
                    Finding(
                        "dependency_unresolved",
                        f"Step {step.get('id')} depends on '{dependency}', which no "
                        "earlier step produces.",
                        step_id=str(step.get("id") or ""),
                    )
                )
                unresolved = True
        produced.update(str(o) for o in (step.get("outputs") or []))
    if not unresolved:
        report.passed_checks.append("Step dependencies all resolve")

    # ── variables are traceable to a step ─────────────────────────────────
    step_tokens = set(signature)
    stray = [
        v["name"]
        for v in variables
        if v.get("step_token") and v["step_token"] not in step_tokens
    ]
    if stray:
        report.findings.append(
            Finding(
                "variable_unmapped",
                f"Variables {', '.join(stray)} are not read on any observed step.",
            )
        )
    elif variables:
        report.passed_checks.append(f"{len(variables)} variables mapped to observed steps")

    # ── guards survived generation ────────────────────────────────────────
    # Checked by comparing against what the observation implied, because a
    # model that drops a guard produces a *simpler* automation that looks
    # better and is more dangerous.
    actual_guard = str(guards.get("requires_approval_if") or "").strip()
    if expected_guard and actual_guard != expected_guard.strip():
        report.findings.append(
            Finding(
                "guard_weakened",
                f"The observed runs all satisfied `{expected_guard}`, but the "
                f"automation's guard is `{actual_guard or 'none'}`. A guard that was "
                "observed and then dropped must not be lost silently.",
            )
        )
    elif actual_guard:
        report.passed_checks.append(f"Guard preserved: {actual_guard}")

    irreversible = list(guards.get("irreversible") or [])
    orphaned = [i for i in irreversible if i not in ids]
    if orphaned:
        report.findings.append(
            Finding(
                "guard_orphaned",
                f"The guard names step(s) {', '.join(orphaned)}, which do not exist. "
                "The hold would never apply.",
            )
        )
    elif irreversible:
        report.passed_checks.append(
            f"{len(irreversible)} irreversible step(s) covered by the guard"
        )

    # ── the chosen runtime can actually run this ──────────────────────────
    feasible, why = feasibility(method, steps)
    if not feasible:
        report.findings.append(Finding("executor_infeasible", why))
    else:
        report.passed_checks.append(f"Executor feasible: {method}")

    # ── the artefact is syntactically valid ───────────────────────────────
    if source and method in _PYTHON_METHODS:
        try:
            ast.parse(source)
        except SyntaxError as exc:
            report.findings.append(
                Finding(
                    "artifact_invalid",
                    f"The generated code does not parse: line {exc.lineno}, {exc.msg}.",
                )
            )
        else:
            report.passed_checks.append("Generated artifact parses")

    return report
