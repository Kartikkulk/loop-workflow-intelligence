"""F1 — normalise any ingestion source into the canonical event stream.

Each adapter's only job is to produce `NormalisedEvent`s. Everything downstream
(sessionising, signatures, clustering, scoring) is source-agnostic, which is why
onboarding Outlook or Jira later touches this file and nothing else.
"""

from __future__ import annotations

import csv
import io
import json
import re
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
    # Verbs a UI collector emits for typing into a field or picking a value.
    # Without these the action stays as the raw word, which is outside the
    # canonical vocabulary and so cannot be compared across two recordings.
    "fill": "update",
    "set": "update",
    "enter": "update",
    "type": "update",
    "select": "update",
    "choose": "update",
    "submit": "create",
    "copy": "extract",
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


def canonical_key(name: str) -> str:
    """Reduce a column heading to a comparable key.

    `Record_ID`, `record id` and `RecordID` are the same column to a person and
    were three different columns to this module, which is why a hand-written
    export failed every row with "missing user_id" while visibly containing the
    data.
    """
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


#: What real exports call each canonical field, in preference order.
#:
#: The console promises that Kriyā AI "maps common column names for you", and this
#: table is that promise. It is ordered: an explicit `user_id` always beats a
#: `role`, so a file carrying both is read the precise way.
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "user_id": (
        "user_id", "userid", "employee_id", "employee", "user", "person",
        "performed_by", "actor", "agent", "owner", "who", "role",
    ),
    "team": ("team", "category", "department", "dept", "group", "function"),
    "timestamp": (
        "timestamp", "ts", "time", "datetime", "date", "occurred_at",
        "start_time", "when",
    ),
    "app": ("app", "application", "tool", "system", "software", "platform", "connector"),
    "action": ("action", "event", "activity", "task", "step", "operation"),
    "object_type": (
        "object_type", "object", "entity", "record_type", "document_type", "target",
    ),
    "object_id": (
        "object_id", "record_id", "reference", "ref", "case_id", "ticket_id",
        "document_id",
    ),
    "duration": (
        "duration", "duration_ms", "duration_seconds", "time_spent", "elapsed",
        "time_taken",
    ),
    "session_id": ("session_id", "run_id"),
    "workflow": ("workflow", "ground_truth_workflow", "process", "process_name"),
    "payload": ("payload",),
}

#: Every alias, for deciding which columns are already accounted for.
_CLAIMED_COLUMNS = frozenset(
    alias for aliases in _COLUMN_ALIASES.values() for alias in aliases
)

_DURATION = re.compile(
    r"([0-9]+(?:\.[0-9]+)?)\s*"
    r"(ms|millisecond|milliseconds|s|sec|secs|second|seconds"
    r"|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)?",
    re.I,
)

_DURATION_SCALE_MS = {
    "ms": 1, "millisecond": 1, "milliseconds": 1,
    "s": 1000, "sec": 1000, "secs": 1000, "second": 1000, "seconds": 1000,
    "m": 60_000, "min": 60_000, "mins": 60_000, "minute": 60_000, "minutes": 60_000,
    "h": 3_600_000, "hr": 3_600_000, "hrs": 3_600_000,
    "hour": 3_600_000, "hours": 3_600_000,
}


def parse_duration_ms(raw: object, *, bare_unit_ms: int = 1000) -> int:
    """Read a duration written the way people write them.

    A hand-kept log says "3 min" or "45s", not 180000. Refusing those cost the
    whole row, and a row rejected for its duration is a row whose *workflow*
    went undetected — so the parse is lenient and falls back to zero rather
    than raising. `bare_unit_ms` is what a unitless number means, which differs
    by column: `duration_ms` is milliseconds, a plain `duration` is seconds.
    """
    if raw in (None, ""):
        return 0
    if isinstance(raw, (int, float)):
        return int(float(raw) * bare_unit_ms)
    match = _DURATION.search(str(raw))
    if not match:
        return 0
    value = float(match.group(1))
    unit = (match.group(2) or "").lower()
    return int(value * (_DURATION_SCALE_MS[unit] if unit else bare_unit_ms))


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
    # Verbs a hand-kept log uses that a collector never emits. Without these a
    # row like "Review resume" produces the token `ats:review_resume:unknown` —
    # the verb and the object fused, which is exactly the opaque token that
    # stops two instances of the same work from clustering. Only mappings whose
    # canonical verb is unambiguous are listed; a word that could reasonably be
    # two different actions is better left to fall through than guessed at.
    "review": "read", "verify": "read", "validate": "read", "inspect": "read",
    "approve": "update", "reject": "update", "close": "update",
    "resolve": "update", "reconcile": "update", "confirm": "update",
    "record": "create", "log": "create", "upload": "create", "attach": "create",
    "schedule": "create", "generate": "create", "raise": "create",
    "forward": "send", "escalate": "send", "share": "send",
    "export": "extract", "fetch": "extract", "retrieve": "extract",
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


#: What a unitless number means, per column name. Anything else is seconds.
_BARE_DURATION_UNIT_MS = {"duration_ms": 1, "duration_seconds": 1000}


def _duration_ms(row: dict) -> int:
    """The step's duration in milliseconds, however the source wrote it."""
    for key in _COLUMN_ALIASES["duration"]:
        if row.get(key) not in (None, ""):
            return parse_duration_ms(
                row[key], bare_unit_ms=_BARE_DURATION_UNIT_MS.get(key, 1000)
            )
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
    return {
        k: v
        for k, v in row.items()
        if k not in _CLAIMED_COLUMNS and k not in ("id", "notes") and v not in (None, "")
    }


def _field(row: dict, canonical: str) -> object:
    """The value for a canonical field, trying each known column name in turn."""
    for alias in _COLUMN_ALIASES.get(canonical, (canonical,)):
        value = row.get(alias)
        if value not in (None, ""):
            return value
    return None


def normalise_row(
    row: dict, *, source: str = "upload", default_user_id: str | None = None
) -> NormalisedEvent:
    """Coerce one source row into a canonical event.

    Column headings are canonicalised first, so `Record_ID`, `record id` and
    `recordId` are one column rather than three, and a log exported from a
    spreadsheet reads the same as one posted by the collector.
    """
    row = {canonical_key(k): v for k, v in row.items() if k is not None}

    # `employee_id` is what the activity collector calls this; `role` is what a
    # hand-kept log usually has instead. Accepting the aliases here rather than
    # translating upstream is what lets the demo generator and a live collector
    # post byte-identical events.
    user_id = str(_field(row, "user_id") or default_user_id or "").strip()
    if not user_id:
        raise NormalisationError(
            "missing user_id: no column named user_id, employee, person or role"
        )

    app_raw = _field(row, "app") or ""
    action_raw = _field(row, "action") or ""
    # Normalised to the same shape `split_action` produces, so a log naming
    # its objects ("Support Dashboard") clusters with one that does not
    # ("support_dashboard"). Two spellings of one object type are two tokens,
    # and two tokens never cluster.
    object_type = canonical_key(str(_field(row, "object_type") or ""))
    if not object_type:
        # No explicit object: derive both halves from the compound action, so a
        # collector emitting whole gestures still produces a signature
        # detection can compare.
        derived_action, derived_object = split_action(str(action_raw))
        action_raw = derived_action
        object_type = derived_object or "unknown"

    object_id = _field(row, "object_id")
    session_id = _field(row, "session_id")
    workflow = _field(row, "workflow")
    return NormalisedEvent(
        user_id=user_id,
        team=str(_field(row, "team") or "unknown").strip(),
        timestamp=parse_timestamp(_field(row, "timestamp") or ""),
        app=canonical_app(str(app_raw)),
        action=canonical_action(str(action_raw)),
        object_type=object_type or "unknown",
        object_id=str(object_id) if object_id else None,
        duration_ms=_duration_ms(row),
        payload=_payload(row),
        session_id=str(session_id) if session_id else None,
        ground_truth_workflow=str(workflow) if workflow else None,
        source=source,
        notes=str(row["notes"]) if row.get("notes") else None,
    )


#: Attributed to activity recorded on one machine with nobody named in it.
#: A laptop collector has exactly one subject, so demanding a user column would
#: reject the most ordinary export there is. Applied per *file*, only when the
#: header names no person at all — never row by row, where a missing value
#: means a broken row rather than a single-subject log.
LOCAL_USER_ID = "u_local"


def _names_a_user(fieldnames: list[str] | None) -> bool:
    keys = {canonical_key(name) for name in (fieldnames or []) if name}
    return bool(keys & set(_COLUMN_ALIASES["user_id"]))


def normalise_csv(text: str, *, source: str = "upload") -> tuple[list[NormalisedEvent], list[str]]:
    """Normalise a CSV upload. Returns (events, per-row error messages)."""
    reader = csv.DictReader(io.StringIO(text))
    default_user = None if _names_a_user(reader.fieldnames) else LOCAL_USER_ID
    events: list[NormalisedEvent] = []
    errors: list[str] = []
    for index, row in enumerate(reader, start=2):
        if not any(str(v or "").strip() for v in row.values()):
            continue  # a blank line is formatting, not a broken row
        try:
            events.append(
                normalise_row(dict(row), source=source, default_user_id=default_user)
            )
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
            default_user = None if _names_a_user(list(row)) else LOCAL_USER_ID
            events.append(
                normalise_row(row, source=source, default_user_id=default_user)
            )
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
