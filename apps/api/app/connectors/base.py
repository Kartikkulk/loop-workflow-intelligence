"""F5 — the connector interface.

One `Connector` protocol, two implementations per system: a real one and a mock.
`ENABLE_MOCK_CONNECTORS` switches between them at resolution time, which is what
lets the same engine drive a safe replay and a live run. A judge asking "could
this hit real Gmail?" gets: yes, swap one class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Step:
    """One step of a flow definition."""

    id: str
    type: str
    connector: str
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    description: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Step:
        return cls(
            id=str(raw.get("id", "s?")),
            type=str(raw.get("type", "read")),
            connector=str(raw.get("connector", "browser")),
            inputs=dict(raw.get("inputs") or {}),
            outputs=list(raw.get("outputs") or []),
            depends_on=list(raw.get("depends_on") or []),
            description=str(raw.get("description", "")),
        )


@dataclass
class Context:
    """Mutable state threaded through a single execution.

    `source_payload` is the union of the historical event payloads for the task
    instance being replayed, and is the only place a mock connector may read
    real values from. `schema` is the *current* shape of each system, which is
    what makes drift observable.
    """

    mode: str
    trigger_payload: dict[str, Any] = field(default_factory=dict)
    source_payload: dict[str, Any] = field(default_factory=dict)
    resolved: dict[str, Any] = field(default_factory=dict)
    schema: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def available(self) -> dict[str, Any]:
        """Everything a step may read: trigger, source, and prior step outputs."""
        merged = dict(self.source_payload)
        merged.update(self.trigger_payload)
        merged.update(self.resolved)
        return merged


@dataclass
class StepResult:
    """Outcome of one step."""

    step_id: str
    status: str  # ok | failed | skipped | needs_approval
    outputs: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    error: str | None = None
    # Which depends_on fields failed to resolve. F8 reads this to detect drift.
    unresolved: list[str] = field(default_factory=list)
    side_effect: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@runtime_checkable
class Connector(Protocol):
    """Every system LOOP can touch implements exactly this."""

    name: str
    # True when execute() has no observable effect outside the process.
    is_mock: bool

    async def execute(self, step: Step, ctx: Context) -> StepResult: ...


class ConnectorError(RuntimeError):
    """Raised when a connector cannot run at all, as opposed to a step failing."""
