"""Capture live API responses as frontend fixtures.

The point is decoupling. With these committed, the frontend developer runs
`NEXT_PUBLIC_API_MOCK=1 npm run dev` and needs no Python, no database and no
running backend — which over a four-day deadline is the difference between two
people working and one person waiting.

Regenerate after any API change:  make fixtures
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

BASE = "http://localhost:8000"
OUT = Path(__file__).resolve().parents[2] / "web" / "lib" / "api" / "fixtures.json"

# Endpoints the console reads on load. Kept to GETs: a fixture set that captured
# mutations would be a recording of one session rather than a usable baseline.
ENDPOINTS = [
    "/health",
    "/api/v1/clusters",
    "/api/v1/automations",
    "/api/v1/exceptions",
    "/api/v1/patches",
    "/api/v1/analytics/roi",
    "/api/v1/system",
    "/api/v1/sources",
    "/api/v1/llm-usage",
]


async def main() -> int:
    captured: dict[str, object] = {}

    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        try:
            await client.get("/health")
        except httpx.HTTPError:
            print(f"cannot reach {BASE} — start it with `make api` first", file=sys.stderr)
            return 1

        for path in ENDPOINTS:
            response = await client.get(path)
            response.raise_for_status()
            captured[path] = response.json()

        # Detail routes need a real id, so they are discovered from the list
        # responses rather than hardcoded.
        clusters = captured["/api/v1/clusters"]
        assert isinstance(clusters, dict)
        pool = list(clusters.get("recommended", [])) + list(clusters.get("not_recommended", []))
        for cluster in pool[:3]:
            cluster_id = cluster["id"]
            for suffix in ("", "/sop"):
                path = f"/api/v1/clusters/{cluster_id}{suffix}"
                response = await client.get(path)
                if response.is_success:
                    captured[path] = response.json()

        automations = captured["/api/v1/automations"]
        assert isinstance(automations, dict)
        for automation in list(automations.get("items", []))[:3]:
            automation_id = automation["id"]
            for suffix in ("", "/shadow-runs"):
                path = f"/api/v1/automations/{automation_id}{suffix}"
                response = await client.get(path)
                if response.is_success:
                    captured[path] = response.json()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(captured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT.name}: {len(captured)} responses")
    for path in sorted(captured):
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
