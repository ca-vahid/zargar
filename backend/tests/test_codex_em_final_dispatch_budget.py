"""EM's moving day budget through the actual OrderManager dispatch path.

Copy into backend/tests and run only through scripts/test-codex.ps1 so the
project fresh_db fixture uses zargar_test_codex. No Engine.start(), no network,
and executor.submit is a recording fake; orders/events use real isolated DB.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from tests.conftest import make_test_config
from zargar.domain import OrderStatus, Quote, now_ms
from zargar.engine import Engine
from zargar.marketstructure.sessions import session_date
from zargar.models import Event, Order, Portfolio, TechniqueRun
from zargar.orders import OrderManager
from zargar.technique.arming import PlanArmer
from zargar.technique.rulebook import Thresholds
from zargar.execution.planrunner import ArmConfig, ArmedPlan, Trade


CONTRACT = "HOOD270618C00101000"


@pytest.fixture
async def dispatch_rig(fresh_db, monkeypatch):
    eng = Engine(make_test_config())
    try:
        async with eng.sf() as session:
            session.add(Portfolio(id="em-dispatch-book", name="EM dispatch test", kind="sim",
                                  base_currency="USD", cash=10000.0))
            session.add(TechniqueRun(id="em-dispatch-run", technique="enhanced_market",
                                     symbol="HOOD", mode="plan", status="done", result={}))
            await session.commit()
        await eng.positions.load()
        await eng.settings.set("risk.allow_options", True)
        await eng.settings.set("trading.mode", "practice")
        await eng.settings.set("techniques.enhanced_market.premium_stop_pct", 50.0)
        monkeypatch.setattr("zargar.risk.is_us_market_hours", lambda *args, **kwargs: True)

        async def ensure(_symbol):
            return None

        submit = AsyncMock(return_value=None)
        eng.sim_executor = SimpleNamespace(connected=True, submit=submit)
        eng.orders = OrderManager(eng.sf, eng.bus, eng.journal, eng.risk, eng.settings,
                                  eng.positions, eng.quotes, eng.executor_for, ensure)
        stamp = now_ms()
        eng.quotes.on_quote(Quote("HOOD", bid=99.99, ask=100.01, last=100.0, ts=stamp))
        eng.quotes.on_quote(Quote(CONTRACT, bid=2.95, ask=3.0, last=2.975,
                                  ts=stamp, source="opra", source_ts=stamp))
        r = PlanArmer(eng, SimpleNamespace(thresholds=lambda: Thresholds(long_only=False)))
        r._persist, r._alert = AsyncMock(), AsyncMock()
        r._log, r._publish = Mock(), Mock()
        ap = ArmedPlan(run_id="em-dispatch-run", symbol="HOOD", plan={},
                       plan_for=session_date(stamp), trackers={}, armed_at=0,
                       config=ArmConfig(portfolio_id="em-dispatch-book", mode="auto",
                                        contracts=None, max_contracts=1, risk_pct=2.0,
                                        daily_loss_limit=160.0, entry_fallback="off", use_critic=False))
        prior = Trade(trigger_id="prior", kind="bounce", fired_ts=stamp, window="prime_open",
                      entry=100.0, stop=99.0, targets=[101.0], status="closed",
                      instrument="shares", multiplier=1.0, realized_pnl=0.0)
        tr = Trade(trigger_id="b1", kind="bounce", fired_ts=stamp, window="prime_open",
                   entry=100.0, stop=99.0, targets=[101.0, 102.0, 103.0], status="fired",
                   instrument="options", multiplier=100.0, contract_attempted=True,
                   order_symbol=CONTRACT, last_price=100.0,
                   contract={"symbol": CONTRACT, "underlying": "HOOD", "ask": 3.0,
                             "bid": 2.95, "mid": 2.975, "spreadPct": 1.68, "priced": "opra",
                             "strike": 101.0, "expiry": "2027-06-18", "optionType": "call",
                             "warnings": []})
        ap.trades = {"prior": prior, "b1": tr}
        r._armed[ap.run_id] = ap
        yield SimpleNamespace(engine=eng, runner=r, ap=ap, trade=tr, prior=prior, submit=submit)
    finally:
        await eng.db.dispose()


@pytest.mark.parametrize("change_at", ["unchanged", "reprice", "submitted"])
async def test_em_day_budget_is_valid_at_actual_dispatch(dispatch_rig, monkeypatch, change_at):
    rig = dispatch_rig
    eng, r, ap, tr = rig.engine, rig.runner, rig.ap, rig.trade
    observed = {"reprice": False, "submitted": False, "risk_passed": []}

    async def reprice(contract):
        await asyncio.sleep(0)  # actual yield; ask and quantity stay unchanged
        observed["reprice"] = True
        if change_at == "reprice":
            rig.prior.realized_pnl = -40.0  # another trade closes: $160 remaining becomes $120
        return contract

    eng.options = SimpleNamespace(reprice=reprice)
    original_risk = eng.risk.evaluate

    async def risk(intent, portfolio):
        verdict = await original_risk(intent, portfolio)
        observed["risk_passed"].append(verdict.passed)
        return verdict

    monkeypatch.setattr(eng.risk, "evaluate", risk)
    original_transition = eng.orders._transition

    async def transition(oid, status, *args, **kwargs):
        result = await original_transition(oid, status, *args, **kwargs)
        if status == OrderStatus.SUBMITTED:
            observed["submitted"] = True
            if change_at == "submitted":
                rig.prior.realized_pnl = -40.0
        return result

    monkeypatch.setattr(eng.orders, "_transition", transition)
    await r._enter(ap, tr, None, journal=True)
    assert observed["reprice"] is True
    assert tr.contract["ask"] == 3.0  # budget changes independently of price
    async with eng.sf() as session:
        orders = list((await session.scalars(select(Order))).all())

    if change_at == "unchanged":
        assert observed["risk_passed"] == [True]
        assert observed["submitted"] is True
        assert rig.submit.await_count == 1
        broker_order = rig.submit.await_args.args[0]
        assert broker_order.qty == 1 and broker_order.limit_price == 3.0
        assert len(orders) == 1 and orders[0].status == "SUBMITTED"
    elif change_at == "reprice":
        assert tr.status == "skipped" and "loss budget" in tr.reason
        assert rig.submit.await_count == 0 and orders == []
    else:
        assert observed["risk_passed"] == [True], "The real RiskGate must have admitted the unchanged $300 intent"
        assert observed["submitted"] is True, "The test must reach OrderManager's final awaited transition"
        assert rig.submit.await_count == 0, "$150 modeled loss was dispatched after the day allowance fell to $120"
        assert len(orders) == 1 and orders[0].status == "REJECTED_RISK"
        assert orders[0].filled_qty == 0
        async with eng.sf() as session:
            rejection = await session.scalar(select(Event).where(
                Event.aggregate_id == orders[0].id, Event.type == "OrderRejected"))
        assert rejection is not None and rejection.payload.get("beforeSubmitRejected") is True
