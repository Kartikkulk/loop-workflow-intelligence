"""Shared fixtures. Detection tests run against the real seed generator."""

from __future__ import annotations

import pytest

from app.services.clustering import cluster_instances
from app.services.generator_seed import generate_events
from app.services.sessioniser import sessionise


@pytest.fixture(scope="session")
def seed_events():
    """The deterministic synthetic activity log."""
    return generate_events(seed=42, days=90)


@pytest.fixture(scope="session")
def instances(seed_events):
    return sessionise(seed_events)


@pytest.fixture(scope="session")
def clusters(instances):
    return cluster_instances(instances)
