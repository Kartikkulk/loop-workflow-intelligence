"""Code generation, one generator per execution method.

The execution planner decides *which* runtime should run an automation; this
package produces the artefact that runtime needs. Keeping the two apart means a
new backend is a generator plus an enum entry, and the routing logic does not
grow a branch every time.
"""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.services.codegen import hybrid_codegen, playwright_codegen, python_codegen
from app.services.codegen.base import GeneratedCode

__all__ = ["GeneratedCode", "generate_code", "SUPPORTED_METHODS"]

#: Methods with a generator here. `n8n` is deliberately absent: it already has
#: a full exporter in `services/n8n_export.py` that emits an importable
#: workflow JSON, and a second half-implementation of it would rot.
SUPPORTED_METHODS = ("python", "playwright", "hybrid")


def generate_code(
    *,
    method: str,
    name: str,
    description: str,
    cluster_id: str,
    steps: list[dict[str, Any]],
    guards: dict[str, Any],
    variables: list[dict[str, Any]] | None = None,
    constants: list[dict[str, Any]] | None = None,
    browser_connectors: list[str] | None = None,
    api_connectors: list[str] | None = None,
    occurrences: int = 0,
) -> GeneratedCode | None:
    """Generate the artefact for one execution method.

    Returns None for `n8n`, whose artefact is the workflow JSON produced by the
    n8n exporter rather than a source file, so callers route to that instead.
    """
    if method == "python":
        return python_codegen.generate(
            name=name,
            description=description,
            cluster_id=cluster_id,
            steps=steps,
            guards=guards,
            files_root=settings.files_root,
        )
    if method == "hybrid":
        return hybrid_codegen.generate(
            name=name,
            description=description,
            cluster_id=cluster_id,
            steps=steps,
            guards=guards,
            variables=variables,
            constants=constants,
            browser_connectors=browser_connectors,
            api_connectors=api_connectors,
            occurrences=occurrences,
        )
    if method == "playwright":
        return playwright_codegen.generate(
            name=name,
            description=description,
            cluster_id=cluster_id,
            steps=steps,
            guards=guards,
        )
    return None
