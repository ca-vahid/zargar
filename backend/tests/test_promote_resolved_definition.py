"""Promotion identity checks on isolated PostgreSQL; the analyst is a no-I/O spy.

Database guard is shared with the adjacent reconciliation test module. Run only
through the Codex isolated test wrapper, sequentially with the other review tests.
"""

import asyncio
import uuid
from types import SimpleNamespace

from sqlalchemy import delete

from zargar.db import make_engine, make_session_factory
from zargar.models import Base, ChatThread, TechniqueRun, TechniqueSweep, TechniqueWalkforward
from zargar.technique.rulebook import session_bounds
from zargar.technique.service import TechniqueService

from .test_reconcile_postgres_atomicity import _safe_database_url


async def _exercise(*, with_vision):
    db = make_engine(_safe_database_url())
    sf = make_session_factory(db)
    token = uuid.uuid4().hex
    prior_id = "review-prior-" + token
    sweep_id = "review-sweep-" + token
    row_id = "review-walk-" + token
    fresh_id = "review-fresh-" + token
    symbol = "TEST" + token[:8].upper()
    day = "2026-09-11"
    _, close = session_bounds(day)
    requested = {"min_risk_reward": 4.0, "long_only": False}
    calls = []
    try:
        async with db.begin() as conn:
            await conn.run_sync(lambda sync: Base.metadata.create_all(
                sync, tables=[ChatThread.__table__, TechniqueRun.__table__,
                              TechniqueSweep.__table__, TechniqueWalkforward.__table__]
            ))
        async with sf() as session:
            session.add(TechniqueRun(
                id=prior_id, symbol=symbol, as_of=close + 1, primary_tf="1m",
                technique="enhanced_market", mode="plan", status="done", verdict="plan",
                result={"passes": [{"name": "entry"}], "plan": {"identity": "older-base"}},
                config={"overrides": {"thresholds": {}},
                        "thresholds": {"min_risk_reward": 3.0, "long_only": False},
                        "processVersion": "older-definition"},
            ))
            session.add(TechniqueSweep(
                id=sweep_id, technique="enhanced_market", symbols=[symbol],
                start=day, end=day, status="done",
                params={"overrides": {}, "thresholds": requested,
                        "structureTfs": ["30m", "1h"], "triggerTf": "1m",
                        "processVersion": "selected-definition"},
            ))
            await session.flush()
            session.add(TechniqueWalkforward(
                id=row_id, sweep_id=sweep_id, symbol=symbol, session=day,
                plan_for="2026-09-14", plan={"identity": "selected-definition"},
            ))
            await session.commit()

        async def analyze(symbol_arg, **kwargs):
            calls.append(kwargs)
            return {"id": fresh_id, "symbol": symbol_arg, "status": "done"}

        svc = SimpleNamespace(engine=SimpleNamespace(sf=sf), analyze=analyze)
        result = await TechniqueService.promote(
            svc, sweep_id, symbol, day, with_vision=with_vision, wait=True
        )
        return result, calls, requested, prior_id
    finally:
        async with sf() as session:
            await session.execute(delete(TechniqueWalkforward).where(TechniqueWalkforward.id == row_id))
            await session.execute(delete(TechniqueSweep).where(TechniqueSweep.id == sweep_id))
            await session.execute(delete(TechniqueRun).where(TechniqueRun.id.in_([prior_id, fresh_id])))
            await session.commit()
        await db.dispose()


def test_equal_overlay_does_not_reuse_a_different_resolved_base():
    result, calls, _, prior_id = asyncio.run(_exercise(with_vision=True))
    assert result["id"] != prior_id and not result.get("reused"), (
        "Two empty overlays can refer to different saved base thresholds; "
        "reuse must match the selected resolved definition."
    )
    assert calls, "A mismatched cached analyst read must not silently satisfy promotion"


def test_fresh_promotion_carries_saved_resolved_thresholds():
    _, calls, requested, _ = asyncio.run(_exercise(with_vision=False))
    assert calls
    assert calls[0].get("thresholds_override") == requested, (
        "Reapplying an empty delta to today's defaults does not reproduce "
        "the selected sweep's saved resolved threshold values."
    )
