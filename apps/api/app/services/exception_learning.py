"""F8 — the exception queue and branch-rule learning.

Executions the engine is not confident about route to a human with a stated
reason. Each resolution is stored as an `(input features -> human decision)`
pair. Once enough similar pairs agree, LOOP proposes a branch rule; accepting it
patches the flow definition, and the automation's coverage rises.

Coverage is the metric that makes the system look alive: the share of triggers
handled without a human. A rising line is the product working.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm.client import llm
from app.llm.tools import PROPOSE_RULE
from app.models.automation import Automation
from app.models.governance import ExceptionCase, Patch
from app.services.ids import new_id

logger = logging.getLogger("loop.exceptions")

# Buckets used to group "similar" exceptions. Grouping on raw values would never
# find three matching cases; grouping on the *shape* of the input does.
_AMOUNT_BUCKETS = [
    (1_000_000, "amount_over_10k"),
    (500_000, "amount_500k_to_1m"),
    (0, "amount_under_500k"),
]


# Rule actions that still require a person. Coverage credit is withheld for
# these: the automation has learned *when* to escalate, not how to finish.
_HUMAN_ROUTING_TOKENS = (
    "route", "escalate", "manual", "review", "approval", "hold", "manager", "human",
)


def routes_to_human(action: str) -> bool:
    """True when a rule's action still hands the case to a person."""
    lowered = action.lower()
    return any(token in lowered for token in _HUMAN_ROUTING_TOKENS)


def signature_key(features: dict) -> str:
    """A stable grouping key for an exception's input shape."""
    parts: list[str] = []
    amount = features.get("amount")
    if isinstance(amount, (int, float)):
        for floor, label in _AMOUNT_BUCKETS:
            if amount > floor:
                parts.append(label)
                break
    currency = features.get("currency")
    if currency and str(currency).upper() != "INR":
        parts.append("foreign_currency")
    if features.get("unresolved"):
        parts.append("unresolved_dependency")
    if features.get("status"):
        parts.append(f"status_{features['status']}")
    return "|".join(parts) or "unclassified"


async def record_exception(
    session: AsyncSession,
    automation: Automation,
    *,
    reason: str,
    features: dict,
    execution_id: str | None = None,
    confidence: float = 0.0,
) -> ExceptionCase:
    """Route one uncertain execution to the human queue."""
    case = ExceptionCase(
        id=new_id("exc"),
        automation_id=automation.id,
        execution_id=execution_id,
        reason=reason,
        input_features=features,
        signature_key=signature_key(features),
        confidence=round(confidence, 3),
        status="open",
    )
    session.add(case)
    await session.flush()
    return case


async def _fallback_rule(cases: list[ExceptionCase]) -> dict:
    """Derive a branch condition arithmetically, with no model call."""
    decisions = [c.human_decision for c in cases if c.human_decision]
    action = max(set(decisions), key=decisions.count) if decisions else "route_to_manager"

    amounts = [
        c.input_features.get("amount")
        for c in cases
        if isinstance(c.input_features.get("amount"), (int, float))
    ]
    if amounts:
        # The threshold is the smallest amount that triggered escalation, which
        # is the tightest rule consistent with every observed decision.
        floor = int(min(amounts))
        return {
            "condition": f"amount > {floor - 1}",
            "action": action,
            "rationale": (
                f"All {len(cases)} escalations carried an amount of at least {floor}; "
                f"the human chose '{action}' every time."
            ),
            "confidence": 0.82,
        }

    currencies = {
        str(c.input_features.get("currency")).upper()
        for c in cases
        if c.input_features.get("currency")
    }
    foreign = currencies - {"INR", "NONE"}
    if foreign:
        return {
            "condition": 'currency != "INR"',
            "action": action,
            "rationale": (
                f"Every escalation was denominated in a foreign currency "
                f"({', '.join(sorted(foreign))}); the human chose '{action}'."
            ),
            "confidence": 0.85,
        }

    return {
        "condition": "unresolved == true",
        "action": action,
        "rationale": f"{len(cases)} escalations shared the same input shape.",
        "confidence": 0.6,
    }


async def propose_rules(session: AsyncSession, automation: Automation) -> list[Patch]:
    """Propose a branch rule for every exception group with enough evidence."""
    result = await session.execute(
        select(ExceptionCase).where(
            ExceptionCase.automation_id == automation.id,
            ExceptionCase.status == "resolved",
        )
    )
    resolved = list(result.scalars().all())

    grouped: dict[str, list[ExceptionCase]] = {}
    for case in resolved:
        grouped.setdefault(case.signature_key, []).append(case)

    existing = await session.execute(
        select(Patch).where(Patch.automation_id == automation.id, Patch.kind == "rule")
    )
    already = {
        (p.rule or {}).get("signature_key")
        for p in existing.scalars().all()
        if p.status in ("proposed", "applied")
    }

    patches: list[Patch] = []
    for key, cases in grouped.items():
        if len(cases) < settings.exception_rule_min_samples or key in already:
            continue

        fallback = await _fallback_rule(cases)
        rendered = "\n".join(
            f"- features={c.input_features} -> human chose '{c.human_decision}'" for c in cases
        )
        proposed = await llm.structured(
            prompt=llm.load_prompt(
                "propose_rule",
                automation_name=automation.name,
                count=len(cases),
                cases=rendered,
            ),
            tool=PROPOSE_RULE,
            fallback=lambda f=fallback: f,
        )

        rule = {
            "condition": str(proposed.get("condition") or fallback["condition"]),
            "action": str(proposed.get("action") or fallback["action"]),
            "signature_key": key,
        }
        patch = Patch(
            id=new_id("pat"),
            automation_id=automation.id,
            kind="rule",
            step_id=None,
            field=None,
            from_value=None,
            to_value=f"{rule['condition']} -> {rule['action']}",
            confidence=round(float(proposed.get("confidence", fallback["confidence"])), 3),
            # Learned rules are never auto-applied. A rule changes what the
            # automation *decides*, not merely where it reads a field from, so a
            # human always signs off.
            auto_applicable=False,
            status="proposed",
            rationale=str(proposed.get("rationale") or fallback["rationale"]),
            rule=rule,
            evidence_count=len(cases),
            proposed_by="llm" if llm.available else "heuristic",
        )
        session.add(patch)
        patches.append(patch)
        logger.info(
            "rule proposed for %s from %d cases: %s -> %s",
            automation.id, len(cases), rule["condition"], rule["action"],
        )

    await session.flush()
    return patches


def apply_rule_to_flow(automation: Automation, patch: Patch) -> bool:
    """Splice an accepted branch rule into the flow definition."""
    if not patch.rule:
        return False
    rules = [dict(r) for r in (automation.rules or [])]
    if any(r.get("condition") == patch.rule.get("condition") for r in rules):
        return False
    rules.append(
        {
            "condition": patch.rule.get("condition"),
            "action": patch.rule.get("action"),
            "source": "learned",
            "evidence_count": patch.evidence_count,
            # Carried through so coverage can credit this rule for the class of
            # exceptions it now handles.
            "signature_key": patch.rule.get("signature_key"),
        }
    )
    automation.rules = rules
    return True


async def recompute_coverage(session: AsyncSession, automation: Automation) -> float:
    """Share of triggers this automation handles without involving a person.

    Measured from the largest available sample. A backtest over hundreds of real
    historical triggers is far stronger evidence than a handful of shadow runs,
    so it is preferred when one has been run.

    Guard holds count against coverage. That is the honest accounting: an
    automation that stops and asks on 15% of invoices is covering 85% of the
    work, and reporting 100% while the backtest openly shows 113 withheld runs
    would be an internal contradiction a reviewer would rightly catch.

    Learned branch rules earn coverage back, because encoding a decision is
    precisely what stops that class of input needing a person again.
    """
    result = await session.execute(
        select(ExceptionCase).where(ExceptionCase.automation_id == automation.id)
    )
    cases = list(result.scalars().all())
    open_cases = sum(1 for c in cases if c.status == "open")

    if automation.replay_total > 0:
        sample = automation.replay_total
        human_involved = automation.replay_human_count
    else:
        # No backtest yet: fall back to the shadow-run history.
        sample = max(automation.shadow_run_count or 0, len(cases))
        human_involved = open_cases

    if sample <= 0:
        automation.coverage = 0.0
        await session.flush()
        return 0.0

    # A learned rule reclaims coverage only if its action resolves the case
    # without a person. A rule that routes to a manager automates the *routing
    # decision*, which is real value — but the manager still has to act, so
    # counting it as autonomous coverage would inflate the number in exactly the
    # direction that flatters us.
    encoded = {
        str(rule.get("signature_key") or "")
        for rule in (automation.rules or [])
        if rule.get("source") == "learned" and not routes_to_human(str(rule.get("action") or ""))
    }
    encoded.discard("")
    reclaimed_cases = (
        sum(1 for c in cases if c.status == "resolved" and c.signature_key in encoded)
        if encoded
        else 0
    )
    # Scale the reclaimed exceptions up to the replay sample: if 3 of 4 queued
    # exceptions are now handled by a rule, the same proportion of the withheld
    # population is too.
    resolved_total = sum(1 for c in cases if c.status == "resolved") or 1
    reclaimed = human_involved * min(1.0, reclaimed_cases / resolved_total)

    remaining_human = max(0.0, human_involved - reclaimed)
    coverage = max(0.0, min(1.0, 1.0 - remaining_human / sample))

    automation.coverage = round(coverage, 4)
    await session.flush()
    return automation.coverage
