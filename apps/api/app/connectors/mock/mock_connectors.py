"""Mock connector implementations: no side effects, real resolution semantics.

These are not stubs. They perform the actual dependency resolution a real
connector would — reading each `depends_on` field out of the context and
reporting exactly which ones failed to resolve — because that resolution is what
F8 self-healing watches. A mock that always succeeded would make drift
undetectable and the whole healing feature untestable.
"""

from __future__ import annotations

from typing import Any

from app.connectors.base import Connector, Context, Step, StepResult


def _resolve(step: Step, ctx: Context) -> tuple[dict[str, Any], list[str]]:
    """Resolve a step's declared dependencies against the available context.

    Returns (resolved values, names that could not be resolved). A dependency
    written as `email.attachment` is matched on its last segment too, so a flow
    generated with dotted paths still resolves against flat payloads.
    """
    available = ctx.available()
    resolved: dict[str, Any] = {}
    unresolved: list[str] = []
    for field_name in step.depends_on:
        if field_name in available and available[field_name] not in (None, ""):
            resolved[field_name] = available[field_name]
            continue
        tail = field_name.split(".")[-1]
        if tail in available and available[tail] not in (None, ""):
            resolved[field_name] = available[tail]
            continue
        # Case-insensitive last resort: real column headers vary in casing.
        lowered = {str(k).lower(): v for k, v in available.items()}
        if tail.lower() in lowered and lowered[tail.lower()] not in (None, ""):
            resolved[field_name] = lowered[tail.lower()]
            continue
        unresolved.append(field_name)
    return resolved, unresolved


class MockConnector:
    """Shared behaviour for every mocked system."""

    name = "mock"
    is_mock = True
    # Steps of these types have effects that cannot be undone.
    irreversible_types: frozenset[str] = frozenset({"send", "delete"})

    async def execute(self, step: Step, ctx: Context) -> StepResult:
        resolved, unresolved = _resolve(step, ctx)

        if unresolved:
            # A dependency that no longer resolves is precisely the drift signal.
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"unresolved dependencies: {', '.join(unresolved)}",
                unresolved=unresolved,
                confidence=0.0,
            )

        outputs = self.produce(step, ctx, resolved)
        # Confidence falls when the step produced fewer outputs than declared —
        # a partially-filled result is exactly what should reach a human.
        declared = len(step.outputs) or 1
        filled = sum(1 for key in step.outputs if outputs.get(key) not in (None, ""))
        confidence = 1.0 if not step.outputs else max(0.15, filled / declared)

        return StepResult(
            step_id=step.id,
            status="ok",
            outputs=outputs,
            confidence=confidence,
            side_effect=(
                f"{self.name}.{step.type} (mocked)"
                if step.type in self.irreversible_types
                else None
            ),
        )

    def produce(self, step: Step, ctx: Context, resolved: dict[str, Any]) -> dict[str, Any]:
        """Produce this step's declared outputs. Overridden per system."""
        available = ctx.available()
        out: dict[str, Any] = {}
        for key in step.outputs:
            if key in resolved:
                out[key] = resolved[key]
            elif key in available:
                out[key] = available[key]
            else:
                out[key] = None
        return out


class MockGmailConnector(MockConnector):
    name = "gmail"

    def produce(self, step: Step, ctx: Context, resolved: dict[str, Any]) -> dict[str, Any]:
        available = ctx.available()
        if step.type == "send":
            return {
                key: available.get(key, f"drafted:{key}")
                for key in (step.outputs or ["message_id"])
            }
        return super().produce(step, ctx, resolved)


class MockOutlookConnector(MockGmailConnector):
    name = "outlook"


class MockPdfConnector(MockConnector):
    name = "pdf"

    def produce(self, step: Step, ctx: Context, resolved: dict[str, Any]) -> dict[str, Any]:
        """Extract ledger fields from the document payload.

        Deliberately copies `amount` through as its face value. When the invoice
        is in a foreign currency the human converts it first, so replay will
        disagree — a real, nameable failure mode rather than a hidden one.
        """
        available = ctx.available()
        out: dict[str, Any] = {}
        for key in step.outputs:
            if key == "amount":
                out["amount"] = available.get("amount")
            elif key == "currency":
                out["currency"] = available.get("currency", "INR")
            else:
                out[key] = resolved.get(key, available.get(key))
        return out


class MockSheetsConnector(MockConnector):
    name = "sheets"


class MockErpConnector(MockConnector):
    name = "erp"


class MockDriveConnector(MockConnector):
    name = "drive"


class MockSlackConnector(MockConnector):
    name = "slack"


class MockBrowserConnector(MockConnector):
    name = "browser"


MOCK_REGISTRY: dict[str, Connector] = {
    "gmail": MockGmailConnector(),
    "outlook": MockOutlookConnector(),
    "pdf": MockPdfConnector(),
    "sheets": MockSheetsConnector(),
    "erp": MockErpConnector(),
    "drive": MockDriveConnector(),
    "slack": MockSlackConnector(),
    "browser": MockBrowserConnector(),
}
