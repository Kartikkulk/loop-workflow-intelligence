"""Connector resolution. The single place mock and live implementations diverge."""

from __future__ import annotations

from app.config import settings
from app.connectors.base import Connector
from app.connectors.mock.mock_connectors import MOCK_REGISTRY, MockConnector
from app.connectors.real_connectors import REAL_REGISTRY

_FALLBACK = MockConnector()


def get_connector(name: str, *, force_mock: bool = False) -> Connector:
    """Resolve a connector by name.

    `force_mock` is set by the engine for replay and shadow modes, which must
    never produce a side effect regardless of how the deployment is configured.
    That guarantee lives here rather than in each connector, so a new connector
    cannot forget it.
    """
    if force_mock or settings.enable_mock_connectors:
        return MOCK_REGISTRY.get(name, _FALLBACK)
    return REAL_REGISTRY.get(name, _FALLBACK)


def connector_inventory() -> list[dict]:
    """Describe every connector, for the console's system page."""
    out = []
    for name, real in REAL_REGISTRY.items():
        out.append(
            {
                "name": name,
                "mock_available": name in MOCK_REGISTRY,
                "live_available": True,
                "required_credentials": list(getattr(real, "required_credentials", ())),
                "api": getattr(real, "api", ""),
                "active": "mock" if settings.enable_mock_connectors else "live",
            }
        )
    return sorted(out, key=lambda c: c["name"])
