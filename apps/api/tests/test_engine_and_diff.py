"""Engine, guard-safety and diff tests."""

from __future__ import annotations

import pytest

from app.models.execution import ExecutionMode
from app.services.diffing import compare, explain_failure, values_match
from app.services.engine import engine, evaluate_condition, evaluate_rules
from app.services.healing import _heuristic_remap
from app.services.normaliser import (
    NormalisationError,
    canonical_action,
    canonical_app,
    normalise_csv,
    normalise_jsonl,
    parse_timestamp,
)

STEPS = [
    {"id": "s1", "type": "read", "connector": "gmail",
     "outputs": ["vendor", "amount"], "depends_on": []},
    {"id": "s2", "type": "create", "connector": "sheets",
     "outputs": ["row_id"], "depends_on": ["vendor", "amount"]},
    {"id": "s3", "type": "send", "connector": "gmail",
     "outputs": ["message_id"], "depends_on": ["row_id"]},
]


async def test_engine_runs_a_clean_flow():
    result = await engine.run(
        steps=STEPS,
        guards={},
        mode=ExecutionMode.REPLAY,
        source_payload={"vendor": "Sundaram Steel", "amount": 50_000, "row_id": "r1"},
    )
    assert result.status == "ok"
    assert len(result.step_results) == 3


async def test_engine_reports_unresolved_dependency():
    """The drift signal: a depends_on field that no longer resolves."""
    result = await engine.run(
        steps=STEPS, guards={}, mode=ExecutionMode.REPLAY, source_payload={"vendor": "X"}
    )
    assert result.status == "failed"
    assert "amount" in result.unresolved_fields


async def test_guard_withholds_irreversible_step():
    result = await engine.run(
        steps=STEPS,
        guards={"requires_approval_if": "amount > 1000000", "irreversible": ["s3"]},
        mode=ExecutionMode.REPLAY,
        source_payload={"vendor": "X", "amount": 2_000_000, "row_id": "r1"},
    )
    assert result.status == "needs_approval"
    assert result.needs_approval
    assert "amount > 1000000" in (result.approval_reason or "")


async def test_guard_does_not_block_below_threshold():
    result = await engine.run(
        steps=STEPS,
        guards={"requires_approval_if": "amount > 1000000", "irreversible": ["s3"]},
        mode=ExecutionMode.REPLAY,
        source_payload={"vendor": "X", "amount": 5_000, "row_id": "r1"},
    )
    assert result.status == "ok"


async def test_replay_and_shadow_never_produce_real_side_effects():
    """The safety guarantee that makes the ladder meaningful."""
    for mode in (ExecutionMode.REPLAY, ExecutionMode.SHADOW):
        result = await engine.run(
            steps=STEPS,
            guards={},
            mode=mode,
            source_payload={"vendor": "X", "amount": 1, "row_id": "r1"},
        )
        assert result.status == "ok"
        assert all("mocked" in effect for effect in result.side_effects)


def test_guard_expressions_are_not_evaluated_as_code():
    """Flow definitions are partly model-generated, so they are untrusted input."""
    assert evaluate_condition("__import__('os').system('echo hi')", {}) is False
    assert evaluate_condition("amount > 100", {"amount": 500}) is True
    assert evaluate_condition("amount > 100", {"amount": 50}) is False


def test_unparseable_guard_fails_closed():
    """An unparseable guard must never silently permit an action."""
    assert evaluate_condition("this is not a condition", {"amount": 999}) is False
    assert evaluate_condition("", {"amount": 999}) is False


def test_guard_operators():
    values = {"amount": 100, "currency": "EUR"}
    assert evaluate_condition("amount >= 100", values)
    assert evaluate_condition("amount <= 100", values)
    assert evaluate_condition("amount == 100", values)
    assert not evaluate_condition("amount != 100", values)
    assert evaluate_condition('currency != "INR"', values)
    assert evaluate_condition("currency == EUR", values)


def test_guard_on_missing_field_is_false():
    assert evaluate_condition("amount > 10", {}) is False


def test_guard_type_mismatch_does_not_raise():
    assert evaluate_condition("amount > 10", {"amount": "not a number"}) is False


def test_evaluate_rules_returns_matches():
    rules = [{"condition": "amount > 100", "action": "route"},
             {"condition": "amount > 10000", "action": "escalate"}]
    matched = evaluate_rules(rules, {"amount": 500})
    assert len(matched) == 1
    assert matched[0]["action"] == "route"


# ── diffing ────────────────────────────────────────────────────────────────

def test_values_match_tolerates_case_and_small_numeric_drift():
    assert values_match("Sundaram Steel", "sundaram steel")
    assert values_match(100.0, 100.005)
    assert not values_match(100, 200)
    assert values_match(None, None)
    assert not values_match(None, "x")


def test_critical_field_mismatch_is_flagged():
    diff = compare({"amount": 100, "subject": "a"}, {"amount": 200, "subject": "a"})
    assert diff.critical_mismatch
    assert "amount" in diff.diff_fields
    assert not diff.correct


def test_non_critical_mismatch_is_not_critical():
    diff = compare({"subject": "a", "amount": 1}, {"subject": "b", "amount": 1})
    assert not diff.critical_mismatch
    assert not diff.correct
    assert diff.score > 0


def test_critical_fields_are_weighted_double():
    critical = compare({"amount": 1, "subject": "a"}, {"amount": 2, "subject": "a"})
    ordinary = compare({"amount": 1, "subject": "a"}, {"amount": 1, "subject": "b"})
    assert critical.score < ordinary.score


def test_full_agreement_is_correct():
    diff = compare({"amount": 1, "vendor": "x"}, {"amount": 1, "vendor": "x"})
    assert diff.correct
    assert diff.score == 1.0


def test_no_shared_fields_is_not_treated_as_agreement():
    diff = compare({"a": 1}, {"b": 2})
    assert diff.compared == 0
    assert diff.score == 0.0
    assert not diff.correct


def test_failure_explanation_names_the_currency_cause():
    diff = compare({"amount": 100}, {"amount": 9000})
    reason = explain_failure(diff, {"amount": 100, "currency": "EUR"}, {"amount": 9000})
    assert "EUR" in reason
    assert "conversion" in reason


# ── normalisation ──────────────────────────────────────────────────────────

def test_app_and_action_aliases():
    assert canonical_app("Excel") == "sheets"
    assert canonical_app("Microsoft Exchange") == "outlook"
    assert canonical_action("opened") == "read"
    assert canonical_action("append") == "create"


def test_timestamp_parsing_is_always_utc():
    for raw in ("2026-01-01T10:00:00Z", "2026-01-01 10:00:00", "2026-01-01T10:00:00+00:00"):
        assert parse_timestamp(raw).tzinfo is not None
    with pytest.raises(NormalisationError):
        parse_timestamp("")


def test_csv_normalisation_reports_bad_rows_without_failing():
    csv_text = (
        "user_id,timestamp,app,action,object_type\n"
        "u1,2026-01-01T10:00:00Z,Gmail,opened,invoice_email\n"
        ",2026-01-01T10:01:00Z,Gmail,opened,invoice_email\n"
    )
    events, errors = normalise_csv(csv_text)
    assert len(events) == 1
    assert len(errors) == 1
    assert events[0].app == "gmail"
    assert events[0].action == "read"


def test_jsonl_normalisation():
    events, errors = normalise_jsonl(
        '{"user_id":"u1","timestamp":"2026-01-01T10:00:00Z","app":"sheets",'
        '"action":"append","object_type":"row"}\n'
    )
    assert not errors
    assert events[0].step_token == "sheets:create:row"


# ── healing heuristic ──────────────────────────────────────────────────────

def test_synonym_remap_is_high_confidence():
    field, confidence, _ = _heuristic_remap("Vendor", ["Supplier Name", "amount"])
    assert field == "Supplier Name"
    assert confidence > 0.9


def test_token_containment_remap():
    field, confidence, reason = _heuristic_remap("vendor", ["Vendor Legal Name", "amount"])
    assert field == "Vendor Legal Name"
    assert confidence > 0.9
    assert "token" in reason


def test_weak_match_stays_below_auto_apply_threshold():
    """A merely plausible string match must always reach a human."""
    from app.config import settings

    _, confidence, _ = _heuristic_remap("vendor", ["zzz_unrelated_column"])
    assert confidence < settings.patch_auto_apply_confidence


def test_no_candidates_yields_zero_confidence():
    field, confidence, _ = _heuristic_remap("vendor", [])
    assert field == ""
    assert confidence == 0.0


# ── sessionising ───────────────────────────────────────────────────────────

def test_reset_event_never_starts_an_instance():
    """Ambient noise must not become the first step of a workflow.

    A resetting event (a Slack read, a browser navigation) marks a task
    boundary. Letting one land at the head of the next instance polluted
    signatures with noise and made the "this step varied" display misleading.
    """
    from datetime import UTC, datetime, timedelta

    from app.services.sessioniser import sessionise

    class E:
        def __init__(self, app, action, obj, minutes):
            self.user_id = "u1"
            self.team = "t"
            self.app = app
            self.action = action
            self.object_type = obj
            self.timestamp = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes)
            self.duration_ms = 0
            self.session_id = None
            self.ground_truth_workflow = None
            self.id = f"e{minutes}"

        @property
        def step_token(self):
            return f"{self.app}:{self.action}:{self.object_type}"

    events = [
        E("slack", "read", "message", 0),          # reset, before anything
        E("gmail", "read", "invoice_email", 1),
        E("sheets", "create", "row", 2),
        E("browser", "navigate", "page", 3),       # reset, mid-stream
        E("gmail", "read", "invoice_email", 4),
        E("sheets", "create", "row", 5),
    ]
    instances = sessionise(events)

    assert len(instances) == 2
    for instance in instances:
        assert instance.signature == ["gmail:read:invoice_email", "sheets:create:row"]
        for token in instance.raw_signature:
            assert not token.startswith(("slack:read", "browser:navigate"))


def test_reset_event_splits_an_instance():
    from datetime import UTC, datetime, timedelta

    from app.services.sessioniser import sessionise

    class E:
        def __init__(self, app, action, obj, minutes):
            self.user_id = "u1"
            self.team = "t"
            self.app = app
            self.action = action
            self.object_type = obj
            self.timestamp = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes)
            self.duration_ms = 0
            self.session_id = None
            self.ground_truth_workflow = None
            self.id = f"e{minutes}"

        @property
        def step_token(self):
            return f"{self.app}:{self.action}:{self.object_type}"

    # Two events, a reset, then two more: two instances, not one.
    events = [
        E("gmail", "read", "a", 0),
        E("sheets", "create", "b", 1),
        E("slack", "read", "message", 2),
        E("erp", "read", "c", 3),
        E("erp", "update", "d", 4),
    ]
    assert len(sessionise(events)) == 2
