"""Export the OpenAPI schema to contracts/openapi.json.

This file is the contract between the backend and the frontend, and it is
committed. CI regenerates it and fails if the committed copy is stale, so a
backend change that alters the API surface cannot merge without the contract
change being visible in the same diff — which is what lets the frontend
developer see a breaking change in a review rather than at runtime.

    uv run python scripts/export_openapi.py          # write
    uv run python scripts/export_openapi.py --check  # fail if stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "openapi.json"


def render() -> str:
    """The schema as deterministic, diff-friendly JSON."""
    schema = app.openapi()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export or verify the OpenAPI contract.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the committed contract does not match the code.",
    )
    args = parser.parse_args()

    current = render()
    CONTRACT.parent.mkdir(parents=True, exist_ok=True)

    if args.check:
        if not CONTRACT.exists():
            print(f"contract missing: {CONTRACT}", file=sys.stderr)
            print("run: make contract", file=sys.stderr)
            return 1
        if CONTRACT.read_text(encoding="utf-8") != current:
            print(
                "The committed API contract is out of date.\n"
                "A change to the API surface must be committed alongside the code, so the\n"
                "frontend developer sees it in review rather than at runtime.\n\n"
                "  run: make contract   then commit contracts/openapi.json",
                file=sys.stderr,
            )
            return 1
        print(f"contract up to date ({len(json.loads(current)['paths'])} paths)")
        return 0

    CONTRACT.write_text(current, encoding="utf-8")
    schema = json.loads(current)
    print(f"wrote {CONTRACT.relative_to(CONTRACT.parents[1])}")
    print(f"  {len(schema['paths'])} paths, {len(schema['components']['schemas'])} models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
