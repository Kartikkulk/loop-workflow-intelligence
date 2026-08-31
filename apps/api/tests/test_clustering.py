"""Clustering tests.

The three cases the spec calls for — identical sequences must cluster, one
optional step must still cluster, structurally different sequences must not —
are asserted directly on the similarity function and again on the full
end-to-end pass over the seed data.
"""

from __future__ import annotations

from app.config import settings
from app.services.clustering import (
    cluster_instances,
    combined_similarity,
    embed,
    sequence_similarity,
    set_similarity,
)
from app.services.sessioniser import collapse_interruptions, signature_text

INVOICE = [
    "gmail:read:invoice_email",
    "pdf:extract:fields",
    "sheets:create:row",
    "gmail:send:confirmation",
]
INVOICE_WITH_OPTIONAL = [
    "gmail:read:invoice_email",
    "pdf:extract:fields",
    "erp:search:vendor_record",
    "sheets:create:row",
    "gmail:send:confirmation",
]
PO_MATCHING = [
    "erp:read:purchase_order",
    "erp:search:invoice",
    "sheets:update:match_log",
]
VENDOR_REPORT = [
    "sheets:read:report_source",
    "sheets:search:overdue_rows",
    "sheets:update:summary",
    "gmail:send:report",
]


def _similarity(a: list[str], b: list[str]) -> float:
    vectors = embed([signature_text(a), signature_text(b)])
    return combined_similarity(a, b, vectors[0], vectors[1])


def test_identical_sequences_are_maximally_similar():
    assert _similarity(INVOICE, INVOICE) == 1.0


def test_one_optional_step_still_clusters():
    """The core requirement: an optional step must not split a workflow."""
    assert _similarity(INVOICE, INVOICE_WITH_OPTIONAL) >= settings.cluster_threshold


def test_structurally_different_sequences_do_not_cluster():
    for other in (PO_MATCHING, VENDOR_REPORT):
        assert _similarity(INVOICE, other) < settings.cluster_threshold
    assert _similarity(PO_MATCHING, VENDOR_REPORT) < settings.cluster_threshold


def test_separation_margin_is_wide():
    """Same-workflow and different-workflow scores must not be adjacent.

    Guards against a future weight change that leaves the threshold sitting on
    a knife edge, where a single new workflow silently merges everything.
    """
    same = _similarity(INVOICE, INVOICE_WITH_OPTIONAL)
    different = max(_similarity(INVOICE, PO_MATCHING), _similarity(INVOICE, VENDOR_REPORT))
    assert same - different > 0.3


def test_sequence_similarity_counts_one_edit_once():
    """A substituted step must cost one edit, not one per character."""
    a = ["gmail:read:invoice_email", "sheets:create:row"]
    b = ["gmail:read:invoice_email", "erp:create:record_with_a_very_long_name"]
    assert sequence_similarity(a, b) == 0.5


def test_set_similarity_is_order_invariant():
    assert set_similarity(INVOICE, list(reversed(INVOICE))) == 1.0
    assert set_similarity(INVOICE, PO_MATCHING) == 0.0


def test_collapse_removes_interruption_bounce():
    """A -> B -> A is an interruption, not a different workflow."""
    interrupted = [
        "gmail:read:invoice_email",
        "pdf:extract:fields",
        "erp:search:vendor_record",
        "pdf:extract:fields",
        "sheets:create:row",
        "gmail:send:confirmation",
    ]
    assert collapse_interruptions(interrupted) == INVOICE


def test_collapse_removes_repeated_step():
    assert collapse_interruptions(["a", "a", "b"]) == ["a", "b"]


def test_collapse_preserves_genuine_sequence():
    assert collapse_interruptions(INVOICE) == INVOICE
    assert collapse_interruptions(PO_MATCHING) == PO_MATCHING


def test_empty_input_yields_no_clusters():
    assert cluster_instances([]) == []


def test_clustering_recovers_ground_truth(clusters):
    """Every seeded workflow must be recovered as its own dominant cluster.

    Ground truth is carried on the events but read by no detection service, so
    this asserts that detection found the structure independently.
    """
    # One workflow per domain, so the ground-truth labels are the domain keys.
    # Read from the registry rather than hardcoded: adding a domain should
    # extend what this test demands, not silently escape it.
    from app.domains import DOMAINS

    expected = {domain.key for domain in DOMAINS}
    largest: dict[str, int] = {}
    for cluster in clusters:
        counts: dict[str, int] = {}
        for instance in cluster.instances:
            label = instance.ground_truth_workflow
            if label:
                counts[label] = counts.get(label, 0) + 1
        if not counts:
            continue
        dominant, count = max(counts.items(), key=lambda kv: kv[1])
        largest[dominant] = max(largest.get(dominant, 0), count)

    assert expected <= set(largest), f"missing workflows: {expected - set(largest)}"


def test_clusters_are_pure(clusters):
    """Clusters must not mix workflows: weighted purity above 99%."""
    total = 0
    dominant_total = 0
    for cluster in clusters:
        counts: dict[str, int] = {}
        for instance in cluster.instances:
            label = instance.ground_truth_workflow or "noise"
            counts[label] = counts.get(label, 0) + 1
        total += cluster.size
        dominant_total += max(counts.values())
    assert dominant_total / total > 0.99


def test_hero_workflow_is_organisational(clusters):
    """Finance is performed by six people and must clear the org threshold."""
    for cluster in clusters:
        labels = [i.ground_truth_workflow for i in cluster.instances]
        if labels.count("finance") > 100:
            users = {i.user_id for i in cluster.instances}
            assert len(users) > settings.org_user_threshold
            return
    raise AssertionError("no substantial finance cluster was found")
