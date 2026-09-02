"""A live connector that reads invoice fields out of a real PDF.

Text extraction is done directly rather than through pdfplumber. A one-page
invoice is a shallow document: the text lives in content streams as `(...) Tj`
operators, and the only encoding likely to sit in front of it is Flate, which
the standard library already handles. Avoiding the dependency keeps the whole
pipeline runnable on a clean clone with nothing installed.

This reads. It never writes, and it is confined to `settings.files_root` for
the same reason the files connector is: the path reaching it comes partly from
a generated flow definition.
"""

from __future__ import annotations

import contextlib
import logging
import re
import zlib
from pathlib import Path
from typing import Any

from app.config import settings
from app.connectors.base import Context, Step, StepResult

logger = logging.getLogger("loop.connectors.pdf")

_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_SHOW_TEXT = re.compile(r"\((?:\\.|[^\\()])*\)\s*Tj", re.S)
_UNESCAPE = re.compile(r"\\([nrtbf()\\])")
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}

_AMOUNT = re.compile(
    r"(?:total\s+due|total|amount\s+due|grand\s+total)\D{0,20}?"
    r"([0-9][0-9,]*\.?[0-9]{0,2})",
    re.I,
)
_INVOICE_NO = re.compile(r"invoice\s*(?:number|no\.?|#)\s*[:\-]?\s*([A-Za-z0-9\-/]+)", re.I)
_DATE = re.compile(r"invoice\s*date\s*[:\-]?\s*(\d{4}-\d{2}-\d{2}|\d{2}[/-]\d{2}[/-]\d{4})", re.I)


def _decode_escapes(raw: str) -> str:
    return _UNESCAPE.sub(lambda m: _ESCAPES.get(m.group(1), m.group(1)), raw)


def extract_text(data: bytes) -> str:
    """Every `Tj` string in the document, in order, one per line."""
    lines: list[str] = []
    for match in _STREAM.finditer(data):
        chunk = match.group(1)
        if chunk[:1] == b"\x78":  # zlib header — a FlateDecode stream
            try:
                chunk = zlib.decompress(chunk)
            except zlib.error:
                continue
        try:
            text = chunk.decode("latin-1")
        except UnicodeDecodeError:
            continue
        for shown in _SHOW_TEXT.findall(text):
            inner = shown[shown.index("(") + 1 : shown.rindex(")")]
            lines.append(_decode_escapes(inner))
    return "\n".join(lines)


def parse_invoice(text: str) -> dict[str, Any]:
    """The fields a filing workflow needs, or nothing where they are absent."""
    found: dict[str, Any] = {}

    number = _INVOICE_NO.search(text)
    if number:
        found["invoice_no"] = number.group(1)

    date = _DATE.search(text)
    if date:
        raw = date.group(1)
        if "-" in raw and len(raw) == 10 and raw[4] == "-":
            found["invoice_date"] = raw
        else:
            parts = re.split(r"[/-]", raw)
            found["invoice_date"] = f"{parts[2]}-{parts[1]}-{parts[0]}"

    # Last match wins: a per-service line can look like a total, and the real
    # total is written after them.
    amounts = _AMOUNT.findall(text)
    if amounts:
        cleaned = amounts[-1].replace(",", "")
        # Money is carried in minor units everywhere else in LOOP, so the rupee
        # figure on the page is converted rather than stored as it reads.
        # Keeping it as a float would put a float in the ledger.
        with contextlib.suppress(ValueError):
            found["amount"] = int(round(float(cleaned) * 100))

    for line in text.splitlines():
        stripped = line.strip()
        if stripped and stripped.isupper() and len(stripped) > 8:
            found["vendor"] = stripped.title()
            break

    return found


class PdfConnector:
    """Reads invoice fields out of a PDF on disk."""

    name = "pdf"
    is_mock = False
    api = "local text extraction — no external service, no credentials"
    required_credentials: tuple[str, ...] = ()

    async def execute(self, step: Step, ctx: Context) -> StepResult:
        if step.type not in ("extract", "read"):
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"the pdf connector cannot perform '{step.type}'; it only reads",
                confidence=0.0,
            )

        available = ctx.available()
        name = None
        for source in (step.inputs, available):
            for key in ("source_path", "path", "filename", "file"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    name = value.strip()
                    break
            if name:
                break
        if not name:
            return StepResult(
                step_id=step.id,
                status="failed",
                error="no PDF path for this step",
                unresolved=["filename"],
                confidence=0.0,
            )

        base = Path(settings.files_root).expanduser().resolve()
        path = Path(name).expanduser()
        if not path.is_absolute():
            path = base / path
        path = path.resolve()
        try:
            path.relative_to(base)
        except ValueError:
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"{path} is outside {base}; refusing to read it",
                confidence=0.0,
            )
        if not path.is_file():
            return StepResult(
                step_id=step.id, status="failed", error=f"no such file: {path}", confidence=0.0
            )

        try:
            fields = parse_invoice(extract_text(path.read_bytes()))
        except OSError as exc:
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"could not read {path.name}: {exc}",
                confidence=0.0,
            )

        wanted = step.outputs or list(fields)
        outputs = {key: fields.get(key) for key in wanted}
        outputs.setdefault("filename", name)
        filled = sum(1 for key in wanted if outputs.get(key) not in (None, ""))
        confidence = filled / len(wanted) if wanted else 1.0

        missing = [key for key in wanted if outputs.get(key) in (None, "")]
        if missing:
            # Report what could not be found rather than passing a half-read
            # document downstream as though it were complete.
            ctx.notes.append(f"{path.name}: could not find {', '.join(missing)}")

        return StepResult(
            step_id=step.id,
            status="ok",
            outputs=outputs,
            confidence=max(0.15, confidence),
            unresolved=missing,
        )
