"""Coverage accounting tests.

Coverage is the headline number on the ROI screen, so the ways it could be
quietly overstated are worth pinning down explicitly.
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.automation import Automation, TrustLevel
from app.models.governance import ExceptionCase
from app.services.exception_learning import recompute_coverage, routes_to_human, signature_key
from app.services.ids import new_id


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _automation(session, **kwargs) -> Automation:
    automation = Automation(
        id=new_id("auto"),
        cluster_id="clu_test",
        name="test",
        trigger={},
        steps=[],
        guards={},
        rules=[],
        trust_level=TrustLevel.SHADOW,
        **kwargs,
    )
    session.add(automation)
    await session.flush()
    return automation


def test_routes_to_human_classification():
    for action in ("route_to_manager", "escalate", "manual review", "needs approval", "hold"):
        assert routes_to_human(action), action
    for action in ("approve", "reject", "post_to_ledger", "send_confirmation"):
        assert not routes_to_human(action), action


def test_signature_key_buckets_by_shape_not_value():
    """Grouping on raw amounts would never find three matching cases."""
    a = signature_key({"amount": 2_000_000})
    b = signature_key({"amount": 3_500_000})
    assert a == b == "amount_over_10k"
    assert signature_key({"amount": 1000}) != a
    assert "foreign_currency" in signature_key({"amount": 1000, "currency": "EUR"})
    assert signature_key({}) == "unclassified"


async def test_coverage_is_zero_without_evidence(session):
    automation = await _automation(session)
    assert await recompute_coverage(session, automation) == 0.0


async def test_coverage_reflects_guard_holds(session):
    """The core fix: withheld runs must count against coverage."""
    automation = await _automation(session, replay_total=773, replay_human_count=113)
    coverage = await recompute_coverage(session, automation)
    assert coverage == round(1 - 113 / 773, 4)
    assert coverage < 1.0


async def test_coverage_prefers_the_replay_sample(session):
    """A 773-trigger backtest is better evidence than 5 shadow runs."""
    automation = await _automation(
        session, replay_total=773, replay_human_count=113, shadow_run_count=5
    )
    coverage = await recompute_coverage(session, automation)
    assert coverage == round(1 - 113 / 773, 4)


async def test_perfect_replay_gives_full_coverage(session):
    automation = await _automation(session, replay_total=100, replay_human_count=0)
    assert await recompute_coverage(session, automation) == 1.0


async def test_human_routing_rule_earns_no_coverage(session):
    """A rule that routes to a manager still requires a manager."""
    automation = await _automation(session, replay_total=100, replay_human_count=20)
    baseline = await recompute_coverage(session, automation)

    for _ in range(3):
        session.add(
            ExceptionCase(
                id=new_id("exc"),
                automation_id=automation.id,
                reason="guard held",
                input_features={"amount": 2_000_000},
                signature_key="amount_over_10k",
                status="resolved",
                human_decision="route_to_manager",
            )
        )
    automation.rules = [
        {
            "condition": "amount > 1000000",
            "action": "route_to_manager",
            "source": "learned",
            "signature_key": "amount_over_10k",
        }
    ]
    await session.flush()
    assert await recompute_coverage(session, automation) == baseline


async def test_autonomous_rule_earns_coverage_back(session):
    """Encoding a decision the automation can now make itself is real coverage."""
    automation = await _automation(session, replay_total=100, replay_human_count=20)
    baseline = await recompute_coverage(session, automation)

    for _ in range(3):
        session.add(
            ExceptionCase(
                id=new_id("exc"),
                automation_id=automation.id,
                reason="guard held",
                input_features={"amount": 2_000_000},
                signature_key="amount_over_10k",
                status="resolved",
                human_decision="approve",
            )
        )
    automation.rules = [
        {
            "condition": "amount > 1000000",
            "action": "approve",
            "source": "learned",
            "signature_key": "amount_over_10k",
        }
    ]
    await session.flush()
    improved = await recompute_coverage(session, automation)
    assert improved > baseline
    assert improved <= 1.0


async def test_coverage_never_exceeds_one(session):
    automation = await _automation(session, replay_total=10, replay_human_count=10)
    for _ in range(50):
        session.add(
            ExceptionCase(
                id=new_id("exc"),
                automation_id=automation.id,
                reason="x",
                input_features={},
                signature_key="k",
                status="resolved",
                human_decision="approve",
            )
        )
    automation.rules = [
        {"condition": "x > 1", "action": "approve", "source": "learned", "signature_key": "k"}
    ]
    await session.flush()
    assert 0.0 <= await recompute_coverage(session, automation) <= 1.0
