#!/usr/bin/env python3
"""Push a discovered automation into a running n8n as a real workflow.

The division of labour: LOOP works out what repeats and whether it has earned
the right to act. n8n has the connectors and the credential handling to carry
it out. This is the seam between them.

The workflow arrives in n8n **inactive and without credentials**, on purpose.
You open it, pick which Jira or Gmail account each node should use, and switch
it on. Nothing runs because a script pushed it.

    # look at what would be sent
    apps/api/.venv/bin/python apps/api/scripts/push_to_n8n.py --schedule hourly

    # send it
    apps/api/.venv/bin/python apps/api/scripts/push_to_n8n.py --schedule hourly --push
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_API = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_API))
os.chdir(_API)


def _ipv4(url: str) -> str:
    """Point `localhost` at 127.0.0.1 explicitly.

    uvicorn binds IPv4 only unless told otherwise, while `localhost` resolves to
    ::1 first on macOS. The result is a connection reset that reads like the
    server being down rather than a name resolving to the wrong family.
    """
    return url.replace("//localhost:", "//127.0.0.1:")


def _request(url: str, *, method: str = "GET", body: bytes | None = None,
             headers: dict[str, str] | None = None) -> dict:
    url = _ipv4(url)
    request = urllib.request.Request(
        url, data=body, method=method, headers=headers or {}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def main() -> int:
    from app.config import settings
    from app.services.n8n_export import SCHEDULES

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--automation", help="Match on part of the name. Default: the first one.")
    parser.add_argument("--schedule", default="manual", choices=sorted(SCHEDULES))
    parser.add_argument("--push", action="store_true", help="Actually create it in n8n.")
    parser.add_argument("--out", type=Path, help="Write the workflow JSON here.")
    args = parser.parse_args()

    loop_api = settings.api_base_url.rstrip("/")
    try:
        listing = _request(f"{loop_api}/api/v1/automations")
    except urllib.error.URLError as exc:
        print(f"could not reach LOOP at {loop_api}: {exc}", file=sys.stderr)
        return 1

    items = listing.get("items") or []
    if args.automation:
        items = [a for a in items if args.automation.lower() in a["name"].lower()]
    if not items:
        print("no matching automation. Run detection and generate one first.", file=sys.stderr)
        return 1
    automation = items[0]

    export = _request(
        f"{loop_api}/api/v1/automations/{automation['id']}/n8n?schedule={args.schedule}"
    )
    workflow = export["workflow"]

    print(f"automation : {automation['name']} ({automation['trust_level']})")
    print(f"schedule   : {args.schedule}")
    print(f"nodes      : {len(workflow['nodes'])}")
    for node in workflow["nodes"]:
        print(f"   {node['name']:<34} {node['type']}")
    if export["needs_credentials"]:
        print()
        print("These need an account chosen inside n8n before the workflow can run:")
        for name in export["needs_credentials"]:
            print(f"   - {name}")
    for note in export["notes"]:
        print(f"   note: {note}")

    if args.out:
        args.out.write_text(json.dumps(workflow, indent=2) + "\n")
        print(f"\nwrote {args.out}")

    if not args.push:
        print("\nDry run. Pass --push to create this in n8n.")
        return 0

    if not settings.n8n_api_key.strip():
        print(
            "\nLOOP_N8N_API_KEY is not set. In n8n: Settings > n8n API > create an "
            "API key, then put it in .env as LOOP_N8N_API_KEY.",
            file=sys.stderr,
        )
        return 1

    n8n = settings.n8n_base_url.rstrip("/")
    # n8n rejects unknown top-level keys, and `active` is read-only on create —
    # a workflow is switched on from its own page, not by whoever pushed it.
    payload = {
        "name": workflow["name"],
        "nodes": workflow["nodes"],
        "connections": workflow["connections"],
        "settings": workflow["settings"],
    }
    try:
        created = _request(
            f"{n8n}/api/v1/workflows",
            method="POST",
            body=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "X-N8N-API-KEY": settings.n8n_api_key.strip(),
            },
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        print(f"\nn8n returned {exc.code}: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(
            f"\ncould not reach n8n at {n8n}: {exc}. Is the container up "
            "(docker compose up n8n)?",
            file=sys.stderr,
        )
        return 1

    workflow_id = created.get("id")
    print(f"\ncreated in n8n: {workflow_id}")
    print(f"open it at {n8n}/workflow/{workflow_id}")
    print("It is inactive. Choose the accounts, then switch it on there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
