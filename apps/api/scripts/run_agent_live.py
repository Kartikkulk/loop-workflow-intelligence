"""Development-only: run Phase 3 Agent v1 against a real Ollama server.

Uses the default LLM client (no FakeLLM). Does not write Cluster/Discovery rows.

    .venv\\Scripts\\python.exe scripts\\run_agent_live.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.llm.client import llm
from app.schemas.atlas import ActivityAtlas
from app.services.agent import analyze_activity_atlas

FIXTURE = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "activity_atlas_generic.json"
)


def _print_result(analysis) -> None:
    real = analysis.generated_by == "llm" and analysis.status == "ok"
    print("=" * 72)
    if real:
        print("REAL LLM RESPONSE")
    else:
        print("FALLBACK / UNAVAILABLE RESPONSE")
    print("=" * 72)
    print(f"model being used:     {settings.llm_model}")
    print(f"Ollama endpoint:      {settings.ollama_base_url.rstrip('/')}/api/chat")
    print(f"provider:             {settings.llm_provider}")
    print(f"llm.available:        {llm.available}")
    print(f"llm.call_count:       {llm.call_count}")
    print(f"llm.fallback_count:   {llm.fallback_count}")
    print(f"Agent status:         {analysis.status}")
    print(f"generated_by:         {analysis.generated_by}")
    print(f"model_name (result):  {analysis.model_name}")
    print(f"proposed workflows:   {len(analysis.proposed_workflows)}")
    print(f"analysis_notes:       {analysis.analysis_notes}")
    print()
    for i, proposal in enumerate(analysis.proposed_workflows, start=1):
        print(f"--- proposal {i} ---")
        print(f"name:                 {proposal.name}")
        print(f"supporting signatures:{proposal.supporting_signature_ids}")
        print(f"supporting motifs:    {proposal.supporting_motif_ids}")
        print(f"core steps:           {[s.token for s in proposal.core_steps]}")
        print(f"optional steps:       {[s.token for s in proposal.optional_steps]}")
        print(f"confidence:           {proposal.confidence}")
        print(f"evidence:             {proposal.evidence.model_dump()}")
        print(f"evidence gaps:        {proposal.evidence_gaps}")
        print(f"dropped ungrounded:   {proposal.dropped_ungrounded_tokens}")
        print()
    print("full JSON:")
    print(json.dumps(analysis.model_dump(mode="json"), indent=2))


async def main() -> int:
    atlas = ActivityAtlas.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    print(f"fixture: {FIXTURE}")
    print("calling analyze_activity_atlas(atlas) with the default LLM client")
    print()
    analysis = await analyze_activity_atlas(atlas)
    _print_result(analysis)
    return 0 if analysis.generated_by == "llm" else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
