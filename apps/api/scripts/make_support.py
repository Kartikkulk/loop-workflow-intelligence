#!/usr/bin/env python3
"""Generate customer-support activity: emails turned into Jira tickets by hand.

Every event here uses the collector's own field names — `run_id`,
`employee_id`, `application`, `action`, `category`, `duration_seconds` — and
goes through the same normaliser a live laptop collector would post to. Nothing
is pre-digested for the detector: if the normaliser or the detection engine
could not handle a real collector's output, this generator would fail too.

Nothing here says "customer support email to Jira ticket". The runs are
activity; the name is something detection and the model arrive at afterwards.

    apps/api/scripts/make_support.py --upload
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

AGENTS = ["support-agent-01", "support-agent-02"]

#: Real support traffic, so the extracted category and priority vary.
COMPLAINTS = [
    ("Payment deducted but order still pending",
     "My payment was deducted from my account, but my order is still showing as "
     "pending. Please check.", "Payment", "High"),
    ("Cannot log in after password reset",
     "I reset my password yesterday and now the app rejects it every time.",
     "Account", "High"),
    ("Wrong item delivered",
     "I ordered the 500ml bottle and received the 250ml one instead.",
     "Delivery", "Medium"),
    ("Invoice missing GST number",
     "The invoice for order 88231 does not show our GST number. We need it "
     "reissued for accounting.", "Billing", "Medium"),
    ("App crashes when opening order history",
     "Every time I tap Order History the app closes immediately. Android 14.",
     "Bug", "High"),
    ("Refund not received after 10 days",
     "The refund was approved on the 12th and still has not reached my account.",
     "Payment", "High"),
    ("Change delivery address",
     "Could you change the delivery address for order 91002 to my office?",
     "Delivery", "Low"),
    ("Subscription renewed without notice",
     "My annual plan renewed and I was not warned beforehand. I would like it "
     "cancelled.", "Billing", "Medium"),
]

#: The base gesture sequence, in the collector's vocabulary. The variations
#: below add or swap steps, which is what the detector has to see through.
BASE = [
    ("Gmail", "open_email", 15),
    ("Gmail", "read_email", 30),
    ("Gmail", "copy_customer_information", 10),
    ("Jira", "open_create_issue", 15),
    ("Jira", "enter_customer_information", 20),
    ("Jira", "create_issue", 15),
]


def _run_steps(rng: random.Random) -> list[tuple[str, str, int]]:
    """One run's gestures, with the variation real work has."""
    steps = [list(step) for step in BASE]

    # Some agents live in Outlook. The same workflow, a different mail client.
    if rng.random() < 0.25:
        for step in steps:
            if step[0] == "Gmail":
                step[0] = "Outlook"

    # Triage detail gets filled in on some tickets and not others.
    extra = []
    if rng.random() < 0.45:
        extra.append(["Jira", "set_priority", 8])
    if rng.random() < 0.35:
        extra.append(["Jira", "set_category", 9])
    for step in extra:
        steps.insert(len(steps) - 1, step)

    # A minority get an acknowledgement sent straight back.
    if rng.random() < 0.3:
        steps.append(["Gmail" if steps[0][0] == "Gmail" else "Outlook",
                      "send_acknowledgement", 25])

    return [(str(a), str(b), int(c)) for a, b, c in steps]


def build(runs: int, rng: random.Random) -> list[dict]:
    events: list[dict] = []
    start = datetime.now(UTC) - timedelta(days=21)

    for index in range(runs):
        agent = AGENTS[index % len(AGENTS)]
        subject, body, category, priority = COMPLAINTS[index % len(COMPLAINTS)]
        run_id = f"support-{index + 1:03d}"
        # Spread across working days and mornings.
        moment = start + timedelta(
            days=index * 21 / max(1, runs), hours=rng.randint(0, 6), minutes=rng.randint(0, 55)
        )

        for application, action, seconds in _run_steps(rng):
            jitter = rng.uniform(0.7, 1.4)
            duration = round(seconds * jitter, 1)
            events.append(
                {
                    "run_id": run_id,
                    "employee_id": agent,
                    "timestamp": moment.isoformat(),
                    "application": application,
                    "action": action,
                    "category": "customer_support",
                    "duration_seconds": duration,
                    # Metadata only: what kind of request it was, never the
                    # customer's words. Body text stays out of the event log.
                    "payload": {
                        "subject": subject,
                        "request_category": category,
                        "priority": priority,
                        "project": "SAM1",
                    },
                }
            )
            moment += timedelta(seconds=duration + rng.randint(2, 9))

    return events


def upload(events: list[dict], api: str) -> dict:
    api = api.replace("//localhost:", "//127.0.0.1:")
    body = "\n".join(json.dumps(event) for event in events).encode()
    boundary = f"----loop{uuid.uuid4().hex}"
    parts = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="support-activity.jsonl"\r\n'
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
            return json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(f"could not reach the Kriyā AI API at {api}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=18)
    parser.add_argument("--seed", type=int, default=5)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    events = build(args.runs, random.Random(args.seed))
    print(f"built {args.runs} runs, {len(events)} events", file=sys.stderr)

    if args.out:
        args.out.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        print(f"wrote {args.out}", file=sys.stderr)
    if args.upload:
        result = upload(events, args.api)
        print(
            f"ingested {result.get('events_ingested', 0)} events; "
            f"{result.get('clusters_detected', 0)} workflow(s) detected",
            file=sys.stderr,
        )
        for warning in result.get("warnings") or []:
            print(f"  warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
