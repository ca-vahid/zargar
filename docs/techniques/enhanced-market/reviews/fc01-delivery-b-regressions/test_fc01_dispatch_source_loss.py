"""FC-01: losing current executable source evidence is a final-entry refusal.

Copy into backend/tests beside the adopted dispatch fixture and run only with
scripts/test-codex.ps1. Real isolated OrderManager/RiskGate/DB; fake executor.
"""
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tests.test_codex_em_final_dispatch_budget import CONTRACT, dispatch_rig as dispatch_rig
from zargar.domain import OrderStatus, Quote, now_ms
from zargar.models import Event, Order


@pytest.mark.parametrize("source_loss", ["missing", "delayed_chain"])
async def test_fc01_source_loss_after_risk_cannot_reuse_clean_captured_warnings(
    dispatch_rig, monkeypatch, source_loss
):
    rig = dispatch_rig
    eng, r, ap, tr = rig.engine, rig.runner, rig.ap, rig.trade
    observed = {"risk_passed": [], "submitted_transition": False}
    monkeypatch.setattr(eng.risk, "live_option_quotes_expected", lambda: True)

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
            if source_loss == "missing":
                eng.quotes._quotes.pop(CONTRACT, None)
            else:
                stamp = now_ms()
                eng.quotes.on_quote(Quote(CONTRACT, bid=2.95, ask=3.0, last=2.975,
                                          ts=stamp, source="chain", source_ts=stamp - 900000))
        return result

    monkeypatch.setattr(eng.orders, "_transition", transition)
    await r._enter(ap, tr, None, journal=True)
    assert observed["risk_passed"] == [True]
    assert observed["submitted_transition"] is True
    current = eng.quotes.get(CONTRACT)
    assert current is None if source_loss == "missing" else current.delayed
    assert tr.contract["priced"] == "opra" and tr.contract["warnings"] == []
    assert rig.submit.await_count == 0, "Old clean warnings cannot replace missing or delayed current entry evidence"
    async with eng.sf() as session:
        orders = list((await session.scalars(select(Order))).all())
        assert len(orders) == 1 and orders[0].status == "REJECTED_RISK"
        assert orders[0].filled_qty == 0
        rejection = await session.scalar(select(Event).where(
            Event.aggregate_id == orders[0].id, Event.type == "OrderRejected"))
        assert rejection is not None and rejection.payload.get("beforeSubmitRejected") is True
