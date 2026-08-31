"""Field-level comparison shared by replay (F6) and shadow mode (F7).

Both features answer the same question — did the automation do what the human
did? — so they use one comparator. Critical fields are weighted double because a
wrong vendor name and a wrong ledger amount are not equally forgivable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Fields whose disagreement is disqualifying. A mismatch on any of these sets
# `critical_mismatch`, which blocks promotion outright and forces demotion —
# no amount of good average scoring can outvote it.
CRITICAL_FIELDS: frozenset[str] = frozenset(
    {"amount", "amount_inr", "vendor", "supplier", "po_number", "recipient", "status"}
)

_NUMERIC_TOLERANCE = 0.01


@dataclass
class Diff:
    """The result of comparing a prediction against an observation."""

    field_matches: dict[str, bool] = field(default_factory=dict)
    score: float = 0.0
    critical_mismatch: bool = False
    diff_fields: list[str] = field(default_factory=list)
    compared: int = 0

    @property
    def correct(self) -> bool:
        """A run counts as correct only if nothing critical disagreed."""
        return not self.critical_mismatch and self.score >= 0.999


def _normalise(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    return str(value).strip().lower()


def values_match(predicted: Any, observed: Any) -> bool:
    """Compare two field values with numeric tolerance and case folding."""
    left, right = _normalise(predicted), _normalise(observed)
    if left is None or right is None:
        return left == right
    if isinstance(left, float) and isinstance(right, float):
        scale = max(abs(left), abs(right), 1.0)
        return abs(left - right) / scale <= _NUMERIC_TOLERANCE
    return left == right


def compare(predicted: dict[str, Any], observed: dict[str, Any]) -> Diff:
    """Compare a prediction against an observation, field by field.

    Only fields present in *both* dictionaries are scored. Penalising the
    automation for fields the log never recorded would make the accuracy number
    a measure of log completeness rather than of automation quality.
    """
    shared = [k for k in predicted if k in observed]
    result = Diff(compared=len(shared))
    if not shared:
        # Nothing comparable is not evidence of agreement.
        result.score = 0.0
        return result

    weighted_total = 0.0
    weighted_hit = 0.0
    for key in shared:
        matched = values_match(predicted[key], observed[key])
        result.field_matches[key] = matched
        weight = 2.0 if key in CRITICAL_FIELDS else 1.0
        weighted_total += weight
        if matched:
            weighted_hit += weight
        else:
            result.diff_fields.append(key)
            if key in CRITICAL_FIELDS:
                result.critical_mismatch = True

    result.score = round(weighted_hit / weighted_total, 4) if weighted_total else 0.0
    return result


def explain_failure(diff: Diff, predicted: dict, observed: dict) -> str:
    """A specific, honest reason a run disagreed — never a generic message."""
    if not diff.diff_fields:
        return "no field disagreement"

    reasons = []
    if "amount" in diff.diff_fields or "amount_inr" in diff.diff_fields:
        currency = observed.get("currency") or predicted.get("currency")
        if currency and str(currency).upper() != "INR":
            reasons.append(
                f"invoice denominated in {currency}; the flow has no currency-conversion rule"
            )
        else:
            reasons.append("amount extracted differs from the amount the human recorded")
    for name in ("vendor", "supplier"):
        if name in diff.diff_fields:
            reasons.append(f"{name} name resolved differently (likely a renamed source column)")
    if "po_number" in diff.diff_fields:
        reasons.append("purchase order number did not match the human's entry")
    if "status" in diff.diff_fields:
        reasons.append("outcome status differs; this instance likely required a judgement call")

    if not reasons:
        reasons.append(f"disagreement on {', '.join(diff.diff_fields)}")
    return "; ".join(reasons)
