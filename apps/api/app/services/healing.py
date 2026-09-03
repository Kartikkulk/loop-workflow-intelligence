"""F8 — drift detection and self-healing patches.

When a step's `depends_on` field stops resolving, the cause is almost always
that the world moved: a spreadsheet column was renamed, an API field was
restructured, a DOM selector changed. Kriyā AI captures the schema as it exists
*now*, asks for a remapping, and scores its own confidence.

The confidence gate is the whole safety story. A high-confidence remapping on a
non-destructive step applies itself; anything else queues for a human. Note the
`irreversible` check: a rename on a step that sends email or writes a ledger is
never auto-applied, however confident the proposal.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm.client import llm
from app.llm.tools import REMAP_FIELD
from app.models.automation import Automation
from app.models.event import Event
from app.models.governance import Patch
from app.services.ids import new_id

logger = logging.getLogger("loop.healing")

_IRREVERSIBLE_TYPES = {"send", "delete"}


async def observe_schema(
    session: AsyncSession, app: str, *, window_days: int = 20
) -> list[str]:
    """The field names a system is currently using, read from recent activity.

    Derived from data rather than declared in config: that is what makes drift
    genuinely *detectable* instead of merely configurable.
    """
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    result = await session.execute(
        select(Event).where(Event.app == app, Event.timestamp >= cutoff)
    )
    keys: set[str] = set()
    for event in result.scalars().all():
        for key in (event.payload or {}):
            if key != "workflow_hint":
                keys.add(key)
    return sorted(keys)


async def historical_schema(
    session: AsyncSession, app: str, *, before_days: int = 40
) -> list[str]:
    """The field names the system used when the automation was built."""
    cutoff = datetime.now(UTC) - timedelta(days=before_days)
    result = await session.execute(
        select(Event).where(Event.app == app, Event.timestamp < cutoff)
    )
    keys: set[str] = set()
    for event in result.scalars().all():
        for key in (event.payload or {}):
            if key != "workflow_hint":
                keys.add(key)
    return sorted(keys)


def _tokens(name: str) -> set[str]:
    """Split a field name into comparable tokens, ignoring case and separators."""
    return {t for t in re.split(r"[^a-z0-9]+", name.lower()) if t}


def _heuristic_remap(missing: str, candidates: list[str]) -> tuple[str, float, str]:
    """Match a missing field against the current schema, with no model call.

    Three rules, in descending order of evidential strength:

    1. A known synonym pair (`Vendor` / `Supplier Name`). Strongest: these are
       semantically identical but share almost no characters, so no string
       metric would ever find them.
    2. Token containment (`Vendor` -> `Vendor Legal Name`). Strong and general:
       a renamed column that gained a qualifier keeps every original token, and
       this catches `amount` -> `Net Amount` and `date` -> `Invoice Date` too.
    3. Fuzzy similarity. Weakest, and deliberately capped below the auto-apply
       threshold so a merely plausible string match always reaches a human.
    """
    synonyms = {
        "vendor": ("supplier", "supplier name", "payee", "merchant", "counterparty"),
        "supplier": ("vendor", "vendor name", "payee"),
        "amount": ("total", "value", "net amount", "gross", "sum"),
        "date": ("invoice date", "issued", "created", "timestamp"),
        "po_number": ("purchase order", "po", "order number", "po ref"),
        "recipient": ("to", "send_to", "addressee"),
    }
    if not candidates:
        return "", 0.0, "no fields are currently observable for this system."

    lowered = {c.lower(): c for c in candidates}
    key = missing.lower()

    # Rule 1 — known synonym.
    for canonical, alternatives in synonyms.items():
        if key == canonical or key in alternatives:
            for alt in {canonical, *alternatives}:
                if alt in lowered:
                    return (
                        lowered[alt],
                        0.94,
                        f"'{missing}' and '{lowered[alt]}' are known synonyms for the same "
                        "field; the source system renamed the column.",
                    )

    # Rule 2 — token containment.
    missing_tokens = _tokens(missing)
    if missing_tokens:
        contained = [
            c for c in candidates if missing_tokens and missing_tokens <= _tokens(c)
        ]
        if contained:
            # Prefer the least-qualified candidate: `Vendor Legal Name` over
            # `Vendor Legal Name Archived Copy`.
            best = min(contained, key=lambda c: len(_tokens(c)))
            return (
                best,
                0.92,
                f"'{best}' contains every token of '{missing}'; the column was renamed "
                "with an added qualifier rather than replaced.",
            )

    # Rule 3 — fuzzy fallback.
    match = process.extractOne(
        missing, candidates, scorer=fuzz.token_set_ratio, processor=str.lower
    )
    if match is None:
        return "", 0.0, "no candidate field resembles the missing one."
    best, score, _ = match
    return (
        best,
        min(0.88, score / 100.0),
        f"'{best}' is the closest field currently present (string similarity {score:.0f}%). "
        "Held for review: a string match alone is not strong enough to apply unattended.",
    )


async def propose_drift_patch(
    session: AsyncSession,
    automation: Automation,
    step_id: str,
    missing_field: str,
) -> Patch | None:
    """Propose a remapping for one unresolved dependency."""
    step = next((s for s in (automation.steps or []) if s.get("id") == step_id), None)
    if step is None:
        return None

    existing = await session.execute(
        select(Patch).where(
            Patch.automation_id == automation.id,
            Patch.step_id == step_id,
            Patch.field == missing_field,
            Patch.status == "proposed",
        )
    )
    if existing.scalars().first() is not None:
        return None  # already queued; do not spam the reviewer

    connector = str(step.get("connector", ""))
    current = await observe_schema(session, connector)
    original = await historical_schema(session, connector)

    heuristic_field, heuristic_conf, heuristic_reason = _heuristic_remap(missing_field, current)

    proposed = await llm.structured(
        prompt=llm.load_prompt(
            "remap_field",
            automation_name=automation.name,
            step_id=step_id,
            step_type=str(step.get("type", "")),
            connector=connector,
            missing_field=missing_field,
            current_schema=", ".join(current) or "(none observed)",
            original_schema=", ".join(original) or "(none observed)",
        ),
        tool=REMAP_FIELD,
        fallback=lambda: {
            "to_field": heuristic_field,
            "confidence": heuristic_conf,
            "rationale": heuristic_reason,
        },
    )

    to_field = str(proposed.get("to_field") or heuristic_field)
    confidence = float(proposed.get("confidence", heuristic_conf))
    rationale = str(proposed.get("rationale") or heuristic_reason)

    if not to_field:
        return None

    # A rename is only auto-applicable when it is both confident AND on a step
    # that cannot cause harm if the guess is wrong.
    destructive = str(step.get("type")) in _IRREVERSIBLE_TYPES
    auto_applicable = confidence >= settings.patch_auto_apply_confidence and not destructive
    if destructive and confidence >= settings.patch_auto_apply_confidence:
        rationale += (
            " Held for review despite high confidence: this step's effect is "
            "irreversible, so a wrong remapping could not be undone."
        )

    patch = Patch(
        id=new_id("pat"),
        automation_id=automation.id,
        kind="drift",
        step_id=step_id,
        field=missing_field,
        from_value=missing_field,
        to_value=to_field,
        confidence=round(confidence, 3),
        auto_applicable=auto_applicable,
        status="proposed",
        rationale=rationale,
        proposed_by="llm" if llm.available else "heuristic",
    )
    session.add(patch)
    await session.flush()
    logger.info(
        "drift patch proposed: %s.%s '%s' -> '%s' (confidence %.2f, auto=%s)",
        automation.id, step_id, missing_field, to_field, confidence, auto_applicable,
    )
    return patch


def apply_patch_to_flow(automation: Automation, patch: Patch) -> bool:
    """Rewrite the flow definition so the patched dependency resolves again."""
    steps = [dict(s) for s in (automation.steps or [])]
    changed = False
    for step in steps:
        if step.get("id") != patch.step_id:
            continue
        depends = list(step.get("depends_on") or [])
        for index, name in enumerate(depends):
            if name == patch.from_value:
                depends[index] = str(patch.to_value)
                changed = True
        step["depends_on"] = depends
        inputs = dict(step.get("inputs") or {})
        for key, value in list(inputs.items()):
            if value == patch.from_value:
                inputs[key] = patch.to_value
                changed = True
        step["inputs"] = inputs
    if changed:
        # Reassigned rather than mutated in place, so SQLAlchemy marks the
        # JSON column dirty and actually persists the change.
        automation.steps = steps
    return changed


async def detect_and_heal(
    session: AsyncSession, automation: Automation, unresolved: list[str], step_id: str | None
) -> list[Patch]:
    """Propose patches for every unresolved dependency, auto-applying safe ones."""
    patches: list[Patch] = []
    for field_name in dict.fromkeys(unresolved):
        target_step = step_id
        if target_step is None:
            target_step = next(
                (
                    s.get("id")
                    for s in (automation.steps or [])
                    if field_name in (s.get("depends_on") or [])
                ),
                None,
            )
        if target_step is None:
            continue
        patch = await propose_drift_patch(session, automation, str(target_step), field_name)
        if patch is None:
            continue
        if patch.auto_applicable and apply_patch_to_flow(automation, patch):
            patch.status = "applied"
        patches.append(patch)
    await session.flush()
    return patches
