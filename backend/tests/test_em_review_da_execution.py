"""Independent Delivery A boundary acceptance cases. No DB or real orders.

Submission is intercepted. Failures prove runner intent/state behavior, not
that a real RiskGate or broker accepted an order. Run by the parent reviewer.
"""
import asyncio
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from zargar.domain import Bar, Quote
from zargar.execution.planrunner import ArmConfig, ArmedPlan, PlanRunner, Trade


def _runner(settings=None):
    engine = SimpleNamespace(settings=settings or {},
                             positions=SimpleNamespace(equity=AsyncMock(return_value=10000.0)),
                             journal=SimpleNamespace(append=AsyncMock()), quotes={}, options=None)
    r = PlanRunner(engine)
    r._log, r._publish = Mock(), Mock()
    r._persist, r._alert = AsyncMock(), AsyncMock()
    r._place_with_retry = AsyncMock(return_value=None)
    return r


def _plan(**config):
    return ArmedPlan(run_id="review", symbol="X", plan={}, plan_for="2026-09-14",
                     config=ArmConfig(**{"portfolio_id": "review", "mode": "auto",
                                         "contracts": None, "risk_pct": 2.0, **config}),
                     trackers={}, armed_at=0, bar_index=10)


def _trade(**updates):
    return Trade(**{"trigger_id": "b1", "kind": "bounce", "fired_ts": 1,
                    "window": "prime_open", "entry": 100.0, "stop": 99.0,
                    "targets": [101.0, 102.0, 103.0], "instrument": "options",
                    "multiplier": 100.0, "status": "fired", "contract_attempted": True,
                    "order_symbol": "X260918C00101000", **updates})


def test_delivery_a_rechecks_widened_spread_before_submission():
    r = _runner({"execution.premium_stop_pct": 50.0})
    ap = _plan(skip_wide_spread=True)
    tr = _trade(contract={"symbol": "X260918C00101000", "ask": 2.0, "bid": 1.98,
                          "warnings": [], "priced": "opra", "spreadPct": 1.01})

    async def reprice(contract):
        contract.update(ask=2.2, bid=1.7, mid=1.95, spreadPct=25.64, priced="opra")
        return contract

    r.engine.options = SimpleNamespace(reprice=reprice)
    asyncio.run(r._enter(ap, tr, None, journal=True))
    assert any("T5.4 wide spread" in w for w in tr.contract["warnings"])
    assert r._place_with_retry.await_count == 0, "Updating the warning must also re-run the final spread gate"


def test_delivery_a_rechecks_remaining_daily_loss_budget_after_reprice():
    r = _runner({"execution.premium_stop_pct": 50.0})
    ap = _plan(daily_loss_limit=160.0)
    tr = _trade(contract={"symbol": "X260918C00101000", "ask": 3.0, "bid": 2.95,
                          "warnings": [], "priced": "opra", "spreadPct": 1.68})

    async def reprice(contract):
        contract.update(ask=3.9, bid=3.85, mid=3.875, spreadPct=1.29, priced="opra")
        return contract

    r.engine.options = SimpleNamespace(reprice=reprice)
    asyncio.run(r._enter(ap, tr, None, journal=True))
    if r._place_with_retry.await_count:
        intent = r._place_with_retry.await_args.args[2]
        assert intent.qty * intent.limit_price * 100 * 0.5 <= 160.0, (
            "$195 modeled loss fits the $200 trade budget but exceeds the $160 day budget; "
            "the earlier $150 quote must not authorize it"
        )
    else:
        assert tr.status == "skipped"


def test_delivery_a_older_quote_cannot_confirm_a_newer_premium_stop_sighting():
    r = _runner({"execution.premium_stop_pct": 50.0, "execution.quote_exit_polls": 2})
    ap = _plan()
    tr = _trade(status="open", remaining=2.0, filled_qty=2.0, avg_fill=1.0)
    ap.trades[tr.trigger_id], r._armed[ap.run_id] = tr, ap
    stamp = int(time.time() * 1000)
    r.engine.quotes = {"X": Quote(symbol="X", last=100.0, ts=stamp),
                       tr.order_symbol: Quote(symbol=tr.order_symbol, bid=0.4, ask=0.42,
                                              ts=stamp, source="opra", source_ts=stamp)}
    r._exit = AsyncMock()
    asyncio.run(r.on_quote_watch())
    # A distinct but older packet: reception remains fresh; source time goes back.
    r.engine.quotes[tr.order_symbol] = Quote(symbol=tr.order_symbol, bid=0.4, ask=0.42,
                                            ts=stamp, source="opra", source_ts=stamp - 1000)
    asyncio.run(r.on_quote_watch())
    assert r._exit.await_count == 0, "An out-of-order observation is not forward confirmation"


def test_delivery_a_pending_cancelled_exit_does_not_consume_unexecuted_tp2():
    r = _runner()
    r.rules = lambda: SimpleNamespace(stop_on_close=True, scratch_r=0.0)
    r._exit = AsyncMock()
    ap = _plan(single_contract_exit="tp2")
    tr = _trade(status="open", remaining=2.0, filled_qty=2.0, avg_fill=1.0,
                exits=[{"orderId": "manual-close", "kind": "manual", "qty": 2.0,
                        "filledQty": 0.0, "status": "SUBMITTED", "barIndex": 9}])
    bar = Bar(symbol="X", tf="1m", ts=1000, open=100.0, high=102.2,
              low=100.0, close=100.5, volume=100)
    # Both observations occur while the full manual exit remains pending.
    asyncio.run(r._manage(ap, tr, bar, 10**13, journal=True))
    ap.bar_index = 11
    asyncio.run(r._manage(ap, tr, replace(bar, ts=61000), 10**13, journal=True))
    assert r._exit.await_count == 0
    tr.exits[0]["status"] = "CANCELLED"
    # A new target touch should now authorize the still-unexecuted full TP2 exit.
    ap.bar_index = 12
    asyncio.run(r._manage(ap, tr, replace(bar, ts=121000), 10**13, journal=True))
    assert r._exit.await_count == 1, "Pending observations advanced past TP2 without any target fill"
    assert r._exit.await_args.args[2:4] == ("tp2", 2.0)
