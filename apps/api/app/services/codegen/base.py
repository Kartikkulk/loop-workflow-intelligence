"""Shared types for the code generators.

One generator per execution method. Each takes a flow definition and returns a
file that can be written to disk and run, rather than a snippet for a person to
finish — a half-written script is a worse deliverable than an honest error,
because it looks finished.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class GeneratedCode:
    """A runnable artefact produced from a flow definition."""

    #: "python", "playwright" or "n8n".
    method: str
    #: Suggested file name, including extension.
    filename: str
    #: The file's full contents.
    source: str
    #: What has to exist before this will run. Shown next to the code.
    requirements: list[str]
    #: Honest limits — steps that could not be fully generated, and why.
    caveats: list[str]

    @property
    def line_count(self) -> int:
        return self.source.count("\n") + 1

    def as_dict(self) -> dict:
        return {
            "method": self.method,
            "filename": self.filename,
            "source": self.source,
            "requirements": list(self.requirements),
            "caveats": list(self.caveats),
            "line_count": self.line_count,
        }


_UNSAFE = re.compile(r"[^A-Za-z0-9_]+")


def identifier(text: str, fallback: str = "step") -> str:
    """A safe Python identifier built from arbitrary text.

    Step ids and connector names reach the generators from a partly
    model-generated flow definition, so they are untrusted and must never be
    interpolated into source unescaped.
    """
    cleaned = _UNSAFE.sub("_", str(text or "")).strip("_").lower()
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"{fallback}_{cleaned}" if cleaned else fallback
    return cleaned[:60]


def literal(text: object) -> str:
    """Render a value as a Python literal, safely."""
    return repr(text)
