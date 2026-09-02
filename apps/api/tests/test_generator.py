"""Flow generation: the guards a generated automation is given.

A guard is the only thing standing between an automation and an irreversible
action, so the rule these tests enforce is that a guard must be able to fire.
"""

from __future__ import annotations

from app.models.cluster import Cluster
from app.services.engine import evaluate_condition
from app.services.generator import _fallback_flow, _sanitise_flow


def _cluster(name: str, signature: list[str], observed: dict[str, list[str]]) -> Cluster:
    return Cluster(
        id="clu_test",
        name=name,
        signature=signature,
        observed_fields=observed,
        instance_count=100,
        distinct_users=4,
    )


FINANCE = _cluster(
    "Invoice to ledger",
    ["gmail:read:invoice_email", "pdf:extract:fields", "gmail:send:confirmation"],
    {
        "gmail:read:invoice_email": ["sender", "subject"],
        # Mirrors the real cluster: the extraction step writes the face value,
        # the currency, and the converted figure the human recorded.
        "pdf:extract:fields": ["vendor", "amount", "currency", "amount_inr"],
        "gmail:send:confirmation": ["recipient"],
    },
)

SERVICE_DESK = _cluster(
    "Access request to granted permission",
    ["jira:read:access_request", "okta:update:group_membership", "slack:send:confirmation"],
    {
        "jira:read:access_request": ["requester", "system", "ticket_id"],
        "okta:update:group_membership": ["requester", "system"],
        "slack:send:confirmation": ["requester"],
    },
)


def test_money_guard_is_given_to_a_workflow_that_handles_money():
    flow = _fallback_flow(FINANCE)
    expression = flow["guards"]["requires_approval_if"]
    assert expression == "amount > 1000000"

    # And it must actually fire on a payload this workflow could produce.
    assert evaluate_condition(expression, {"amount": 2_500_000}) is True
    assert evaluate_condition(expression, {"amount": 500}) is False


def test_the_guard_never_names_a_field_the_engine_hides_at_run_time():
    """A guard on a decision field parses, displays, and never fires.

    `source_payload` withholds decision fields from the automation so the
    human's judgement cannot leak into its prediction. A guard naming one is
    therefore dead on arrival: `evaluate_condition` finds no such key and
    returns False for every instance, while the console shows a spend limit.
    """
    hidden = {"status", "amount_inr", "approval", "note"}
    flow = _fallback_flow(FINANCE)
    expression = flow["guards"]["requires_approval_if"]
    named_field = expression.split()[0]
    assert named_field not in hidden, f"guard names {named_field}, which is withheld"


def test_no_money_guard_where_there_is_no_money():
    """An access request has no amount, so it must not claim a spend limit.

    `evaluate_condition` returns False for a field that is absent, so a guard
    naming one would let every irreversible step through while the console
    displayed a limit. No guard is honest; a dead guard is not.
    """
    flow = _fallback_flow(SERVICE_DESK)
    assert "requires_approval_if" not in flow["guards"]
    # The protection that does apply is still there.
    assert flow["guards"]["irreversible"] == ["s3"]


def test_a_model_guard_naming_an_unknown_field_is_dropped():
    """The model invents plausible guards on fields that do not exist here."""
    invented = {
        "steps": [
            {"id": "s1", "type": "read", "connector": "jira", "outputs": ["ticket_id"]},
            {"id": "s2", "type": "send", "connector": "slack", "depends_on": ["ticket_id"]},
        ],
        "guards": {"requires_approval_if": "amount > 1000000", "irreversible": ["s2"]},
        "trigger": {"type": "manual", "filter": {}},
    }
    flow = _sanitise_flow(invented, SERVICE_DESK)
    assert "requires_approval_if" not in flow["guards"]
    assert "s2" in flow["guards"]["irreversible"]


def test_a_model_guard_on_a_real_field_is_kept():
    kept = {
        "steps": [
            {"id": "s1", "type": "extract", "connector": "pdf", "outputs": ["amount"]},
            {"id": "s2", "type": "send", "connector": "gmail", "depends_on": ["amount"]},
        ],
        "guards": {"requires_approval_if": "amount > 50000", "irreversible": ["s2"]},
        "trigger": {"type": "manual", "filter": {}},
    }
    flow = _sanitise_flow(kept, FINANCE)
    assert flow["guards"]["requires_approval_if"] == "amount > 50000"


def test_every_irreversible_step_is_listed_even_if_the_model_forgot():
    forgetful = {
        "steps": [
            {"id": "s1", "type": "read", "connector": "jira", "outputs": ["ticket_id"]},
            {"id": "s2", "type": "send", "connector": "slack", "depends_on": ["ticket_id"]},
            {"id": "s3", "type": "delete", "connector": "jira", "depends_on": ["ticket_id"]},
        ],
        "guards": {"irreversible": []},
        "trigger": {"type": "manual", "filter": {}},
    }
    flow = _sanitise_flow(forgetful, SERVICE_DESK)
    assert set(flow["guards"]["irreversible"]) == {"s2", "s3"}
