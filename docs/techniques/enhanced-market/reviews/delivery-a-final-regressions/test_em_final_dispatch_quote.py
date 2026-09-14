"""One remaining FA-01 acceptance: current NBBO changes after the last await.

Copy into backend/tests; reuse the already-validated isolated OrderManager
fixture. No Engine.start(), network or real executor. Run by parent reviewer.
"""
import asyncio
from types import SimpleNamespace

from sqlalchemy import select

from tests.test_codex_em_final_dispatch_budget import CONTRACT, dispatch_rig as dispatch_rig
from zargar.domain import OrderStatus, Quote, now_ms
from zargar.models import Event, Order


async def test_em_dispatch_rechecks_current_nbbo_not_captured_contract_warnings(dispatch_rig, monkeypatch):
    rig = dispatch_rig
    eng, r, ap, tr = rig.engine, rig.runner, rig.ap, rig.trade
    observed = {"submitted_transition": False, "risk_passed": []}

    async def reprice(contract):
        await asyncio.sleep(0)
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
            observed["submitted_transition"] = True
            stamp = now_ms()
            # Ask/size/day budget unchanged: only current executable spread widens
            # from 1.68% to 18.18%, beyond EM's configured T5.4 10% threshold.
            eng.quotes.on_quote(Quote(CONTRACT, bid=2.5, ask=3.0, last=2.75,
                                      ts=stamp, source="opra", source_ts=stamp))
        return result

    monkeypatch.setattr(eng.orders, "_transition", transition)
    await r._enter(ap, tr, None, journal=True)
    assert observed["risk_passed"] == [True]
    assert observed["submitted_transition"] is True
    assert eng.quotes.get(CONTRACT).spread_pct > 10.0
    assert rig.prior.realized_pnl == 0.0 and ap.config.daily_loss_limit == 160.0
    assert rig.submit.await_count == 0, "The guard approved stale contract warnings after the executable NBBO widened"
    async with eng.sf() as session:
        orders = list((await session.scalars(select(Order))).all())
        assert len(orders) == 1 and orders[0].status == "REJECTED_RISK"
        assert orders[0].filled_qty == 0
        rejection = await session.scalar(select(Event).where(
            Event.aggregate_id == orders[0].id, Event.type == "OrderRejected"))
        assert rejection is not None and rejection.payload.get("beforeSubmitRejected") is True
