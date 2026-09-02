"""End-to-end API tests over an isolated in-memory database.

Walks the entire product arc in one test — detect, generate, replay, shadow,
promote, break, heal, learn — because that arc *is* the deliverable, and a
regression anywhere in it should fail the build.
"""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_session
from app.main import app


@pytest_asyncio.fixture
async def client():
    """An app instance backed by its own database, seeded once."""
    engine = create_async_engine("sqlite+aiosqlite:///./test_loop.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = override

    from app.services.demo_state import rebuild_demo_state

    async with maker() as session:
        await rebuild_demo_state(session)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
    await engine.dispose()
    import os

    if os.path.exists("./test_loop.db"):
        os.remove("./test_loop.db")


async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_clusters_split_recommended_from_not(client):
    response = await client.get("/api/v1/clusters")
    assert response.status_code == 200
    body = response.json()

    assert body["total"] > 0
    assert body["recommended"], "no automatable workflows detected"
    assert body["not_recommended"], "the do-not-automate list must not be empty"
    assert body["total_annual_hours"] > 0

    # Recommended clusters are ordered by priority.
    priorities = [c["priority"] for c in body["recommended"]]
    assert priorities == sorted(priorities, reverse=True)

    # Every do-not-automate cluster carries a specific reason.
    for cluster in body["not_recommended"]:
        assert cluster["do_not_automate"]
        assert cluster["automatability"] < 0.4
        assert len(cluster["reasoning"]) > 40

    # At least one organisational opportunity was found.
    assert any(c["is_organisational"] for c in body["recommended"])


async def test_cluster_investigation_uses_grounded_safe_fallback(
    client, monkeypatch
):
    from app.schemas.investigation import InvestigationResult
    from app.services import investigation_pipeline

    async def safe_investigation(atlas, analysis, *, client=None):
        assert atlas.signature_catalog
        assert analysis.proposed_workflows
        return [
            InvestigationResult(
                status="insufficient_evidence",
                generated_by="fallback",
                candidate_workflow_id=analysis.proposed_workflows[0].proposal_id,
                evidence_gaps=["LLM unavailable"],
                final_decision="insufficient_evidence",
            )
        ]

    monkeypatch.setattr(
        investigation_pipeline, "investigate_agent_analysis", safe_investigation
    )
    clusters = (await client.get("/api/v1/clusters")).json()
    cluster_id = clusters["recommended"][0]["id"]

    response = await client.post(f"/api/v1/clusters/{cluster_id}/investigate")

    assert response.status_code == 200
    body = response.json()
    assert body["cluster_id"] == cluster_id
    assert body["investigation"]["status"] == "insufficient_evidence"
    assert body["investigation"]["final_decision"] == "insufficient_evidence"
    assert body["automation_eligible"] is False
    serialized = str(body).lower()
    for forbidden in (
        "ground_truth_workflow",
        "email_body",
        "cell_value",
        "password",
        "clipboard",
        "raw_payload",
    ):
        assert forbidden not in serialized


async def test_cluster_detail_has_graph_users_and_variants(client):
    listing = (await client.get("/api/v1/clusters")).json()
    cluster_id = listing["recommended"][0]["id"]

    response = await client.get(f"/api/v1/clusters/{cluster_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["step_graph"]
    assert body["users"]
    assert body["variants"]
    assert sum(u["instance_count"] for u in body["users"]) == body["instance_count"]


async def test_missing_cluster_returns_404(client):
    assert (await client.get("/api/v1/clusters/clu_nope")).status_code == 404


async def test_sop_generation_and_download(client):
    listing = (await client.get("/api/v1/clusters")).json()
    cluster_id = listing["recommended"][0]["id"]

    response = await client.get(f"/api/v1/clusters/{cluster_id}/sop")
    assert response.status_code == 200
    markdown = response.json()["markdown"]
    for heading in ("## Purpose", "## Trigger", "## Procedure", "## Known Exceptions"):
        assert heading in markdown

    download = await client.get(f"/api/v1/clusters/{cluster_id}/sop.md")
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]


async def test_do_not_automate_cluster_refuses_generation(client):
    """The system's own recommendation must not be bypassable silently."""
    listing = (await client.get("/api/v1/clusters")).json()
    cluster_id = listing["not_recommended"][0]["id"]

    blocked = await client.post(f"/api/v1/clusters/{cluster_id}/generate-automation", json={})
    assert blocked.status_code == 409
    assert "DO NOT AUTOMATE" in str(blocked.json())

    allowed = await client.post(
        f"/api/v1/clusters/{cluster_id}/generate-automation",
        json={"override_do_not_automate": True},
    )
    assert allowed.status_code == 200


async def test_generated_flow_steps_declare_dependencies(client):
    """Self-healing depends entirely on depends_on existing."""
    automations = (await client.get("/api/v1/automations")).json()["items"]
    automation_id = automations[0]["id"]
    body = (await client.get(f"/api/v1/automations/{automation_id}")).json()

    assert body["steps"]
    assert any(step["depends_on"] for step in body["steps"]), "no step declares a dependency"
    for step in body["steps"]:
        assert step["outputs"], f"step {step['id']} produces nothing"
    # Irreversible steps must be declared in the guards.
    send_steps = {s["id"] for s in body["steps"] if s["type"] in ("send", "delete")}
    assert send_steps <= set(body["guards"]["irreversible"])


async def test_replay_reports_honest_accuracy_with_named_failures(client):
    automations = (await client.get("/api/v1/automations")).json()["items"]
    hero = max(automations, key=lambda a: a["annual_hours"])

    response = await client.post(
        f"/api/v1/automations/{hero['id']}/replay", json={"days": 90}
    )
    assert response.status_code == 200
    body = response.json()

    assert body["total"] > 0
    assert 0.5 < body["accuracy"] < 1.0, "accuracy is suspiciously perfect or broken"
    assert body["failures"], "a real backtest has failures"
    assert body["failure_modes"], "failures must be named, not hidden"
    for failure in body["failures"]:
        assert failure["reason"]
        assert failure["reason"] != "no field disagreement"


async def test_trust_ladder_promotes_then_auto_demotes(client):
    automations = (await client.get("/api/v1/automations")).json()["items"]
    hero = max(automations, key=lambda a: a["annual_hours"])
    automation_id = hero["id"]

    # Blocked before any shadow runs, with an explanation.
    before = (await client.get(f"/api/v1/automations/{automation_id}")).json()
    assert not before["trust"]["can_promote"]
    assert before["trust"]["blockers"]

    blocked = await client.post(f"/api/v1/automations/{automation_id}/promote", json={})
    assert blocked.json()["ok"] is False

    # Five clean runs unlock it.
    runs = await client.post(
        "/api/v1/demo/simulate-shadow-run",
        json={"automation_id": automation_id, "count": 5},
    )
    assert runs.status_code == 200
    assert runs.json()["trust"]["can_promote"]

    promoted = await client.post(f"/api/v1/automations/{automation_id}/promote", json={})
    assert promoted.json()["ok"] is True
    level_after = promoted.json()["level"]

    # A forced critical mismatch demotes it again, automatically.
    mismatch = await client.post(
        "/api/v1/demo/simulate-shadow-run",
        json={"automation_id": automation_id, "count": 1, "force_mismatch": True},
    )
    body = mismatch.json()
    assert body["runs"][0]["critical_mismatch"] is True
    assert body["level"] != level_after

    history = (await client.get(f"/api/v1/automations/{automation_id}")).json()["trust_history"]
    assert len(history) >= 3


async def test_shadow_runs_expose_per_field_agreement(client):
    automations = (await client.get("/api/v1/automations")).json()["items"]
    automation_id = max(automations, key=lambda a: a["annual_hours"])["id"]
    await client.post(
        "/api/v1/demo/simulate-shadow-run", json={"automation_id": automation_id, "count": 2}
    )
    body = (await client.get(f"/api/v1/automations/{automation_id}/shadow-runs")).json()
    assert body["total"] >= 2
    assert body["items"][0]["field_matches"]
    assert body["items"][0]["note"]


async def test_break_schema_triggers_a_patch(client):
    """The live-on-stage moment: a real rename, rediscovered from the data."""
    response = await client.post("/api/v1/demo/break-schema", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["events_updated"] > 0
    assert body["patches_proposed"] > 0

    patches = (await client.get("/api/v1/patches")).json()
    assert patches["total"] > 0
    drift = [p for p in patches["items"] if p["kind"] == "drift"]
    assert drift
    assert drift[0]["to_value"] == "Vendor Legal Name"
    assert drift[0]["confidence"] > 0.5
    assert drift[0]["rationale"]


async def test_exception_resolution_learns_a_rule(client):
    automations = (await client.get("/api/v1/automations")).json()["items"]
    automation_id = max(automations, key=lambda a: a["annual_hours"])["id"]

    await client.post(
        f"/api/v1/demo/seed-exceptions?automation_id={automation_id}&count=4"
    )
    queue = (await client.get("/api/v1/exceptions?status=open")).json()
    guard_cases = [e for e in queue["items"] if e["signature_key"] == "amount_over_10k"]
    assert len(guard_cases) >= 3

    for case in guard_cases:
        resolved = await client.post(
            f"/api/v1/exceptions/{case['id']}/resolve",
            json={"decision": "route_to_manager", "note": "over policy limit"},
        )
        assert resolved.status_code == 200

    patches = (await client.get("/api/v1/patches")).json()
    rules = [p for p in patches["items"] if p["kind"] == "rule"]
    assert rules, "no branch rule was proposed after repeated identical decisions"
    rule = rules[0]
    assert rule["evidence_count"] >= 3
    # A learned rule changes what the automation decides, so it never self-applies.
    assert rule["auto_applicable"] is False

    applied = await client.post(f"/api/v1/patches/{rule['id']}/apply")
    assert applied.status_code == 200
    detail = (await client.get(f"/api/v1/automations/{automation_id}")).json()
    assert detail["rules"], "accepted rule was not spliced into the flow"


async def test_describe_endpoint_creates_detectable_workflow(client):
    """The fallback input path: prose in, detected workflow out."""
    before = (await client.get("/api/v1/clusters")).json()["total"]
    response = await client.post(
        "/api/v1/ingest/describe",
        json={
            "description": (
                "Every Monday I open my email, download the vendor report attachment, "
                "filter for overdue rows, update the summary spreadsheet and email finance."
            ),
            "user_id": "u_test_describe",
            "weeks": 12,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["events_ingested"] > 0
    assert body["clusters_detected"] >= before


async def test_upload_rejects_a_file_with_no_valid_rows(client):
    files = {"file": ("bad.csv", b"nothing,useful\n1,2\n", "text/csv")}
    response = await client.post("/api/v1/ingest/upload", files=files)
    assert response.status_code == 400


async def test_roi_realised_never_exceeds_projected(client):
    body = (await client.get("/api/v1/analytics/roi")).json()
    assert body["projected_annual_hours"] > 0
    assert body["realised_annual_hours"] <= body["projected_annual_hours"]
    assert body["do_not_automate_clusters"] > 0
    assert sum(t["count"] for t in body["trust_distribution"]) == body["total_automations"]


async def test_system_status_lists_connectors(client):
    body = (await client.get("/api/v1/system")).json()
    assert body["mock_connectors"] is True
    names = {c["name"] for c in body["connectors"]}
    assert {"gmail", "sheets", "pdf", "erp", "browser"} <= names
    # Every live connector documents what it would need.
    for connector in body["connectors"]:
        assert connector["api"]


async def test_demo_reset_is_idempotent(client):
    first = (await client.post("/api/v1/demo/reset")).json()
    second = (await client.post("/api/v1/demo/reset")).json()
    assert first["message"] == second["message"], "reset is not deterministic"


async def test_forced_mismatch_is_always_a_real_critical_mismatch(client):
    """The demo's most dramatic control must not be a coin flip.

    Only ~8% of invoices produce a genuine critical mismatch, and a guard hold
    is not one — it is correct behaviour that scores as agreement. Both traps
    previously let this return `critical_mismatch: false` while claiming to have
    forced one.
    """
    automations = (await client.get("/api/v1/automations")).json()["items"]
    automation_id = max(automations, key=lambda a: a["annual_hours"])["id"]

    for _ in range(5):
        response = await client.post(
            "/api/v1/demo/simulate-shadow-run",
            json={"automation_id": automation_id, "count": 1, "force_mismatch": True},
        )
        assert response.status_code == 200
        run = response.json()["runs"][0]
        assert run["critical_mismatch"] is True
        assert run["score"] < 1.0
        assert run["note"]


async def test_unforced_shadow_runs_are_clean_agreements(client):
    """The other half of the same guarantee, so promotion is reliable on stage."""
    automations = (await client.get("/api/v1/automations")).json()["items"]
    automation_id = max(automations, key=lambda a: a["annual_hours"])["id"]

    response = await client.post(
        "/api/v1/demo/simulate-shadow-run",
        json={"automation_id": automation_id, "count": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert all(not run["critical_mismatch"] for run in body["runs"])
    assert body["trust"]["can_promote"]
