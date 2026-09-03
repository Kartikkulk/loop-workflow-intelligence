"""Orchestrates the full detection pass: events -> instances -> clusters -> scores.

Kept as one explicit function rather than spread across the API layer so the
same pass runs identically from the seed script, the upload endpoint and the
tests.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.automation import Automation
from app.models.cluster import Cluster, TaskInstance
from app.models.event import Event
from app.services.clustering import ClusterResult, cluster_instances
from app.services.scoring import discovery_confidence, score_cluster, variance_as_dict
from app.services.sessioniser import Instance, sessionise, signature_hash
from app.services.variables import METADATA_KEYS
from app.services.variables import detect as detect_variables

logger = logging.getLogger("loop.pipeline")



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


def field_name_for(step_token: str, key: str) -> str:
    """Name a step's field after what it holds, not after the column it arrived in.

    A UI collector labels every captured datum `value`, so a ten-step workflow
    produced ten fields all called `value`. They then collide: each step's
    output overwrites the last, and a later step depending on `value` resolves
    to whichever step ran most recently rather than the one it read from. Naming
    by the step's object type — the `value` on `browser:read:customer` is the
    customer — makes the dependency graph mean what it says, and matches the
    names variable detection gives the same fields.
    """
    if key not in ("value", "target"):
        return key
    parts = step_token.split(":")
    object_type = parts[2] if len(parts) > 2 else ""
    return object_type or key

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
                # Collector bookkeeping — which tab, which hostname, which DOM
                # control — describes how the observation was made, not what the
                # work moved. Letting it through made `domain` a step output and
                # then a dependency, so every run failed resolving a field no
                # step could ever produce.
                if key in METADATA_KEYS:
                    continue
                bucket.add(_FIELD_ALIASES.get(key, field_name_for(token, key)))
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
    min_instances = settings.effective_min_instances
    min_steps = settings.min_signature_steps
    groups = [
        g for g in groups if g.size >= min_instances and len(g.representative) >= min_steps
    ]
    logger.info(
        "detection: %d clusters above the floor (>=%d instances, >=%d steps, mode=%s)",
        len(groups),
        min_instances,
        min_steps,
        settings.discovery_mode,
    )

    # A rejected candidate must stay rejected across a re-detection. Cluster ids
    # are a deterministic function of the signature, so the same workflow keeps
    # the same id — capture which ids were dismissed before the wipe and
    # reinstate the flag on the rebuilt rows below.
    dismissed_before = await session.execute(select(Cluster.id).where(Cluster.dismissed.is_(True)))
    dismissed_ids = {row[0] for row in dismissed_before}

    # Replace rather than merge: detection is a pure function of the event log.
    await session.execute(delete(TaskInstance))
    await session.execute(delete(Cluster))
    await session.flush()

    # Scored first, and all at once. Each cluster's score costs one model call,
    # and running them in sequence made detection take as long as the slowest
    # model multiplied by the number of workflows found — two minutes for three
    # clusters on a local 8B, during which an upload appears to have hung. The
    # scores are independent of one another, so there was never a reason to wait
    # for one before starting the next.
    provisional_names = [
        _pretty_name(list(group.representative), "Repetitive workflow") for group in groups
    ]
    scores = await asyncio.gather(
        *(score_cluster(group, name) for group, name in zip(groups, provisional_names, strict=True))
    )
    logger.info("detection: scored %d clusters concurrently", len(scores))

    created: list[Cluster] = []
    used_ids: set[str] = set()
    for group, provisional_name, score in zip(groups, provisional_names, scores, strict=True):
        signature = list(group.representative)

        # Low-occurrence gate. In demo mode the instance floor is dropped to two
        # or three, so a weak floor must be balanced by a real signal: a couple
        # of runs only count as a pattern if they are genuinely alike and the
        # workflow is plausibly automatable. Two unrelated short tasks that fell
        # into one cluster clear the count but not this, and are dropped. This
        # gate never runs in production — those clusters already have dozens of
        # instances of statistical support.
        if settings.demo_mode and score.instance_count < settings.discovery_strong_occurrences:
            similarity = score.variance.sequence_similarity
            confidence = discovery_confidence(
                occurrences=score.instance_count,
                similarity=similarity,
                automatability=score.automatability,
            )
            if (
                similarity < settings.discovery_min_similarity
                or confidence < settings.discovery_min_confidence
            ):
                logger.info(
                    "detection: dropped low-occurrence candidate %r "
                    "(occurrences=%d, similarity=%.2f, confidence=%.2f) — "
                    "below the demo gate",
                    provisional_name,
                    score.instance_count,
                    similarity,
                    confidence,
                )
                continue

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

        # Which fields are inputs and which are constants is a property of the
        # observed runs, so it is computed here with detection rather than at
        # generation time — two generations of one cluster must not disagree
        # about what the workflow's parameters are.
        group_variables, group_constants = detect_variables(group.instances)

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
            variables=[v.as_dict() for v in group_variables],
            constants=[c.as_dict() for c in group_constants],
            build_effort=score.build_effort,
            priority=score.priority,
            do_not_automate=score.do_not_automate,
            reasoning=score.reasoning,
            evidence_level=score.evidence_level,
            requires_more_observation=score.requires_more_observation,
            dismissed=cluster_id in dismissed_ids,
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
