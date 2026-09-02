"""F1 — normalise any ingestion source into the canonical event stream.

Each adapter's only job is to produce `NormalisedEvent`s. Everything downstream
(sessionising, signatures, clustering, scoring) is source-agnostic, which is why
onboarding Outlook or Jira later touches this file and nothing else.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.llm.tools import ACTIONS, APPS
from app.services.ids import new_id

# Aliases from common real-world source vocabularies onto our canonical verbs.
_ACTION_ALIASES = {
    "open": "read",
    "opened": "read",
    "view": "read",
    "viewed": "read",
    "receive": "read",
    "received": "read",
    "write": "create",
    "add": "create",
    "append": "create",
    "insert": "create",
    "edit": "update",
    "modify": "update",
    "save": "update",
    "remove": "delete",
    "sent": "send",
    "email": "send",
    "reply": "send",
    "parse": "extract",
    "download": "extract",
    "query": "search",
    "filter": "search",
    "find": "search",
    "click": "navigate",
    "goto": "navigate",
    "visit": "navigate",
}

_APP_ALIASES = {
    "mail": "gmail",
    "gmail.com": "gmail",
    "google mail": "gmail",
    "ms outlook": "outlook",
    "outlook.com": "outlook",
    "exchange": "outlook",
    "excel": "sheets",
    "google sheets": "sheets",
    "spreadsheet": "sheets",
    "sap": "erp",
    "netsuite": "erp",
    "tally": "erp",
    "onedrive": "drive",
    "sharepoint": "drive",
    "google drive": "drive",
    "chrome": "browser",
    "edge": "browser",
    "acrobat": "pdf",
}


class NormalisationError(ValueError):
    """Raised when a source row cannot be coerced into a canonical event."""


@dataclass
class NormalisedEvent:
    """A canonical event, not yet persisted."""

    user_id: str
    timestamp: datetime
    app: str
    action: str
    object_type: str
    team: str = "unknown"
    object_id: str | None = None
    duration_ms: int = 0
    payload: dict = field(default_factory=dict)
    session_id: str | None = None
    ground_truth_workflow: str | None = None
    source: str = "upload"
    notes: str | None = None
    id: str = field(default_factory=lambda: new_id("evt"))

    @property
    def step_token(self) -> str:
        """Value-stripped token, matching Event.step_token.

        Present so a NormalisedEvent is structurally interchangeable with a
        persisted Event throughout detection, letting the tests exercise the
        real pipeline without a database.
        """
        return f"{self.app}:{self.action}:{self.object_type}"


def canonical_app(raw: str) -> str:
    """Map a source application label onto the canonical vocabulary."""
    key = (raw or "").strip().lower()
    if key in APPS:
        return key
    if key in _APP_ALIASES:
        return _APP_ALIASES[key]
    for alias, target in _APP_ALIASES.items():
        if alias in key:
            return target
    return key or "browser"


#: Trailing nouns that describe *how* a step was done rather than what it acted
#: on, so they are dropped from the object rather than becoming part of it.
_NOISE_WORDS = {"information", "info", "details", "data", "form", "field", "fields"}

#: Verbs recognised when splitting a compound action, mapped to the canonical
#: vocabulary.
#:
#: Deliberately not `_ACTION_ALIASES`: that table exists for rows whose whole
#: action is one word, and it maps nouns like "email" onto verbs. Reusing it
#: here turned `open_email` into "send", because the noun matched last and won.
_SPLIT_VERBS = {
    "open": "read", "view": "read", "read": "read", "receive": "read", "check": "read",
    "copy": "extract", "extract": "extract", "parse": "extract", "download": "extract",
    "create": "create", "add": "create", "write": "create", "insert": "create",
    "submit": "create", "file": "create",
    "enter": "update", "update": "update", "edit": "update", "set": "update",
    "assign": "update", "save": "update", "categorize": "update", "categorise": "update",
    "send": "send", "reply": "send", "notify": "send", "acknowledge": "send",
    "search": "search", "find": "search", "lookup": "search",
    "delete": "delete", "remove": "delete",
    "navigate": "navigate", "goto": "navigate",
}


def split_action(raw: str) -> tuple[str, str]:
    """Split a collector's compound action into a canonical verb and an object.

    Real collectors emit whole gestures — `copy_customer_information`,
    `open_create_issue` — because that is the grain a UI event arrives at.
    Detection needs the verb apart from the thing acted on, or every step
    becomes one opaque token and nothing clusters.

    `copy_customer_information` -> ("extract", "customer")
    `open_create_issue`         -> ("create", "issue")
    `set_priority`              -> ("update", "priority")
    """
    key = (raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not key:
        return "read", ""
    parts = [p for p in key.split("_") if p]

    positions = [i for i, part in enumerate(parts) if part in _SPLIT_VERBS]
    if not positions:
        return canonical_action(key), ""

    chosen = positions[0]
    verb = _SPLIT_VERBS[parts[chosen]]

    # A navigation verb stacked in front of another verb describes going to the
    # place where that thing is done, not doing it. `open_create_issue` is
    # opening the create-issue form; collapsing it to "create" made it
    # indistinguishable from the `create_issue` that actually submits, so the
    # workflow appeared to create the same ticket twice.
    if len(positions) > 1 and verb == "read":
        rest = [p for p in parts[chosen + 1 :] if p not in _NOISE_WORDS]
        return "navigate", "_".join(rest)

    after = [
        p for p in parts[chosen + 1 :] if p not in _NOISE_WORDS and p not in _SPLIT_VERBS
    ]
    before = [
        p for p in parts[:chosen] if p not in _NOISE_WORDS and p not in _SPLIT_VERBS
    ]
    return verb, "_".join(after or before)


def canonical_action(raw: str) -> str:
    """Map a source verb onto the canonical vocabulary."""
    key = (raw or "").strip().lower()
    if key in ACTIONS:
        return key
    if key in _ACTION_ALIASES:
        return _ACTION_ALIASES[key]
    return key or "read"


def as_utc(moment: datetime) -> datetime:
    """Read a stored timestamp as UTC.

    SQLite has no timezone type, so a datetime written as aware comes back
    naive — and comparing one of those against `datetime.now(UTC)` raises
    rather than returning a wrong answer. Anywhere a persisted timestamp meets
    the current time, it goes through here first.
    """
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def parse_timestamp(raw: str | datetime) -> datetime:
    """Parse a timestamp from any of the shapes real logs use. Always returns UTC."""
    if isinstance(raw, datetime):
        return as_utc(raw)
    text = str(raw).strip()
    if not text:
        raise NormalisationError("missing timestamp")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            raise NormalisationError(f"unparseable timestamp: {raw!r}") from None
    return as_utc(parsed)


def _duration_ms(row: dict) -> int:
    if row.get("duration_seconds") not in (None, ""):
        return int(float(row["duration_seconds"]) * 1000)
    for key in ("duration_ms", "durationMs", "duration"):
        if row.get(key) not in (None, ""):
            value = float(row[key])
            # A bare `duration` is assumed to be seconds.
            return int(value if key != "duration" else value * 1000)
    return 0


def _payload(row: dict) -> dict:
    raw = row.get("payload")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            loaded = json.loads(raw)
            return loaded if isinstance(loaded, dict) else {"value": loaded}
        except json.JSONDecodeError:
            return {"raw": raw}
    # Fall back to collecting any unrecognised columns — real exports always
    # carry extra fields, and drift detection needs them.
    known = {
        "id", "user_id", "userId", "team", "timestamp", "ts", "app", "application",
        "action", "event", "object_type", "objectType", "object_id", "objectId",
        "duration_ms", "durationMs", "duration", "payload", "session_id",
        "sessionId", "workflow", "ground_truth_workflow", "notes",
    }
    return {k: v for k, v in row.items() if k not in known and v not in (None, "")}


def normalise_row(row: dict, *, source: str = "upload") -> NormalisedEvent:
    """Coerce one source row into a canonical event."""
    # `employee_id` is what the activity collector calls this. Accepting the
    # alias here rather than translating upstream is what lets the demo
    # generator and a live collector post byte-identical events.
    user_id = str(
        row.get("user_id") or row.get("userId") or row.get("employee_id") or ""
    ).strip()
    if not user_id:
        raise NormalisationError("missing user_id")

    app_raw = row.get("app") or row.get("application") or ""
    action_raw = row.get("action") or row.get("event") or ""
    object_type = str(row.get("object_type") or row.get("objectType") or "").strip()
    if not object_type:
        # No explicit object: derive both halves from the compound action, so a
        # collector emitting whole gestures still produces a signature
        # detection can compare.
        derived_action, derived_object = split_action(str(action_raw))
        action_raw = derived_action
        object_type = derived_object or "unknown"

    return NormalisedEvent(
        user_id=user_id,
        team=str(row.get("team") or row.get("category") or "unknown").strip(),
        timestamp=parse_timestamp(row.get("timestamp") or row.get("ts") or ""),
        app=canonical_app(str(app_raw)),
        action=canonical_action(str(action_raw)),
        object_type=object_type or "unknown",
        object_id=(str(row["object_id"]) if row.get("object_id") else None)
        or (str(row["objectId"]) if row.get("objectId") else None),
        duration_ms=_duration_ms(row),
        payload=_payload(row),
        # `run_id` is the collector's name for one pass through a workflow,
        # which is exactly what a session is here.
        session_id=str(
            row.get("session_id") or row.get("sessionId") or row.get("run_id") or ""
        )
        or None,
        ground_truth_workflow=str(row.get("ground_truth_workflow") or row.get("workflow") or "")
        or None,
        source=source,
        notes=str(row["notes"]) if row.get("notes") else None,
    )


def normalise_csv(text: str, *, source: str = "upload") -> tuple[list[NormalisedEvent], list[str]]:
    """Normalise a CSV upload. Returns (events, per-row error messages)."""
    reader = csv.DictReader(io.StringIO(text))
    events: list[NormalisedEvent] = []
    errors: list[str] = []
    for index, row in enumerate(reader, start=2):
        try:
            events.append(normalise_row(dict(row), source=source))
        except (NormalisationError, ValueError) as exc:
            errors.append(f"line {index}: {exc}")
    return events, errors


def normalise_jsonl(
    text: str, *, source: str = "upload"
) -> tuple[list[NormalisedEvent], list[str]]:
    """Normalise a JSONL upload. Returns (events, per-row error messages)."""
    events: list[NormalisedEvent] = []
    errors: list[str] = []
    for index, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise NormalisationError("line is not a JSON object")
            events.append(normalise_row(row, source=source))
        except (NormalisationError, ValueError) as exc:
            errors.append(f"line {index}: {exc}")
    return events, errors


def normalise_upload(
    filename: str, text: str, *, source: str = "upload"
) -> tuple[list[NormalisedEvent], list[str]]:
    """Dispatch on file extension, sniffing the content when it is ambiguous."""
    lowered = filename.lower()
    if lowered.endswith((".jsonl", ".ndjson", ".json")):
        return normalise_jsonl(text, source=source)
    if lowered.endswith(".csv"):
        return normalise_csv(text, source=source)
    return (
        normalise_jsonl(text, source=source)
        if text.lstrip().startswith("{")
        else normalise_csv(text, source=source)
    )
