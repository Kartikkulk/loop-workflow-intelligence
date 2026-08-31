"""Translate raw browser-collector signals into canonical events.

The collector deliberately sends near-raw observations — a URL, a DOM role, an
event type — and this module does the interpretation server-side. That split
matters: the interpretation rules improve constantly, and pushing a new
heuristic to a server is a deploy while pushing one to an installed extension is
a release cycle across every laptop.

Nothing here needs the *content* of what the person did. A hostname, an
interaction type and a field name are enough to recover the shape of a workflow.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlparse

# Hostname → canonical app. Longest-suffix match wins, so a specific host beats
# a wildcard on the same domain.
_HOST_APP_MAP: dict[str, str] = {
    "mail.google.com": "gmail",
    "outlook.office.com": "outlook",
    "outlook.office365.com": "outlook",
    "outlook.live.com": "outlook",
    "docs.google.com": "docs",
    "sheets.google.com": "sheets",
    "drive.google.com": "drive",
    "calendar.google.com": "calendar",
    "app.slack.com": "slack",
    "teams.microsoft.com": "teams",
    "atlassian.net": "jira",
    "sharepoint.com": "drive",
    "onedrive.live.com": "drive",
    "salesforce.com": "crm",
    "force.com": "crm",
    "netsuite.com": "erp",
    "sap.com": "erp",
    "zoho.com": "erp",
    "quickbooks.intuit.com": "erp",
    "xero.com": "erp",
    "tally.com": "erp",
    "notion.so": "docs",
    "github.com": "code",
    "zendesk.com": "helpdesk",
    "freshdesk.com": "helpdesk",
    "hubspot.com": "crm",
}

# Google Sheets and Docs share a hostname; the path discriminates.
_PATH_APP_OVERRIDES: list[tuple[str, str, str]] = [
    ("docs.google.com", "/spreadsheets", "sheets"),
    ("docs.google.com", "/document", "docs"),
    ("docs.google.com", "/presentation", "slides"),
    ("docs.google.com", "/forms", "forms"),
]

# Interaction type → canonical action.
_INTERACTION_ACTIONS: dict[str, str] = {
    "pageview": "read",
    "route_change": "navigate",
    "click": "navigate",
    "submit": "create",
    "search": "search",
    "copy": "extract",
    "paste": "create",
    "download": "extract",
    "upload": "create",
    "field_edit": "update",
    "focus": "read",
}

# Button/link label → the action it most likely performs. Checked in order, so
# more specific verbs must come first.
_LABEL_ACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(send|reply|forward|submit for approval|post)\b", re.I), "send"),
    (re.compile(r"\b(delete|remove|discard|archive)\b", re.I), "delete"),
    (re.compile(r"\b(save|update|apply|confirm|approve|reject)\b", re.I), "update"),
    (re.compile(r"\b(create|add|new|insert|upload|import)\b", re.I), "create"),
    (re.compile(r"\b(search|find|filter|query|lookup)\b", re.I), "search"),
    (re.compile(r"\b(download|export|extract)\b", re.I), "extract"),
    (re.compile(r"\b(open|view|read|show|details)\b", re.I), "read"),
]

# URL path segment → object type. Singularised.
_OBJECT_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"invoice", re.I), "invoice"),
    (re.compile(r"purchase[-_]?order|\bpo\b", re.I), "purchase_order"),
    (re.compile(r"expense|claim|reimburse", re.I), "expense_claim"),
    (re.compile(r"vendor|supplier", re.I), "vendor_record"),
    (re.compile(r"customer|account|client", re.I), "customer_record"),
    (re.compile(r"ticket|issue|case|escalation", re.I), "ticket"),
    (re.compile(r"report|dashboard|analytic", re.I), "report"),
    (re.compile(r"spreadsheet|sheet", re.I), "spreadsheet"),
    (re.compile(r"payment|remittance", re.I), "payment"),
    (re.compile(r"ledger|journal|posting", re.I), "ledger_entry"),
    (re.compile(r"message|thread|conversation|mail", re.I), "email"),
    (re.compile(r"document|\bdoc\b|file", re.I), "document"),
    (re.compile(r"contract|agreement", re.I), "contract"),
]

_GENERIC_SUBDOMAINS = frozenset({"www", "app", "web", "my", "portal", "secure", "login"})

# Second-level labels that are part of a public suffix rather than a brand.
_SECOND_LEVEL_TLDS = frozenset({"co", "com", "net", "org", "gov", "edu", "ac", "or", "ne"})


@dataclass
class RawSignal:
    """One observation as reported by a collector."""

    interaction: str
    url: str = ""
    title: str = ""
    label: str = ""
    role: str = ""
    field_name: str = ""
    duration_ms: int = 0
    # Hash of transferred text, never the text. Correlating two hashes proves
    # data moved between two applications without capturing what moved.
    payload_digest: str = ""
    occurred_at: str = ""
    tab_id: str = ""


@dataclass
class Interpreted:
    app: str
    action: str
    object_type: str
    object_id: str | None
    payload: dict


def digest(text: str) -> str:
    """Stable short digest of transferred text.

    Used to match a copy in one application against a paste in another. The
    original text is never sent by the collector and cannot be recovered from
    this, which is what makes cross-application tracking privacy-preserving
    rather than merely privacy-adjacent.
    """
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def sanitise_url(url: str) -> str:
    """Strip values out of a URL, keeping only its structure.

    Applied server-side as well as in the collector. The collector is the right
    place to do this — a value stripped there never crosses the network — but an
    old or third-party collector cannot be trusted to have done it, and a GET
    form putting every field into the query string is entirely routine. Defence
    in depth on the one thing that would sink the product if it leaked.
    """
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"https://{url}")

    segments = []
    for segment in parsed.path.split("/"):
        decoded = unquote(segment)
        segments.append("_" if len(decoded) > 40 or re.search(r"[\s@]", decoded) else segment)
    path = "/".join(segments)

    query = ""
    if parsed.query:
        keys = [k for k, _ in parse_qsl(parsed.query, keep_blank_values=True)]
        query = "?" + "&".join(f"{k}=" for k in dict.fromkeys(keys)) if keys else ""

    fragment = ""
    if parsed.fragment:
        if "=" in parsed.fragment:
            keys = [k for k, _ in parse_qsl(parsed.fragment, keep_blank_values=True)]
            fragment = "#" + "&".join(f"{k}=" for k in dict.fromkeys(keys)) if keys else ""
        elif len(parsed.fragment) <= 120:
            fragment = f"#{parsed.fragment}"

    base = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
    return f"{base}{path}{query}{fragment}"


def canonical_app_for_host(url: str) -> str:
    """Map a URL onto a canonical application key.

    Unknown hosts fall back to their registrable-domain label rather than being
    lumped into a generic "browser" bucket. That is what lets an employee
    onboard a tool nobody anticipated simply by using it — the app registry is a
    table, so a new key is data, not a code change.
    """
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower()
    if not host:
        return "browser"

    for host_match, path_prefix, app in _PATH_APP_OVERRIDES:
        if host == host_match and parsed.path.startswith(path_prefix):
            return app

    if host in _HOST_APP_MAP:
        return _HOST_APP_MAP[host]
    # Longest matching suffix, so `x.atlassian.net` resolves via `atlassian.net`.
    best: tuple[int, str] | None = None
    for suffix, app in _HOST_APP_MAP.items():
        matches = host == suffix or host.endswith(f".{suffix}")
        if matches and (best is None or len(suffix) > best[0]):
            best = (len(suffix), app)
    if best is not None:
        return best[1]

    parts = [p for p in host.split(".") if p]
    if len(parts) < 2:
        return "browser"

    # Strip the public suffix, which may be two labels (`.co.in`, `.com.au`,
    # `.co.uk`). Getting this wrong names the app after the country code.
    two_label_suffix = len(parts) >= 3 and parts[-2] in _SECOND_LEVEL_TLDS
    parts = parts[:-2] if two_label_suffix else parts[:-1]

    # What remains is subdomains plus the brand; the brand is the last label.
    candidates = [p for p in parts if p not in _GENERIC_SUBDOMAINS] or parts
    if not candidates:
        return "browser"
    return re.sub(r"[^a-z0-9_-]", "", candidates[-1])[:40] or "browser"


def infer_action(signal: RawSignal) -> str:
    """Infer the canonical verb from the interaction and its label."""
    interaction = (signal.interaction or "").lower()

    # A labelled click is far more informative than the click itself.
    if interaction in ("click", "submit") and signal.label:
        for pattern, action in _LABEL_ACTIONS:
            if pattern.search(signal.label):
                return action
    if interaction == "click" and signal.role in ("searchbox", "search"):
        return "search"
    return _INTERACTION_ACTIONS.get(interaction, "read")


def infer_object_type(signal: RawSignal, app: str) -> str:
    """Infer what was acted upon, from the URL path and page title."""
    parsed = urlparse(signal.url if "://" in signal.url else f"https://{signal.url}")
    haystack = " ".join(
        part for part in (parsed.path, parsed.query or "", signal.title, signal.label) if part
    )
    for pattern, object_type in _OBJECT_HINTS:
        if pattern.search(haystack):
            return object_type

    if signal.field_name:
        return "form_field"
    # Fall back to the last non-identifier path segment, which is usually the
    # resource name in a REST-shaped URL.
    segments = [s for s in parsed.path.split("/") if s]
    for segment in reversed(segments):
        if not re.fullmatch(r"[0-9a-f-]{6,}|\d+", segment, re.I):
            cleaned = re.sub(r"[^a-z0-9_]", "_", segment.lower()).strip("_")
            if cleaned:
                return cleaned[:40].rstrip("s") or "page"
    return "page" if app != "browser" else "page"


def extract_object_id(url: str) -> str | None:
    """Pull a stable resource identifier out of a URL, if there is one.

    Used only to tell two instances of the same workflow apart. Never displayed.
    """
    parsed = urlparse(url if "://" in url else f"https://{url}")
    segments = [s for s in parsed.path.split("/") if s]
    for segment in reversed(segments):
        if re.fullmatch(r"\d{2,}|[0-9a-f]{8,}|[A-Z]{2,}-\d+", segment):
            return segment[:128]
    return None


def interpret(signal: RawSignal, *, allow_values: bool) -> Interpreted:
    """Turn one raw signal into a canonical event's fields."""
    signal.url = sanitise_url(signal.url)
    app = canonical_app_for_host(signal.url)
    action = infer_action(signal)
    object_type = infer_object_type(signal, app)

    payload: dict = {}
    if signal.field_name:
        # The field *name*, never its value. This is the whole privacy posture in
        # one line: knowing that `amount` was filled is enough to detect the
        # workflow; knowing it was 45,000 is not needed and is not collected.
        payload["field"] = signal.field_name[:64]
    if signal.label:
        payload["control"] = signal.label[:80]
    if signal.payload_digest:
        payload["transfer_digest"] = signal.payload_digest
    if allow_values and signal.title:
        payload["title"] = signal.title[:200]

    return Interpreted(
        app=app,
        action=action,
        object_type=object_type,
        object_id=extract_object_id(signal.url),
        payload=payload,
    )
