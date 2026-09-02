"""Development demo: generic event → trigger → F5 REPLAY/MOCK execution.

Does not call Gmail, Sheets, OAuth, or live connectors.

    .venv\\Scripts\\python.exe scripts\\trigger_demo.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.llm.client import llm
from app.schemas.agent import (
    AgentAnalysis,
    CatalogEvidence,
    CoreStep,
    OptionalStep,
    ProposedWorkflow,
)
from app.schemas.atlas import ActivityAtlas
from app.services.promotion import persist_validated_proposal
from app.services.trigger import TriggerEvent, trigger_event
from app.services.validator import validate_agent_analysis

FIXTURE = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "activity_atlas_generic.json"
)

A = "app_a:read:item"
B = "app_b:update:item"
C = "app_c:send:item"
X = "app_x:search:item"


def _proposal() -> ProposedWorkflow:
    return ProposedWorkflow(
        proposal_id="proposal_demo",
        name="item to item",
        supporting_signature_ids=["sig_core", "sig_optional"],
        supporting_motif_ids=["motif_core"],
        core_steps=[
            CoreStep(token=A),
            CoreStep(token=B),
            CoreStep(token=C),
        ],
        optional_steps=[OptionalStep(token=X, frequency=0.33)],
        confidence=0.72,
        evidence=CatalogEvidence(
            supporting_instances=15,
            total_occurrences=15,
            distinct_users=2,
        ),
    )


async def main() -> int:
    # Force F4 heuristic path so the demo does not require Ollama.
    original = llm.structured

    async def _structured(*, prompt, tool, fallback, max_tokens=2048):
        return fallback()

    llm.structured = _structured  # type: ignore[method-assign]

    engine_ = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine_.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine_, expire_on_commit=False)

    try:
        async with maker() as session:
            atlas = ActivityAtlas.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
            validation = validate_agent_analysis(
                atlas,
                AgentAnalysis(
                    status="ok",
                    generated_by="llm",
                    proposed_workflows=[_proposal()],
                ),
            )
            persisted = await persist_validated_proposal(
                session, atlas, validation.validated[0]
            )
            await session.commit()

            trig = dict(persisted.automation.trigger or {})
            filt = dict(trig.get("filter") or {})
            event = TriggerEvent(
                source="app_a",
                event_type=str(trig.get("type") or "manual"),
                object_type=filt.get("object_type"),
                metadata={},
                payload={"title": "demo", "status_flag": "open"},
            )

            print("EVENT RECEIVED")
            print(f"  source={event.source}")
            print(f"  event_type={event.event_type}")
            print(f"  object_type={event.object_type}")
            print()

            result = await trigger_event(session, event)

            if not result.matched:
                print("NO AUTOMATION MATCHED")
                print(f"  reason={result.reason}")
                return 1

            print("AUTOMATION MATCHED")
            print(f"AUTOMATION ID:   {result.automation_id}")
            print(f"NAME:            {result.automation_name}")
            print(f"TRIGGER:         {result.trigger}")
            print(f"NUMBER OF STEPS: {result.step_count}")
            print(f"EXECUTION MODE:  {result.execution_mode}")
            print()
            print("REPLAY / MOCK EXECUTION")
            print("(No real Gmail/Sheets/API side effects.)")
            print()
            assert result.execution is not None
            print(f"FINAL STATUS:    {result.execution.status}")
            print("STEP RESULTS:")
            for step in result.execution.step_results:
                print(
                    f"  - {step.step_id}: status={step.status} "
                    f"confidence={step.confidence} error={step.error!r}"
                )
            return 0 if result.execution.status in {"ok", "needs_approval"} else 2
    finally:
        llm.structured = original  # type: ignore[method-assign]
        await engine_.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
