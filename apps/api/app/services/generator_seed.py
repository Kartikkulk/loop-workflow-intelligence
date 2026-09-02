"""Deterministic synthetic activity-log generator.

Given a fixed seed this produces byte-identical output, so a demo is
reproducible and the clustering tests have stable ground truth to assert on.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from app.domains import DOMAINS, DomainPack, Step
from app.services.ids import SequentialIds
from app.services.normaliser import NormalisedEvent
from app.services.seed_spec import (
    CUSTOMERS,
    ERROR_SIGNATURES,
    ESCALATION_NOTES,
    IT_SYSTEMS,
    PRIVILEGED_SYSTEMS,
    REPOSITORIES,
    SCHEMA_CHANGE_DAY,
    SCHEMA_CHANGE_FROM,
    SCHEMA_CHANGE_TO,
    USERS,
    VENDORS,
)

# Mid-task lookups used to create genuine A -> B -> A context switches. None of
# these are sessioniser reset tokens, so the bounce stays inside one instance
# where the Interruption Tax can measure it.
_SWITCH_STEPS: list[Step] = [
    Step("erp", "search", "vendor_record", 35),
    Step("drive", "search", "supporting_doc", 30),
    Step("sheets", "read", "reference_table", 25),
]

# Coherent ambient activity. Every triple here is a sessioniser reset token, so
# noise reliably ends a task rather than contaminating one.
_NOISE_ACTIVITY = [
    ("slack", "read", "message"),
    ("browser", "navigate", "page"),
    ("browser", "read", "page"),
]

_ANOMALY_STEPS: list[Step] = [
    Step("erp", "delete", "duplicate_record", 55),
    Step("browser", "search", "tax_rule", 95),
    Step("drive", "create", "manual_note", 40),
]

# Working hours, so timestamps do not fall at 3am.
_WORK_START_HOUR = 9
_WORK_END_HOUR = 18


def _column_name(day_index: int) -> str:
    """The vendor column header, which is renamed part-way through the window."""
    return SCHEMA_CHANGE_FROM if day_index < SCHEMA_CHANGE_DAY else SCHEMA_CHANGE_TO


def _instance_facts(rng: random.Random, domain: DomainPack) -> dict:
    """Draw the facts of one task instance, once.

    Every step of an instance then reads from these shared facts. This is not a
    tidiness point: if each step drew its own random amount, a single invoice
    would carry a different value at extraction than at ledger entry, and a
    replay backtest would be measuring the generator's inconsistency instead of
    the automation's accuracy.
    """
    amount = (
        rng.randint(1_200_000, 4_500_000)
        if rng.random() < 0.12
        else rng.randint(15_000, 900_000)
    )
    # A minority of invoices arrive in a foreign currency. The generated
    # automation has no conversion rule, so replay will get these wrong. This is
    # a deliberate, genuine failure mode: an honest backtest needs real failures
    # to name, not a fabricated accuracy number.
    currency = "INR" if rng.random() > 0.08 else rng.choice(["EUR", "USD", "AED"])
    vendor = rng.choice(VENDORS)

    facts = {
        "vendor": vendor,
        "amount": amount,
        "currency": currency,
        "sender": f"ap@{vendor.lower().replace(' ', '')}.com",
        "subject": rng.choice(
            [
                "Invoice for August",
                f"INV-{rng.randint(1000, 9999)} attached",
                "Payment due notice",
                "Monthly invoice",
            ]
        ),
        "recipient": "finance-ap@northwind.example",
        "claimant": rng.choice(list(USERS.keys())),
        "po_number": f"PO-{rng.randint(10000, 99999)}",
        # Most requests end the same routine way. Skewing this rather than
        # drawing uniformly is what lets an automation that predicts the common
        # outcome be measurably right most of the time and genuinely wrong the
        # rest — a uniform draw would make every backtest look broken.
        "status": (
            "approved"
            if rng.random() < 0.88
            else rng.choice(["rejected", "routed", "on_hold"])
        ),
        "requester": rng.choice(list(USERS.keys())),
        "approver": rng.choice(list(USERS.keys())),
        "assignee": rng.choice(list(USERS.keys())),
        "system": (system := rng.choice(IT_SYSTEMS)),
        # What the desk actually granted. For a privileged system that is
        # usually a reduced level, so the value the human ends up recording is
        # not the value that was asked for.
        "granted_system": (
            f"{system} (read-only)"
            if system in PRIVILEGED_SYSTEMS and rng.random() < 0.7
            else system
        ),
        "ticket_id": f"SD-{rng.randint(10000, 99999)}",
        "build_id": f"build-{rng.randint(4000, 9999)}",
        "channel": rng.choice(["#platform", "#engineering", "#it-helpdesk"]),
        "repo": rng.choice(REPOSITORIES),
        "pr_number": rng.randint(100, 4000),
        "error_signature": rng.choice(ERROR_SIGNATURES),
        "folder": rng.choice(["/Reports/Daily", "/Reports/Builds"]),
        "report_date": "2026-08-14",
        "sheet_name": "Vendor Ageing FY25",
        "filter_expr": "days_overdue > 30",
        "customer": rng.choice(CUSTOMERS),
        "tone": rng.choice(["frustrated", "neutral", "angry", "formal"]),
        "note": rng.choice(ESCALATION_NOTES),
    }
    if currency != "INR":
        # The human converts to INR before writing the ledger row; the
        # automation copies the face value through unchanged.
        facts["amount_inr"] = int(amount * rng.uniform(80, 95))
    return facts


def _payload_for(
    step: Step, facts: dict, day_index: int, domain: DomainPack
) -> dict:
    """Build one step's payload by projecting the instance's shared facts.

    The `vendor_column` key is special: its *name* changes at the schema-change
    day, which is the drift F8 has to find.
    """
    payload: dict = {}
    for key in step.fields:
        if key == "vendor_column":
            payload[_column_name(day_index)] = facts["vendor"]
        elif key == "amount":
            payload["amount"] = facts["amount"]
            payload["currency"] = facts["currency"]
            if "amount_inr" in facts:
                payload["amount_inr"] = facts["amount_inr"]
        elif key == "system":
            # The request carries the system asked for; the grant carries what
            # was actually given. `source_payload` keeps the first value it sees
            # and `observed_outcome` keeps the last, so a reduced grant becomes
            # a real disagreement between the flow's prediction and the record.
            # Everything from the grant onwards — including the confirmation
            # sent back to the requester — reports what was actually granted.
            # Only the original request carries what was asked for.
            payload["system"] = (
                facts["granted_system"]
                if step.action in ("update", "send")
                else facts["system"]
            )
        elif key in facts:
            payload[key] = facts[key]
        else:
            # A field no domain fact covers still has to carry *something*, but
            # it must not masquerade as a real value: handing back the vendor
            # name made a new domain's `ticket_id` read as "Orbit Print Works",
            # which is indistinguishable from a working field until someone
            # reads the payload. Naming the gap makes it obvious instead.
            payload[key] = f"<{key} not in seed vocabulary>"
    payload["workflow_hint"] = domain.key
    return payload


def _steps_for_instance(domain: DomainPack, rng: random.Random) -> list[Step]:
    """Draw the step sequence for one instance, applying the spec's variance."""
    if domain.freeform:
        count = rng.randint(domain.freeform_min, domain.freeform_max)
        chosen = rng.sample(domain.steps, min(count, len(domain.steps)))
        rng.shuffle(chosen)
        return chosen

    chosen = [s for s in domain.steps if rng.random() <= s.probability]
    if len(chosen) < 2:
        chosen = list(domain.steps[:2])

    if rng.random() < domain.reorder_probability and len(chosen) >= 3:
        i = rng.randrange(len(chosen) - 1)
        chosen[i], chosen[i + 1] = chosen[i + 1], chosen[i]

    if rng.random() < domain.anomaly_probability:
        chosen.insert(rng.randrange(len(chosen) + 1), rng.choice(_ANOMALY_STEPS))

    return chosen


def _inject_context_switch(
    steps: list[Step], domain: DomainPack, rng: random.Random
) -> list[Step]:
    """Insert an A -> B -> A bounce so the Interruption Tax has real data."""
    if rng.random() >= domain.context_switch_probability or len(steps) < 2:
        return steps
    anchor_index = rng.randrange(len(steps) - 1)
    anchor = steps[anchor_index]
    lookup = rng.choice([s for s in _SWITCH_STEPS if s.app != anchor.app])
    out = list(steps)
    # anchor, lookup, anchor-again -> one measurable switch.
    out.insert(anchor_index + 1, lookup)
    out.insert(anchor_index + 2, anchor)
    return out


def generate_events(
    *, seed: int = 42, days: int = 90, start: datetime | None = None
) -> list[NormalisedEvent]:
    """Generate the full synthetic activity log.

    Returns events sorted by timestamp, each tagged with a ground-truth workflow
    key that no detection service reads — it exists only so tests can verify
    that detection independently recovered the right answer.
    """
    rng = random.Random(seed)
    # Deterministic ids: the same seed must produce the same log, byte for byte.
    new_id = SequentialIds(salt=seed)
    window_start = start or (datetime.now(UTC) - timedelta(days=days)).replace(
        hour=_WORK_START_HOUR, minute=0, second=0, microsecond=0
    )
    events: list[NormalisedEvent] = []

    for domain in DOMAINS:
        for user_id in domain.people:
            team = USERS[user_id]
            # Poisson-ish weekly volume, drawn per week so the frequency is
            # realistic rather than perfectly uniform.
            for week in range(max(days // 7, 1)):
                weekly = max(0, int(rng.gauss(domain.per_person_per_week, 
                                              domain.per_person_per_week * 0.25)))
                for _ in range(weekly):
                    day_offset = week * 7 + rng.randrange(0, 5)  # weekdays only
                    if day_offset >= days:
                        continue
                    day_index = day_offset
                    cursor = window_start + timedelta(
                        days=day_offset,
                        hours=rng.randrange(0, _WORK_END_HOUR - _WORK_START_HOUR),
                        minutes=rng.randrange(0, 60),
                    )
                    steps = _inject_context_switch(
                        _steps_for_instance(domain, rng), domain, rng
                    )
                    facts = _instance_facts(rng, domain)
                    session_id = new_id("ses")
                    for step in steps:
                        duration = max(5, int(rng.gauss(step.seconds, step.seconds * 0.3)))
                        events.append(
                            NormalisedEvent(
                                id=new_id("evt"),
                                user_id=user_id,
                                team=team,
                                timestamp=cursor,
                                app=step.app,
                                action=step.action,
                                object_type=step.object_type,
                                object_id=new_id("obj"),
                                duration_ms=duration * 1000,
                                payload=_payload_for(step, facts, day_index, domain),
                                session_id=session_id,
                                ground_truth_workflow=domain.key,
                                source="seed",
                            )
                        )
                        # Small within-task gap, always under the session gap.
                        cursor += timedelta(seconds=duration + rng.randrange(2, 40))

    # Ambient noise: genuine task boundaries and unrelated activity.
    #
    # The (app, action, object) triples are coherent, not independently random.
    # Pairing them randomly produced nonsense like `browser:read:message`, and
    # worse: only some combinations were sessioniser reset tokens, so the rest
    # were absorbed into real task instances and showed up in the console as
    # "this step varied" — noise masquerading as workflow variance.
    noise_count = max(200, len(events) // 12)
    for _ in range(noise_count):
        user_id = rng.choice(list(USERS.keys()))
        app, action, object_type = rng.choice(_NOISE_ACTIVITY)
        events.append(
            NormalisedEvent(
                id=new_id("evt"),
                user_id=user_id,
                team=USERS[user_id],
                timestamp=window_start
                + timedelta(
                    days=rng.randrange(0, days),
                    hours=rng.randrange(0, _WORK_END_HOUR - _WORK_START_HOUR),
                    minutes=rng.randrange(0, 60),
                ),
                app=app,
                action=action,
                object_type=object_type,
                object_id=new_id("obj"),
                duration_ms=rng.randrange(20, 400) * 1000,
                payload={},
                session_id=None,
                ground_truth_workflow=None,
                source="seed",
            )
        )

    events.sort(key=lambda e: e.timestamp)
    return events


def current_sheet_schema(events: list[NormalisedEvent]) -> list[str]:
    """The spreadsheet column headers as they exist at the end of the window.

    Derived from the data, not declared: this is what F8 compares a step's
    depends_on against to notice that a column was renamed.
    """
    latest: dict[str, datetime] = {}
    for event in events:
        if event.app != "sheets":
            continue
        for key in (event.payload or {}):
            if key == "workflow_hint":
                continue
            if key not in latest or event.timestamp > latest[key]:
                latest[key] = event.timestamp
    if not latest:
        return []
    cutoff = max(latest.values()) - timedelta(days=20)
    return sorted([k for k, ts in latest.items() if ts >= cutoff])
