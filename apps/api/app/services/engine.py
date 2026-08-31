"""F5 — the execution engine. One engine, three modes.

This is the architectural decision that makes the scope achievable. `replay`,
`shadow` and `live` are not three engines; they are one engine with two
switches: whether side effects are real, and what the result gets compared
against.

    mode      side effects   compared against
    ─────────────────────────────────────────
    replay    mocked         the historical log
    shadow    mocked         live human actions
    live      real           nothing

Because the comparison happens *outside* the engine, adding shadow mode on top
of replay cost almost nothing — and the trust ladder, which is the product's
centrepiece, is built entirely out of that comparison.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.connectors.base import Context, Step, StepResult
from app.connectors.registry import get_connector
from app.models.execution import ExecutionMode

logger = logging.getLogger("loop.engine")

# Guard expressions are evaluated by this restricted comparator rather than by
# eval(). A flow definition is partly model-generated, so it is untrusted input;
# handing it to eval() would be a code-execution hole.
_CONDITION = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_. ]*?)\s*(>=|<=|==|!=|>|<)\s*(.+?)\s*$"
)


@dataclass
class ExecutionResult:
    """Outcome of one full flow run."""

    status: str
    step_results: list[StepResult] = field(default_factory=list)
    output: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    error: str | None = None
    needs_approval: bool = False
    approval_reason: str | None = None
    side_effects: list[str] = field(default_factory=list)

    @property
    def unresolved_fields(self) -> list[str]:
        """Every dependency that failed to resolve. The drift signal for F8."""
        out: list[str] = []
        for result in self.step_results:
            out.extend(result.unresolved)
        return out


def _coerce(raw: str) -> Any:
    """Parse the right-hand side of a guard condition."""
    text = raw.strip().strip("'\"")
    for caster in (int, float):
        try:
            return caster(text)
        except ValueError:
            continue
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    return text


def evaluate_condition(expression: str, values: dict[str, Any]) -> bool:
    """Evaluate a single comparison against available values, safely.

    Supports `field <op> literal` only. Anything else returns False, which fails
    closed: an unparseable guard never silently permits an action.
    """
    if not expression:
        return False
    match = _CONDITION.match(expression)
    if not match:
        logger.warning("unparseable guard condition, failing closed: %r", expression)
        return False
    field_name, operator, literal = match.groups()
    key = field_name.strip()
    if key not in values:
        key = key.split(".")[-1]
    if key not in values:
        return False
    left = values[key]
    right = _coerce(literal)
    try:
        if operator == ">":
            return left > right
        if operator == "<":
            return left < right
        if operator == ">=":
            return left >= right
        if operator == "<=":
            return left <= right
        if operator == "==":
            return left == right
        if operator == "!=":
            return left != right
    except TypeError:
        return False
    return False


def evaluate_rules(rules: list[dict], values: dict[str, Any]) -> list[dict]:
    """Return the branch rules (learned via F8) whose conditions currently match."""
    matched = []
    for rule in rules or []:
        if evaluate_condition(str(rule.get("condition", "")), values):
            matched.append(rule)
    return matched


class Engine:
    """Runs a flow definition. Mode-agnostic by construction."""

    async def run(
        self,
        *,
        steps: list[dict],
        guards: dict,
        rules: list[dict] | None = None,
        mode: ExecutionMode = ExecutionMode.REPLAY,
        trigger_payload: dict | None = None,
        source_payload: dict | None = None,
        schema: dict[str, list[str]] | None = None,
    ) -> ExecutionResult:
        """Execute every step in order, stopping at the first hard failure."""
        # replay and shadow must never touch a real system. Enforced here, once.
        force_mock = mode in (ExecutionMode.REPLAY, ExecutionMode.SHADOW)

        ctx = Context(
            mode=mode.value,
            trigger_payload=dict(trigger_payload or {}),
            source_payload=dict(source_payload or {}),
            schema=dict(schema or {}),
        )

        results: list[StepResult] = []
        side_effects: list[str] = []
        irreversible = set(guards.get("irreversible") or [])
        approval_expression = str(guards.get("requires_approval_if") or "")

        matched_rules = evaluate_rules(rules or [], ctx.available())
        for rule in matched_rules:
            ctx.notes.append(f"rule matched: {rule.get('condition')} -> {rule.get('action')}")

        for raw_step in steps:
            step = Step.from_dict(raw_step)

            # Guards are checked before the step runs, not after, and only for
            # steps whose effects cannot be undone.
            is_irreversible = step.id in irreversible or step.type in irreversible
            if (
                approval_expression
                and is_irreversible
                and evaluate_condition(approval_expression, ctx.available())
            ):
                results.append(
                    StepResult(
                        step_id=step.id,
                        status="needs_approval",
                        confidence=0.0,
                        error=f"guard held execution: {approval_expression}",
                    )
                )
                return ExecutionResult(
                    status="needs_approval",
                    step_results=results,
                    output=dict(ctx.resolved),
                    confidence=_mean_confidence(results),
                    needs_approval=True,
                    approval_reason=(
                        f"Guard `{approval_expression}` matched on an irreversible "
                        f"step ({step.id}: {step.type})."
                    ),
                    side_effects=side_effects,
                )

            # A matched branch rule can redirect an irreversible step to a human.
            redirect = next(
                (r for r in matched_rules if is_irreversible and "approval" in
                 str(r.get("action", "")).lower()),
                None,
            )
            if redirect is not None:
                results.append(
                    StepResult(
                        step_id=step.id,
                        status="needs_approval",
                        confidence=0.0,
                        error=f"learned rule routed this step: {redirect.get('action')}",
                    )
                )
                return ExecutionResult(
                    status="needs_approval",
                    step_results=results,
                    output=dict(ctx.resolved),
                    confidence=_mean_confidence(results),
                    needs_approval=True,
                    approval_reason=(
                        f"Learned rule `{redirect.get('condition')}` routed this to "
                        f"{redirect.get('action')}."
                    ),
                    side_effects=side_effects,
                )

            connector = get_connector(step.connector, force_mock=force_mock)
            try:
                result = await connector.execute(step, ctx)
            except Exception as exc:  # noqa: BLE001 — one bad step must not kill the run
                result = StepResult(
                    step_id=step.id, status="failed", error=str(exc), confidence=0.0
                )

            results.append(result)
            if result.side_effect:
                side_effects.append(result.side_effect)

            if result.ok:
                # None values are kept deliberately. Dropping them would hide a
                # field the automation failed to produce, and the replay diff
                # would then score it as "not compared" instead of "wrong".
                # Dependency resolution already refuses to satisfy a dependency
                # from a None, so keeping them cannot mask a real failure.
                ctx.resolved.update(result.outputs)
            else:
                return ExecutionResult(
                    status="failed",
                    step_results=results,
                    output=dict(ctx.resolved),
                    confidence=_mean_confidence(results),
                    error=result.error,
                    side_effects=side_effects,
                )

        return ExecutionResult(
            status="ok",
            step_results=results,
            output=dict(ctx.resolved),
            confidence=_mean_confidence(results),
            side_effects=side_effects,
        )


def _mean_confidence(results: list[StepResult]) -> float:
    if not results:
        return 0.0
    return round(sum(r.confidence for r in results) / len(results), 3)


engine = Engine()
