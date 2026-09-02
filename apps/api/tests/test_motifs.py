"""Deterministic motif-mining tests. Generic tokens only — no domain packs."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.models.event import Event
from app.services.atlas import AtlasLimits, atlas_as_jsonable, build_activity_atlas
from app.services.motifs import (
    count_nonoverlapping,
    discover_tandem_motifs,
    has_tandem_repeat,
    motif_id_for,
)
from app.services.sessioniser import Instance

A = "app_a:read:item"
B = "app_b:update:item"
C = "app_c:send:item"
D = "app_d:create:item"
E = "app_e:search:item"


def _ts(seconds: int) -> datetime:
    return datetime(2026, 4, 1, 9, 0, tzinfo=UTC) + timedelta(seconds=seconds)


def _instance_from_tokens(
    tokens: list[str],
    *,
    instance_id: str,
    user_id: str = "u_a",
    start_second: int = 0,
    payload: dict | None = None,
    ground_truth_workflow: str | None = None,
) -> Instance:
    events: list[Event] = []
    for i, token in enumerate(tokens):
        app, action, object_type = token.split(":")
        events.append(
            Event(
                id=f"evt_{instance_id}_{i}",
                user_id=user_id,
                team="ops",
                timestamp=_ts(start_second + i),
                app=app,
                action=action,
                object_type=object_type,
                object_id=None,
                duration_ms=1_000,
                payload=payload or {},
                session_id=f"ses_{instance_id}",
                ground_truth_workflow=ground_truth_workflow,
                source="test",
            )
        )
    return Instance(user_id=user_id, team="ops", events=events, id=instance_id)


def _motif_by_tokens(atlas, tokens: list[str]):
    wanted = tuple(tokens)
    for entry in atlas.motif_catalog:
        if tuple(entry.tokens) == wanted:
            return entry
    return None


def test_abc_twice_counts_two():
    seq = [A, B, C, A, B, C]
    found = discover_tandem_motifs(seq)
    assert found[(A, B, C)] == 2
    atlas = build_activity_atlas([_instance_from_tokens(seq, instance_id="ti_1")])
    motif = _motif_by_tokens(atlas, [A, B, C])
    assert motif is not None
    assert motif.total_occurrences == 2
    assert motif.length == 3
    assert motif.instance_support == 1


def test_abc_three_times_counts_three():
    seq = [A, B, C, A, B, C, A, B, C]
    found = discover_tandem_motifs(seq)
    assert found[(A, B, C)] == 3
    atlas = build_activity_atlas([_instance_from_tokens(seq, instance_id="ti_1")])
    assert _motif_by_tokens(atlas, [A, B, C]).total_occurrences == 3


def test_longer_motif_preferred_over_substrings():
    seq = [A, B, C, D, A, B, C, D]
    found = discover_tandem_motifs(seq)
    assert (A, B, C, D) in found
    assert found[(A, B, C, D)] == 2
    assert (A, B, C) not in found
    assert (B, C, D) not in found
    atlas = build_activity_atlas([_instance_from_tokens(seq, instance_id="ti_1")])
    tokens = [tuple(m.tokens) for m in atlas.motif_catalog]
    assert (A, B, C, D) in tokens
    assert (A, B, C) not in tokens
    assert (B, C, D) not in tokens
    assert (A, B) not in tokens


def test_no_repeat_yields_no_motif():
    seq = [A, B, C, D, E]
    assert discover_tandem_motifs(seq) == {}
    atlas = build_activity_atlas([_instance_from_tokens(seq, instance_id="ti_1")])
    assert atlas.motif_catalog == []


def test_abc_abd_does_not_report_abc():
    seq = [A, B, C, A, B, D]
    assert (A, B, C) not in discover_tandem_motifs(seq)
    atlas = build_activity_atlas([_instance_from_tokens(seq, instance_id="ti_1")])
    assert _motif_by_tokens(atlas, [A, B, C]) is None


def test_cross_instance_support_and_occurrences():
    instances = [
        _instance_from_tokens([A, B, C, A, B, C], instance_id="ti_1", start_second=0),
        _instance_from_tokens([A, B, C, A, B, C], instance_id="ti_2", start_second=100),
        _instance_from_tokens([A, B, C], instance_id="ti_3", start_second=200),
    ]
    atlas = build_activity_atlas(instances)
    motif = _motif_by_tokens(atlas, [A, B, C])
    assert motif is not None
    assert motif.instance_support == 3
    assert motif.total_occurrences == 5
    assert set(motif.example_instance_ids) == {"ti_1", "ti_2", "ti_3"}


def test_distinct_users_across_instances():
    instances = [
        _instance_from_tokens(
            [A, B, C, A, B, C], instance_id="ti_1", user_id="u_a", start_second=0
        ),
        _instance_from_tokens(
            [A, B, C, A, B, C], instance_id="ti_2", user_id="u_b", start_second=100
        ),
        _instance_from_tokens(
            [A, B, C, A, B, C], instance_id="ti_3", user_id="u_a", start_second=200
        ),
    ]
    atlas = build_activity_atlas(instances)
    motif = _motif_by_tokens(atlas, [A, B, C])
    assert motif.distinct_users == 2


def test_overlapping_matches_do_not_inflate_counts():
    seq = [A, A, A, A, A, A]
    motif = [A, A, A]
    assert count_nonoverlapping(seq, motif) == 2
    found = discover_tandem_motifs(seq)
    assert found[(A, A, A)] == 2


def test_motif_id_is_stable():
    tokens = [A, B, C]
    assert motif_id_for(tokens) == motif_id_for(list(tokens))
    assert motif_id_for(tokens).startswith("motif_")
    first = build_activity_atlas(
        [_instance_from_tokens([A, B, C, A, B, C], instance_id="ti_1")]
    )
    second = build_activity_atlas(
        [_instance_from_tokens([A, B, C, A, B, C], instance_id="ti_2")]
    )
    assert first.motif_catalog[0].motif_id == second.motif_catalog[0].motif_id
    assert first.motif_catalog[0].motif_id == motif_id_for([A, B, C])


def test_motif_catalog_respects_cap():
    instances = []
    for i in range(25):
        a, b, c = f"app_a:read:t{i}", f"app_b:update:t{i}", f"app_c:send:t{i}"
        seq = [a, b, c, a, b, c]
        instances.append(
            _instance_from_tokens(seq, instance_id=f"ti_{i:02d}", start_second=i * 50)
        )
    atlas = build_activity_atlas(instances, limits=AtlasLimits(max_motifs=20))
    assert len(atlas.motif_catalog) == 20
    ranked = sorted(
        atlas.motif_catalog,
        key=lambda e: (-e.total_occurrences, -e.instance_support, -e.length, e.motif_id),
    )
    assert [m.motif_id for m in atlas.motif_catalog] == [m.motif_id for m in ranked]


def test_generic_tokens_only_no_sales_assumptions():
    seq = [A, B, C, A, B, C]
    atlas = build_activity_atlas([_instance_from_tokens(seq, instance_id="ti_1")])
    blob = json.dumps(atlas_as_jsonable(atlas))
    for banned in ("sales", "enquiry", "lead", "acknowledgement", "customer"):
        assert banned not in blob.lower()
    assert atlas.motif_catalog[0].tokens == [A, B, C]


def test_privacy_fields_are_not_emitted():
    payload = {
        "body": "secret-email-body",
        "clipboard": "clipboard-plaintext",
        "password": "hunter2",
        "workflow_hint": "do-not-emit",
    }
    inst = _instance_from_tokens(
        [A, B, C, A, B, C],
        instance_id="ti_1",
        payload=payload,
        ground_truth_workflow="inbound_lead_processing",
    )
    atlas = build_activity_atlas([inst])
    dumped = atlas_as_jsonable(atlas)
    blob = json.dumps(dumped)
    assert "secret-email-body" not in blob
    assert "clipboard-plaintext" not in blob
    assert "hunter2" not in blob
    assert "do-not-emit" not in blob
    assert "ground_truth_workflow" not in blob
    assert "inbound_lead_processing" not in blob
    assert "payload" not in json.dumps(dumped["motif_catalog"])


def test_empty_activity_has_empty_motif_catalog():
    atlas = build_activity_atlas([])
    assert atlas.motif_catalog == []


def test_four_abc_copies_reduce_to_primitive_not_doubled_block():
    seq = [A, B, C] * 4
    found = discover_tandem_motifs(seq)
    assert found[(A, B, C)] == 4
    assert (A, B, C, A, B, C) not in found


def test_seed_generates_motifs_when_tandems_exist(seed_events):
    from app.services.atlas import build_activity_atlas_from_events
    from app.services.sessioniser import sessionise

    instances = sessionise(seed_events)
    atlas = build_activity_atlas_from_events(seed_events)
    assert len(atlas.motif_catalog) <= 20
    tandem_exists = any(has_tandem_repeat(i.signature) for i in instances)
    if tandem_exists:
        assert atlas.motif_catalog
        for motif in atlas.motif_catalog:
            assert motif.length >= 3
            assert motif.total_occurrences >= 2
            assert motif.instance_support >= 1
    dumped = atlas_as_jsonable(atlas)
    assert "ground_truth_workflow" not in json.dumps(dumped)
