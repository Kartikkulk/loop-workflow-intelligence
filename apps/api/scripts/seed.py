"""CLI: rebuild the demo database from scratch.

    uv run python scripts/seed.py            # full reset
    uv run python scripts/seed.py --export   # also write CSV/JSONL fixtures
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402
from app.services.demo_state import rebuild_demo_state  # noqa: E402
from app.services.generator_seed import generate_events  # noqa: E402

_FIELDS = [
    "id", "user_id", "team", "timestamp", "app", "action", "object_type",
    "object_id", "duration_ms", "session_id", "workflow", "payload",
]


def export_fixtures(out_dir: Path) -> tuple[Path, Path]:
    """Write the seed log as CSV and JSONL, for demoing the upload path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    events = generate_events(seed=settings.seed, days=settings.seed_days)

    csv_path = out_dir / "northwind-activity-log.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FIELDS)
        writer.writeheader()
        for event in events:
            writer.writerow(
                {
                    "id": event.id,
                    "user_id": event.user_id,
                    "team": event.team,
                    "timestamp": event.timestamp.isoformat(),
                    "app": event.app,
                    "action": event.action,
                    "object_type": event.object_type,
                    "object_id": event.object_id or "",
                    "duration_ms": event.duration_ms,
                    "session_id": event.session_id or "",
                    "workflow": event.ground_truth_workflow or "",
                    "payload": json.dumps(event.payload),
                }
            )

    jsonl_path = out_dir / "northwind-activity-log.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(
                json.dumps(
                    {
                        "id": event.id,
                        "user_id": event.user_id,
                        "team": event.team,
                        "timestamp": event.timestamp.isoformat(),
                        "app": event.app,
                        "action": event.action,
                        "object_type": event.object_type,
                        "object_id": event.object_id,
                        "duration_ms": event.duration_ms,
                        "session_id": event.session_id,
                        "workflow": event.ground_truth_workflow,
                        "payload": event.payload,
                    }
                )
                + "\n"
            )
    return csv_path, jsonl_path


async def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the LOOP demo database.")
    parser.add_argument("--export", action="store_true", help="also write CSV/JSONL fixtures")
    parser.add_argument(
        "--out", default="fixtures", help="directory for exported fixtures (default: fixtures)"
    )
    args = parser.parse_args()

    await init_db()
    async with SessionLocal() as session:
        summary = await rebuild_demo_state(session)
        await session.commit()

    print(f"seeded: {summary}")

    if args.export:
        csv_path, jsonl_path = export_fixtures(Path(args.out))
        print(f"exported: {csv_path}")
        print(f"exported: {jsonl_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
