#!/usr/bin/env python3
"""Create the daily code-change report task, and the log of it being done by hand.

The second repetitive workflow: every weekday each engineer reads what landed
in the repository overnight, writes it up as a dated report, and pastes the
summary onto their standup ticket. It is genuinely dull, genuinely daily, and
it touches three different systems — which is what makes it worth detecting.

The report files are built from this repository's real `git log`. The twelve
weeks of history are synthesised, because the repo does not have twelve weeks
of commits and pretending otherwise would put a number in the console that the
log cannot support.

    apps/api/scripts/make_standup.py --upload
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

#: The engineers on the rota. Four is above the threshold that makes a detected
#: workflow an organisational problem rather than one person's habit.
ENGINEERS = ["u_ishan", "u_naveen", "u_priyanka", "u_tejas"]

BRANCHES = ["main", "release/2026.09", "develop"]


def real_commits(repo: Path, limit: int = 40) -> list[str]:
    """Recent commits from the actual repository, for the report bodies."""
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "log", f"--max-count={limit}",
             "--pretty=format:%h\t%an\t%s"],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if done.returncode != 0:
        return []
    return [line for line in done.stdout.splitlines() if line.strip()]


def weekdays(count: int) -> list[datetime]:
    """The last `count` weekdays, oldest first."""
    days: list[datetime] = []
    cursor = datetime.now(UTC).replace(hour=9, minute=30, second=0, microsecond=0)
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


def write_report(path: Path, day: datetime, commits: list[str], branch: str) -> None:
    lines = [
        f"# Code changes — {day:%A %d %B %Y}",
        "",
        f"Branch: {branch}",
        f"Commits: {len(commits)}",
        "",
        "## What landed",
        "",
    ]
    if commits:
        for entry in commits:
            parts = entry.split("\t")
            if len(parts) >= 3:
                lines.append(f"- `{parts[0]}` **{parts[1]}** — {parts[2]}")
    else:
        lines.append("- No commits found in this window.")
    lines += [
        "",
        "---",
        "",
        "Written for the standup ticket. Generated from the repository log.",
        "",
    ]
    path.write_text("\n".join(lines))


def build(inbox: Path, repo: Path, days: int, rng: random.Random) -> list[dict]:
    """Write the report files and return the activity log of writing them."""
    inbox.mkdir(parents=True, exist_ok=True)
    pool = real_commits(repo)
    events: list[dict] = []

    for index, day in enumerate(weekdays(days)):
        who = ENGINEERS[index % len(ENGINEERS)]
        branch = BRANCHES[0] if rng.random() < 0.8 else rng.choice(BRANCHES[1:])
        # A slice of the real log, so no two reports read identically.
        start = rng.randint(0, max(0, len(pool) - 4))
        commits = pool[start : start + rng.randint(2, 6)] if pool else []

        filename = f"code-changes-{day:%Y-%m-%d}.md"
        write_report(inbox / filename, day, commits, branch)

        session_id = f"ses_{uuid.uuid4().hex[:12]}"
        cursor = day + timedelta(minutes=rng.randint(0, 25))
        steps = [
            ("git", "read", "commit_log", 48,
             {"repo": repo.name, "repo_path": str(repo), "branch": branch,
              "since": "1.day"}),
            ("files", "create", "daily_report", 72,
             {"filename": filename, "invoice_date": f"{day:%Y-%m-%d}",
              "folder": "Reports", "vendor": repo.name}),
            ("jira", "send", "standup_note", 41,
             {"ticket_id": f"ENG-{day:%Y%m%d}", "report_date": f"{day:%Y-%m-%d}",
              "commit_count": len(commits)}),
        ]

        for app, action, object_type, seconds, payload in steps:
            duration = int(seconds * rng.uniform(0.8, 1.3) * 1000)
            events.append(
                {
                    "id": f"evt_{uuid.uuid4().hex[:12]}",
                    "user_id": who,
                    "team": "engineering",
                    "timestamp": cursor.isoformat(),
                    "app": app,
                    "action": action,
                    "object_type": object_type,
                    "object_id": f"obj_{uuid.uuid4().hex[:12]}",
                    "duration_ms": duration,
                    "session_id": session_id,
                    "payload": payload,
                }
            )
            cursor += timedelta(milliseconds=duration + rng.randint(2000, 7000))

    return events


def upload(events: list[dict], api: str) -> None:
    api = api.replace("//localhost:", "//127.0.0.1:")
    body = "\n".join(json.dumps(event) for event in events).encode()
    boundary = f"----loop{uuid.uuid4().hex}"
    parts = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="standup-reports.jsonl"\r\n'
        "Content-Type: application/x-ndjson\r\n\r\n"
    ).encode() + body + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{api.rstrip('/')}/api/v1/ingest/upload?run_detection_after=true",
        data=parts,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            result = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(f"could not reach the Kriyā AI API at {api}: {exc}") from exc
    print(
        f"uploaded {result.get('events_ingested', 0)} events; "
        f"{result.get('clusters_detected', 0)} workflow(s) detected now",
        file=sys.stderr,
    )


def main() -> int:
    repo_default = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("~/Kriya-Invoices"))
    parser.add_argument("--repo", type=Path, default=repo_default)
    parser.add_argument("--days", type=int, default=60, help="Weekdays of history.")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    root = args.root.expanduser()
    inbox = root / "Reports" / "Inbox"
    repo = args.repo.expanduser().resolve()

    events = build(inbox, repo, args.days, random.Random(args.seed))
    print(f"wrote {len(list(inbox.glob('*.md')))} report files to {inbox}", file=sys.stderr)
    print(f"built {len(events)} activity events", file=sys.stderr)

    if args.out:
        args.out.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    if args.upload:
        upload(events, args.api)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
