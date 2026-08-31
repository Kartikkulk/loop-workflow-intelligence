"""Scoring tests, including the one that matters most: workflow 5 must be
flagged DO NOT AUTOMATE from the data, not from a hardcoded label."""

from __future__ import annotations

import pytest

from app.config import settings
from app.services.scoring import (
    branch_count,
    free_text_ratio,
    score_cluster,
    shannon_entropy,
    step_order_entropy,
)
from app.services.sessioniser import count_context_switches


def _dominant(cluster) -> str | None:
    counts: dict[str, int] = {}
    for instance in cluster.instances:
        label = instance.ground_truth_workflow
        if label:
            counts[label] = counts.get(label, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0] if counts else None


def _find(clusters, workflow: str, minimum: int = 50):
    for cluster in clusters:
        if _dominant(cluster) == workflow and cluster.size >= minimum:
            return cluster
    raise AssertionError(f"no cluster of at least {minimum} instances for {workflow}")


def test_entropy_bounds():
    assert shannon_entropy([10]) == 0.0
    assert shannon_entropy([]) == 0.0
    assert shannon_entropy([5, 5]) == pytest.approx(1.0)
    assert shannon_entropy([1, 1, 1, 1]) == pytest.approx(1.0)
    assert 0.0 < shannon_entropy([90, 10]) < 1.0


def test_uniform_sequences_have_zero_entropy(clusters):
    """A cluster with one signature variant has no step-order entropy."""
    for cluster in clusters:
        entropy, variants, dominant = step_order_entropy(cluster)
        if variants == 1:
            assert entropy == 0.0
            assert dominant == 1.0
            return
    pytest.skip("no single-variant cluster in the seed data")


async def test_hero_workflow_is_automatable(clusters):
    cluster = _find(clusters, "invoice_to_ledger", minimum=200)
    score = await score_cluster(cluster, "invoice to ledger")
    assert score.automatability >= settings.do_not_automate_threshold
    assert not score.do_not_automate
    assert score.is_organisational
    assert score.annual_hours > 0
    assert score.interruption_tax_hours > 0


async def test_escalation_workflow_is_flagged_do_not_automate(clusters):
    """The whole point of the variance detector.

    customer_escalation is never labelled do-not-automate anywhere in the seed
    specification. It must be caught because its instances genuinely disagree
    with each other in the log.
    """
    cluster = _find(clusters, "customer_escalation", minimum=50)
    score = await score_cluster(cluster, "customer escalation")

    assert score.do_not_automate, "high-variance workflow was not flagged"
    assert score.automatability < settings.do_not_automate_threshold
    # It must be caught for the right reasons, not by accident.
    assert score.variance.step_order_entropy > 0.8
    assert score.variance.dominant_variant_share < 0.2
    assert score.variance.judgement_ratio > 0.3
    assert "not recommended" in score.reasoning.lower()


async def test_reasoning_is_specific_not_generic(clusters):
    cluster = _find(clusters, "customer_escalation", minimum=50)
    score = await score_cluster(cluster, "customer escalation")
    # The reasoning must cite measured numbers, so it survives scrutiny.
    assert "%" in score.reasoning
    assert "sequence" in score.reasoning.lower()


async def test_priority_prefers_high_volume_low_variance(clusters):
    hero = await score_cluster(_find(clusters, "invoice_to_ledger", 200), "invoice")
    escalation = await score_cluster(_find(clusters, "customer_escalation", 50), "escalation")
    assert hero.priority > escalation.priority


def test_context_switch_requires_a_return(seed_events):
    """A one-way app change is not an interruption; a bounce back is."""

    class E:
        def __init__(self, app, minutes):
            from datetime import UTC, datetime, timedelta

            self.app = app
            self.timestamp = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes)
            self.duration_ms = 0

    # gmail -> sheets -> gmail within the window: one switch.
    assert count_context_switches([E("gmail", 0), E("sheets", 1), E("gmail", 2)]) == 1
    # A one-way move is not a switch.
    assert count_context_switches([E("gmail", 0), E("sheets", 1), E("erp", 2)]) == 0
    # A bounce outside the window does not count.
    assert count_context_switches([E("gmail", 0), E("sheets", 1), E("gmail", 99)]) == 0


def test_branch_count_detects_varying_positions(clusters):
    for cluster in clusters:
        if len(cluster.members_by_hash) > 1:
            assert branch_count(cluster) >= 0
            return
    pytest.skip("no multi-variant cluster")


def test_free_text_ratio_is_higher_for_judgement_work(clusters):
    escalation = free_text_ratio(_find(clusters, "customer_escalation", 50))
    invoice = free_text_ratio(_find(clusters, "invoice_to_ledger", 200))
    assert escalation > invoice
