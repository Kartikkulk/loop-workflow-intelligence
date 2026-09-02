"""Translating a LOOP automation into an n8n workflow.

The rule these tests hold: the exported workflow must carry LOOP's safety
decisions with it. A workflow that arrived in n8n without the guard, or with a
credential baked in, would be worse than not exporting at all — it would look
like the automation LOOP approved while behaving like a different one.
"""

from __future__ import annotations

import json

import pytest

from app.services.n8n_export import to_n8n_workflow

INVOICE = {
    "name": "Aws Invoice Pdf to billing note",
    "trigger": {"type": "manual", "filter": {"object_type": "aws_invoice_pdf"}},
    "steps": [
        {"id": "s1", "type": "read", "connector": "files",
         "description": "read aws invoice pdf in files", "outputs": ["filename"]},
        {"id": "s2", "type": "extract", "connector": "pdf",
         "description": "extract invoice total in pdf", "outputs": ["amount"]},
        {"id": "s3", "type": "create", "connector": "files",
         "description": "create filed invoice in files", "outputs": ["filename"]},
        {"id": "s4", "type": "send", "connector": "jira",
         "description": "send billing note in jira", "outputs": ["ticket_id"]},
    ],
    "guards": {"requires_approval_if": "amount > 1000000", "irreversible": ["s4"]},
}


def _named(workflow: dict, fragment: str) -> dict | None:
    for node in workflow["nodes"]:
        if fragment.lower() in node["name"].lower():
            return node
    return None


def test_every_step_becomes_a_node_plus_a_trigger():
    workflow = to_n8n_workflow(INVOICE)
    # 4 steps + 1 trigger + 1 guard.
    assert len(workflow["nodes"]) == 6
    assert workflow["nodes"][0]["type"].endswith("manualTrigger")


def test_the_nodes_are_chained_in_order():
    workflow = to_n8n_workflow(INVOICE)
    names = [node["name"] for node in workflow["nodes"]]
    for earlier, later in zip(names, names[1:], strict=False):
        target = workflow["connections"][earlier]["main"][0][0]["node"]
        assert target == later, f"{earlier} does not lead to {later}"
    # The last node ends the chain rather than looping back.
    assert names[-1] not in workflow["connections"]


def test_the_guard_sits_in_front_of_the_irreversible_step():
    """The hold LOOP measured has to be enforced by whatever runs the work."""
    workflow = to_n8n_workflow(INVOICE)
    names = [node["name"] for node in workflow["nodes"]]
    guard = _named(workflow, "policy limit")
    jira = _named(workflow, "jira")
    assert guard is not None, "no guard node was emitted"
    assert guard["type"].endswith(".if")
    assert names.index(guard["name"]) < names.index(jira["name"])


def test_the_guard_condition_is_inverted_so_it_continues_when_under_the_limit():
    """LOOP says 'hold when over'; n8n needs 'carry on when not over'.

    Emitting the condition unchanged would invert the policy: everything cheap
    would be held and every expensive invoice would sail through.
    """
    workflow = to_n8n_workflow(INVOICE)
    guard = _named(workflow, "policy limit")
    condition = guard["parameters"]["conditions"]["conditions"][0]
    assert condition["operator"]["operation"] == "lte"
    assert condition["rightValue"] == 1000000
    assert "amount" in condition["leftValue"]


def test_an_untranslatable_guard_is_reported_rather_than_dropped_silently():
    broken = {**INVOICE, "guards": {"requires_approval_if": "amount BETWEEN 1 AND 2",
                                    "irreversible": ["s4"]}}
    workflow = to_n8n_workflow(broken)
    assert _named(workflow, "policy limit") is None
    assert any("could not be translated" in note for note in workflow["_loop_notes"])


def test_no_credential_is_ever_written_into_the_workflow():
    """Nobody's account gets wired up by a script."""
    workflow = to_n8n_workflow(INVOICE)
    serialised = json.dumps(workflow)
    assert "credentials" not in serialised
    for node in workflow["nodes"]:
        assert "credentials" not in node


def test_an_unmapped_connector_becomes_a_visible_placeholder():
    exotic = {
        **INVOICE,
        "steps": [{"id": "s1", "type": "read", "connector": "mainframe",
                   "description": "read batch job in mainframe", "outputs": []}],
        "guards": {},
    }
    workflow = to_n8n_workflow(exotic)
    step = workflow["nodes"][1]
    assert step["type"].endswith("noOp")
    assert any("mainframe" in note for note in workflow["_loop_notes"])


@pytest.mark.parametrize(
    ("schedule", "expected"),
    [("hourly", "hours"), ("daily", "days"), ("weekly", "weeks")],
)
def test_the_schedule_can_be_chosen(schedule, expected):
    workflow = to_n8n_workflow(INVOICE, schedule=schedule)
    trigger = workflow["nodes"][0]
    assert trigger["type"].endswith("scheduleTrigger")
    assert trigger["parameters"]["rule"]["interval"][0]["field"] == expected


def test_manual_stays_manual():
    workflow = to_n8n_workflow(INVOICE, schedule="manual")
    assert workflow["nodes"][0]["type"].endswith("manualTrigger")


def test_an_unknown_schedule_is_refused():
    with pytest.raises(ValueError, match="unknown schedule"):
        to_n8n_workflow(INVOICE, schedule="fortnightly")
