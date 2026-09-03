"""The runtime choice must follow from what the steps can physically reach."""

from __future__ import annotations

from app.services.execution_planner import (
    ExecutionPlan,
    choose_method_deterministically,
)


def _steps(*connectors: str) -> list[dict]:
    return [
        {"id": f"s{i}", "connector": c, "type": "read"}
        for i, c in enumerate(connectors, start=1)
    ]


def test_a_browser_only_flow_goes_to_playwright():
    """No other runtime can reach a system with no API, so nothing else wins."""
    plan = choose_method_deterministically(_steps("browser", "browser"))
    assert plan.method == "playwright"
    assert "s1" in plan.rationale


def test_a_browser_step_beside_an_api_splits_rather_than_forcing_one_runtime():
    """Clicking through a system that has a good API is the worse half of both."""
    plan = choose_method_deterministically(_steps("gmail", "browser", "sheets"))
    assert plan.method == "hybrid"
    assert plan.browser_connectors == ["browser"]
    assert plan.api_connectors == ["gmail", "sheets"]


def test_desktop_counts_as_no_api_too():
    plan = choose_method_deterministically(_steps("desktop", "desktop"))
    assert plan.method == "playwright"


def test_local_file_work_goes_to_a_script():
    """The AWS invoice shape: read a file, parse a document, file it away."""
    plan = choose_method_deterministically(_steps("files", "pdf", "files", "jira"))
    assert plan.method == "python"


def test_an_all_saas_chain_goes_to_n8n():
    plan = choose_method_deterministically(_steps("gmail", "sheets", "slack"))
    assert plan.method == "n8n"
    assert plan.confidence > 0.5


def test_a_connector_with_no_n8n_node_falls_to_a_script():
    """n8n cannot cover the whole flow, so it is not offered as if it could."""
    plan = choose_method_deterministically(_steps("gmail", "wharfside_portal"))
    assert plan.method == "python"


def test_no_steps_still_returns_a_usable_plan():
    plan = choose_method_deterministically([])
    assert plan.method == "python"
    assert plan.confidence < 0.5


def test_plan_serialises_every_field_the_console_reads():
    fields = ExecutionPlan(method="python", rationale="r", confidence=0.5).as_dict()
    assert set(fields) == {
        "method",
        "rationale",
        "confidence",
        "overruled",
        "decided_by",
        "alternative_method",
        "alternative_rationale",
        "factors",
        "browser_connectors",
        "api_connectors",
    }
