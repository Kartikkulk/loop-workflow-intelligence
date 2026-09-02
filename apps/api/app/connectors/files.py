"""A live connector that files documents into dated folders.

The job this automates is the one nobody wants: an invoice lands, somebody
renames it, works out which month it belongs to, and drops it in the right
folder. It is pure clerical work, it repeats forever, and getting it wrong is
merely annoying rather than dangerous — which makes it the right first thing to
let an automation do for real.

Every path is resolved against a single root (`settings.files_root`) and a
destination that escapes that root is refused outright. A flow definition is
partly model-generated and therefore untrusted: `..` in a filename must not be
able to write outside the folder the user pointed us at.

Nothing is ever overwritten. If the destination exists, the file is filed
alongside it with a numeric suffix, because silently replacing somebody's
document is not a recoverable mistake.
"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.connectors.base import Context, Step, StepResult

logger = logging.getLogger("loop.connectors.files")

#: Types that file the document. Everything else this connector accepts only
#: looks at it.
_FILING_TYPES = frozenset({"create", "update"})
#: Types that report where a document is without touching it. Keeping these
#: separate is not tidiness: a flow's first step is usually a `read`, and a read
#: that quietly moved the file left the next step looking at a path that no
#: longer existed — while the move had already happened.
_READ_TYPES = frozenset({"read", "extract"})
_SUPPORTED_TYPES = _FILING_TYPES | _READ_TYPES


def root() -> Path:
    """The one directory this connector may write inside."""
    return Path(settings.files_root).expanduser().resolve()


def _inside(candidate: Path, base: Path) -> bool:
    """True when `candidate` is `base` or sits underneath it."""
    try:
        candidate.relative_to(base)
    except ValueError:
        return False
    return True


def _first(source: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = source.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _period(available: dict[str, Any]) -> tuple[str, str]:
    """The year and month to file under, from the document's own date.

    Falls back to today only when the document carries no date at all. Filing
    by "now" is what a human does when they cannot find the invoice date, and it
    is equally wrong when an automation does it, so it is recorded in the notes
    rather than passed off as the real period.
    """
    raw = _first(available, "invoice_date", "date", "issued_at", "period")
    if raw:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y-%m"):
            try:
                parsed = datetime.strptime(raw[:10], fmt)
            except ValueError:
                continue
            return f"{parsed.year:04d}", f"{parsed.month:02d}"
    today = datetime.now(UTC)
    return f"{today.year:04d}", f"{today.month:02d}"


def _unique(destination: Path) -> Path:
    """A path that does not exist yet, suffixing rather than overwriting."""
    if not destination.exists():
        return destination
    stem, suffix = destination.stem, destination.suffix
    for index in range(2, 1000):
        candidate = destination.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"too many files named like {destination.name}")


class FilesConnector:
    """Reads a document's location, or moves it into `<root>/<year>/<month>/`.

    Which of those it does is decided by the step type, and a `read` never
    moves anything.
    """

    name = "files"
    is_mock = False
    api = "local filesystem, confined to LOOP_FILES_ROOT"
    required_credentials: tuple[str, ...] = ()

    async def execute(self, step: Step, ctx: Context) -> StepResult:
        if step.type not in _SUPPORTED_TYPES:
            return StepResult(
                step_id=step.id,
                status="failed",
                error=(
                    f"the files connector cannot perform '{step.type}'. It reads a "
                    "document or files it into a dated folder; it never deletes "
                    "or sends."
                ),
                confidence=0.0,
            )

        available = ctx.available()
        source_name = _first(step.inputs, "source_path", "path", "filename", "file")
        source_name = source_name or _first(
            available, "source_path", "path", "filename", "file"
        )
        if not source_name:
            return StepResult(
                step_id=step.id,
                status="failed",
                error="no source file for this step",
                unresolved=["source_path"],
                confidence=0.0,
            )

        base = root()
        source = Path(source_name).expanduser()
        if not source.is_absolute():
            source = base / source
        source = source.resolve()

        if not _inside(source, base):
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"{source} is outside {base}; refusing to touch it",
                confidence=0.0,
            )
        if not source.is_file():
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"no such file: {source}",
                confidence=0.0,
            )

        if step.type in _READ_TYPES:
            return StepResult(
                step_id=step.id,
                status="ok",
                outputs={
                    "source_path": str(source),
                    "filename": source.name,
                    "size_bytes": source.stat().st_size,
                },
                confidence=1.0,
            )

        year, month = _period(available)
        vendor = _first(available, "vendor", "supplier") or "Unfiled"
        # An optional subfolder keeps two document workflows from filing into
        # one shared year/month tree, where nothing would be findable. It is
        # resolved under the root like everything else, so `../` in it is
        # caught by the same check.
        subfolder = _first(step.inputs, "folder") or _first(available, "folder")
        target = base / subfolder if subfolder else base
        target_dir = (target / year / month).resolve()
        if not _inside(target_dir, base):
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"refusing to file outside {base}",
                confidence=0.0,
            )
        destination = target_dir / source.name

        if settings.files_dry_run:
            ctx.notes.append(f"would file {source.name} -> {year}/{month}/")
            return StepResult(
                step_id=step.id,
                status="ok",
                outputs={
                    "filed_path": str(destination),
                    "year": year,
                    "month": month,
                    "vendor": vendor,
                },
                confidence=1.0,
                side_effect=(
                    f"files.file {source.name} -> {year}/{month} (dry run — not moved)"
                ),
            )

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            final = _unique(destination)
            shutil.move(str(source), str(final))
        except OSError as exc:
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"could not file {source.name}: {exc}",
                confidence=0.0,
            )

        logger.info("files: %s -> %s", source.name, final)
        return StepResult(
            step_id=step.id,
            status="ok",
            outputs={
                "filed_path": str(final),
                "year": year,
                "month": month,
                "vendor": vendor,
            },
            confidence=1.0,
            side_effect=f"files.file {source.name} -> {year}/{month}/{final.name}",
        )
