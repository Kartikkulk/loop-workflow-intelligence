"""Activity Atlas builder tests. Generic fixtures only — no domain packs."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.models.event import Event
from app.services.atlas import (
    AtlasLimits,
    atlas_as_jsonable,
    build_activity_atlas,
    build_activity_atlas_from_events,
    signature_id_for,
)
from app.services.sessioniser import Instance, signature_hash

_SENSITIVE_VALUES = (
    "secret-email-body",
    "clipboard-plaintext",
    "hunter2",
    "cell-value-42",
    "SELECT * FROM hidden",
)


def _ts(seconds: int) -> datetime:
    return datetime(2026, 3, 1, 10, 0, tzinfo=UTC) + timedelta(seconds=seconds)


def _event(
    *,
    index: int,
    user_id: str,
    app: str,
    action: str,
    object_type: str,
    seconds: int,
    duration_ms: int = 1_000,
    payload: dict | None = None,
    session_id: str | None = None,
    ground_truth_workflow: str | None = None,
    object_id: str | None = None,
) -> Event:
    return Event(
        id=f"evt_{index:04d}",
        user_id=user_id,
        team="ops",
        timestamp=_ts(seconds),
        app=app,
        action=action,
        object_type=object_type,
        object_id=object_id,
        duration_ms=duration_ms,
        payload=payload or {},
        session_id=session_id,
        ground_truth_workflow=ground_truth_workflow,
        source="test",
    )


def _instance(events: list[Event], *, instance_id: str, user_id: str | None = None) -> Instance:
    return Instance(
        user_id=user_id or events[0].user_id,
        team=events[0].team,
        events=events,
        id=instance_id,
    )


def _gmail_sheets_gmail(
    *,
    index: int,
    user_id: str,
    start_second: int,
    duration_ms: int = 6_000,
    session_id: str | None = None,
    payload: dict | None = None,
    ground_truth_workflow: str | None = None,
) -> Instance:
    base = index * 3
    step_ms = duration_ms // 3
    common = dict(
        user_id=user_id,
        session_id=session_id,
        ground_truth_workflow=ground_truth_workflow,
        payload=payload or {},
        duration_ms=step_ms,
    )
    events = [
        _event(
            index=base,
            app="gmail",
            action="read",
            object_type="email",
            seconds=start_second,
            **common,
        ),
        _event(
            index=base + 1,
            app="sheets",
            action="update",
            object_type="spreadsheet",
            seconds=start_second + 1,
            **common,
        ),
        _event(
            index=base + 2,
            app="gmail",
            action="send",
            object_type="email",
            seconds=start_second + 2,
            **common,
        ),
    ]
    return _instance(events, instance_id=f"ti_{index:04d}", user_id=user_id)


def _walk_strings(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            found.append(str(key))
            found.extend(_walk_strings(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_strings(item))
    elif isinstance(value, str):
        found.append(value)
    return found


def test_empty_activity_yields_valid_empty_atlas():
    atlas = build_activity_atlas([])
    dumped = atlas_as_jsonable(atlas)
    assert dumped["summary"] == {
        "event_count": 0,
        "instance_count": 0,
        "distinct_users": 0,
        "distinct_sessions": 0,
    }
    assert dumped["signature_catalog"] == []
    assert dumped["candidate_groups"] == []
    assert dumped["motif_catalog"] == []
    assert dumped["app_transitions"] == []
    assert dumped["sample_instances"] == []
    assert dumped["field_name_histograms"] == {}
    assert dumped["time_window"]["start"] is None
    assert dumped["time_window"]["end"] is None


def test_identical_signatures_share_one_catalog_entry():
    instances = [
        _gmail_sheets_gmail(index=i, user_id="u_a", start_second=i * 1_200) for i in range(5)
    ]
    atlas = build_activity_atlas(instances)
    assert len(atlas.signature_catalog) == 1
    entry = atlas.signature_catalog[0]
    assert entry.occurrence_count == 5
    assert entry.tokens == [
        "gmail:read:email",
        "sheets:update:spreadsheet",
        "gmail:send:email",
    ]


def test_different_signatures_are_separate_catalog_entries():
    a = _gmail_sheets_gmail(index=0, user_id="u_a", start_second=0)
    other_events = [
        _event(index=10, user_id="u_a", app="drive", action="read", object_type="file", seconds=40),
        _event(index=11, user_id="u_a", app="drive", action="update", object_type="file", seconds=41),
        _event(index=12, user_id="u_a", app="gmail", action="send", object_type="email", seconds=42),
    ]
    b = _instance(other_events, instance_id="ti_other")
    atlas = build_activity_atlas([a, b])
    assert len(atlas.signature_catalog) == 2
    token_sets = {tuple(e.tokens) for e in atlas.signature_catalog}
    assert len(token_sets) == 2


def test_distinct_user_count():
    instances = [
        _gmail_sheets_gmail(index=0, user_id="u_a", start_second=0),
        _gmail_sheets_gmail(index=1, user_id="u_b", start_second=1_200),
        _gmail_sheets_gmail(index=2, user_id="u_a", start_second=2_400),
    ]
    atlas = build_activity_atlas(instances)
    assert atlas.summary.distinct_users == 2
    assert atlas.signature_catalog[0].distinct_users == 2


def test_median_duration():
    instances = []
    for i, duration in enumerate((3_000, 9_000, 6_000)):
        instances.append(
            _gmail_sheets_gmail(
                index=i, user_id="u_a", start_second=i * 1_200, duration_ms=duration
            )
        )
    atlas = build_activity_atlas(instances)
    assert atlas.signature_catalog[0].median_duration_ms == 6_000


def test_candidate_groups_include_below_discovery_floor():
    instances = [
        _gmail_sheets_gmail(index=i, user_id="u_a", start_second=i * 1_200) for i in range(7)
    ]
    atlas = build_activity_atlas(instances)
    assert atlas.candidate_groups
    assert atlas.candidate_groups[0].occurrence_count == 7
    assert all(g.occurrence_count < 15 for g in atlas.candidate_groups)


def test_app_transition_counts():
    instances = [
        _gmail_sheets_gmail(index=0, user_id="u_a", start_second=0),
        _gmail_sheets_gmail(index=1, user_id="u_a", start_second=1_200),
    ]
    atlas = build_activity_atlas(instances)
    dumped = atlas_as_jsonable(atlas)
    pairs = {(row["from"], row["to"]): row["count"] for row in dumped["app_transitions"]}
    assert pairs[("gmail", "sheets")] == 2
    assert pairs[("sheets", "gmail")] == 2


def test_sample_instances_respect_maximum():
    instances = []
    for i in range(12):
        events = [
            _event(
                index=i * 3,
                user_id="u_a",
                app="gmail",
                action="read",
                object_type=f"item_{i}",
                seconds=i * 60,
            ),
            _event(
                index=i * 3 + 1,
                user_id="u_a",
                app="sheets",
                action="update",
                object_type=f"item_{i}",
                seconds=i * 60 + 1,
            ),
            _event(
                index=i * 3 + 2,
                user_id="u_a",
                app="gmail",
                action="send",
                object_type=f"item_{i}",
                seconds=i * 60 + 2,
            ),
        ]
        instances.append(_instance(events, instance_id=f"ti_{i:04d}"))
    atlas = build_activity_atlas(instances, limits=AtlasLimits(max_sample_instances=8))
    assert len(atlas.sample_instances) <= 8
    for sample in atlas.sample_instances:
        assert sample.instance_id
        assert sample.signature
        assert sample.user_id
        assert sample.event_count >= 2


def test_sensitive_payload_values_are_never_included():
    payload = {
        "body": "secret-email-body",
        "Message_Body": "secret-email-body",
        "clipboard": "clipboard-plaintext",
        "password": "hunter2",
        "A1": "cell-value-42",
        "query": "SELECT * FROM hidden",
    }
    inst = _gmail_sheets_gmail(index=0, user_id="u_a", start_second=0, payload=payload)
    inst.events[0].payload = payload
    atlas = build_activity_atlas([inst])
    blob = json.dumps(atlas_as_jsonable(atlas))
    for secret in _SENSITIVE_VALUES:
        assert secret not in blob
    names = atlas.field_name_histograms["gmail:read:email"]
    assert "Message_Body" in names
    assert "password" in names
    assert "A1" in names


def test_ground_truth_workflow_is_never_included():
    inst = _gmail_sheets_gmail(
        index=0,
        user_id="u_a",
        start_second=0,
        ground_truth_workflow="inbound_lead_processing",
    )
    atlas = build_activity_atlas([inst])
    dumped = atlas_as_jsonable(atlas)
    keys_and_values = _walk_strings(dumped)
    assert "ground_truth_workflow" not in keys_and_values
    assert "inbound_lead_processing" not in keys_and_values
    blob = json.dumps(dumped)
    assert "ground_truth" not in blob


def test_atlas_size_limits_are_respected():
    instances = []
    for i in range(45):
        events = [
            _event(
                index=i * 3,
                user_id="u_a",
                app="gmail",
                action="read",
                object_type=f"type_{i}",
                seconds=i * 60,
            ),
            _event(
                index=i * 3 + 1,
                user_id="u_a",
                app="sheets",
                action="update",
                object_type=f"type_{i}",
                seconds=i * 60 + 1,
            ),
            _event(
                index=i * 3 + 2,
                user_id="u_a",
                app="gmail",
                action="send",
                object_type=f"type_{i}",
                seconds=i * 60 + 2,
            ),
        ]
        instances.append(_instance(events, instance_id=f"ti_{i:04d}"))
    limits = AtlasLimits(
        max_signatures=40,
        max_candidate_groups=15,
        max_sample_instances=8,
        max_example_ids_per_signature=8,
    )
    atlas = build_activity_atlas(instances, limits=limits)
    assert len(atlas.signature_catalog) == 40
    assert len(atlas.candidate_groups) <= 15
    assert len(atlas.sample_instances) <= 8
    assert atlas.motif_catalog == []
    for entry in atlas.signature_catalog:
        assert len(entry.example_instance_ids) <= 8


def test_signature_ids_are_stable():
    tokens = ["gmail:read:email", "sheets:update:spreadsheet", "gmail:send:email"]
    first = signature_id_for(tokens)
    second = signature_id_for(list(tokens))
    assert first == second
    assert first == f"sig_{signature_hash(tokens)}"
    instances = [
        _gmail_sheets_gmail(index=0, user_id="u_a", start_second=0),
        _gmail_sheets_gmail(index=1, user_id="u_b", start_second=1_200),
    ]
    a = build_activity_atlas(instances)
    b = build_activity_atlas(list(reversed(instances)))
    assert a.signature_catalog[0].signature_id == b.signature_catalog[0].signature_id


def test_seed_events_convert_to_atlas(seed_events):
    atlas = build_activity_atlas_from_events(seed_events)
    dumped = atlas_as_jsonable(atlas)
    assert atlas.summary.instance_count > 0
    assert atlas.summary.event_count > 0
    assert atlas.signature_catalog
    assert atlas.candidate_groups
    assert len(atlas.motif_catalog) <= 20
    assert len(atlas.signature_catalog) <= 40
    assert len(atlas.candidate_groups) <= 15
    assert len(atlas.sample_instances) <= 8
    blob = json.dumps(dumped)
    assert "ground_truth_workflow" not in blob
    for sample in atlas.sample_instances:
        assert "payload" not in sample.model_dump()


def test_example_instance_ids_are_capped():
    instances = [
        _gmail_sheets_gmail(index=i, user_id="u_a", start_second=i * 1_200) for i in range(12)
    ]
    atlas = build_activity_atlas(
        instances, limits=AtlasLimits(max_example_ids_per_signature=8)
    )
    assert len(atlas.signature_catalog[0].example_instance_ids) == 8


def test_workflow_hint_is_not_a_field_name():
    inst = _gmail_sheets_gmail(
        index=0,
        user_id="u_a",
        start_second=0,
        payload={"workflow_hint": "do-not-emit", "vendor": True},
    )
    atlas = build_activity_atlas([inst])
    names = atlas.field_name_histograms.get("gmail:read:email", [])
    assert "workflow_hint" not in names
    assert "vendor" in names
    assert "do-not-emit" not in json.dumps(atlas_as_jsonable(atlas))
