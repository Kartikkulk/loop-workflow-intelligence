"""F3 — time cost, Interruption Tax, automatability, build effort, priority.

The automatability score is deliberately built from four *measured* signals plus
one LLM-scored one, and the measured signals dominate. A workflow is flagged
DO NOT AUTOMATE because its instances genuinely disagree with each other in the
log, not because a model was asked for an opinion about it.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from rapidfuzz.distance import Levenshtein

from app.config import settings
from app.llm.client import llm
from app.llm.tools import SCORE_VARIANCE
from app.services.clustering import ClusterResult
from app.services.sessioniser import count_context_switches, signature_hash, signature_text

_MS_PER_HOUR = 3_600_000


@dataclass
class VarianceBreakdown:
    """The components behind an automatability score, surfaced so the UI can
    explain the number rather than merely assert it."""

    step_order_entropy: float
    parameter_spread: float
    branch_count: int
    judgement_ratio: float
    variant_count: int
    dominant_variant_share: float
    #: Mean similarity of each run to the cluster's representative. See
    #: `sequence_similarity` for why this is not the inverse of entropy.
    sequence_similarity: float = 0.0


@dataclass
class ClusterScore:
    """Everything F3 computes for one cluster."""

    annual_hours: float
    median_duration_ms: int
    instances_per_user_per_week: float
    distinct_users: int
    instance_count: int
    context_switches_total: int
    interruption_tax_hours: float
    automatability: float
    variance: VarianceBreakdown
    build_effort: int
    priority: float
    do_not_automate: bool
    reasoning: str
    is_organisational: bool
    #: 0–100 ranking heuristic; see `automation_potential`. Defaulted, so it
    #: has to sit after every required field.
    potential: int = 0
    potential_factors: list[dict] = field(default_factory=list)


def shannon_entropy(counts: Sequence[int]) -> float:
    """Normalised Shannon entropy of a distribution, in [0, 1].

    0 means every instance followed the identical step order; 1 means the
    observed orders are uniformly spread with no dominant pattern.
    """
    total = sum(counts)
    if total <= 0 or len(counts) <= 1:
        return 0.0
    entropy = -sum((c / total) * math.log2(c / total) for c in counts if c > 0)
    return entropy / math.log2(len(counts))


def step_order_entropy(cluster: ClusterResult) -> tuple[float, int, float]:
    """Entropy over the distinct step sequences observed in a cluster.

    Returns (entropy, distinct variant count, share held by the most common).
    """
    counts: dict[str, int] = {}
    for instance in cluster.instances:
        counts[signature_hash(instance.signature)] = (
            counts.get(signature_hash(instance.signature), 0) + 1
        )
    values = list(counts.values())
    total = sum(values)
    dominant = max(values) / total if total else 0.0
    return shannon_entropy(values), len(values), dominant


def parameter_spread(cluster: ClusterResult) -> float:
    """How widely the payload values vary across instances, in [0, 1].

    Computed as the mean normalised cardinality of each payload key: a key
    holding the same value every time contributes 0, a key holding a distinct
    value every time contributes 1.
    """
    values_by_key: dict[str, list[str]] = {}
    for instance in cluster.instances:
        for event in instance.events:
            for key, value in (event.payload or {}).items():
                if isinstance(value, (str, int, float, bool)):
                    values_by_key.setdefault(key, []).append(str(value))
    if not values_by_key:
        return 0.0
    spreads = []
    for values in values_by_key.values():
        if len(values) < 2:
            continue
        spreads.append((len(set(values)) - 1) / (len(values) - 1))
    return float(statistics.fmean(spreads)) if spreads else 0.0


def sequence_similarity(cluster: ClusterResult) -> float:
    """How alike the observed runs are, as a mean similarity in [0, 1].

    Distinct from `step_order_entropy`, and both are needed. Entropy answers
    "how many different orders are there?", which goes high the moment a
    workflow has a few optional steps — nine variants over eighteen runs looks
    like chaos by that measure. This answers "how alike are two runs of it?",
    and two sequences differing by one inserted step are genuinely ~90% alike.

    Reporting only entropy made a workflow that a person would call obviously
    repetitive read as 9% similar, which is true of the orders and false of the
    work.
    """
    representative = cluster.representative
    if not representative or not cluster.instances:
        return 0.0
    scores = [
        Levenshtein.normalized_similarity(instance.signature, representative)
        for instance in cluster.instances
    ]
    return float(statistics.fmean(scores)) if scores else 0.0


#: Weights for Automation Potential. They sum to 1.0 before penalties.
#:
#: These are a judgement about what makes a workflow worth automating, not a
#: measurement. Similarity carries the most because a workflow done the same
#: way every time is the one a rule can actually cover; frequency and time
#: decide whether it is worth the trouble. They are declared here, in one
#: place, so the number can be argued with rather than only accepted.
POTENTIAL_WEIGHTS = {
    "similarity": 0.30,
    "frequency": 0.25,
    "time_impact": 0.20,
    "predictability": 0.15,
    "systems": 0.10,
}

#: Executions at which a workflow is as clearly repetitive as it needs to be.
#: Absolute count rather than a weekly rate: something seen twenty times is
#: repetitive whether that took a week or a quarter, and rate-scoring made a
#: plainly repetitive workflow look marginal because the window was long.
_FREQUENCY_CEILING = 20.0
#: Observed minutes of manual effort that count as full marks for time impact.
_EFFORT_CEILING_MINUTES = 120.0
#: Applications above which extra systems add no further score.
_SYSTEMS_CEILING = 4.0


def automation_potential(
    cluster: ClusterResult,
    *,
    similarity: float,
    dominant_share: float,
    executions: int,
    observed_minutes: float,
    apps: int,
    judgement: float,
    branches: int,
    steps: int,
    parameter_spread: float = 0.0,
) -> tuple[int, list[dict[str, object]]]:
    """Automation Potential, 0–100, with the arithmetic behind it.

    Returns the score and one row per factor, so the console can show how it
    was reached instead of asserting a number. This is a ranking heuristic and
    is labelled as one: it is useful for deciding what to look at first, and it
    is not a prediction of whether an automation will work.
    """
    # `predictability` is about the *values* a run carries, not its order.
    # Using the dominant-variant share here counted order variation twice —
    # once as similarity and again as predictability — and then a third time as
    # the branch penalty, so a workflow with two optional steps scored 31 when
    # a person would call it obviously automatable.
    parts = {
        "similarity": min(1.0, max(0.0, similarity)),
        "frequency": min(1.0, executions / _FREQUENCY_CEILING),
        "time_impact": min(1.0, observed_minutes / _EFFORT_CEILING_MINUTES),
        "predictability": min(1.0, max(0.0, 1.0 - parameter_spread)),
        "systems": min(1.0, apps / _SYSTEMS_CEILING),
    }

    rows: list[dict[str, object]] = []
    total = 0.0
    for name, weight in POTENTIAL_WEIGHTS.items():
        contribution = parts[name] * weight * 100
        total += contribution
        rows.append(
            {
                "factor": name,
                "measured": round(parts[name], 3),
                "weight": weight,
                "points": round(contribution, 1),
            }
        )

    # Penalties, subtracted after the weighted sum so they read as deductions
    # rather than being buried inside a factor.
    judgement_penalty = min(25.0, judgement * 100 * 0.4)
    # Scaled by how *dissimilar* the runs are. When they are 77% alike, most
    # differing positions are one optional step shifting everything after it,
    # not a genuine fork the automation has to decide between.
    branch_penalty = min(15.0, (branches / max(steps, 1)) * 15) * (1.0 - min(1.0, similarity))
    for name, points in (
        ("judgement", -judgement_penalty),
        ("branching", -branch_penalty),
    ):
        total += points
        rows.append({"factor": name, "measured": None, "weight": None, "points": round(points, 1)})

    return int(round(max(0.0, min(100.0, total)))), rows


def branch_count(cluster: ClusterResult) -> int:
    """Distinct step tokens observed at any single position in the sequence.

    A workflow whose third step is sometimes `sheets:create:row` and sometimes
    `erp:update:record` has a real branch, and branches are what make an
    automation hard to write correctly.

    Steps that are not part of this workflow are dropped before positions are
    compared. Someone breaking off mid-task to check something unrelated pushes
    every later step along by one; counting from the raw sequence read that
    shift as a branch at each shifted position, so a rigid three-step workflow
    reported four branches that no automation would ever have to handle.
    """
    own_steps = set(cluster.representative)
    by_position: dict[int, set[str]] = {}
    for instance in cluster.instances:
        sequence = [token for token in instance.signature if token in own_steps]
        for position, token in enumerate(sequence):
            by_position.setdefault(position, set()).add(token)
    return sum(1 for tokens in by_position.values() if len(tokens) > 1)


def free_text_ratio(cluster: ClusterResult) -> float:
    """Share of events carrying substantial free-text content.

    A cheap, purely measured proxy for judgement work, used as the fallback when
    no LLM key is configured.
    """
    total = 0
    texty = 0
    for instance in cluster.instances:
        for event in instance.events:
            total += 1
            payload = event.payload or {}
            for key, value in payload.items():
                if isinstance(value, str) and len(value) > 40 and key not in {"object_id", "id"}:
                    texty += 1
                    break
    return texty / total if total else 0.0


def _text_samples(cluster: ClusterResult, limit: int = 8) -> list[str]:
    """Sample of free-text payload content, for the LLM judgement scorer."""
    samples: list[str] = []
    for instance in cluster.instances:
        for event in instance.events:
            for value in (event.payload or {}).values():
                if isinstance(value, str) and len(value) > 30:
                    samples.append(value[:200])
                    if len(samples) >= limit:
                        return samples
    return samples


def median_duration_ms(cluster: ClusterResult) -> int:
    return int(statistics.median([i.duration_ms for i in cluster.instances]))


def instances_per_user_per_week(cluster: ClusterResult) -> float:
    """Observed frequency, per person, per week."""
    instances = cluster.instances
    users = {i.user_id for i in instances}
    if not users:
        return 0.0
    starts = [i.started_at for i in instances]
    span_days = max((max(starts) - min(starts)).days, 1)
    weeks = max(span_days / 7.0, 1.0 / 7.0)
    return len(instances) / len(users) / weeks


def annual_hours(cluster: ClusterResult) -> float:
    """Projected organisation-wide hours per year spent on this workflow."""
    median_hours = median_duration_ms(cluster) / _MS_PER_HOUR
    per_week = instances_per_user_per_week(cluster)
    users = len({i.user_id for i in cluster.instances})
    return median_hours * per_week * settings.working_weeks * users


def interruption_tax_hours(cluster: ClusterResult) -> tuple[int, float]:
    """The Interruption Tax: annualised cost of context switching.

    Reported separately from raw task time because it is invisible in a
    time-and-motion study. A four-minute task that bounces you between three
    applications nine times a day costs far more than thirty-six minutes.
    """
    switches_observed = sum(count_context_switches(i.events) for i in cluster.instances)
    instances = len(cluster.instances)
    if not instances:
        return 0, 0.0
    switches_per_instance = switches_observed / instances
    per_week = instances_per_user_per_week(cluster)
    users = len({i.user_id for i in cluster.instances})
    annual_switches = switches_per_instance * per_week * settings.working_weeks * users
    return switches_observed, annual_switches * settings.interruption_cost_minutes / 60.0


def _heuristic_variance(
    entropy: float, spread: float, branches: int, text_ratio: float, steps: int
) -> tuple[float, int, str]:
    """Deterministic judgement/effort estimate used when no LLM key is set."""
    judgement = min(1.0, text_ratio * 1.4)
    effort = max(1, min(5, 1 + steps // 3 + (1 if branches > 2 else 0)))

    # Appended to a framing sentence that already states the entropy, branch
    # count and judgement score, so restating those made the published reasoning
    # stutter. Describe the *character* of the work instead.
    #
    # Each phrasing must also stay factual rather than carrying a verdict: the
    # same sentence is appended to both a "recommended" and a "do not automate"
    # framing, and an editorialising clause ended up arguing against the very
    # recommendation it was attached to.
    if text_ratio > 0.35:
        reasoning = (
            f"{text_ratio:.0%} of the observed steps carry substantial free text, so part "
            "of the outcome depends on what was written rather than on which fields were "
            "filled."
        )
    elif branches > 3:
        reasoning = (
            f"{branches} step positions vary between instances, and each would need its "
            "own rule."
        )
    elif entropy > 0.6:
        reasoning = "No single step order dominates the cluster."
    else:
        reasoning = (
            "The steps repeat consistently, and what changes between instances is the "
            "kind of value a rule can supply."
        )
    return judgement, effort, reasoning


async def score_cluster(cluster: ClusterResult, name: str) -> ClusterScore:
    """Compute every F3 metric for one cluster."""
    entropy, variant_count, dominant_share = step_order_entropy(cluster)
    spread = parameter_spread(cluster)
    branches = branch_count(cluster)
    text_ratio = free_text_ratio(cluster)
    steps = len(cluster.representative)

    heuristic_judgement, heuristic_effort, heuristic_reasoning = _heuristic_variance(
        entropy, spread, branches, text_ratio, steps
    )

    scored = await llm.structured(
        prompt=llm.load_prompt(
            "score_variance",
            name=name,
            signature=signature_text(cluster.representative),
            samples="\n".join(f"- {s}" for s in _text_samples(cluster)) or "(none observed)",
            entropy=f"{entropy:.3f}",
            variants=variant_count,
            spread=f"{spread:.3f}",
        ),
        tool=SCORE_VARIANCE,
        fallback=lambda: {
            "judgement_ratio": heuristic_judgement,
            "build_effort": heuristic_effort,
            "reasoning": heuristic_reasoning,
        },
    )

    judgement = max(0.0, min(1.0, float(scored.get("judgement_ratio", heuristic_judgement))))
    build_effort = max(1, min(5, int(scored.get("build_effort", heuristic_effort))))
    llm_reasoning = str(scored.get("reasoning", heuristic_reasoning))

    # Automatability is the inverse of variance. Weights favour the structural
    # signals (entropy, branches) because those are directly measured from the
    # log; judgement is the softest input and is weighted accordingly.
    branch_penalty = min(1.0, branches / max(steps, 1))
    variance = (
        0.35 * entropy
        + 0.20 * spread
        + 0.20 * branch_penalty
        + 0.25 * judgement
    )
    automatability = max(0.0, min(1.0, 1.0 - variance))

    users = sorted({i.user_id for i in cluster.instances})
    switches, tax_hours = interruption_tax_hours(cluster)
    hours = annual_hours(cluster)
    priority = (hours + tax_hours) * automatability / build_effort

    do_not_automate = automatability < settings.do_not_automate_threshold

    similarity = sequence_similarity(cluster)
    potential, potential_factors = automation_potential(
        cluster,
        similarity=similarity,
        dominant_share=dominant_share,
        executions=len(cluster.instances),
        observed_minutes=sum(i.duration_ms for i in cluster.instances) / 60_000,
        apps=len({token.split(":")[0] for token in cluster.representative}),
        judgement=judgement,
        branches=branches,
        steps=steps,
        parameter_spread=spread,
    )
    if do_not_automate:
        reasoning = (
            f"Not recommended for automation. Step order varies across "
            f"{1 - dominant_share:.0%} of instances ({variant_count} distinct "
            f"sequences observed); {branches} branch point(s); judgement content "
            f"scored {judgement:.0%}. {llm_reasoning}"
        )
    else:
        reasoning = (
            f"{dominant_share:.0%} of instances follow an identical step order "
            f"across {len(users)} employee(s). {llm_reasoning}"
        )

    return ClusterScore(
        annual_hours=round(hours, 1),
        median_duration_ms=median_duration_ms(cluster),
        instances_per_user_per_week=round(instances_per_user_per_week(cluster), 2),
        distinct_users=len(users),
        instance_count=len(cluster.instances),
        context_switches_total=switches,
        interruption_tax_hours=round(tax_hours, 1),
        automatability=round(automatability, 3),
        potential=potential,
        potential_factors=potential_factors,
        variance=VarianceBreakdown(
            step_order_entropy=round(entropy, 3),
            parameter_spread=round(spread, 3),
            branch_count=branches,
            judgement_ratio=round(judgement, 3),
            variant_count=variant_count,
            dominant_variant_share=round(dominant_share, 3),
            sequence_similarity=round(similarity, 3),
        ),
        build_effort=build_effort,
        priority=round(priority, 1),
        do_not_automate=do_not_automate,
        reasoning=reasoning,
        is_organisational=len(users) > settings.org_user_threshold,
    )


def variance_as_dict(variance: VarianceBreakdown) -> dict:
    return asdict(variance)
