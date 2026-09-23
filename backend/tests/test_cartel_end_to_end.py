"""The end-to-end fixture required by the 2026-09-21 brief (section 13) and the PR246 review.

Frozen pre-open plan -> complete closed-bar 5m confirmation -> preferred/diverse fresh quote search
(the saved contract fails the spread limit; the bounded search must find an eligible alternative) ->
final preflight -> simulated order through the shared OrderManager/RiskGate -> partial then cumulative
entry fills -> managed exit (first target trim) -> restart -> session report. The matched 15m control
keeps observing after the executing plan signals. No duplicate submission, correct money and fees,
truthful states. Every quote and Greek in this rig is SYNTHETIC and labelled so.
"""
import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from zargar.brokers.base import ExecReport
from zargar.domain import Bar, Quote
from zargar.execution.positions import PositionManager
from zargar.models import Execution, Order, TechniqueRun
from zargar.techniques.options_cartel.cadence import control_config
from zargar.techniques.options_cartel.contracts import ContractSelectionInput
from zargar.techniques.options_cartel.execution import ExecutionInput
from zargar.techniques.options_cartel.exits import ExitCampaign
from zargar.techniques.options_cartel.position_adapter import register_cartel_policy
from zargar.techniques.options_cartel.runtime import CartelRuntime
from zargar.techniques.options_cartel.session_review import report

from .conftest import wait_for
from dataclasses import replace

from .test_options_cartel_entry import OPEN, MIN, plan as hood_plan, tape
from .test_options_cartel_runtime import runtime
from .test_options_cartel_state import repo as _repo_fixture

repo = _repo_fixture
OLD = "HOOD270416C00050000"   # saved contract: SYNTHETIC wide book (40% of mid) at the signal; distant expiries keep the wall-clock risk gate out of the rig
NEW = "HOOD270521C00049000"   # eligible alternative in the other expiry: SYNTHETIC 1.95/2.00 book


class Options:
    """SYNTHETIC options service: two expiries, refresh stamps fresh OPRA quotes on the engine's book."""

    def __init__(self, engine, clock):
        self.engine, self.clock = engine, clock
        self.refreshed, self.chain_calls = [], []
        self.books = {OLD: (1.5, 2.5), NEW: (1.95, 2.0), "HOOD270416C00051000": (1.2, 1.9), "HOOD270521C00050000": (1.7, 1.8)}

    def provider(self):
        return self

    async def track(self, symbol):
        assert symbol in self.books

    async def expirations(self, symbol):
        return ["2027-04-16", "2027-05-21"]

    async def chain(self, symbol, expiry):
        self.chain_calls.append(expiry)
        return [{"symbol": s, "expiry": expiry, "greeks": {"delta": .5}, "open_interest": 400}
                for s in self.books if s[4:10] == dt.date.fromisoformat(expiry).strftime("%y%m%d")]

    async def reprice(self, contract):
        symbol = contract["symbol"]
        bid, ask = self.books[symbol]
        now = self.clock()
        self.refreshed.append(symbol)
        self.engine.quotes.on_quote(Quote(symbol, bid=bid, ask=ask, last=ask, bid_size=50, ask_size=50, source="opra", source_ts=now, ts=now))

    def snapshot_cached(self, symbol):
        return {"greeks": {"delta": .5}, "greeksFieldAsOf": {"delta": self.clock()}}


async def publish_exchange_tape(repo, runner):
    """The entry-test tape with exchange provenance, delivered through the bus like the live feed."""
    from zargar import bus as topics
    for bar in (replace(b, source="exchange") for b in tape()):
        runner.clock = lambda b=bar: b.ts+MIN
        repo.engine.quotes.on_quote(Quote("HOOD", bid=bar.close-.01, ask=bar.close+.01, last=bar.close, ts=runner.clock()))

        async def seen(current=bar):
            repo.engine.bus.publish(topics.BARS, {"symbol": "HOOD", "tf": "1m", "bar": current})
            return (await repo.load("r1"))["state"].get("lastMinute") == current.ts
        await wait_for(seen)

    async def signalled():
        return (await repo.load("r1"))["state"].get("signal") is not None
    await wait_for(signalled)


async def test_plan_to_report_with_diverse_search_partial_fills_exit_restart_and_control(repo, monkeypatch):
    runner, _ = await runtime(repo, monkeypatch)
    engine = repo.engine
    monkeypatch.setattr("zargar.risk.is_us_market_hours", lambda *args, **kwargs: True)
    monkeypatch.setattr(engine.quotes, "source_age_seconds", lambda symbol: 0.)
    engine.options = Options(engine, lambda: runner.clock())
    engine.position_manager._now = lambda: runner.clock()/1000
    policy = ContractSelectionInput(dte_min=21, dte_max=730, target_dte=345, target_abs_delta=.5, max_ask=5, max_spread_pct=20,
                                    min_open_interest=100, refresh_limit=6, selection_version="diverse_liquidity_v1",
                                    ranking_version="executable_cost_v1")
    spec = ExecutionInput(portfolio_id="pf", mode="auto", instrument="options", budget=500, risk_pct=10, max_units=2,
                          contract_symbol=OLD, overnight_ack=True, max_premium=5, contract_policy=policy)
    base = hood_plan()
    async with engine.sf() as session, session.begin():   # small-lot exits: the first target trims one of two contracts
        run = await session.get(TechniqueRun, "r1")
        run.result = {**run.result, "exitCampaign": ExitCampaign.for_profile("september_2026", [55, 60], september_fractions=(.25, .25, .20, .20, .10), allocation_policy="whole_contracts_v2").model_dump(mode="json")}
    control = control_config("breakout_5m_v1", {"timeframeMinutes": 15, "baselines": {i: 1000. for i in range(26)}}, base.baseline_as_of)
    await runner.arm("r1", {"mode": "auto", "portfolioId": "pf", "execution": spec.model_dump(), "clientKind": "desktop", "cadence": control,
                            "preparation": {"workspace": "practice", "validUntil": OPEN+8*3600_000}})
    # The saved contract's book at the signal is wide: SYNTHETIC 1.50/2.50.
    engine.quotes.on_quote(Quote(OLD, bid=1.5, ask=2.5, last=2.5, bid_size=50, ask_size=50, source="opra", source_ts=OPEN+10*MIN, ts=OPEN+10*MIN))
    try:
        # 1. Complete closed-bar 5m confirmation on the executing plan.
        await publish_exchange_tape(repo, runner)
        async def selection_completed():
            snapshot = await repo.load("r1")
            return bool(snapshot["state"].get("contractReselection"))
        await wait_for(selection_completed)
        await runner.wait_idle()
        row = await repo.load("r1")
        assert row["state"]["signal"]["id"] == f"r1:entry:{OPEN+10*MIN}"
        # 2. Preferred/diverse search: OLD refreshed first (preferred), still wide; NEW selected; both expiries searched.
        reselection = row["state"].get("contractReselection") or {}
        assert reselection.get("status") == "selected", (row["state"].get("runtimeError"), reselection)
        selection = reselection["selection"]
        assert reselection["newContract"] == NEW and reselection["selectionVersion"] == "diverse_liquidity_v1"
        assert selection["allocation"]["order"][0] == OLD and selection["preferredContract"]["status"] == "ineligible_after_refresh"
        assert sorted(selection["searchedExpiries"]) == ["2027-04-16", "2027-05-21"] and selection["searchComplete"] is True
        assert selection["selected"]["symbol"] == NEW and selection["selected"]["economics"]["status"] == "estimated"
        assert selection["rankingVersion"] == "executable_cost_v1" and NEW in engine.options.refreshed
        # 3. Final preflight passed and ONE order was routed through the shared order path.
        assert row["state"].get("orderId")
        async with engine.sf() as session:
            entry = await session.get(Order, row["state"]["orderId"])
        assert entry.symbol == NEW and entry.qty == 2 and entry.limit_price == 2.0 and entry.qty*entry.limit_price*100 <= spec.budget
        # 4. Partial then cumulative fills through the shared OrderManager (SYNTHETIC reports at the rig's clock).
        fill_at = runner.clock()
        await engine.orders.on_report(ExecReport(kind="fill", order_id=entry.id, ts=fill_at, fill_qty=1, fill_price=2.0, commission=1.04, exec_id="e2e-partial"))

        async def protected():
            positions = engine.position_manager.positions()
            return bool(positions) and positions[0]["legs"][0]["qty"] == 1
        await wait_for(protected)
        async with engine.sf() as session:
            entry = await session.get(Order, entry.id)
        assert entry.status == "PARTIALLY_FILLED" and entry.filled_qty == 1
        await engine.orders.on_report(ExecReport(kind="fill", order_id=entry.id, ts=fill_at+1000, fill_qty=1, fill_price=2.0, commission=1.04, exec_id="e2e-rest"))

        async def adopted():
            return (await repo.load("r1"))["state"]["phase"] == "managed"
        await wait_for(adopted)
        await runner.wait_idle()
        position = engine.position_manager.get(engine.position_manager.positions()[0]["id"])
        assert position.legs[0].qty == 2 and position.legs[0].avg_fill == 2.0
        # 5. The matched 15m control keeps observing AFTER the executing plan signalled and filled.
        for i in range(10, 15):
            bar = Bar("HOOD", "1m", OPEN+i*MIN, 48.7, 48.94, 48.6, 48.92, 500, source="exchange")
            runner.clock = lambda b=bar: b.ts+MIN
            await runner.on_minute_bar("HOOD", bar)
        control_state = (await repo.load("r1"))["state"]["control"]
        assert control_state["cadence"] == "breakout_15m_v1" and control_state["lastMinute"] == OPEN+14*MIN
        assert control_state["executingPhase"] == "managed" and control_state["placesOrders"] is False
        assert any(d["at"] == OPEN+15*MIN for d in control_state["decisionHistory"])
        # 6. Managed exit: the first target trims one contract at the bid.
        runner.clock = lambda: OPEN+16*MIN
        engine.sim_executor.clock = lambda: runner.clock()
        engine.position_manager._now = lambda: runner.clock()/1000
        engine.quotes.on_quote(Quote("HOOD", bid=55, ask=55.01, last=55, ts=runner.clock()))
        premium = Quote(NEW, bid=2.60, ask=2.61, last=2.60, bid_size=50, ask_size=50, source="opra", source_ts=runner.clock(), ts=runner.clock())
        engine.quotes.on_quote(premium)
        await engine.position_manager.on_minute_bar(position, Bar("HOOD", "1m", OPEN+15*MIN, 55, 55.1, 54.9, 55, 1000))
        await engine.sim_executor.on_quote(premium)

        async def trimmed():
            return position.legs[0].qty == 1
        await wait_for(trimmed)
        assert position.realized_pnl == pytest.approx(60., abs=.01)   # (2.60-2.00) x 100 gross on the closed unit; fees are on the ledger below
        position_id = position.id
        # 7. Restart: positions, the arm and the control survive; nothing is resubmitted.
        await runner.stop()
        await engine.position_manager.stop()
        engine.position_manager = PositionManager(engine)
        engine.position_manager._now = lambda: (OPEN+17*MIN)/1000
        assert engine.position_manager.now_ms() == OPEN+17*MIN
        register_cartel_policy(engine)
        await engine.position_manager.restore()
        restored = CartelRuntime(engine)
        restored.clock = lambda: OPEN+17*MIN
        engine.cartel_observer = restored
        engine.plan_runners = {"options_cartel": restored}
        await restored.restore()
        restored.start()
        await restored.wait_idle()
        assert engine.position_manager.get(position_id).legs[0].qty == 1
        assert "r1" in restored.controls and restored.controls["r1"]["floor"] == OPEN+17*MIN
        bar = Bar("HOOD", "1m", OPEN+16*MIN, 48.7, 48.94, 48.6, 48.92, 500, source="exchange")
        await restored.on_minute_bar("HOOD", bar)
        await restored.wait_idle()
        after = (await repo.load("r1"))["state"]["control"]
        assert after["lastMinute"] == OPEN+16*MIN and after["observeAfter"] >= OPEN+17*MIN
        async with engine.sf() as session:
            buys = (await session.scalars(select(Order).where(Order.side == "BUY"))).all()
            sells = (await session.scalars(select(Order).where(Order.side == "SELL"))).all()
        assert len(buys) == 1 and [(o.qty, o.filled_qty, o.status) for o in buys] == [(2, 2, "FILLED")]
        assert sum(o.filled_qty for o in sells) == 1
        # 8. Session report from the actual ledger. The rig's ORDER rows carry wall-clock creation stamps
        #    while every decision, execution and quote runs on the synthetic session clock; align only the
        #    order/position creation stamps to that clock so the report's cutoff sees them (fixture plumbing).
        day = base.first_session.isoformat()
        async with engine.sf() as session, session.begin():
            stamp = {"at": dt.datetime.fromtimestamp(fill_at/1000, dt.UTC)}
            await session.execute(text("UPDATE orders SET created_at = :at, updated_at = :at WHERE portfolio_id = 'pf'"), stamp)
            await session.execute(text("UPDATE managed_positions SET created_at = :at WHERE portfolio_id = 'pf'"), stamp)
        monkeypatch.setattr("zargar.techniques.options_cartel.session_review.now_ms", lambda: OPEN+18*MIN)
        result = await report(engine, "pf", day)
        row = next(r for r in result["rows"] if r["planId"] == "r1")
        assert row["category"] == "open"
        attribution = row["attribution"]
        assert attribution["actualOutcome"] == "held"
        assert attribution["entry"] == {"requestedQty": 2, "filledQty": 2, "orderStatuses": ["FILLED"], "terminal": True, "working": False, "entryStatus": "filled"}
        assert attribution["selectionCoverage"]["status"] == "eligible_expression_found"
        assert attribution["funnel"] == {"priceTouch": True, "confirmation": True, "contractEligibility": True, "submission": True, "fill": True}
        async with engine.sf() as session:
            exit_fees = sum(e.commission for e in (await session.scalars(select(Execution).where(Execution.side == "SELL"))).all())
        assert attribution["economics"]["actualFees"] == pytest.approx(2.08+exit_fees, abs=.01)   # both entry fills' fees plus the trim's
        assert row["assets"][0]["entryFilledQty"] == 2 and row["assets"][0]["exitFilledQty"] == 1 and row["assets"][0]["remainingQty"] == 1
        assert row["cadence"]["executing"] == "breakout_5m_v1" and row["cadence"]["control"]["control"] == "breakout_15m_v1"
        assert row["cadence"]["control"]["controlDecisionCounts"] and row["cadence"]["control"]["placesOrders"] is False
        assert result["cadenceComparison"]["executing"]["breakout_5m_v1"] == pytest.approx(
            {"plans": 1, "signals": 1, "entryOrders": 1, "filledEntries": 1, "netRealized": row["assets"][0]["netRealized"]})
        assert result["cadenceComparison"]["control"]["entryOrders"] == 0 and result["cadenceComparison"]["control"]["netRealized"] is None
        assert result["entryOrders"] == 1 and result["exitOrders"] == 1 and result["openInstruments"] == 1
    finally:
        await engine.cartel_observer.stop()
        await engine.position_manager.stop()
