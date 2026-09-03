#!/usr/bin/env python3
"""Run the discovered invoice automation over everything sitting in the inbox.

This is the last mile: the workflow Kriyā AI detected, executed for real, moving
real files on this machine and noting each one on its month's Jira ticket.

It defaults to a dry run and prints exactly what it would do. Nothing moves
until you pass --yes, and even then only inside LOOP_FILES_ROOT.

    # see the plan, change nothing
    apps/api/.venv/bin/python apps/api/scripts/file_invoices.py

    # actually file them
    apps/api/.venv/bin/python apps/api/scripts/file_invoices.py --yes
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))
# The configured database URL is relative to the api directory, so the script
# has to run from there whatever directory it was invoked from.
os.chdir(_HERE)

_INVOICE_NAME = re.compile(r"^AWS-(\d{4})(\d{2})-(\d{4})-(.+)\.pdf$")


def _trigger_for(pdf: Path) -> dict | None:
    """The payload an arriving invoice would carry, read from its own name."""
    match = _INVOICE_NAME.match(pdf.name)
    if match is None:
        return None
    year, month, account, alias = match.groups()
    return {
        "filename": f"Inbox/{pdf.name}",
        "invoice_date": f"{year}-{month}-03",
        "vendor": "Amazon Web Services",
        "invoice_no": f"AWS-{year}{month}-{account}",
        "account_alias": alias,
        "ticket_id": f"FIN-{year}{month}",
    }


async def _process(
    automation, engine, ExecutionMode, pdfs: list[Path]
) -> tuple[int, int, int, int]:
    """Run the automation over each invoice. Returns (filed, held, failed, skipped)."""
    filed = held = failed = skipped = 0
    for pdf in pdfs:
        payload = _trigger_for(pdf)
        if payload is None:
            skipped += 1
            continue
        result = await engine.run(
            steps=automation.steps,
            guards=automation.guards or {},
            rules=automation.rules or [],
            mode=ExecutionMode.LIVE,
            trigger_payload=payload,
            source_payload=payload,
        )
        if result.status == "needs_approval":
            held += 1
            print(f"  held    {pdf.name}  (over the policy limit — note not posted)", flush=True)
        elif result.status == "ok":
            filed += 1
            where = next(
                (
                    r.outputs.get("filed_path")
                    for r in result.step_results
                    if r.outputs.get("filed_path")
                ),
                None,
            )
            tail = Path(where).parent.name if where else "?"
            print(f"  filed   {pdf.name}  ->  {tail}", flush=True)
        else:
            failed += 1
            for step in result.step_results:
                if step.status != "ok":
                    print(f"  failed  {pdf.name}: {step.step_id} — {step.error}", flush=True)
                    break
    return filed, held, failed, skipped


async def _watch(automation, engine, ExecutionMode, inbox: Path, interval: float) -> int:
    """File invoices as they arrive, until interrupted.

    This is the shape the work actually has: nobody batches a year of invoices,
    they turn up one at a time. Watching makes the automation visible — drop a
    file in the folder and it is filed before you have switched windows.
    """
    print(
        f"watching {inbox} every {interval:g}s. Drop an invoice in. Ctrl-C to stop.",
        flush=True,
    )
    print()
    seen: set[str] = set()
    totals = [0, 0, 0]
    try:
        while True:
            arrivals = [p for p in sorted(inbox.glob("*.pdf")) if p.name not in seen]
            if arrivals:
                filed, held, failed, _ = await _process(
                    automation, engine, ExecutionMode, arrivals
                )
                totals[0] += filed
                totals[1] += held
                totals[2] += failed
                # A held invoice is still filed — the guard stops the note to
                # the ticket, not the move, because moving a file is
                # reversible. Anything left in the inbox therefore failed, and
                # is remembered so a permanent failure is not retried on every
                # tick until it fills the screen.
                for pdf in arrivals:
                    if pdf.exists():
                        seen.add(pdf.name)
            await asyncio.sleep(interval)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    print()
    print(f"filed {totals[0]} | held {totals[1]} | failed {totals[2]}")
    return 0


async def _run(automation_name: str, live: bool, watch: bool, interval: float) -> int:
    from sqlalchemy import select

    from app.config import settings
    from app.db.session import SessionLocal
    from app.models.automation import Automation
    from app.models.execution import ExecutionMode
    from app.services.engine import engine

    async with SessionLocal() as session:
        rows = (await session.execute(select(Automation))).scalars().all()
    matches = [a for a in rows if automation_name.lower() in a.name.lower()]
    if not matches:
        print(
            f"no automation matching {automation_name!r}. "
            "Run detection first, then generate one from the cluster.",
            file=sys.stderr,
        )
        return 1
    automation = matches[0]

    inbox = Path(settings.files_root).expanduser() / "Inbox"
    pdfs = sorted(inbox.glob("*.pdf"))
    print(f"automation : {automation.name} ({automation.trust_level})")
    print(f"root       : {Path(settings.files_root).expanduser()}")
    print(f"inbox      : {len(pdfs)} invoice(s)")
    print(f"mode       : {'LIVE — files will move' if live else 'dry run — nothing moves'}")
    print()
    if not pdfs and not watch:
        return 0

    if watch:
        return await _watch(automation, engine, ExecutionMode, inbox, interval)

    filed, held, failed, skipped = await _process(
        automation, engine, ExecutionMode, pdfs
    )
    print()
    print(f"filed {filed} | guard held {held} | failed {failed} | unrecognised {skipped}")
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--automation", default="Aws Invoice")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually move the files. Without this nothing on disk changes.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep running and file invoices as they arrive.",
    )
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between checks.")
    args = parser.parse_args()

    # Set before app.config is imported, so the settings object sees them.
    os.environ["LOOP_ENABLE_MOCK_CONNECTORS"] = "false"
    os.environ["LOOP_FILES_DRY_RUN"] = "false" if args.yes else "true"
    # Jira stays in dry run here regardless: filing a document is reversible,
    # writing to somebody's tracker is not. Turn it off deliberately in .env
    # once the credentials are set and you have watched a dry run.
    os.environ.setdefault("LOOP_JIRA_DRY_RUN", "true")

    return asyncio.run(
        _run(args.automation, live=args.yes, watch=args.watch, interval=args.interval)
    )


if __name__ == "__main__":
    raise SystemExit(main())
