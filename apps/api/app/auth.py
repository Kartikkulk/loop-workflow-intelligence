"""Who is using Kriyā AI, and which database their work lives in.

Deliberately small. This is a shared-password sign-in for a demo deployment,
not an identity system: it establishes *which* of a known set of people is
looking at the console so each gets their own data, and it does not pretend to
be more than that. What it does buy is real isolation — one person's upload,
discoveries and automations are invisible to everyone else, which is the whole
point of handing the same URL to seven people.

The honest limits, so nobody mistakes this for security:

  * One password for everyone. Knowing it is enough to sign in as anybody in
    the list, so the separation is between *users*, not against an attacker.
  * The cookie is signed, so it cannot be edited to become another user, but it
    is not encrypted and it does not expire on the server.
  * Databases are per-user files on the instance's own disk. On a
    scale-to-zero host that disk is ephemeral, so data does not survive the
    instance going away.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re

from app.config import settings

#: The people this deployment is for, in the order the sign-in screen shows
#: them. The key is the identifier used for the database file and the event
#: `user_id`; the value is how the name is displayed.
USERS: dict[str, str] = {
    "vijay": "Vijay",
    "kavita": "Kavita Joshi",
    "anushree": "Anushree",
    "kartik": "Kartik Kulkarni",
    "anirudh": "Anirudh Zalki",
    "gouri": "Gouri Kulkarni",
    "pradyumna": "Pradyumna",
}

SESSION_COOKIE = "loop_session"

#: Only these characters can reach a filename, so a username can never walk out
#: of the data directory however this is called.
_SAFE_USERNAME = re.compile(r"^[a-z0-9_-]{1,32}$")


def display_name(username: str) -> str:
    return USERS.get(username, username)


def check_password(username: str, password: str) -> bool:
    """Whether these credentials sign in.

    `compare_digest` rather than `==`: string comparison returns as soon as it
    finds a difference, so its timing leaks how much of the password was right.
    """
    if username not in USERS:
        return False
    return hmac.compare_digest(password, settings.demo_password)


def _signature(username: str) -> str:
    digest = hmac.new(
        settings.session_secret.encode(), username.encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def issue_cookie(username: str) -> str:
    """A signed cookie value naming the signed-in user."""
    return f"{username}.{_signature(username)}"


def read_cookie(raw: str | None) -> str | None:
    """The username a cookie attests to, or None if it does not verify.

    Signed rather than stored, so no server-side session table is needed. The
    signature is what stops someone editing `vijay` to `kartik` in their own
    browser and reading somebody else's discoveries.
    """
    if not raw or "." not in raw:
        return None
    username, _, signature = raw.rpartition(".")
    if username not in USERS:
        return None
    if not hmac.compare_digest(signature, _signature(username)):
        return None
    return username


def database_url_for(username: str) -> str:
    """The database this user's work lives in.

    One file each. The alternative — one shared database filtered by a user
    column on every query — is a far larger change and fails open: a single
    query that forgets its filter silently shows one person another's work.
    A separate file cannot leak that way.
    """
    if not _SAFE_USERNAME.match(username):
        raise ValueError(f"unsafe username: {username!r}")
    root = settings.data_dir.rstrip("/")
    return f"sqlite+aiosqlite:///{root}/loop-{username}.db"


def resolve_user(request) -> str | None:
    """The signed-in user for a request, from either the header or the cookie.

    The bearer header comes first, and is what every deployment actually uses.
    A cookie shared between two different sites is a third-party cookie, and
    Safari discards those by default — `run.app` is on the Public Suffix List,
    so the console and the API are genuinely cross-site and the cookie never
    survived the redirect back. The token carries the same signed value, in a
    place no browser filters.

    The cookie is still honoured so that a same-origin deployment, and local
    development, keep working without JavaScript having to hold a token.
    """
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        username = read_cookie(header[7:].strip())
        if username:
            return username
    return read_cookie(request.cookies.get(SESSION_COOKIE))
