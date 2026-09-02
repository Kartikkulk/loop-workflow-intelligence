#!/usr/bin/env python3
"""Create a year of dummy AWS invoices, and the activity log of filing them.

Two outputs, and they describe the same work:

  * Real PDF files in `<root>/Inbox`, one per linked AWS account per month for
    the last twelve months. These are genuine files — the automation moves
    these, not a fixture.
  * A LOOP activity log of three people filing them by hand, month after month.
    Detection reads this and has to find the workflow on its own.

The PDFs are written directly rather than through a library: a one-page invoice
is a small enough document that a dependency is not worth the download, and it
keeps the generator runnable on a clean clone.

    python3 apps/api/scripts/make_invoices.py --upload
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

#: The linked AWS accounts that get billed separately. Each one produces its
#: own invoice every month, which is what turns "a monthly chore" into enough
#: repetitions for detection to have something to cluster.
ACCOUNTS = [
    ("4471-8829-0013", "prod-platform"),
    ("4471-8829-0027", "prod-data"),
    ("4471-8829-0041", "staging"),
    ("4471-8829-0058", "sandbox-dev"),
    ("4471-8829-0066", "analytics"),
    ("4471-8829-0074", "ml-training"),
    ("4471-8829-0082", "backup-dr"),
    ("4471-8829-0099", "security-tooling"),
]

SERVICES = [
    "Amazon EC2", "Amazon S3", "Amazon RDS", "AWS Lambda",
    "Amazon CloudFront", "Amazon EKS", "AWS KMS", "Amazon SageMaker",
]

#: The people who do the filing. More than three makes the detected workflow an
#: organisational problem rather than one person's habit.
FILERS = ["u_kartik", "u_meera", "u_sanjay"]

#: The Jira issue each invoice gets noted on. This has to be a key that really
#: exists, because the generated automation posts a comment to it: a made-up
#: key like FIN-202609 imports fine, passes review, and then fails on the first
#: real run with a 404 that looks like a connector bug.
DEFAULT_TICKET = "SAM1-6"


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def write_pdf(path: Path, lines: list[str]) -> None:
    """Write a single-page PDF containing `lines`, with no dependencies."""
    content = ["BT", "/F1 11 Tf", "56 760 Td", "14 TL"]
    for line in lines:
        content.append(f"({_escape(line)}) Tj")
        content.append("T*")
    content.append("ET")
    stream = "\n".join(content).encode("latin-1", "replace")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n".encode()
    )
    out += b"%%EOF\n"
    path.write_bytes(bytes(out))


def month_starts(count: int) -> list[datetime]:
    """The first of each of the last `count` months, oldest first."""
    today = datetime.now(UTC)
    cursor = datetime(today.year, today.month, 1, tzinfo=UTC)
    months = []
    for _ in range(count):
        months.append(cursor)
        cursor = datetime(
            cursor.year - 1 if cursor.month == 1 else cursor.year,
            12 if cursor.month == 1 else cursor.month - 1,
            1,
            tzinfo=UTC,
        )
    return list(reversed(months))


def build(
    inbox: Path, months: int, rng: random.Random, ticket: str = DEFAULT_TICKET
) -> list[dict]:
    """Write the PDFs and return the activity log of them being filed."""
    inbox.mkdir(parents=True, exist_ok=True)
    events: list[dict] = []

    for period in month_starts(months):
        # AWS bills on the 3rd; the team works through them that morning.
        issued = period.replace(day=3)
        for index, (account_id, alias) in enumerate(ACCOUNTS):
            who = FILERS[index % len(FILERS)]
            # Minor units. Production accounts run far larger bills than
            # sandboxes, and a realistic minority land above the 10,000-rupee
            # guard — which is the point: the automation has to stop and ask on
            # those rather than sail through every invoice identically.
            amount = (
                rng.randint(1_200_000, 6_400_000)
                if alias.startswith("prod") and rng.random() < 0.55
                else rng.randint(18_000, 940_000)
            )
            invoice_no = f"AWS-{period:%Y%m}-{account_id[-4:]}"
            filename = f"{invoice_no}-{alias}.pdf"

            write_pdf(
                inbox / filename,
                [
                    "AMAZON WEB SERVICES EMEA SARL",
                    "",
                    f"Invoice number   {invoice_no}",
                    f"Invoice date     {issued:%Y-%m-%d}",
                    f"Account          {account_id}  ({alias})",
                    f"Billing period   {period:%B %Y}",
                    "",
                    "Charges by service",
                ]
                + [
                    f"  {service:<22} INR {rng.randint(500, 120_000) / 100:>12,.2f}"
                    for service in rng.sample(SERVICES, 4)
                ]
                + [
                    "",
                    f"TOTAL DUE        INR {amount / 100:,.2f}",
                    "",
                    "This is a generated test document. It is not a real invoice.",
                ],
            )

            # The work: open it, read the total, file it under year/month,
            # then note it on the running Jira ticket for that month.
            session_id = f"ses_{uuid.uuid4().hex[:12]}"
            started = issued.replace(hour=9, minute=12) + timedelta(
                minutes=index * 7 + rng.randint(0, 4)
            )
            steps = [
                # The invoice arrives as a file in the inbox folder, not as an
                # email. Recording a Gmail step here would put one in the
                # detected workflow, and the automation would then fail on a
                # mailbox that was never part of this setup.
                ("files", "read", "aws_invoice_pdf", 38,
                 {"filename": filename, "vendor": "Amazon Web Services"}),
                ("pdf", "extract", "invoice_total", 64,
                 {"vendor": "Amazon Web Services", "amount": amount,
                  "invoice_date": f"{issued:%Y-%m-%d}", "invoice_no": invoice_no}),
                ("files", "create", "filed_invoice", 47,
                 {"filename": filename, "invoice_date": f"{issued:%Y-%m-%d}",
                  "vendor": "Amazon Web Services"}),
                # A note appended to that month's billing ticket, not an edit
                # of its fields. It is also the one step here that reaches
                # outside this machine, so it should land in the guards as
                # irreversible — which `send` does and `update` does not.
                ("jira", "send", "billing_note", 55,
                 {"ticket_id": ticket, "invoice_no": invoice_no,
                  "amount": amount}),
            ]

            cursor = started
            for app, action, object_type, seconds, payload in steps:
                jitter = rng.uniform(0.75, 1.35)
                duration = int(seconds * jitter * 1000)
                events.append(
                    {
                        "id": f"evt_{uuid.uuid4().hex[:12]}",
                        "user_id": who,
                        "team": "finance_ops",
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
                cursor += timedelta(milliseconds=duration + rng.randint(1500, 6000))

    return events


def drop_one(inbox: Path, rng: random.Random) -> Path:
    """Write one invoice dated today, for triggering the watcher live.

    Deliberately random rather than seeded: pressing this twice during a demo
    should produce two different invoices, and one of them being over the
    policy limit is what makes the guard visible rather than theoretical.
    """
    inbox.mkdir(parents=True, exist_ok=True)
    issued = datetime.now(UTC)
    account_id, alias = rng.choice(ACCOUNTS)
    amount = (
        rng.randint(1_200_000, 6_400_000)
        if rng.random() < 0.4
        else rng.randint(18_000, 940_000)
    )
    invoice_no = f"AWS-{issued:%Y%m}-{account_id[-4:]}"
    # Suffixed so a second drop in the same month does not overwrite the first.
    stem = f"{invoice_no}-{alias}"
    path = inbox / f"{stem}.pdf"
    counter = 2
    while path.exists():
        path = inbox / f"{stem}-{counter}.pdf"
        counter += 1

    write_pdf(
        path,
        [
            "AMAZON WEB SERVICES EMEA SARL",
            "",
            f"Invoice number   {invoice_no}",
            f"Invoice date     {issued:%Y-%m-%d}",
            f"Account          {account_id}  ({alias})",
            f"Billing period   {issued:%B %Y}",
            "",
            "Charges by service",
        ]
        + [
            f"  {service:<22} INR {rng.randint(500, 120_000) / 100:>12,.2f}"
            for service in rng.sample(SERVICES, 4)
        ]
        + [
            "",
            f"TOTAL DUE        INR {amount / 100:,.2f}",
            "",
            "This is a generated test document. It is not a real invoice.",
        ],
    )
    return path


def upload(events: list[dict], api: str) -> None:
    body = "\n".join(json.dumps(event) for event in events).encode()
    boundary = f"----loop{uuid.uuid4().hex}"
    parts = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="aws-invoice-filing.jsonl"\r\n'
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
        raise SystemExit(f"could not reach the LOOP API at {api}: {exc}") from exc
    print(
        f"uploaded {result.get('events_ingested', 0)} events; "
        f"{result.get('clusters_detected', 0)} workflow(s) detected",
        file=sys.stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("~/LOOP-Invoices"),
        help="Where the invoices live. Must match LOOP_FILES_ROOT.",
    )
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--ticket",
        default=DEFAULT_TICKET,
        help="A Jira issue key that really exists; the automation comments on it.",
    )
    parser.add_argument(
        "--one",
        action="store_true",
        help="Drop a single new invoice dated today, and write no activity log. "
        "Use this on stage: the watcher picks it up while people are looking.",
    )
    parser.add_argument("--out", type=Path, help="Also write the activity log here.")
    parser.add_argument("--upload", action="store_true", help="Send it to the LOOP API.")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    root = args.root.expanduser()
    inbox = root / "Inbox"

    if args.one:
        path = drop_one(inbox, random.Random())
        print(f"dropped {path.name} into {inbox}", file=sys.stderr)
        return 0

    events = build(inbox, args.months, random.Random(args.seed), args.ticket)

    written = len(list(inbox.glob("*.pdf")))
    print(f"wrote {written} invoice PDFs to {inbox}", file=sys.stderr)
    print(f"built {len(events)} activity events", file=sys.stderr)

    if args.out:
        args.out.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        print(f"wrote {args.out}", file=sys.stderr)
    if args.upload:
        upload(events, args.api)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
