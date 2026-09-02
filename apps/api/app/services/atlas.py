"""Build a compact Activity Atlas from sessionised task instances.

This module does not decide that a pattern is a repetitive workflow. It
compresses already-computed signatures, counts, and clustering *candidates*
into a bounded JSON document for a future Agent.

It does not call an LLM. It does not write Cluster rows. It does not change
sessionisation, clustering, or scoring.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from app.schemas.atlas import (
    ActivityAtlas,
    AppTransition,
    AtlasSummary,
    CandidateGroup,
    MotifCatalogEntry,
    SampleInstance,
    SignatureCatalogEntry,
    TimeWindow,
)
from app.services.clustering import cluster_instances
from app.services.motifs import (
    DEFAULT_MAX_MOTIF_LENGTH,
    DEFAULT_MAX_SCAN_LENGTH,
    MIN_MOTIF_LENGTH,
    count_nonoverlapping,
    discover_tandem_motifs,
    motif_id_for,
)
from app.services.sessioniser import Instance, signature_hash

# Payload keys that are seed/test labels, not observed field names.
_SKIP_FIELD_KEYS = frozenset({"workflow_hint"})

_EVIDENCE_ONLY_NOTE = (
    "This atlas is compressed evidence only; it does not decide that a pattern "
    "is a repetitive workflow."
)
_MOTIF_EVIDENCE_NOTE = (
    "motif_catalog lists repeated token subsequences and their counts; "
    "it does not decide that a pattern is a repetitive workflow."
)


@dataclass(frozen=True)
class AtlasLimits:
    """Hard caps so the atlas stays small enough for a later LLM prompt."""

    max_signatures: int = 40
    max_motifs: int = 20
    max_candidate_groups: int = 15
    max_example_ids_per_signature: int = 8
    max_sample_instances: int = 8
    max_field_names_per_token: int = 24
    max_app_transitions: int = 40
    min_motif_length: int = MIN_MOTIF_LENGTH
    max_motif_length: int = DEFAULT_MAX_MOTIF_LENGTH
    max_motif_scan_length: int = DEFAULT_MAX_SCAN_LENGTH


def signature_id_for(tokens: Sequence[str]) -> str:
    """Stable id for an exact collapsed signature. Reuses the F2 hash."""
    return f"sig_{signature_hash(tokens)}"


def build_activity_atlas(
    instances: Sequence[Instance],
    *,
    limits: AtlasLimits | None = None,
) -> ActivityAtlas:
    """Compress task instances into an Activity Atlas.

    Signatures come from each instance's existing collapsed signature, not from
    re-tokenising the event log. Events are read only for session ids, app
    transitions, field *names*, and event counts.
    """
    caps = limits or AtlasLimits()
    notes = [_EVIDENCE_ONLY_NOTE, _MOTIF_EVIDENCE_NOTE]

    if not instances:
        return ActivityAtlas(evidence_notes=notes)

    catalog = _signature_catalog(instances, caps)
    kept_signature_ids = {entry.signature_id for entry in catalog}
    candidates = _candidate_groups(instances, caps)
    samples = _sample_instances(instances, catalog, caps)
    histograms = _field_name_histograms(instances, kept_signature_ids, caps)
    motifs = _motif_catalog(instances, caps)

    return ActivityAtlas(
        time_window=_time_window(instances),
        summary=_summary(instances),
        signature_catalog=catalog,
        candidate_groups=candidates,
        motif_catalog=motifs,
        app_transitions=_app_transitions(instances, caps),
        field_name_histograms=histograms,
        sample_instances=samples,
        evidence_notes=notes,
    )


def build_activity_atlas_from_events(events: Sequence, *, limits: AtlasLimits | None = None) -> ActivityAtlas:
    """Sessionise events with the existing sessioniser, then build an atlas."""
    from app.services.sessioniser import sessionise

    return build_activity_atlas(sessionise(events), limits=limits)


def _time_window(instances: Sequence[Instance]) -> TimeWindow:
    starts = [i.started_at for i in instances]
    ends = [i.ended_at for i in instances]
    return TimeWindow(start=min(starts), end=max(ends))


def _summary(instances: Sequence[Instance]) -> AtlasSummary:
    users = {i.user_id for i in instances}
    session_ids: set[str] = set()
    event_count = 0
    missing_session = 0
    for instance in instances:
        event_count += len(instance.events)
        seen_in_instance = False
        for event in instance.events:
            if event.session_id:
                session_ids.add(event.session_id)
                seen_in_instance = True
        if not seen_in_instance:
            missing_session += 1
    return AtlasSummary(
        event_count=event_count,
        instance_count=len(instances),
        distinct_users=len(users),
        distinct_sessions=len(session_ids) + missing_session,
    )


def _signature_catalog(
    instances: Sequence[Instance], caps: AtlasLimits
) -> list[SignatureCatalogEntry]:
    grouped: dict[str, list[Instance]] = defaultdict(list)
    tokens_by_id: dict[str, list[str]] = {}
    for instance in instances:
        tokens = list(instance.signature)
        sid = signature_id_for(tokens)
        grouped[sid].append(instance)
        tokens_by_id[sid] = tokens

    entries: list[SignatureCatalogEntry] = []
    for sid, members in grouped.items():
        durations = sorted(m.duration_ms for m in members)
        example_ids = [
            m.id
            for m in sorted(members, key=lambda i: (i.started_at, i.id))[
                : caps.max_example_ids_per_signature
            ]
        ]
        entries.append(
            SignatureCatalogEntry(
                signature_id=sid,
                tokens=tokens_by_id[sid],
                occurrence_count=len(members),
                distinct_users=len({m.user_id for m in members}),
                median_duration_ms=_median_int(durations),
                example_instance_ids=example_ids,
            )
        )

    entries.sort(key=lambda e: (-e.occurrence_count, e.signature_id))
    return entries[: caps.max_signatures]


def _candidate_groups(
    instances: Sequence[Instance], caps: AtlasLimits
) -> list[CandidateGroup]:
    """Reuse F2 clustering with no Discovery occurrence floor."""
    groups = cluster_instances(instances)
    used_ids: set[str] = set()
    out: list[CandidateGroup] = []
    for group in groups:
        member_ids = sorted({signature_id_for(i.signature) for i in group.instances})
        candidate_id = f"cand_{signature_hash(group.representative)}"
        if candidate_id in used_ids:
            suffix = 1
            while f"{candidate_id}_{suffix}" in used_ids:
                suffix += 1
            candidate_id = f"{candidate_id}_{suffix}"
        used_ids.add(candidate_id)
        out.append(
            CandidateGroup(
                candidate_id=candidate_id,
                occurrence_count=group.size,
                medoid_signature=list(group.representative),
                member_signature_ids=member_ids,
            )
        )
    out.sort(key=lambda c: (-c.occurrence_count, c.candidate_id))
    return out[: caps.max_candidate_groups]


def _motif_catalog(
    instances: Sequence[Instance], caps: AtlasLimits
) -> list[MotifCatalogEntry]:
    """Aggregate tandem-discovered motifs across instances. Evidence only."""
    discovered: set[tuple[str, ...]] = set()
    for instance in instances:
        found = discover_tandem_motifs(
            instance.signature,
            min_len=caps.min_motif_length,
            max_len=caps.max_motif_length,
            max_scan_length=caps.max_motif_scan_length,
        )
        discovered.update(found)

    entries: list[MotifCatalogEntry] = []
    for tokens in discovered:
        holders: list[Instance] = []
        total = 0
        for instance in instances:
            hits = count_nonoverlapping(instance.signature, tokens)
            if hits:
                total += hits
                holders.append(instance)
        if total < 2:
            continue
        holders.sort(key=lambda i: (i.started_at, i.id))
        entries.append(
            MotifCatalogEntry(
                motif_id=motif_id_for(tokens),
                tokens=list(tokens),
                length=len(tokens),
                instance_support=len(holders),
                total_occurrences=total,
                distinct_users=len({i.user_id for i in holders}),
                example_instance_ids=[
                    i.id for i in holders[: caps.max_example_ids_per_signature]
                ],
            )
        )

    # Deterministic ranking: occurrences, then instance support, then length.
    entries.sort(
        key=lambda e: (-e.total_occurrences, -e.instance_support, -e.length, e.motif_id)
    )
    return entries[: caps.max_motifs]


def _app_transitions(instances: Sequence[Instance], caps: AtlasLimits) -> list[AppTransition]:
    counts: Counter[tuple[str, str]] = Counter()
    for instance in instances:
        apps = [event.app for event in instance.events]
        for left, right in zip(apps, apps[1:], strict=False):
            if left and right and left != right:
                counts[(left, right)] += 1
    ranked = counts.most_common(caps.max_app_transitions)
    return [
        AppTransition(from_app=src, to_app=dst, count=n) for (src, dst), n in ranked
    ]


def _field_name_histograms(
    instances: Sequence[Instance],
    kept_signature_ids: set[str],
    caps: AtlasLimits,
) -> dict[str, list[str]]:
    names: dict[str, set[str]] = defaultdict(set)
    for instance in instances:
        if signature_id_for(instance.signature) not in kept_signature_ids:
            continue
        for event in instance.events:
            token = event.step_token
            payload = event.payload or {}
            if not isinstance(payload, dict):
                continue
            for key in payload:
                if key in _SKIP_FIELD_KEYS or not isinstance(key, str):
                    continue
                names[token].add(key)
    return {
        token: sorted(keys)[: caps.max_field_names_per_token]
        for token, keys in sorted(names.items())
    }


def _sample_instances(
    instances: Sequence[Instance],
    catalog: Sequence[SignatureCatalogEntry],
    caps: AtlasLimits,
) -> list[SampleInstance]:
    """At most one sample per catalog signature, up to the global cap."""
    by_id = {i.id: i for i in instances}
    samples: list[SampleInstance] = []
    seen: set[str] = set()
    for entry in catalog:
        if len(samples) >= caps.max_sample_instances:
            break
        for instance_id in entry.example_instance_ids:
            instance = by_id.get(instance_id)
            if instance is None or instance.id in seen:
                continue
            samples.append(
                SampleInstance(
                    instance_id=instance.id,
                    signature=list(instance.signature),
                    duration_ms=instance.duration_ms,
                    user_id=instance.user_id,
                    started_at=instance.started_at,
                    event_count=len(instance.events),
                )
            )
            seen.add(instance.id)
            break
    return samples


def _median_int(values: Sequence[int]) -> int:
    if not values:
        return 0
    return int(statistics.median(values))


def atlas_as_jsonable(atlas: ActivityAtlas) -> dict:
    """JSON-ready dict using `from`/`to` keys for app transitions."""
    return atlas.model_dump(mode="json", by_alias=True)
