"""`.env.example` must stay short, and must stay honest.

Two failures are possible in a configuration example, and they pull in
opposite directions.

The first is lying. This file once claimed `LOOP_CLUSTER_THRESHOLD=0.82` long
after the code had moved to `0.35`, so anyone who uncommented the documented
value would have silently fragmented detection into hundreds of near-identical
clusters with no idea why. An example that lies is worse than none, because it
is believed.

The second is drowning. The obvious guard against the first — require every
setting to appear — grew the file to 222 lines of knobs, most of which were
weights chosen by measurement that nobody should touch. A new person opening
that has to decide what to fill in before they can start, and the answer
("nothing") is the one thing 222 lines fail to convey.

So the contract here is: whatever the file *does* claim must be true, and it
may only claim the handful of things a person would really change. The tuning
constants live in `config.py`, next to the reasoning that produced them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_EXAMPLE = REPO_ROOT / ".env.example"

#: Read by Next.js at build time, so legitimately here without being a
#: Python setting.
FRONTEND_KEYS = {"NEXT_PUBLIC_API_BASE", "NEXT_PUBLIC_API_MOCK"}

#: What a person plausibly changes on their own machine. These must be present
#: and correct; anything beyond them is a judgement call left to the author.
ESSENTIAL = {
    "LOOP_LLM_PROVIDER",
    "LOOP_LLM_MODEL",
    "LOOP_OLLAMA_BASE_URL",
    "LOOP_DATABASE_URL",
    "LOOP_API_BASE_URL",
    "LOOP_CONSOLE_URL",
    "LOOP_ENABLE_MOCK_CONNECTORS",
}

#: Chosen by measurement. Putting these in front of someone as a form to fill
#: in invites a guess where the code has an argued answer.
TUNING_ONLY = {
    "LOOP_CLUSTER_THRESHOLD",
    "LOOP_SEQUENCE_WEIGHT",
    "LOOP_SET_WEIGHT",
    "LOOP_SESSION_GAP_MINUTES",
    "LOOP_INTERRUPTION_COST_MINUTES",
    "LOOP_DO_NOT_AUTOMATE_THRESHOLD",
    "LOOP_SHADOW_PROMOTION_THRESHOLD",
    "LOOP_PATCH_AUTO_APPLY_CONFIDENCE",
}


def env_key(field_name: str) -> str:
    """The environment variable a Settings field reads from."""
    return f"LOOP_{field_name.upper()}"


def documented() -> dict[str, str]:
    """Every KEY=value pair in .env.example, ignoring comments."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    return {
        m.group(1): m.group(2).strip()
        for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=(.*)$", text, re.M)
    }


def values_agree(claimed: str, default: object) -> bool:
    if claimed == "" and (default == "" or default is None):
        return True
    if isinstance(default, bool):
        return claimed.lower() == str(default).lower()
    if isinstance(default, (int, float)):
        try:
            return float(claimed) == float(default)
        except ValueError:
            return False
    return claimed == str(default)


def test_env_example_exists():
    assert ENV_EXAMPLE.exists(), f"{ENV_EXAMPLE} is missing"


# ── it must not lie ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", sorted(documented()))
def test_documented_default_matches_the_code(key):
    """Every value claimed here has to be the value the code actually uses."""
    if key in FRONTEND_KEYS:
        return
    field = key.removeprefix("LOOP_").lower()
    assert field in Settings.model_fields, f"{key} is not a real setting"
    default = Settings.model_fields[field].default
    assert values_agree(documented()[key], default), (
        f"{key} says {documented()[key]!r} but the code default is {default!r}. "
        "Someone who uncomments the documented value would silently change behaviour."
    )


def test_no_orphan_keys():
    real = {env_key(name) for name in Settings.model_fields} | FRONTEND_KEYS
    orphans = set(documented()) - real
    assert not orphans, f"{sorted(orphans)} are documented but are not settings."


def test_the_essentials_are_present():
    missing = ESSENTIAL - set(documented())
    assert not missing, (
        f"{sorted(missing)} are things a person genuinely sets and must be here."
    )


# ── it must not drown the reader ────────────────────────────────────────────

def test_tuning_constants_stay_out():
    """Keep the measured values in config.py, beside the reasoning for them."""
    intruders = TUNING_ONLY & set(documented())
    assert not intruders, (
        f"{sorted(intruders)} were chosen by measurement and belong in "
        "apps/api/app/config.py next to their reasoning, not in a file that "
        "reads as a form to fill in."
    )


def test_it_stays_short():
    """A cap, because this file grew to 222 lines one well-meant comment at a time."""
    lines = len(ENV_EXAMPLE.read_text(encoding="utf-8").splitlines())
    assert lines <= 80, (
        f".env.example is {lines} lines. It is the first file a new person "
        "opens; if something needs more explanation than fits here, it belongs "
        "in the README or beside the code."
    )


# ── it must not carry a real secret ─────────────────────────────────────────

def test_no_real_secret_committed():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for pattern in (
        r"sk-ant-[A-Za-z0-9_-]{10,}",
        r"GOCSPX-[A-Za-z0-9_-]{10,}",
        r"xox[bp]-[0-9]{8,}",
    ):
        assert not re.search(pattern, text), f"a real credential matching {pattern} is here"

    # Every OAuth key is either absent or empty; none may carry a value.
    for key, value in documented().items():
        if key.endswith(("_CLIENT_ID", "_CLIENT_SECRET", "_API_KEY")):
            assert value == "", f"{key} must be left empty in the example"


def test_the_dangerous_default_is_flagged():
    """Someone skimming for a knob should hit the reason before the value."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    key = "LOOP_ENABLE_MOCK_CONNECTORS"
    preceding = text[: text.index(f"{key}=")][-700:]
    assert "⚠" in preceding, f"{key} should be preceded by a warning explaining the risk"


# ── the local database must never be committable ────────────────────────────

def test_gitignore_covers_the_local_database_and_its_sidecars():
    """A public repo plus a connectable account is a token leak waiting to happen.

    Once somebody connects an account, `loop.db` holds live OAuth access and
    refresh tokens for a real mailbox. SQLite also writes recent transactions
    to `-wal` and `-shm` sidecars, so ignoring `*.db` alone leaves the newest
    pages — the ones most likely to hold a token just issued — sitting beside
    it, untracked but perfectly visible to `git add -A`.
    """
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    patterns = {
        line.strip()
        for line in gitignore.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    for required in ("*.db", "*.db-wal", "*.db-shm", "*.db-journal", ".env"):
        assert required in patterns, f"{required} must be in .gitignore"
    assert "!.env.example" in patterns
