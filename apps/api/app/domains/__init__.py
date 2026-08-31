"""Domain registry.

Every module in this package that exposes a `DOMAIN` is picked up
automatically. Adding a domain is adding a file — there is no list to edit and
therefore no merge conflict when two people add domains on the same day.
"""

from __future__ import annotations

import importlib
import pkgutil

from app.domains.base import DomainPack, Step


def _discover() -> list[DomainPack]:
    """Import every sibling module and collect its DOMAIN."""
    found: list[DomainPack] = []
    for module in pkgutil.iter_modules(__path__):
        if module.name in ("base",) or module.name.startswith("_"):
            continue
        loaded = importlib.import_module(f"{__name__}.{module.name}")
        domain = getattr(loaded, "DOMAIN", None)
        if isinstance(domain, DomainPack):
            found.append(domain)
    # Sorted by key so the seed is deterministic regardless of filesystem order.
    return sorted(found, key=lambda d: d.key)


DOMAINS: list[DomainPack] = _discover()
DOMAINS_BY_KEY: dict[str, DomainPack] = {d.key: d for d in DOMAINS}

#: Every person across every domain, mapped to their team.
PEOPLE: dict[str, str] = {
    person: domain.team for domain in DOMAINS for person in domain.people
}

__all__ = ["DOMAINS", "DOMAINS_BY_KEY", "PEOPLE", "DomainPack", "Step"]
