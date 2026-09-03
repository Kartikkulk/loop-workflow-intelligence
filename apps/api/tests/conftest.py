"""Shared fixtures. Detection tests run against the real seed generator."""

from __future__ import annotations

import pytest

from app.config import settings
from app.services.clustering import cluster_instances
from app.services.generator_seed import generate_events
from app.services.sessioniser import sessionise


@pytest.fixture(autouse=True)
def _deterministic_llm(monkeypatch):
    """Run the suite against the deterministic fallback, never a live model.

    CI has neither Ollama nor a key, so scoring already falls back there. A
    developer's own `.env` may point at a running model or an OpenAI key,
    though, which would make `score_cluster` reach the network — slow, flaky,
    and in the OpenAI case not free. Pinning the provider off here makes a local
    run behave like CI. Tests that specifically exercise provider selection
    set their own state on top of this, and a function-level monkeypatch applied
    in the test body wins over this fixture.
    """
    monkeypatch.setattr(settings, "llm_provider", "none")
    monkeypatch.setattr(settings, "openai_api_key", "")


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
