"""Independent EM execution acceptance cases. No database or live services.

Run against the pinned audit tree. Failures describe missing invariants, not
permission to alter runtime settings. Do not weaken these cases to turn green.
"""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from zargar.domain import Bar, Quote
from zargar.execution.exits import plan_exit
from zargar.execution.planrunner import ArmConfig, ArmedPlan, PlanRunner, Trade


def trade(**kwargs):
    base = dict(trigger_id="b1", kind="bounce", fired_ts=1, window="prime_open",
                entry=100.0, stop=99.0, targets=[101.0, 102.0, 103.0],
                instrument="options", multiplier=100.0, status="open",
                remaining=2.0, filled_qty=2.0, avg_fill=1.0,
                order_symbol="X260918C00101000")
    return Trade(**{**base, **kwargs})


def plan(config=None):
    return ArmedPlan(run_id="review", symbol="X", plan={}, plan_for="2026-09-14",
                     config=config or ArmConfig(portfolio_id="review", mode="auto"),
                     trackers={}, armed_at=0)


def runner(settings=None):
    engine = SimpleNamespace(settings=settings or {},
                             positions=SimpleNamespace(equity=AsyncMock(return_value=10000.0)),
                             journal=SimpleNamespace(append=AsyncMock()),
                             quotes={}, options=None)
    r = PlanRunner(engine)
    r._log = Mock()
    r._persist = AsyncMock()
    r._publish = Mock()
    r._alert = AsyncMock()
    r._place_with_retry = AsyncMock(return_value=None)
    return r


def test_shares_fallback_changes_multiplier_before_submission():
    r = runner()
    ap = plan(ArmConfig(portfolio_id="review", mode="auto", instrument="options",
                        entry_fallback="shares", qty=100))
    tr = trade(status="fired", remaining=0, filled_qty=0,
               contract_attempted=True,
               contract={"symbol": "X260918C00101000", "warnings": ["T5.4 wide spread 20%"]})
    asyncio.run(r._enter(ap, tr, None, journal=True))
    intent = r._place_with_retry.await_args.args[2]
    assert intent.sec_type == "STK"
    assert tr.instrument == "shares"
    assert tr.multiplier == 1.0, "A shares fallback must not retain the option's 100x P&L multiplier"


def test_shares_fallback_realized_pnl_matches_executions():
    r = runner()
    ap = plan(ArmConfig(portfolio_id="review", mode="auto", instrument="options",
                        entry_fallback="shares", qty=100))
    tr = trade(entry=34.9114, stop=34.7, status="fired", remaining=0, filled_qty=0,
               contract_attempted=True,
               contract={"symbol": "X260918C00035000", "warnings": ["T5.4 wide spread 20%"]})
    asyncio.run(r._enter(ap, tr, None, journal=True))
    ap.trades[tr.trigger_id] = tr
    r._armed[ap.run_id] = ap
    tr.status, tr.avg_fill, tr.filled_qty, tr.remaining = "open", 34.77, 100, 100
    tr.exit_order_ids = ["tp", "stop"]
    tr.exits = [{"orderId": "tp", "kind": "tp1", "qty": 30, "filledQty": 0},
                {"orderId": "stop", "kind": "stop", "qty": 70, "filledQty": 0}]
    for oid in tr.exit_order_ids:
        r.register_order(oid, (ap.run_id, tr.trigger_id))
    asyncio.run(r.on_order_update({"id": "tp", "status": "FILLED", "filledQty": 30,
                                   "avgFillPrice": 34.803}))
    asyncio.run(r.on_order_update({"id": "stop", "status": "FILLED", "filledQty": 70,
                                   "avgFillPrice": 34.6531}))
    assert tr.realized_pnl == pytest.approx(-7.193)


@pytest.mark.parametrize("direction,low,high", [("long", 100.1, 102.2), ("short", 97.8, 99.9)])
def test_two_contract_tp2_in_same_bar_as_tp1_exits(direction, low, high):
    tr = trade(direction=direction,
               stop=101.0 if direction == "short" else 99.0,
               targets=[99.0, 98.0, 97.0] if direction == "short" else [101.0, 102.0, 103.0])
    bar = Bar(symbol="X", tf="1m", ts=1000, open=100.0, low=low, high=high,
              close=99.5 if direction == "short" else 100.5, volume=100)
    decision = plan_exit(tr, bar, close_ms=10**13, flatten_minutes=5, single_exit="tp2", stop_on="close")
    assert decision is not None, "TP2 was reached; the first TP1 observation must not consume the bar"
    assert decision.kind == "tp2" and decision.qty == 2


def test_contract_risk_sizing_can_refuse_one_unaffordable_contract():
    r = runner({"execution.premium_stop_pct": 50.0})
    ap = plan(ArmConfig(portfolio_id="review", contracts=None, risk_pct=0.5))
    qty = asyncio.run(r._size_contracts(ap, trade(), {"ask": 5.0}))
    assert qty == 0, "One $500 contract risks $250 at the stop against only $50 of trade budget"


def test_final_reprice_resizes_before_submission():
    r = runner({"execution.premium_stop_pct": 50.0})

    async def reprice(contract):
        contract.update(ask=4.0, bid=3.9, mid=3.95, spreadPct=2.53, priced="opra")
        return contract

    r.engine.options = SimpleNamespace(reprice=reprice)
    ap = plan(ArmConfig(portfolio_id="review", contracts=None, max_contracts=10, risk_pct=2.0))
    tr = trade(status="fired", remaining=0, filled_qty=0, contract_attempted=True,
               contract={"symbol": "X260918C00101000", "ask": 2.0, "bid": 1.95, "warnings": []})
    asyncio.run(r._enter(ap, tr, None, journal=True))
    intent = r._place_with_retry.await_args.args[2]
    assert intent.qty * intent.limit_price * 100 * 0.5 <= 200.0, "A fresh ask must not double the authorized $200 risk"


def test_premium_stop_does_not_confirm_the_same_cached_quote_twice():
    r = runner({"execution.premium_stop_pct": 50.0, "execution.quote_exit_polls": 2})
    ap = plan()
    tr = trade()
    ap.trades[tr.trigger_id] = tr
    r._armed[ap.run_id] = ap
    stamp = int(time.time() * 1000)
    r.engine.quotes = {"X": Quote(symbol="X", last=100.0, ts=stamp),
                       tr.order_symbol: Quote(symbol=tr.order_symbol, bid=0.4, ask=0.42,
                                              last=0.41, ts=stamp, source="opra", source_ts=stamp)}
    r._exit = AsyncMock()
    asyncio.run(r.on_quote_watch())
    asyncio.run(r.on_quote_watch())
    assert r._exit.await_count == 0, "Polling one observation twice is not two independent premium-stop observations"
