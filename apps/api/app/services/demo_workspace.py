"""Seed a workspace of real invoice files, and the activity log of filing them.

The point of this module is that the demo automation is not a simulation. It
writes genuine PDFs to disk, and the automation built from the activity log
opens those same files, reads the totals out of them, and moves them into a
dated folder. Nothing is mocked and nothing needs a credential: the `files` and
`pdf` connectors are local, so this runs anywhere the application runs.

The workflow is deliberately three steps of purely local work. A step that
reached a SaaS system would need an account configured before the automation
could run, and an automation that cannot run is the wrong thing to put behind a
button labelled "Run".
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

#: Linked accounts, each billed separately. One invoice per account per month
#: is what turns a monthly chore into enough repetitions to detect.
ACCOUNTS = [
    ("4471-8829-0013", "prod-platform"),
    ("4471-8829-0027", "prod-data"),
    ("4471-8829-0041", "staging"),
    ("4471-8829-0058", "sandbox-dev"),
]

SERVICES = ["Amazon EC2", "Amazon S3", "Amazon RDS", "AWS Lambda", "Amazon EKS"]

#: The people observed doing it. More than three makes the detected workflow an
#: organisational opportunity rather than one person's habit.
FILERS = ["u_kartik", "u_meera", "u_sanjay"]

VENDOR = "Amazon Web Services"


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def write_pdf(path: Path, lines: list[str]) -> None:
    """Write a one-page PDF containing `lines`, with no dependencies.

    Written by hand rather than through a library: a one-page invoice is a
    small enough document that the dependency is not worth it, and it keeps
    this runnable on a clean install.
    """
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
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n".encode()
    out += b"%%EOF\n"
    path.write_bytes(bytes(out))


def _month_starts(count: int) -> list[datetime]:
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


def build(root: Path, months: int = 6, seed: int = 7) -> tuple[int, list[dict]]:
    """Write the invoice PDFs and return the activity log of them being filed.

    Returns (files written, activity events). The activity is what detection
    reads; the files are what the automation will actually move.
    """
    rng = random.Random(seed)
    inbox = root / "Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    written = 0
    events: list[dict] = []
    for period in _month_starts(months):
        issued = period.replace(day=3)
        for index, (account_id, alias) in enumerate(ACCOUNTS):
            who = FILERS[index % len(FILERS)]
            # Minor units. Production accounts run larger bills, and a realistic
            # minority land above the guard — which is the point: the automation
            # has to stop and ask on those rather than sail through every one.
            amount = (
                rng.randint(1_200_000, 6_400_000)
                if alias.startswith("prod") and rng.random() < 0.5
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
            written += 1

            # Three steps, all local: open it, read the total, file it away.
            session = f"ses_{uuid.uuid4().hex[:12]}"
            started = issued.replace(hour=9, minute=12) + timedelta(
                minutes=index * 7 + rng.randint(0, 4)
            )
            steps = [
                ("files", "read", "aws_invoice_pdf", 38,
                 {"filename": f"Inbox/{filename}", "vendor": VENDOR}),
                ("pdf", "extract", "invoice_total", 64,
                 {"vendor": VENDOR, "amount": amount,
                  "invoice_date": f"{issued:%Y-%m-%d}", "invoice_no": invoice_no}),
                ("files", "create", "filed_invoice", 47,
                 {"filename": f"Inbox/{filename}", "invoice_date": f"{issued:%Y-%m-%d}",
                  "vendor": VENDOR}),
            ]
            cursor = started
            for app_name, action, object_type, seconds, payload in steps:
                duration = int(seconds * rng.uniform(0.8, 1.3) * 1000)
                events.append(
                    {
                        "id": f"evt_{uuid.uuid4().hex[:12]}",
                        "user_id": who,
                        "team": "finance_ops",
                        "timestamp": cursor.isoformat(),
                        "app": app_name,
                        "action": action,
                        "object_type": object_type,
                        "duration_ms": duration,
                        "payload": payload,
                        "session_id": session,
                    }
                )
                cursor += timedelta(milliseconds=duration + rng.randint(2000, 9000))

    return written, events
