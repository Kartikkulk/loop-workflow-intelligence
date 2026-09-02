"""F2/F3/F4 — cluster listing, detail, SOP and automation generation."""

from __future__ import annotations

import statistics

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.llm.client import llm
from app.models.automation import Automation, TrustLevel
from app.models.cluster import Cluster, TaskInstance
from app.schemas.automations import AutomationDetail, GenerateAutomationRequest
from app.schemas.clusters import (
    ClusterDetail,
    ClusterList,
    ClusterSummary,
    ClusterUser,
    SignatureVariant,
    SopOut,
    StepNode,
    VarianceOut,
)
from app.services.generator import generate_flow, generate_sop
from app.services.ids import new_id
from app.services.sessioniser import signature_hash

router = APIRouter(prefix="/clusters", tags=["clusters"])


async def _automation_index(session: AsyncSession) -> dict[str, str]:
    result = await session.execute(select(Automation.cluster_id, Automation.id))
    return {cluster_id: automation_id for cluster_id, automation_id in result.all()}


def _to_summary(cluster: Cluster, automation_id: str | None) -> ClusterSummary:
    return ClusterSummary(
        id=cluster.id,
        name=cluster.name,
        description=cluster.description,
        signature=cluster.signature or [],
        apps=cluster.apps or [],
        instance_count=cluster.instance_count,
        distinct_users=cluster.distinct_users,
        user_ids=cluster.user_ids or [],
        teams=cluster.teams or [],
        median_duration_ms=cluster.median_duration_ms,
        instances_per_user_per_week=cluster.instances_per_user_per_week,
        annual_hours=cluster.annual_hours,
        is_organisational=cluster.is_organisational,
        context_switches_total=cluster.context_switches_total,
        interruption_tax_hours=cluster.interruption_tax_hours,
        automatability=cluster.automatability,
        potential=cluster.potential,
        potential_factors=list(cluster.potential_factors or []),
        variance_breakdown=VarianceOut(**(cluster.variance_breakdown or {})),
        build_effort=cluster.build_effort,
        priority=cluster.priority,
        do_not_automate=cluster.do_not_automate,
        reasoning=cluster.reasoning,
        has_automation=automation_id is not None,
        automation_id=automation_id,
    )


@router.get("", response_model=ClusterList)
async def list_clusters(session: AsyncSession = Depends(get_session)) -> ClusterList:
    """Detected workflows, split into recommended and not-recommended.

    Not-recommended clusters are returned as a first-class list, not an error
    state: knowing a task should stay human is a real result.
    """
    result = await session.execute(select(Cluster).order_by(Cluster.priority.desc()))
    clusters = list(result.scalars().all())
    index = await _automation_index(session)

    recommended = [
        _to_summary(c, index.get(c.id)) for c in clusters if not c.do_not_automate
    ]
    not_recommended = [
        _to_summary(c, index.get(c.id)) for c in clusters if c.do_not_automate
    ]

    return ClusterList(
        total=len(clusters),
        recommended=recommended,
        not_recommended=not_recommended,
        total_annual_hours=round(sum(c.annual_hours for c in clusters), 1),
        total_interruption_tax_hours=round(sum(c.interruption_tax_hours for c in clusters), 1),
    )


async def _get_cluster(session: AsyncSession, cluster_id: str) -> Cluster:
    cluster = await session.get(Cluster, cluster_id)
    if cluster is None:
        raise HTTPException(404, f"cluster {cluster_id} not found")
    return cluster


@router.get("/{cluster_id}", response_model=ClusterDetail)
async def get_cluster(
    cluster_id: str, session: AsyncSession = Depends(get_session)
) -> ClusterDetail:
    """One workflow, with its per-user breakdown, step graph and variants."""
    cluster = await _get_cluster(session, cluster_id)
    index = await _automation_index(session)

    result = await session.execute(
        select(TaskInstance).where(TaskInstance.cluster_id == cluster_id)
    )
    instances = list(result.scalars().all())

    # Per-user breakdown.
    by_user: dict[str, list[TaskInstance]] = {}
    for instance in instances:
        by_user.setdefault(instance.user_id, []).append(instance)

    users: list[ClusterUser] = []
    for user_id, user_instances in sorted(
        by_user.items(), key=lambda kv: -len(kv[1])
    ):
        median = int(statistics.median([i.duration_ms for i in user_instances]))
        weeks = max(cluster.instances_per_user_per_week, 0.01)
        users.append(
            ClusterUser(
                user_id=user_id,
                team=user_instances[0].team,
                instance_count=len(user_instances),
                median_duration_ms=median,
                annual_hours=round(median / 3_600_000 * weeks * 48, 1),
            )
        )

    # Step graph, including what else was observed at each position.
    signature = cluster.signature or []
    alternatives_by_position: dict[int, set[str]] = {}
    for instance in instances:
        for position, token in enumerate(instance.signature or []):
            alternatives_by_position.setdefault(position, set()).add(token)

    per_step_ms = int(cluster.median_duration_ms / max(len(signature), 1))
    step_graph: list[StepNode] = []
    for index_position, token in enumerate(signature):
        parts = token.split(":")
        alternatives = sorted(alternatives_by_position.get(index_position, set()) - {token})
        step_graph.append(
            StepNode(
                index=index_position,
                app=parts[0] if parts else "unknown",
                action=parts[1] if len(parts) > 1 else "unknown",
                object_type=parts[2] if len(parts) > 2 else "unknown",
                label=(parts[2] if len(parts) > 2 else token).replace("_", " "),
                median_duration_ms=per_step_ms,
                alternatives=alternatives[:5],
            )
        )

    # Distinct observed step orders.
    variant_counts: dict[str, tuple[list[str], int]] = {}
    for instance in instances:
        key = signature_hash(instance.signature or [])
        existing = variant_counts.get(key)
        variant_counts[key] = (
            list(instance.signature or []),
            (existing[1] if existing else 0) + 1,
        )
    total_instances = max(len(instances), 1)
    variants = [
        SignatureVariant(signature=sig, count=count, share=round(count / total_instances, 4))
        for sig, count in sorted(variant_counts.values(), key=lambda v: -v[1])[:8]
    ]

    summary = _to_summary(cluster, index.get(cluster.id))
    return ClusterDetail(
        **summary.model_dump(),
        users=users,
        step_graph=step_graph,
        variants=variants,
    )


@router.get("/{cluster_id}/sop", response_model=SopOut)
async def get_sop(
    cluster_id: str, session: AsyncSession = Depends(get_session)
) -> SopOut:
    """The Standard Operating Procedure for a workflow. Cached after first generation."""
    cluster = await _get_cluster(session, cluster_id)
    if not cluster.sop_markdown:
        cluster.sop_markdown = await generate_sop(cluster)
        await session.flush()
    return SopOut(
        cluster_id=cluster.id,
        name=cluster.name,
        markdown=cluster.sop_markdown,
        generated_by="llm" if llm.available else "heuristic",
    )


@router.get("/{cluster_id}/sop.md", response_class=PlainTextResponse)
async def download_sop(
    cluster_id: str, session: AsyncSession = Depends(get_session)
) -> PlainTextResponse:
    """The same SOP as a downloadable Markdown file."""
    cluster = await _get_cluster(session, cluster_id)
    if not cluster.sop_markdown:
        cluster.sop_markdown = await generate_sop(cluster)
        await session.flush()
    slug = cluster.name.lower().replace(" ", "-")[:60]
    return PlainTextResponse(
        cluster.sop_markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="sop-{slug}.md"'},
    )


@router.post("/{cluster_id}/generate-automation", response_model=AutomationDetail)
async def generate_automation(
    cluster_id: str,
    body: GenerateAutomationRequest = GenerateAutomationRequest(),
    session: AsyncSession = Depends(get_session),
) -> AutomationDetail:
    """Generate a runnable automation from a detected workflow."""
    cluster = await _get_cluster(session, cluster_id)

    if cluster.do_not_automate and not body.override_do_not_automate:
        raise HTTPException(
            409,
            {
                "message": "this workflow is flagged DO NOT AUTOMATE",
                "reasoning": cluster.reasoning,
                "automatability": cluster.automatability,
                "hint": "set override_do_not_automate to proceed anyway",
            },
        )

    existing = await session.execute(
        select(Automation).where(Automation.cluster_id == cluster_id)
    )
    automation = existing.scalars().first()

    flow, provenance = await generate_flow(cluster)

    if automation is None:
        automation = Automation(
            id=new_id("auto"),
            cluster_id=cluster.id,
            name=flow["name"],
            description=flow["description"],
            trigger=flow["trigger"],
            steps=flow["steps"],
            guards=flow["guards"],
            rules=[],
            # New automations start at SUGGEST. Nothing begins trusted.
            trust_level=TrustLevel.SUGGEST,
            generated_by=provenance,
            trust_history=[
                {"level": TrustLevel.SUGGEST.value, "reason": "automation generated from cluster"}
            ],
        )
        session.add(automation)
    else:
        automation.name = flow["name"]
        automation.description = flow["description"]
        automation.trigger = flow["trigger"]
        automation.steps = flow["steps"]
        automation.guards = flow["guards"]
        automation.generated_by = provenance

    await session.flush()

    from app.api.v1.automations import build_automation_detail

    return await build_automation_detail(session, automation)
