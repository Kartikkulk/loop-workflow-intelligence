"""Orchestrates the full detection pass: events -> instances -> clusters -> scores.

Kept as one explicit function rather than spread across the API layer so the
same pass runs identically from the seed script, the upload endpoint and the
tests.
"""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import Automation
from app.models.cluster import Cluster, TaskInstance
from app.models.event import Event
from app.services.clustering import ClusterResult, cluster_instances
from app.services.scoring import score_cluster, variance_as_dict
from app.services.sessioniser import Instance, sessionise, signature_hash

logger = logging.getLogger("loop.pipeline")

# A workflow seen fewer times than this is not yet an opportunity.
#
# The floor is about statistical support, not tidiness. Annual hours are
# projected from an observed weekly frequency, and a dozen observations spread
# over a quarter gives a frequency estimate too noisy to put a number on. It
# also keeps the ranking free of one-off fragments that would bury real signal.
MIN_INSTANCES = 15

# A two-step signature is almost always a truncation artefact: a longer workflow
# that got cut in half because an unrelated event landed in the middle of it.
# Surfacing those as separate opportunities double-counts the same work and
# clutters the ranking with 2-hour "workflows".
MIN_SIGNATURE_STEPS = 3


# Above this step-order entropy, a cluster has no stable first or last step, so
# naming it "X to Y" would be arbitrary rather than descriptive.
_UNSTABLE_ORDER_ENTROPY = 0.6

_STOPWORDS = frozenset({"the", "a", "an", "new", "my", "item", "record", "unknown"})


def cluster_id_for(signature: list[str]) -> str:
    """A deterministic cluster id derived from its representative signature.

    Detection is a pure function of the event log, so its output ids must be too.
    Random ids broke that: re-running detection (via redetect, upload, a source
    revoke or an account sync) minted fresh cluster ids and left every existing
    automation pointing at a cluster that no longer existed — so "View workflow"
    404'd. Hashing the signature makes the same workflow keep the same id across
    runs, which is what keeps an automation linked to its source workflow.
    """
    digest = hashlib.sha256("|".join(signature).encode("utf-8")).hexdigest()
    return f"clu_{digest[:12]}"


def _object_types(signature: list[str]) -> list[str]:
    out = []
    for token in signature:
        parts = token.split(":")
        if len(parts) > 2 and parts[2]:
            out.append(parts[2])
    return out


def _subject_name(object_types: list[str], fallback: str) -> str:
    """Name a cluster by its subject matter rather than by its step order.

    Used for high-variance workflows, where the sequence genuinely differs every
    time. The most common leading word across the object types is what the work
    is *about*: `escalation_email`, `escalation_reply` and `escalation_tracker`
    all point at "escalation", even when the order they appear in does not
    repeat.

    Counted across every instance in the cluster, not just the representative
    signature. A high-variance cluster's representative covers only a fraction
    of the steps the workflow actually touches, which is precisely why its order
    is unreliable in the first place.
    """
    counts: dict[str, int] = {}
    for object_type in object_types:
        head = object_type.split("_")[0].lower()
        if head and head not in _STOPWORDS:
            counts[head] = counts.get(head, 0) + 1
    if not counts:
        return fallback
    best = max(counts.items(), key=lambda kv: kv[1])
    if best[1] < 2:
        return fallback
    return f"{best[0].title()} handling"


def cluster_object_types(group: ClusterResult) -> list[str]:
    """Every object type observed anywhere in the cluster."""
    return [event.object_type for instance in group.instances for event in instance.events]


def _pretty_name(
    signature: list[str],
    fallback: str,
    entropy: float = 0.0,
    object_types: list[str] | None = None,
) -> str:
    """A readable workflow name.

    Linear workflows are named by where they start and end. High-variance ones
    are named by their subject, because they have no reliable start or end.
    """
    if not signature:
        return fallback
    if entropy > _UNSTABLE_ORDER_ENTROPY:
        return _subject_name(object_types or _object_types(signature), fallback)

    first = signature[0].split(":")
    last = signature[-1].split(":")
    start = first[2].replace("_", " ") if len(first) > 2 else first[0]
    end = last[2].replace("_", " ") if len(last) > 2 else last[0]
    if start == end:
        return f"{start.title()} handling"
    return f"{start.title()} to {end.replace('_', ' ')}"


# Fields that exist only because a human made a decision. An automation must
# never treat these as inputs it can read, or replay accuracy becomes circular.
DECISION_FIELDS = frozenset({"status", "amount_inr", "approval", "note"})

# Source systems rename columns; these all mean the same field.
_FIELD_ALIASES = {"Vendor": "vendor", "Supplier Name": "vendor"}


def observed_fields_by_token(group: ClusterResult) -> dict[str, list[str]]:
    """Collect the payload keys observed for each step token in a cluster.

    Keyed by token rather than by position because the representative signature
    is interruption-collapsed while the raw events are not, so positional
    indices would not line up.
    """
    collected: dict[str, set[str]] = {}
    for instance in group.instances:
        for event in instance.events:
            token = event.step_token
            bucket = collected.setdefault(token, set())
            for key in (event.payload or {}):
                if key == "workflow_hint":
                    continue
                bucket.add(_FIELD_ALIASES.get(key, key))
    return {token: sorted(keys) for token, keys in collected.items()}


def _describe(signature: list[str], score) -> str:
    apps = " → ".join(dict.fromkeys(s.split(":")[0] for s in signature))
    return (
        f"{len(signature)} steps across {apps}. Observed {score.instance_count} times "
        f"by {score.distinct_users} employee(s)."
    )


async def run_detection(session: AsyncSession) -> list[Cluster]:
    """Re-run detection over every stored event, replacing prior clusters.

    Idempotent by design: running it twice produces the same clusters, which is
    what makes `make demo` able to reset to a known-good state.
    """
    result = await session.execute(select(Event).order_by(Event.timestamp))
    events = list(result.scalars().all())
    if not events:
        return []

    instances: list[Instance] = sessionise(events)
    logger.info("detection: %d events -> %d task instances", len(events), len(instances))

    groups: list[ClusterResult] = cluster_instances(instances)
    groups = [
        g
        for g in groups
        if g.size >= MIN_INSTANCES and len(g.representative) >= MIN_SIGNATURE_STEPS
    ]
    logger.info(
        "detection: %d clusters above the floor (>=%d instances, >=%d steps)",
        len(groups),
        MIN_INSTANCES,
        MIN_SIGNATURE_STEPS,
    )

    # Replace rather than merge: detection is a pure function of the event log.
    await session.execute(delete(TaskInstance))
    await session.execute(delete(Cluster))
    await session.flush()

    created: list[Cluster] = []
    used_ids: set[str] = set()
    for group in groups:
        signature = list(group.representative)
        # Scored first: the final name depends on how stable the step order
        # turns out to be, which scoring is what measures.
        provisional_name = _pretty_name(signature, "Repetitive workflow")
        score = await score_cluster(group, provisional_name)
        name = _pretty_name(
            signature,
            "Repetitive workflow",
            entropy=score.variance.step_order_entropy,
            object_types=cluster_object_types(group),
        )

        # Deterministic id from the signature; disambiguate on the rare chance
        # two clusters share a representative signature in the same pass.
        cluster_id = cluster_id_for(signature)
        if cluster_id in used_ids:
            suffix = 1
            while f"{cluster_id}_{suffix}" in used_ids:
                suffix += 1
            cluster_id = f"{cluster_id}_{suffix}"
        used_ids.add(cluster_id)

        cluster = Cluster(
            id=cluster_id,
            name=name,
            description=_describe(signature, score),
            signature=signature,
            apps=list(dict.fromkeys(s.split(":")[0] for s in signature)),
            instance_count=score.instance_count,
            distinct_users=score.distinct_users,
            user_ids=sorted({i.user_id for i in group.instances}),
            teams=sorted({i.team for i in group.instances}),
            median_duration_ms=score.median_duration_ms,
            instances_per_user_per_week=score.instances_per_user_per_week,
            annual_hours=score.annual_hours,
            is_organisational=score.is_organisational,
            context_switches_total=score.context_switches_total,
            interruption_tax_hours=score.interruption_tax_hours,
            automatability=score.automatability,
            potential=score.potential,
            potential_factors=score.potential_factors,
            variance_breakdown=variance_as_dict(score.variance),
            observed_fields=observed_fields_by_token(group),
            build_effort=score.build_effort,
            priority=score.priority,
            do_not_automate=score.do_not_automate,
            reasoning=score.reasoning,
        )
        session.add(cluster)
        created.append(cluster)

        for instance in group.instances:
            session.add(
                TaskInstance(
                    id=instance.id,
                    user_id=instance.user_id,
                    team=instance.team,
                    started_at=instance.started_at,
                    ended_at=instance.ended_at,
                    duration_ms=instance.duration_ms,
                    signature=instance.signature,
                    signature_hash=signature_hash(instance.signature),
                    event_ids=instance.event_ids,
                    context_switches=instance.context_switches,
                    cluster_id=cluster.id,
                    ground_truth_workflow=instance.ground_truth_workflow,
                )
            )

    await session.flush()

    await _relink_orphaned_automations(session, created)

    created.sort(key=lambda c: c.priority, reverse=True)
    return created


async def _relink_orphaned_automations(
    session: AsyncSession, clusters: list[Cluster]
) -> None:
    """Re-point automations whose cluster no longer exists to a matching cluster.

    Deterministic ids keep new automations linked across re-detection. This is
    the safety net for automations created before that fix, or for a cluster
    that genuinely changed shape between runs: rather than leave the automation
    orphaned (a dead "View workflow" link), match it to the surviving cluster
    with the most step tokens in common with its trigger/steps.
    """
    if not clusters:
        return

    live_ids = {c.id for c in clusters}
    result = await session.execute(select(Automation))
    automations = list(result.scalars().all())

    orphans = [a for a in automations if a.cluster_id not in live_ids]
    if not orphans:
        return

    def automation_tokens(automation: Automation) -> set[str]:
        tokens: set[str] = set()
        for step in automation.steps or []:
            app = step.get("app") or step.get("tool")
            action = step.get("action")
            if app and action:
                tokens.add(f"{app}:{action}")
        return tokens

    for automation in orphans:
        wanted = automation_tokens(automation)
        best: Cluster | None = None
        best_overlap = -1
        for cluster in clusters:
            cluster_tokens = {
                ":".join(token.split(":")[:2]) for token in (cluster.signature or [])
            }
            overlap = len(wanted & cluster_tokens)
            if overlap > best_overlap:
                best, best_overlap = cluster, overlap
        # Fall back to the highest-priority cluster if nothing overlapped, so an
        # automation is never left pointing at a nonexistent workflow.
        target = best or max(clusters, key=lambda c: c.priority)
        automation.cluster_id = target.id
        logger.info(
            "relinked automation %s -> cluster %s (overlap %d)",
            automation.id,
            target.id,
            max(best_overlap, 0),
        )

    await session.flush()
