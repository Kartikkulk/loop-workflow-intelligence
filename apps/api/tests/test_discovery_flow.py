"""The CSV demo flow, end to end, through the real pipeline.

The whole point of the CSV path is that it proves discovery works — so these
tests assert it goes through the same normalisation, sessionisation, clustering
and scoring that a live collector's events do. A test that exercised a separate
CSV-only code path would prove nothing about the product.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.services import variables as V
from app.services.clustering import cluster_instances
from app.services.codegen import generate_code
from app.services.engine import evaluate_condition
from app.services.execution_planner import choose_method_deterministically, feasibility
from app.services.normaliser import normalise_upload
from app.services.sessioniser import sessionise
from app.services.validation import validate

DEMO_CSV = Path(__file__).resolve().parent.parent / "fixtures" / "support-escalation-demo.csv"


@pytest.fixture(scope="module")
def demo_events():
    events, errors = normalise_upload(DEMO_CSV.name, DEMO_CSV.read_text(encoding="utf-8"))
    assert errors == [], f"the shipped demo CSV must parse cleanly: {errors}"
    return events


@pytest.fixture(scope="module")
def demo_instances(demo_events):
    return sessionise(demo_events)


@pytest.fixture(scope="module")
def demo_cluster(demo_instances):
    groups = cluster_instances(demo_instances)
    assert len(groups) == 1, "five runs of one process are one workflow, not several"
    return groups[0]


# ── CSV ──────────────────────────────────────────────────────────────────


def test_the_demo_csv_parses(demo_events):
    assert len(demo_events) == 50


def test_a_csv_with_no_user_column_is_still_attributed():
    """Laptop activity has one subject; demanding a user column rejects it."""
    events, errors = normalise_upload(
        "a.csv",
        "timestamp,application,action,target,connector\n"
        "2026-09-03T10:00:00,Chrome,open,Support Portal,browser\n",
    )
    assert errors == []
    assert events[0].user_id == "u_local"


def test_an_empty_csv_yields_nothing_rather_than_crashing():
    events, errors = normalise_upload("a.csv", "timestamp,application,action\n")
    assert events == [] and errors == []


def test_a_malformed_timestamp_names_its_own_row():
    events, errors = normalise_upload(
        "a.csv",
        "timestamp,application,action,target\n"
        "2026-09-03T10:00:00,Chrome,open,Portal\n"
        "not-a-date,Chrome,open,Portal\n",
    )
    assert len(events) == 1
    assert len(errors) == 1 and "line 3" in errors[0]


def test_a_blank_line_is_not_reported_as_a_broken_row():
    _, errors = normalise_upload(
        "a.csv", "timestamp,application,action,target\n2026-09-03T10:00:00,Chrome,open,P\n\n"
    )
    assert errors == []


# ── discovery ────────────────────────────────────────────────────────────


def test_five_repetitions_are_discovered(demo_cluster):
    """Five is the number a person can perform on stage. It has to be enough."""
    assert demo_cluster.size == 5


def test_the_discovered_task_is_the_business_process_not_the_clicks(demo_cluster):
    """A discovery naming one repeated click would be useless."""
    signature = demo_cluster.representative
    assert len(signature) == 10
    assert signature[0] == "browser:read:support_portal"
    assert signature[-1] == "jira:create:issue"
    # It has to span both systems, which is what makes it worth automating.
    assert {t.split(":")[0] for t in signature} == {"browser", "jira"}


def test_unrelated_activity_does_not_become_a_workflow():
    """Two short unrelated tasks must not be called a repetitive pattern."""
    csv = "timestamp,application,action,target,session_id\n"
    rows = [
        ("2026-09-01T09:00:00", "Chrome", "open", "News", "a"),
        ("2026-09-01T09:01:00", "Chrome", "open", "Weather", "a"),
        ("2026-09-02T11:00:00", "Excel", "open", "Budget", "b"),
        ("2026-09-02T11:01:00", "Excel", "update", "Cell", "b"),
    ]
    csv += "\n".join(",".join(r) for r in rows) + "\n"
    events, _ = normalise_upload("a.csv", csv)
    groups = cluster_instances(sessionise(events))
    assert all(g.size < 2 for g in groups), "unrelated one-offs must not cluster"


# ── variables ────────────────────────────────────────────────────────────


def test_changing_values_become_variables(demo_instances):
    found, _ = V.detect(demo_instances)
    names = {v.name for v in found}
    assert {"customer", "issue"} <= names
    customer = next(v for v in found if v.name == "customer")
    assert customer.distinct_count == 5
    assert "ABC" in customer.samples


def test_an_unchanging_value_is_a_constant_not_a_variable(demo_instances):
    """priority was High on every run — that is the guard, not an input."""
    found, constants = V.detect(demo_instances)
    assert "priority" not in {v.name for v in found}
    assert any(c.name.startswith("priority") and c.value == "High" for c in constants)


def test_a_composed_field_shows_the_fields_it_is_built_from(demo_instances):
    found, _ = V.detect(demo_instances)
    assert V.templatise("ABC - Login failure", found, exclude="summary") == (
        "{{customer}} - {{issue}}"
    )


def test_the_guard_is_derived_in_the_engine_s_polarity(demo_instances):
    """`priority != High` holds anything unlike the observed runs."""
    _, constants = V.detect(demo_instances)
    guard = V.guard_from_constants(constants)
    assert guard == "priority != High"
    assert evaluate_condition(guard, {"priority": "Low"}) is True     # held
    assert evaluate_condition(guard, {"priority": "High"}) is False   # proceeds


# ── planner ──────────────────────────────────────────────────────────────


def _steps(*connectors):
    return [{"id": f"s{i}", "connector": c, "type": "read"} for i, c in enumerate(connectors, 1)]


@pytest.mark.parametrize(
    ("connectors", "expected"),
    [
        (("browser", "browser", "jira", "jira"), "hybrid"),
        (("gmail", "sheets", "jira"), "n8n"),
        (("files", "pdf", "files", "jira"), "python"),
        (("browser", "browser"), "playwright"),
    ],
)
def test_the_planner_routes_on_what_can_reach_the_systems(connectors, expected):
    assert choose_method_deterministically(_steps(*connectors)).method == expected


def test_the_demo_workflow_routes_to_hybrid(demo_cluster):
    steps = [
        {"id": f"s{i}", "connector": t.split(":")[0], "type": t.split(":")[1]}
        for i, t in enumerate(demo_cluster.representative, 1)
    ]
    plan = choose_method_deterministically(steps)
    assert plan.method == "hybrid"
    assert plan.browser_connectors == ["browser"] and plan.api_connectors == ["jira"]
    assert plan.factors, "a recommendation with no visible reasoning is a guess"


def test_an_impossible_override_is_explained_not_silently_generated():
    browser_and_api = _steps("browser", "jira")
    ok, why = feasibility("n8n", browser_and_api)
    assert ok is False and "browser" in why.lower()
    assert feasibility("hybrid", browser_and_api)[0] is True


# ── generator ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def demo_artifact(demo_cluster, demo_instances):
    found, constants = V.detect(demo_instances)
    steps = [
        {"id": f"s{i}", "connector": t.split(":")[0], "type": t.split(":")[1],
         "outputs": [], "depends_on": []}
        for i, t in enumerate(demo_cluster.representative, 1)
    ]
    guards = {"irreversible": ["s10"], "requires_approval_if": "priority != High"}
    code = generate_code(
        method="hybrid", name="Support escalation", description="", cluster_id="c",
        steps=steps, guards=guards, variables=[v.as_dict() for v in found],
        constants=[c.as_dict() for c in constants],
        browser_connectors=["browser"], api_connectors=["jira"], occurrences=5,
    )
    return code, steps, guards, found


def test_the_generated_artifact_is_valid_python(demo_artifact):
    code, *_ = demo_artifact
    ast.parse(code.source)


def test_observed_values_are_not_baked_into_the_generated_code(demo_artifact):
    """An automation must work for the next ticket, not replay the last one."""
    code, *_ = demo_artifact
    tree = ast.parse(code.source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body.pop(0)
    executable = ast.unparse(tree)
    for observed in ("ABC", "Login failure", "SUP-4501", "Ticket 1001"):
        assert observed not in executable, f"{observed!r} was hard-coded into the automation"


def test_the_generated_code_templates_over_the_variables(demo_artifact):
    code, *_ = demo_artifact
    assert "values['customer']" in code.source
    assert "values['issue']" in code.source


def test_the_guard_field_is_actually_read_at_run_time(demo_artifact):
    """A guard testing a value nobody fetched fails closed on every run."""
    code, *_ = demo_artifact
    assert "extracted['priority']" in code.source


def test_no_credentials_are_written_into_the_artifact(demo_artifact):
    code, *_ = demo_artifact
    assert "os.environ" in code.source
    for secret in ("password", "api_key=", "Bearer sk-"):
        assert secret not in code.source.lower().replace("api_token", "")


# ── validation ───────────────────────────────────────────────────────────


def test_a_faithful_automation_validates(demo_artifact, demo_cluster):
    code, steps, guards, found = demo_artifact
    report = validate(
        steps=steps, guards=guards, signature=demo_cluster.representative,
        method="hybrid", variables=[v.as_dict() for v in found],
        source=code.source, expected_guard="priority != High",
    )
    assert report.ok, [f.detail for f in report.blocking]


def test_an_invented_connector_is_rejected(demo_artifact, demo_cluster):
    """The activity log is the source of truth; the model cannot add systems."""
    code, steps, guards, found = demo_artifact
    invented = [*steps, {"id": "s11", "connector": "slack", "type": "send",
                         "outputs": [], "depends_on": []}]
    report = validate(
        steps=invented, guards=guards, signature=demo_cluster.representative,
        method="hybrid", variables=[], source=code.source,
    )
    assert not report.ok
    assert any(f.check == "connector_not_observed" for f in report.blocking)


def test_a_dropped_guard_is_rejected(demo_artifact, demo_cluster):
    code, steps, _guards, found = demo_artifact
    report = validate(
        steps=steps, guards={"irreversible": ["s10"]},
        signature=demo_cluster.representative, method="hybrid", variables=[],
        source=code.source, expected_guard="priority != High",
    )
    assert not report.ok
    assert any(f.check == "guard_weakened" for f in report.blocking)


def test_a_guard_naming_a_missing_step_is_rejected(demo_artifact, demo_cluster):
    """A hold that names no real step protects nothing."""
    code, steps, _g, _v = demo_artifact
    report = validate(
        steps=steps, guards={"irreversible": ["s99"], "requires_approval_if": "priority != High"},
        signature=demo_cluster.representative, method="hybrid", variables=[],
        source=code.source, expected_guard="priority != High",
    )
    assert any(f.check == "guard_orphaned" for f in report.blocking)


def test_a_broken_artifact_is_never_reported_ready(demo_cluster):
    report = validate(
        steps=[{"id": "s1", "connector": "browser", "type": "read"}],
        guards={}, signature=demo_cluster.representative, method="python",
        source="def broken(:\n", variables=[],
    )
    assert not report.ok
    assert any(f.check == "artifact_invalid" for f in report.findings)


# ── approval is a separate gate ──────────────────────────────────────────


async def test_a_dry_run_performs_no_side_effects(demo_cluster, demo_instances):
    """Generation and review must never touch a real system."""
    from app.models.execution import ExecutionMode
    from app.services.engine import engine

    found, constants = V.detect(demo_instances)
    steps = [
        {"id": f"s{i}", "connector": t.split(":")[0], "type": t.split(":")[1],
         "outputs": [], "depends_on": []}
        for i, t in enumerate(demo_cluster.representative, 1)
    ]
    payload = {c.name.rstrip("_0123456789"): c.value for c in constants}
    payload.update({v.name: v.samples[0] for v in found})

    result = await engine.run(
        steps=steps,
        guards={"irreversible": ["s10"], "requires_approval_if": "priority != High"},
        mode=ExecutionMode.REPLAY,
        source_payload=payload,
    )
    assert result.status == "ok"
    # Replay forces mock connectors inside the engine, so no connector can have
    # reached Jira however it was configured.
    assert result.side_effects == []


async def test_the_guard_holds_a_run_unlike_the_observed_ones(demo_cluster):
    """A Low-priority ticket is not what the five observed runs were."""
    from app.models.execution import ExecutionMode
    from app.services.engine import engine

    steps = [
        {"id": f"s{i}", "connector": t.split(":")[0], "type": t.split(":")[1],
         "outputs": [], "depends_on": []}
        for i, t in enumerate(demo_cluster.representative, 1)
    ]
    result = await engine.run(
        steps=steps,
        guards={"irreversible": ["s10"], "requires_approval_if": "priority != High"},
        mode=ExecutionMode.REPLAY,
        source_payload={"priority": "Low", "customer": "NEWCO", "issue": "Disk full"},
    )
    assert result.needs_approval is True
    assert result.status == "needs_approval"
    assert "s10" not in [r.step_id for r in result.step_results if r.status == "ok"]


def test_a_new_automation_starts_below_autonomy():
    """Nothing begins trusted; approval is a later, separate act."""
    from app.models.automation import TrustLevel

    assert TrustLevel.SUGGEST.rank < TrustLevel.AUTONOMOUS.rank
    assert TrustLevel.SUGGEST.next_level() is TrustLevel.SHADOW
