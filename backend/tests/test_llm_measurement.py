"""Codex audit finding 10: the shared LLM usage collector, and source_trust's
cohort/episode corrections (both flaws confirmed in the audit response)."""
import datetime as dt

import pytest
from sqlalchemy import select

from zargar.domain import new_id
from zargar.engine import Engine
from zargar.models import Event, ManagedPositionRow, Order
from zargar.research import llm_stats
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config


@pytest.fixture(autouse=True)
def clean_metrics(monkeypatch):
    # the collector is module-global and now WIRED into the analyst loop —
    # other test modules' runs would leak into these exact-count assertions
    monkeypatch.setattr(llm_stats, "_ACC", {})


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


async def test_collector_rolls_up_into_hook_stats(rig):
    llm_stats.record("extraction", model="m1", input_tokens=100, output_tokens=20,
                     stop_reason="end_turn", latency_ms=500)
    llm_stats.record("extraction", model="m1", input_tokens=50, output_tokens=10,
                     stop_reason="end_turn", latency_ms=200, retried=True)
    llm_stats.record("extraction", model="m1", invalid_output=True, annotation=True)
    llm_stats.record("appraise", model="m2", input_tokens=900, output_tokens=300,
                     stop_reason="max_tokens", latency_ms=1500)
    assert await llm_stats.flush(rig) == 1
    async with rig.sf() as session:
        row = (await session.execute(select(Event).where(
            Event.type == "TechniqueHookStats")
            .order_by(Event.id.desc()))).scalars().first()
    llm = row.payload["llm"]
    ext = llm["extraction"]
    # one logical request: attempt 2 is a retry, the invalid-output mark is an
    # ANNOTATION on attempts already counted (Codex M1) — never a third request
    assert ext["requests"] == 1 and ext["retries"] == 1
    assert ext["inputTokens"] == 150 and ext["invalidOutputs"] == 1
    assert llm["appraise"]["stops"] == {"max_tokens": 1}
    assert row.payload["technique"] == "tip" and row.payload["date"]
    # flushed = cleared
    assert await llm_stats.flush(rig) == 0


async def test_source_trust_ignores_shadow_and_archived_closed_rows(rig):
    svc = rig.signals_service
    shadow = await svc.shadow_portfolio("CohortSrc", "immediate")
    sim_pid = next(p["id"] for p in rig.positions.portfolios() if p["kind"] == "sim")

    def closed(pid, sym):
        return ManagedPositionRow(
            id=new_id(), technique="tip", symbol=sym, portfolio_id=pid,
            status="closed", tags=["source:CohortSrc"], config={}, legs=[],
            state={"realizedPnl": 25.0})
    async with rig.sf() as session:
        session.add(closed(shadow["id"], "SHDW"))       # research noise
        session.add(closed(sim_pid, "REAL"))            # the real record
        await session.commit()
    trust = await svc.source_trust("CohortSrc")
    assert trust["closed"] == {"graded": 1, "hits": 1}   # shadow row excluded


async def test_immediate_lane_ages_by_holding_episode(rig):
    svc = rig.signals_service
    shadow = await svc.shadow_portfolio("EpisodeSrc", "immediate")
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)
    fresh = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)

    def order(side, ts):
        return Order(id=new_id(), portfolio_id=shadow["id"], symbol="EP",
                     sec_type="STK", side=side, qty=10.0, order_type="MKT",
                     status="FILLED", filled_qty=10.0, avg_fill_price=10.0,
                     created_at=ts)
    async with rig.sf() as session:
        # an OLD round trip (episode closed), then a FRESH re-entry
        session.add(order("BUY", old))
        session.add(order("SELL", old + dt.timedelta(days=1)))
        session.add(order("BUY", fresh))
        await session.commit()
    # give the shadow book a live position + a mark
    from zargar.domain import Quote
    rig.positions._positions[(shadow["id"], "EP", "STK")] = {
        "portfolioId": shadow["id"], "symbol": "EP", "secType": "STK",
        "qty": 10.0, "avgCost": 10.0, "realizedPnl": 0.0}
    rig.quotes.on_quote(Quote(symbol="EP", bid=11.9, ask=12.1, last=12.0,
                              bid_size=10, ask_size=10))
    trust = await svc.source_trust("EpisodeSrc")
    # the CURRENT episode is 30 minutes old — the old episode's age must not
    # qualify it as aged (the audit's re-entry flaw)
    assert trust["shadowImmediate"] == {"graded": 0, "hits": 0}
