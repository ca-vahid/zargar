"""Tips v0.9 V3.1 on the ARMED lane (2026-10-05): an at-level plan that fires gets the SAME daily-ATR stop floor as a
direct proposal (`lifecycle.check_exit_geometry` via `horizon_class.decide`), finalized at the fired entry's BUY limit
BEFORE the quantity is sized, so the order is sized from the final stop at the same dollar risk. Out of scope (stop
ATR mode off, geometry gate not enforcing) the arm-time stop and sizing stand; options keep their premium stop.
No LLM calls; the daily facts are stubbed (the sim feed has no daily history)."""
from __future__ import annotations

import datetime as dt
import math

import pytest
from sqlalchemy import select

from zargar.domain import Bar
from zargar.models import Event, Order
from zargar.techniques.tip import horizon_class as hc

from .conftest import wait_for
from .test_tip_runner import MIN, _ingest_tip, _quote, tip_rig  # noqa: F401  (fixture)

ATR = 4.0            # 4% of a ~$100 name: no low-ATR flag; flat day -> swing -> 3x daily ATR
RISK_BUDGET = 60.0


async def _events(eng, kind: str) -> list[dict]:
    async with eng.sf() as s:
        return list((await s.execute(select(Event.payload).where(Event.type == kind)
                                     .order_by(Event.id))).scalars().all())


@pytest.fixture
def daily(monkeypatch):
    async def facts(_eng, sym):
        return {"priorClose": 99.5, "sessionOpen": 99.5, "atrDaily": ATR}
    monkeypatch.setattr(hc, "daily_facts", facts)


async def _bind_practice(eng, sim, **extra):
    await eng.settings.set("techniques.tip.books", [
        {"portfolioId": sim["id"], "role": "practice", "primary": True, "budgetPerTip": 100_000,
         "riskBudgetPerTip": RISK_BUDGET, "reserveSlots": 1, **extra}], journal=False)


async def _arm_and_fire(eng, sim, qty: int = 40, analyst: dict | None = None):
    from zargar.marketstructure.sessions import ET as REAL_ET
    # the $10k Practice book's caps bind at 50 sh here: every quantity in this file stays under them
    await eng.settings.set("risk.max_gross_exposure_pct", 100.0, journal=False)
    await eng.settings.set("techniques.tip.budget_per_tip", 100_000.0, journal=False)   # nor the source's $ budget
    sid = await _ingest_tip(eng)                         # long TEST, entry 99.5, stop 98, target 103
    if analyst:
        from zargar.models import Signal
        async with eng.sf() as s:
            row = await s.get(Signal, sid)
            row.extraction = {**(row.extraction or {}), "analyst": analyst}
            await s.commit()
    snap = await eng.tip_runner.arm_signal(sid, {"portfolioId": sim["id"], "mode": "auto", "instrument": "shares",
                                                 "qty": qty, "maxQty": 10_000, "dailyLossLimit": 5_000.0})
    run_id = snap["runId"]
    await _quote(eng, 99.6)
    y, m, d = (int(x) for x in snap["planFor"].split("-"))
    ts0 = int(dt.datetime(y, m, d, 10, 0, tzinfo=REAL_ET).timestamp() * 1000)
    if snap.get("lastBarTs"):
        ts0 = max(ts0, int(snap["lastBarTs"]) + MIN)
    await eng.tip_runner.on_bar(run_id, Bar(symbol="TEST", tf="1m", ts=ts0, open=100.0, high=100.2, low=99.8,
                                            close=100.0, volume=0))
    await _quote(eng, 99.5)
    s2 = await eng.tip_runner.on_bar(run_id, Bar(symbol="TEST", tf="1m", ts=ts0 + MIN, open=99.8, high=99.9,
                                                 low=99.4, close=99.6, volume=0))
    assert s2["triggers"][0]["status"] == "fired"
    trade = s2["trades"][0]
    assert trade["entryOrderId"], trade
    async with eng.sf() as s:
        order = await s.get(Order, trade["entryOrderId"])
    intent = [e for e in await _events(eng, "TechniquePlanOrderIntent") if e.get("runId") == run_id][-1]
    return run_id, order, intent


async def _handed_off(eng, run_id):
    for _ in range(6):
        await _quote(eng, 99.5)

    async def pos():
        out = [p for p in eng.position_manager.positions() if p.get("technique") == "tip" and p.get("runId") == run_id]
        return out[0] if out else None
    return await wait_for(pos, timeout=15)


async def test_armed_share_fill_in_scope_gets_the_atr_stop_and_is_sized_from_it(tip_rig, daily):
    eng, sim = tip_rig
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    await _bind_practice(eng, sim)
    run_id, order, intent = await _arm_and_fire(eng, sim)
    limit = float(order.limit_price)
    final = intent["stop"]
    # the declared 98 stop (~1.5 from the entry) is inside 2x daily ATR: re-placed at the swing default 3x ATR
    assert abs(final - (limit - 3 * ATR)) < 0.02, (final, limit)
    # sized from the FINAL stop at the same dollar risk (the direct path's budget), never the 98 stop
    assert order.qty == math.floor(RISK_BUDGET / (limit - final) + 1e-9)
    assert order.qty * (limit - final) <= RISK_BUDGET + 1e-6
    rep = [e for e in await _events(eng, "TipGeometryRepaired") if e.get("runId") == run_id]
    assert rep and rep[-1]["phase"] == "armed-fire" and rep[-1]["originalStop"] == 98.0
    assert abs(rep[-1]["finalStop"] - final) < 1e-6 and rep[-1]["atrDaily"] == ATR
    hz = [e for e in await _events(eng, "TipHorizonDecided") if e.get("where") == "armed_fire"]
    assert hz and hz[-1]["horizon"] == "swing" and hz[-1]["atrStop"] is True
    sized = [e for e in await _events(eng, "TipArmedFireSized") if e.get("runId") == run_id]
    assert sized and sized[-1]["atrStop"]["applied"] is True
    # the hand-off manages the stop that was sized (no second widen, no fill-time re-decision)
    pos = await _handed_off(eng, run_id)
    assert abs(pos["policy"]["stop"]["price"] - final) < 1e-6
    assert not [e for e in await _events(eng, "TipHorizonDecided") if e.get("where") == "armed_fill"]


async def test_analyst_exit_campaign_keeps_the_sized_atr_stop(tip_rig, daily):
    """The hand-off's analyst branch reuses the fire's horizon stamp and manages the stop that was sized (not the
    analyst's narrower 98.5, and no fill-time re-decision)."""
    eng, sim = tip_rig
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    await _bind_practice(eng, sim)
    run_id, order, intent = await _arm_and_fire(eng, sim, analyst={
        "verdict": "take", "runId": "an-atr01", "exit_targets": [101.0, 104.0, 107.0],
        "exit_fractions": [0.4, 0.4, 0.2], "underlying_stop": 98.5, "max_hold_sessions": 6})
    final = intent["stop"]
    assert abs(final - (float(order.limit_price) - 3 * ATR)) < 0.02
    pos = await _handed_off(eng, run_id)
    assert "exit:analyst:an-atr01" in pos["tags"]
    assert abs(pos["policy"]["stop"]["price"] - final) < 1e-6
    assert pos["policy"].get("horizon") == "swing"
    assert not [e for e in await _events(eng, "TipHorizonDecided") if e.get("where") == "armed_fill"]


async def test_unbound_practice_book_in_scope_resizes_on_the_atr_stop(tip_rig, daily):
    """A Practice book with no explicit `techniques.tip.books` binding keeps the runner's quantity until the ATR
    floor widens the stop - then the size comes from the final stop against the risk budget."""
    eng, sim = tip_rig
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", RISK_BUDGET, journal=False)
    run_id, order, intent = await _arm_and_fire(eng, sim)
    limit, final = float(order.limit_price), intent["stop"]
    assert abs(final - (limit - 3 * ATR)) < 0.02
    assert order.qty == math.floor(RISK_BUDGET / (limit - final) + 1e-9)
    sized = [e for e in await _events(eng, "TipArmedFireSized") if e.get("runId") == run_id]
    assert sized and sized[-1]["role"] == "legacy" and sized[-1]["runnerQty"] == 40


@pytest.mark.parametrize("knob,value", [("techniques.tip.stop_atr_mode", "off"),
                                        ("techniques.tip.geometry_gate", "shadow")])
async def test_out_of_scope_keeps_the_arm_time_stop(tip_rig, daily, knob, value):
    eng, sim = tip_rig
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    await eng.settings.set(knob, value, journal=False)
    await _bind_practice(eng, sim)
    run_id, order, intent = await _arm_and_fire(eng, sim)
    assert intent["stop"] == 98.0
    limit = float(order.limit_price)
    if value == "off":
        # the enforced book sizing still runs - against the arm-time stop
        assert order.qty == math.floor(RISK_BUDGET / (limit - 98.0) + 1e-9)
    else:
        assert order.qty == 40                           # shadow gate: the runner's quantity, as before
    assert not [e for e in await _events(eng, "TipGeometryRepaired") if e.get("runId") == run_id]
    assert not [e for e in await _events(eng, "TipHorizonDecided") if e.get("where") == "armed_fire"]
    pos = await _handed_off(eng, run_id)
    assert pos["policy"]["stop"]["price"] == 98.0


async def test_options_are_untouched(tip_rig, daily):
    """The ATR stop lives in the SHARE sizing hook: an option fire in scope keeps its declared stop and sizing."""
    from zargar.options import occ as occ_mod

    from .test_tip_express import FakeChain, row as chain_row
    from .test_tip_runner import OPT_SOURCE, _opt_quote, canned_option_tip
    eng, sim = tip_rig
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    await _bind_practice(eng, sim)
    exp14 = (dt.date.today() + dt.timedelta(days=14)).isoformat()
    eng.options.use_client(FakeChain(spot=100.0, expiries=(exp14,),
                                     rows=[chain_row(101.0, expiry=exp14), chain_row(103.0, expiry=exp14),
                                           chain_row(99.0, "put", expiry=exp14)]))
    occ_sym = occ_mod.make("TEST", exp14, "C", 101.0).symbol
    from zargar.domain import new_id
    from zargar.models import RawContent
    content = RawContent(id=new_id(), source_type="manual", source_name="TestRoom", subject="tip",
                         body_text=OPT_SOURCE)
    async with eng.sf() as session:
        session.add(content)
        await session.commit()
    out = await eng.signals_service.handle_extraction(content, canned_option_tip(exp14), source_text=OPT_SOURCE)
    sid = out[0]["signal"]["id"]
    snap = await eng.tip_runner.arm_signal(sid, {"portfolioId": sim["id"], "mode": "auto", "dailyLossLimit": 200.0})
    assert snap["config"]["instrument"] == "options"
    run_id = snap["runId"]
    await _quote(eng, 99.6)
    await _opt_quote(eng, occ_sym, 1.1)
    from zargar.marketstructure.sessions import ET as REAL_ET
    y, m, d = (int(x) for x in snap["planFor"].split("-"))
    ts0 = int(dt.datetime(y, m, d, 10, 0, tzinfo=REAL_ET).timestamp() * 1000)
    if snap.get("lastBarTs"):
        ts0 = max(ts0, int(snap["lastBarTs"]) + MIN)
    await _quote(eng, 99.5)
    s2 = await eng.tip_runner.on_bar(run_id, Bar(symbol="TEST", tf="1m", ts=ts0, open=99.8, high=99.9, low=99.4,
                                                 close=99.6, volume=0))
    trade = s2["trades"][0]
    assert trade["instrument"] == "options", trade
    assert trade["stop"] == 98.0
    assert not [e for e in await _events(eng, "TipGeometryRepaired") if e.get("runId") == run_id]
    assert not [e for e in await _events(eng, "TipHorizonDecided") if e.get("where") == "armed_fire"]
