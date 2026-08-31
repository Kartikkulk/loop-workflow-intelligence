"""Trust-ladder policy tests. The ladder must go down as reliably as up."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.base import Base
from app.models.automation import Automation, TrustLevel
from app.models.execution import ShadowRun
from app.services import trust
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


async def _automation(session: AsyncSession, level=TrustLevel.SHADOW) -> Automation:
    automation = Automation(
        id=new_id("auto"),
        cluster_id="clu_test",
        name="test automation",
        trigger={"type": "email_received"},
        steps=[{"id": "s1", "type": "read", "connector": "gmail", "outputs": [], "depends_on": []}],
        guards={},
        rules=[],
        trust_level=level,
    )
    session.add(automation)
    await session.flush()
    return automation


async def _add_runs(session, automation, scores, critical_at=()):
    for index, score in enumerate(scores, start=1):
        session.add(
            ShadowRun(
                id=new_id("shr"),
                automation_id=automation.id,
                predicted={},
                observed={},
                field_matches={},
                score=score,
                critical_mismatch=index in critical_at,
                sequence=index,
            )
        )
    await session.flush()


def test_ladder_order():
    assert TrustLevel.OBSERVE.rank == 0
    assert TrustLevel.AUTONOMOUS.rank == 4
    assert TrustLevel.OBSERVE.next_level() is TrustLevel.SUGGEST
    assert TrustLevel.AUTONOMOUS.next_level() is None
    assert TrustLevel.OBSERVE.previous_level() is None
    assert TrustLevel.SHADOW.previous_level() is TrustLevel.SUGGEST


async def test_cannot_promote_without_enough_runs(session):
    automation = await _automation(session)
    await _add_runs(session, automation, [1.0, 1.0])
    state = await trust.evaluate(session, automation)
    assert not state.can_promote
    assert any("more shadow run" in b for b in state.blockers)


async def test_cannot_promote_below_threshold(session):
    automation = await _automation(session)
    await _add_runs(session, automation, [0.7] * settings.shadow_min_runs)
    state = await trust.evaluate(session, automation)
    assert not state.can_promote
    assert any("rolling average" in b for b in state.blockers)


async def test_critical_mismatch_blocks_promotion_despite_high_average(session):
    """A single critical mismatch must outvote an otherwise perfect record."""
    automation = await _automation(session)
    await _add_runs(session, automation, [1.0, 1.0, 1.0, 1.0, 0.95], critical_at=(5,))
    state = await trust.evaluate(session, automation)
    assert state.average_score > settings.shadow_promotion_threshold
    assert not state.can_promote
    assert any("critical" in b for b in state.blockers)


async def test_promotion_succeeds_when_policy_is_satisfied(session):
    automation = await _automation(session)
    await _add_runs(session, automation, [1.0] * settings.shadow_min_runs)
    ok, message = await trust.apply_promotion(session, automation)
    assert ok
    assert automation.trust_level is TrustLevel.ASSIST
    assert "policy satisfied" in message
    assert automation.trust_history[-1]["level"] == "ASSIST"


async def test_blockers_explain_exactly_what_is_missing(session):
    """The disabled Promote button must be able to say why."""
    automation = await _automation(session)
    await _add_runs(session, automation, [1.0, 1.0, 1.0])
    state = await trust.evaluate(session, automation)
    assert f"needs {settings.shadow_min_runs - 3} more shadow run(s)" in state.blockers


async def test_critical_mismatch_forces_demotion(session):
    automation = await _automation(session, TrustLevel.ASSIST)
    await _add_runs(session, automation, [1.0, 1.0, 1.0, 1.0, 0.5], critical_at=(5,))
    state = await trust.enforce_policy(session, automation)
    assert automation.trust_level is TrustLevel.SHADOW
    assert state.level is TrustLevel.SHADOW
    assert automation.trust_history[-1]["level"] == "SHADOW"


async def test_old_critical_mismatch_does_not_force_demotion(session):
    """Demotion looks only at the recent window, or an automation could never
    recover from a single historical failure."""
    automation = await _automation(session, TrustLevel.ASSIST)
    await _add_runs(session, automation, [0.4, 1.0, 1.0, 1.0, 1.0], critical_at=(1,))
    await trust.enforce_policy(session, automation)
    assert automation.trust_level is TrustLevel.ASSIST


async def test_cannot_demote_below_observe(session):
    automation = await _automation(session, TrustLevel.OBSERVE)
    ok, message = await trust.apply_demotion(session, automation)
    assert not ok
    assert "already at OBSERVE" in message


async def test_cannot_promote_above_autonomous(session):
    automation = await _automation(session, TrustLevel.AUTONOMOUS)
    await _add_runs(session, automation, [1.0] * settings.shadow_min_runs)
    ok, message = await trust.apply_promotion(session, automation)
    assert not ok
    assert "AUTONOMOUS" in message


async def test_force_promotion_is_recorded_as_an_override(session):
    """An override must leave a trace, or the ladder is decorative."""
    automation = await _automation(session)
    await _add_runs(session, automation, [0.2])
    ok, message = await trust.apply_promotion(session, automation, force=True)
    assert ok
    assert "override" in message.lower()
    assert "override" in automation.trust_history[-1]["reason"].lower()


async def test_confidence_is_damped_while_the_window_fills(session):
    """One perfect run must not read as full confidence."""
    automation = await _automation(session)
    await _add_runs(session, automation, [1.0])
    state = await trust.evaluate(session, automation)
    assert state.confidence < 1.0
    assert state.confidence == pytest.approx(1.0 / settings.shadow_min_runs)
