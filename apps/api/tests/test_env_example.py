"""`.env.example` must stay honest about the real defaults.

This exists because it already went wrong once. The file claimed
`LOOP_CLUSTER_THRESHOLD=0.82` long after the code had moved to `0.35` — so a
developer who uncommented the documented value would have silently fragmented
detection into hundreds of near-identical clusters and had no idea why.

A configuration example that lies is worse than no example at all, because it
is believed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"

#: Frontend variables. Read by Next.js at build time, so they are legitimately
#: documented here without appearing in the Python Settings.
FRONTEND_KEYS = {"NEXT_PUBLIC_API_BASE", "NEXT_PUBLIC_API_MOCK"}


def env_key(field_name: str) -> str:
    """The environment variable a Settings field reads from."""
    if field_name == "anthropic_api_key":
        return "ANTHROPIC_API_KEY"
    return f"LOOP_{field_name.upper()}"


def documented() -> dict[str, str]:
    """Every KEY=value pair in .env.example, ignoring comments."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    pattern = re.finditer(r"^([A-Z][A-Z0-9_]*)=(.*)$", text, re.M)
    return {m.group(1): m.group(2).strip() for m in pattern}


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


@pytest.mark.parametrize("field_name", sorted(Settings.model_fields))
def test_every_setting_is_documented(field_name):
    key = env_key(field_name)
    assert key in documented(), (
        f"{key} is a real setting but is not in .env.example. "
        "Add it, with a comment saying what it does."
    )


@pytest.mark.parametrize("field_name", sorted(Settings.model_fields))
def test_documented_default_matches_the_code(field_name):
    key = env_key(field_name)
    claimed = documented()[key]
    default = Settings.model_fields[field_name].default
    assert values_agree(claimed, default), (
        f"{key} in .env.example says {claimed!r} but the code default is "
        f"{default!r}. A developer who uncomments the documented value would "
        "silently change behaviour."
    )


def test_no_orphan_keys():
    """Nothing documented that is not a real setting."""
    real = {env_key(name) for name in Settings.model_fields} | FRONTEND_KEYS
    orphans = set(documented()) - real
    assert not orphans, (
        f"{sorted(orphans)} are documented in .env.example but are not settings. "
        "Remove them, or add them to FRONTEND_KEYS if they are read by Next.js."
    )


def test_no_real_secret_committed():
    """The example must never carry an actual key."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert not re.search(
        r"sk-ant-[A-Za-z0-9_-]{10,}", text
    ), "a real Anthropic key is in .env.example"
    assert re.search(r"^ANTHROPIC_API_KEY=\s*$", text, re.M), "ANTHROPIC_API_KEY must be left empty"


def test_the_dangerous_defaults_are_flagged():
    """Values chosen by measurement carry a warning, not a bare number.

    Someone skimming for a knob to turn should hit the reason before the value.
    """
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for key in ("LOOP_CLUSTER_THRESHOLD", "LOOP_ENABLE_MOCK_CONNECTORS"):
        block = text[: text.index(f"{key}=")]
        preceding = block[-700:]
        assert "⚠" in preceding, f"{key} should be preceded by a warning explaining the risk"
