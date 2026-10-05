"""Tips v0.9 V5/V6/V7 (2026-10-05) on the real engine (sim broker, offline): risk-first sizing names the binding cap,
the open-risk and sector caps refuse on the record, the source grade rides every card and (enforce) sizes/blocks,
the decision-time context + chase/regime guards observe or enforce, the desk report carries the Tips block.
Network lookups are stubbed through `entry_context.OVERRIDE`; no LLM."""
import datetime as dt
import uuid

import pytest

from zargar.domain import Bar
from zargar.engine import Engine
from zargar.models import ManagedPositionRow
from zargar.signals.service import attach_signal_layer
from zargar.techniques.tip import entry_context as EC

from .conftest import make_test_config
from .test_tip_geometry_wiring import _events, _quote, _tip


@pytest.fixture
async def rig(fresh_db):
    EC.clear_cache()
    EC.OVERRIDE = None
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    await eng.settings.set("techniques.tip.budget_per_tip", 5000.0, journal=False)
    yield eng
    EC.OVERRIDE = None
    EC.clear_cache()
    await eng.stop()


def _book(eng) -> str:
    return next(p for p in eng.positions.portfolios() if p["kind"] == "sim" and not p.get("book"))["id"]


async def _held(eng, pid, symbol, *, qty=10.0, avg=100.0, stop=90.0, status="open", source="Other", extras=None,
                realized=None, closed_ms=None, close_reason=None, peak=None, risk=None):
    row = ManagedPositionRow(
        id=uuid.uuid4().hex, technique="tip", symbol=symbol, portfolio_id=pid, status=status,
        tags=[f"source:{source}"],
        config={"entry": avg, "risk": (risk if risk is not None else avg - stop), "policy": {"stop": {"kind": "fixed", "price": stop}},
                **({"extras": extras} if extras else {})},
        legs=[{"qty": (0.0 if status == "closed" else qty), "symbol": symbol, "avgFill": avg, "secType": "STK",
               "multiplier": 1.0, "entryOrderId": None}],
        state={"policyState": {"stop": stop, **({"peakFavorable": peak} if peak is not None else {})},
               **({"realizedPnl": realized} if realized is not None else {}),
               **({"closedMs": closed_ms} if closed_ms else {}), **({"closeReason": close_reason} if close_reason else {})})
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    return row.id


def _stub(*, sector="Technology", daily=None, spy=None, vix=None, short_ratio=None):
    async def d(sym, days):
        return (spy if sym == "SPY" else daily) or []

    async def prof(sym):
        return {"sector": sector, "shortRatio": short_ratio}

    async def v():
        return vix

    async def earn(sym):
        return None
    EC.OVERRIDE = {"daily": d, "profile": prof, "vix": v, "earnings": earn}


def _bars(sym: str, closes: list[float], *, end=None) -> list:
    end = end or (dt.datetime.now(EC.ET).date() - dt.timedelta(days=1))
    days, day = [], end
    while len(days) < len(closes):
        if day.weekday() < 5:
            days.append(day)
        day -= dt.timedelta(days=1)
    out = []
    for d, c in zip(reversed(days), closes):
        ts = int(dt.datetime(d.year, d.month, d.day, 9, 30, tzinfo=EC.ET).timestamp() * 1000)
        out.append(Bar(symbol=sym, tf="1d", ts=ts, open=c, high=c * 1.01, low=c * 0.99, close=c, volume=1_000_000))
    return out


# ------------------------------------------------------------------ V5.1
async def test_risk_first_sizing_binds_on_a_wide_stop_and_names_the_cap(rig):
    eng = rig
    await eng.settings.set("techniques.tip.geometry_gate", "off", journal=False)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 50.0, journal=False)
    q = await _quote(eng, "RFSA")
    row, sig = await _tip(eng, "RFSA", q.last, stop_pct=10.0)
    p = await eng.proposals.create_from_signal(row, sig, {})
    assert p is not None
    rf = p["context"]["sizing"]["riskFirst"]
    assert rf["binding"] == "risk" and rf["applied"] is True and rf["sizedBy"] == "risk-first sizing"
    assert p["qty"] == rf["caps"]["risk"] < rf["caps"]["notional"]
    assert p["qty"] * rf["stopDistance"] <= 50.0 + 1e-6
    assert p["context"]["sourceGrade"]["status"] == "ungraded"
    # the switch off restores notional sizing (the cap is still recorded)
    await eng.settings.set("techniques.tip.risk_first_sizing", False, journal=False)
    row2, sig2 = await _tip(eng, "RFSA", q.last, stop_pct=10.0)
    p2 = await eng.proposals.create_from_signal(row2, sig2, {})
    assert p2["qty"] > p["qty"] and p2["context"]["sizing"]["riskFirst"]["applied"] is False


async def test_a_trade_over_the_open_risk_cap_is_refused_on_the_record(rig):
    eng = rig
    await eng.settings.set("techniques.tip.geometry_gate", "off", journal=False)
    pid = _book(eng)
    eq = await eng.positions.equity(pid)
    # open positions already risk 4.9% of equity to their stops
    await _held(eng, pid, "ORA1", qty=round(eq * 0.049 / 10.0, 4), avg=100.0, stop=90.0)
    q = await _quote(eng, "ORSK")
    row, sig = await _tip(eng, "ORSK", q.last, stop_pct=5.0)
    assert await eng.proposals.create_from_signal(row, sig, {}) is None
    refused = [e for e in await _events(eng, "TipLaneDecided") if e.get("lane") == "refused"]
    assert refused and "open-risk cap" in refused[-1]["reason"]
    # a per-book override widens it
    await eng.settings.set("techniques.tip.books", [{"portfolioId": pid, "role": "practice", "primary": True,
                                                     "maxOpenRiskPct": 50}], journal=False)
    row2, sig2 = await _tip(eng, "ORSK", q.last, stop_pct=5.0)
    p = await eng.proposals.create_from_signal(row2, sig2, {})
    assert p is not None and p["context"]["sizing"]["openRisk"]["capPct"] == 50


# ------------------------------------------------------------------ V5.3
async def test_sector_cap_refuses_the_third_name_and_unknown_sector_never_blocks(rig):
    eng = rig
    pid = _book(eng)
    await _held(eng, pid, "SECA", qty=1, avg=10, stop=9.9)
    await _held(eng, pid, "SECB", qty=1, avg=10, stop=9.9)
    _stub(sector="Technology")
    q = await _quote(eng, "SECC")
    row, sig = await _tip(eng, "SECC", q.last, stop_pct=2.0)
    assert await eng.proposals.create_from_signal(row, sig, {}) is None
    refused = [e for e in await _events(eng, "TipLaneDecided") if e.get("lane") == "refused"]
    assert "sector cap" in refused[-1]["reason"] and "SECA" in refused[-1]["reason"]
    EC.clear_cache()
    _stub(sector=None)
    row2, sig2 = await _tip(eng, "SECC", q.last, stop_pct=2.0)
    assert await eng.proposals.create_from_signal(row2, sig2, {}) is not None


# ------------------------------------------------------------------ V5.2 / V6.4
async def _graded_history(eng, pid, source, rs):
    now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    for i, r in enumerate(rs):
        await _held(eng, pid, f"H{i}", status="closed", source=source, realized=r * 100.0,
                    extras={"riskPlan": {"plannedRisk": 100.0, "qty": 10}}, closed_ms=now - 86400_000 * 3)


async def test_negative_source_is_observed_then_watch_only_in_enforce(rig):
    eng = rig
    pid = _book(eng)
    await _graded_history(eng, pid, "BadSrc", [-1.0] * 14 + [1.0] * 6)
    q = await _quote(eng, "KELA")
    row, sig = await _tip(eng, "KELA", q.last, stop_pct=2.0, source="BadSrc")
    p = await eng.proposals.create_from_signal(row, sig, {})
    assert p is not None, "observe mode still mints the card"
    g = p["context"]["sourceGrade"]
    assert g["status"] == "negative" and g["n"] == 20 and g["kelly"]["watchOnly"] and g["kelly"]["mode"] == "observe"
    wo = await _events(eng, "TipSourceWatchOnly")
    assert wo and wo[-1]["mode"] == "observe" and wo[-1]["applied"] is False
    await eng.settings.set("techniques.tip.source_kelly_mode", "enforce", journal=False)
    row2, sig2 = await _tip(eng, "KELA", q.last, stop_pct=2.0, source="BadSrc")
    assert await eng.proposals.create_from_signal(row2, sig2, {}) is None
    refused = [e for e in await _events(eng, "TipLaneDecided") if e.get("lane") == "refused"]
    assert "watch-only" in refused[-1]["reason"]


async def test_positive_source_in_enforce_scales_the_risk_budget(rig):
    eng = rig
    pid = _book(eng)
    await eng.settings.set("techniques.tip.geometry_gate", "off", journal=False)
    await _graded_history(eng, pid, "ThinSrc", [1.1] * 10 + [-1.0] * 10)    # edge +0.025R -> 1/4 Kelly ~0.57%
    q = await _quote(eng, "KELB")
    row, sig = await _tip(eng, "KELB", q.last, stop_pct=3.0, source="ThinSrc")
    obs = await eng.proposals.create_from_signal(row, sig, {})
    await eng.settings.set("techniques.tip.source_kelly_mode", "enforce", journal=False)
    row2, sig2 = await _tip(eng, "KELB", q.last, stop_pct=3.0, source="ThinSrc")
    enf = await eng.proposals.create_from_signal(row2, sig2, {})
    rb_obs = obs["context"]["sizing"]["riskFirst"]["riskBudget"]
    rb_enf = enf["context"]["sizing"]["riskFirst"]["riskBudget"]
    k = enf["context"]["sourceGrade"]["kelly"]
    assert k["applied"] and 0 < k["scale"] < 1
    assert rb_enf == pytest.approx(rb_obs * k["scale"], rel=0.02)
    assert enf["context"]["riskScale"]["parts"]["kelly"] == k["scale"]


# ------------------------------------------------------------------ V6
async def test_entry_context_rides_the_card_and_the_chase_filter_observes_then_enforces(rig):
    eng = rig
    await eng.settings.set("techniques.tip.geometry_gate", "off", journal=False)
    q = await _quote(eng, "CHSA")
    px = float(q.last)
    # the prior close sits 4% below the live price: a chased entry
    daily = _bars("CHSA", [px / 1.04 * (1 + 0.001 * (i - 60)) for i in range(61)])
    spy = _bars("SPY", [400 + 0.1 * i for i in range(540)])
    _stub(sector="Energy", daily=daily, spy=spy, vix=17.0, short_ratio=3.4)
    row, sig = await _tip(eng, "CHSA", px, stop_pct=3.0)
    p = await eng.proposals.create_from_signal(row, sig, {})
    ec = p["context"]["entryContext"]
    assert ec["sector"] == "Energy" and ec["shortRatio"] == 3.4 and ec["atrPct"] is not None
    assert ec["regime"]["vix"] == 17.0 and ec["regime"]["spyAbove200"] is True
    ch = p["context"]["guards"]["chase"]
    assert ch["chased"] and ch["mode"] == "observe" and not ch["applied"]
    shadows = await _events(eng, "TipChaseShadow")
    assert shadows and shadows[-1]["signalId"] == row.id
    qty_obs = p["qty"]
    await eng.settings.set("techniques.tip.chase_filter", "enforce", journal=False)
    row2, sig2 = await _tip(eng, "CHSA", px, stop_pct=3.0)
    p2 = await eng.proposals.create_from_signal(row2, sig2, {})
    assert p2["context"]["guards"]["chase"]["applied"] and p2["context"]["exitPlan"]["maxHoldSessions"] <= 3
    assert p2["qty"] <= max(1, qty_obs // 2 + 1)
    assert p2["context"]["riskScale"]["parts"]["chase"] == 0.5


async def test_hostile_regime_is_journaled_as_a_shadow(rig):
    eng = rig
    q = await _quote(eng, "RGMA")
    px = float(q.last)
    daily = _bars("RGMA", [px * (1 + 0.001 * (i - 60)) for i in range(61)])
    spy = _bars("SPY", [600 - 0.3 * i for i in range(540)])                # 2-year return < 0
    _stub(daily=daily, spy=spy, vix=32.0)
    row, sig = await _tip(eng, "RGMA", px, stop_pct=3.0)
    p = await eng.proposals.create_from_signal(row, sig, {})
    rg = p["context"]["guards"]["regime"]
    assert rg["hostile"] and rg["would"] == "halve" and not rg["applied"]
    ev = await _events(eng, "TipRegimeShadow")
    assert ev and ev[-1]["regime"]["vix"] == 32.0


async def test_prefetch_seeds_the_decision_time_context_line(rig):
    eng = rig
    from zargar.techniques.tip import prefetch as PF
    q = await _quote(eng, "PFCA")
    daily = _bars("PFCA", [float(q.last) * (1 + 0.001 * (i - 60)) for i in range(61)])
    _stub(daily=daily, spy=_bars("SPY", [400 + 0.1 * i for i in range(540)]), vix=20.0, short_ratio=8.0)
    row, _sig = await _tip(eng, "PFCA", float(q.last), stop_pct=3.0)
    pre = await PF.prefetch(eng, row, timeout_s=5.0)
    assert pre["items"]["context"]["ok"]
    seed = PF.seed_block(pre, fetched_at="now")
    assert "decision-time context" in seed and "days-to-cover 8" in seed


async def test_offline_feed_gives_no_context_and_never_blocks(rig):
    eng = rig
    q = await _quote(eng, "OFFA")
    row, sig = await _tip(eng, "OFFA", q.last, stop_pct=2.0)
    p = await eng.proposals.create_from_signal(row, sig, {})
    assert p is not None
    assert ("entryContext" not in p["context"]) or (p["context"]["entryContext"]["status"] == "offline")


# ------------------------------------------------------------------ V7.3
async def test_morning_report_carries_the_tips_block(rig):
    eng = rig
    from zargar.desk import attach_desk
    pid = _book(eng)
    await _held(eng, pid, "DSKA", qty=10, avg=100.0, stop=95.0)
    now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    await _held(eng, pid, "DSKB", status="closed", realized=100.0, risk=5.0, stop=95.0, peak=10.0,
                extras={"riskPlan": {"plannedRisk": 50.0, "qty": 10}}, closed_ms=now - 3600_000, close_reason="stop hit")
    # the session after the stop-out traded 106 >= entry 100 + 1R (5): a noise stop-out
    _stub(daily=[Bar(symbol="DSKB", tf="1d", ts=now + 3600_000, open=101.0, high=106.0, low=100.0, close=105.0)])
    desk = getattr(eng, "desk", None) or attach_desk(eng)
    r = await desk.morning_report()
    tb = r["tips"]["books"][0]
    assert tb["openPositions"] == 1 and tb["openRisk"] == 50.0 and tb["openRiskCapPct"] == 5.0
    assert tb["horizonMix"] == {"unlabelled": 1} and tb["utilisationPct"] is not None
    c = tb["closed"][0]
    assert c["r"] == 2.0 and c["peakR"] == 2.0 and c["mfeKept"] == 1.0
    assert tb["stopOuts"] == 1 and tb["noiseStopOuts"] == 1 and tb["noiseUnknown"] == 0
