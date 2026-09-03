"""Low-occurrence discovery for the demo.

A live pitch cannot produce ninety-six repetitions by hand, so demo mode drops
the instance floor to two or three. The risk that opens is calling every pair of
unrelated actions a "workflow", so the floor is balanced by a similarity and
confidence gate and every low-occurrence finding is labelled by how strong its
evidence actually is. These tests pin that behaviour, and pin that lowering the
discovery floor never lowers a safety gate.

The LLM is forced off so the scoring path is deterministic everywhere — the
evidence logic must not depend on whether a model happens to be running.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.config import settings
from app.models.event import Event
from app.services.clustering import cluster_instances
from app.services.scoring import (
    classify_evidence,
    discovery_confidence,
    score_cluster,
)
from app.services.sessioniser import sessionise

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "invoice-demo-small.jsonl"


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Force the deterministic path: evidence must not depend on a live model."""
    monkeypatch.setattr(settings, "llm_provider", "none")
    monkeypatch.setattr(settings, "openai_api_key", "")


@pytest.fixture
def _demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "discovery_mode", "demo")
    monkeypatch.setattr(settings, "discovery_min_occurrences", 2)
    monkeypatch.setattr(settings, "discovery_strong_occurrences", 3)
    monkeypatch.setattr(settings, "discovery_min_similarity", 0.70)
    monkeypatch.setattr(settings, "discovery_strong_similarity", 0.85)
    monkeypatch.setattr(settings, "discovery_min_confidence", 0.60)
    monkeypatch.setattr(settings, "discovery_strong_confidence", 0.75)


def _demo_events() -> list[Event]:
    events: list[Event] = []
    for line in _FIXTURE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        events.append(
            Event(
                id=d["id"],
                user_id=d["user_id"],
                team=d["team"],
                timestamp=datetime.fromisoformat(d["timestamp"]),
                app=d["app"],
                action=d["action"],
                object_type=d["object_type"],
                object_id=d.get("object_id"),
                duration_ms=d["duration_ms"],
                payload=d.get("payload", {}),
                session_id=d.get("session_id"),
            )
        )
    return events


# ── the confidence weighting ─────────────────────────────────────────────────

def test_confidence_is_not_dominated_by_occurrence_count():
    """Two clean runs must beat many ragged ones — frequency is not the driver."""
    two_clean = discovery_confidence(occurrences=2, similarity=0.95, automatability=0.9)
    many_ragged = discovery_confidence(occurrences=10, similarity=0.2, automatability=0.3)
    assert two_clean > many_ragged


def test_confidence_is_bounded():
    assert discovery_confidence(occurrences=0, similarity=0.0, automatability=0.0) >= 0.0
    assert discovery_confidence(occurrences=99, similarity=1.0, automatability=1.0) <= 1.0


# ── evidence labelling ───────────────────────────────────────────────────────

def test_two_consistent_occurrences_are_early_or_moderate(_demo_mode):
    level, more = classify_evidence(occurrences=2, similarity=0.82, confidence=0.74)
    assert level in {"early", "moderate"}
    assert more is True, "a two-occurrence candidate always recommends more observation"


def test_three_consistent_occurrences_are_strong(_demo_mode):
    level, more = classify_evidence(occurrences=3, similarity=0.90, confidence=0.86)
    assert level == "strong"
    assert more is False


def test_many_occurrences_are_strong(_demo_mode):
    level, more = classify_evidence(occurrences=96, similarity=0.94, confidence=0.93)
    assert level == "strong"
    assert more is False


def test_two_occurrences_seen_very_consistently_is_moderate(_demo_mode):
    """Seen only twice but nearly identical: real enough to preview, watch more."""
    level, more = classify_evidence(occurrences=2, similarity=0.97, confidence=0.7)
    assert level == "moderate"
    assert more is True


# ── the end-to-end small demo sample ─────────────────────────────────────────

async def test_small_invoice_sample_produces_one_strong_candidate(_demo_mode):
    events = _demo_events()
    instances = sessionise(events)
    assert len(instances) == 3, "three invoice runs in, three instances out"

    groups = cluster_instances(instances)
    invoice = max(groups, key=lambda g: g.size)
    assert invoice.size == 3, "the three near-identical runs cluster as one workflow"

    score = await score_cluster(invoice, "Invoice filing")
    assert score.instance_count == 3
    assert score.evidence_level == "strong"
    assert score.requires_more_observation is False
    # The signature the demo relies on, produced from the observed events.
    assert invoice.representative == [
        "files:read:invoice_pdf",
        "pdf:extract:invoice_fields",
        "files:create:filed_invoice",
        "jira:send:billing_note",
    ]


async def test_first_two_invoices_alone_are_an_early_candidate(_demo_mode):
    """Exactly the pitch: process two invoices and something already shows up."""
    events = [e for e in _demo_events() if e.session_id in {"ses_demo_a1", "ses_demo_b2"}]
    instances = sessionise(events)
    assert len(instances) == 2

    groups = cluster_instances(instances)
    invoice = max(groups, key=lambda g: g.size)
    assert invoice.size == 2

    score = await score_cluster(invoice, "Invoice filing")
    assert score.instance_count == 2
    assert score.evidence_level in {"early", "moderate"}
    assert score.requires_more_observation is True


# ── the safety line demo mode must not cross ─────────────────────────────────

def test_demo_mode_lowers_the_floor_but_not_the_guard_threshold(_demo_mode):
    """Discovery gets more sensitive; the money guard does not move."""
    assert settings.effective_min_instances == settings.discovery_min_occurrences
    # The approval threshold is a safety setting, untouched by discovery mode.
    assert settings.do_not_automate_threshold == 0.4


def test_production_mode_keeps_the_full_floor(monkeypatch):
    monkeypatch.setattr(settings, "discovery_mode", "production")
    assert settings.effective_min_instances == settings.min_instances
    assert not settings.demo_mode
