#!/usr/bin/env python3
"""Turn the detected invoice cluster into an automation.

Split out of the reset script so it can be re-run on its own after a
re-detection, which is what you want when you have changed the flow and only
need the automation rebuilt.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_API = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_API))
os.chdir(_API)


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def main() -> int:
    from app.config import settings

    base = settings.api_base_url.rstrip("/")
    try:
        clusters = _get(f"{base}/api/v1/clusters")
    except urllib.error.URLError as exc:
        print(f"could not reach the API at {base}: {exc}", file=sys.stderr)
        return 1

    recommended = clusters.get("recommended") or []
    if not recommended:
        print("nothing was detected, so there is nothing to build.", file=sys.stderr)
        return 1

    cluster = recommended[0]
    request = urllib.request.Request(
        f"{base}/api/v1/clusters/{cluster['id']}/generate-automation", method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            automation = json.load(response)
    except urllib.error.URLError as exc:
        print(f"could not generate the automation: {exc}", file=sys.stderr)
        return 1

    print(f"  built: {automation['name']} ({automation['trust_level']})")
    for step in automation["steps"]:
        print(f"    {step['id']}  {step['connector']}:{step['type']}")
    guards = automation.get("guards") or {}
    if guards.get("requires_approval_if"):
        print(f"    guard: hold when {guards['requires_approval_if']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
