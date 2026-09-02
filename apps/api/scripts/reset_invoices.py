#!/usr/bin/env python3
"""Put the AWS-invoice demo back to its starting state, in one step.

Clears everything downstream of the event log, rewrites the invoice PDFs into
the inbox, uploads the activity log, runs detection, and builds the automation
from whatever it found. What you are left with is the moment before the demo
starts: a pile of unfiled invoices and a workflow LOOP has just discovered.

    make invoices
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

_API = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_API))
os.chdir(_API)


async def _clear() -> None:
    from app.db.session import SessionLocal
    from app.services.demo_state import clear_all

    async with SessionLocal() as session:
        await clear_all(session)
        await session.commit()


def _flatten(root: Path) -> int:
    """Move any already-filed invoices back into the inbox.

    A demo that only works the first time is not a demo. Running this twice has
    to leave the same starting state as running it once.
    """
    inbox = root / "Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    moved = 0
    for pdf in root.rglob("*.pdf"):
        if pdf.parent == inbox:
            continue
        destination = inbox / pdf.name
        if destination.exists():
            pdf.unlink()
        else:
            shutil.move(str(pdf), str(destination))
        moved += 1
    # Deepest first, so `2025/10` is gone before `2025` is considered —-
    # otherwise the year folder is still non-empty when it is checked and an
    # empty shell survives into the next run.
    directories = sorted(
        (p for p in root.rglob("*") if p.is_dir() and p != inbox),
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for directory in directories:
        if not any(directory.iterdir()):
            directory.rmdir()
    return moved


def main() -> int:
    from app.config import settings

    root = Path(settings.files_root).expanduser()
    api = settings.api_base_url

    print("clearing detected workflows and automations…")
    asyncio.run(_clear())

    if root.exists():
        returned = _flatten(root)
        if returned:
            print(f"moved {returned} already-filed invoice(s) back to the inbox")

    print("writing invoices and uploading the activity log…")
    generate = subprocess.run(
        [
            sys.executable,
            str(_API / "scripts" / "make_invoices.py"),
            "--root", str(root),
            "--upload",
            "--api", api,
        ],
        check=False,
    )
    if generate.returncode != 0:
        print("could not build the invoices — is the API running?", file=sys.stderr)
        return 1

    print("generating the automation from what was detected…")
    build = subprocess.run(
        [sys.executable, str(_API / "scripts" / "build_invoice_automation.py")],
        check=False,
    )
    if build.returncode != 0:
        return 1

    print()
    inbox = root / "Inbox"
    print(f"Ready. {len(list(inbox.glob('*.pdf')))} invoices waiting in {inbox}")
    print("Run sheet: MANUAL_DEMO.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
