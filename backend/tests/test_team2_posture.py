"""Team2 posture items closed after the second review (PLAN 'Second review'): X5 trim-and-add,
X3b the running high/low of day as a re-entry's target, and — on the runner — trims judged on the
contract's LIVE premium before the model's, adds placed as real orders on the same contract.
Session tests are synthetic days (no DB); runner tests use the engine rig."""
from __future__ import annotations

import math

import pytest

from zargar.domain import Quote
from zargar.execution.planrunner import Trade
from zargar.marketdata import persist_bars
from zargar.marketstructure import aggregate, filter_session
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.session import simulate_session

from .test_team2_runner import rig  # noqa: F401 - the engine fixture
from .test_team2_session import DAY, make_rules, path_1m, prev_day_bars, trend_day, zones_of

PREV = prev_day_bars()
TOP = zones_of(PREV)["pdh"].top


def run(price_fn, **rule_kw):
    rules = make_rules(**rule_kw)
    today = path_1m(DAY, (4, 0), (20, 0), price_fn)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(PREV, 15), rules), today)
    return simulate_session(plan, today, rules, sigma=0.2, warmup_1m=PREV)


def _pre(i):
    return 566 + 2.0 * (i / 330)


def add_day(i):
    """Break, EMA dip (entry), rally (+50/+100% trims), a second EMA13 hold (the add), rally on, fade."""
    m = 4 * 60 + i
    if m < 9 * 60 + 30:
        return _pre(i)
    x = m - 9 * 60 - 30
    if x < 15:
        return 568.5 + (TOP + 1.2 - 568.5) * (x / 14)
    if x < 30:
        return TOP + 1.2 - 1.0 * ((x - 15) / 15)
    if x < 70:
        return TOP + 0.2 + 3.5 * ((x - 30) / 40)
    if x < 82:
        return TOP + 3.7 - 1.3 * ((x - 70) / 12)
    if x < 150:
        return TOP + 2.4 + 4.0 * ((x - 82) / 68)
    if x < 300:
        return TOP + 6.4 - 6.0 * ((x - 150) / 150)
    return TOP + 0.4 + 0.05 * math.sin(i / 3)


def hod_day(i):
    """Break, entry 1 pushes to the HOD then stops out; entry 2 on the next dip targets that HOD."""
    m = 4 * 60 + i
    if m < 9 * 60 + 30:
        return _pre(i)
    x = m - 9 * 60 - 30
    if x < 15:
        return 568.5 + (TOP + 1.2 - 568.5) * (x / 14)
    if x < 30:
        return TOP + 1.2 - 1.0 * ((x - 15) / 15)
    if x < 50:
        return TOP + 0.2 + 3.0 * ((x - 30) / 20)
    if x < 70:
        return TOP + 3.2 - 2.6 * ((x - 50) / 20)
    if x < 95:
        return TOP + 0.6 + 1.6 * ((x - 70) / 25)
    if x < 105:
        return TOP + 2.2 - 0.7 * ((x - 95) / 10)
    if x < 150:
        return TOP + 1.5 + 2.5 * ((x - 105) / 45)
    if x < 300:
        return TOP + 4.0 - 4.0 * ((x - 150) / 150)
    return TOP + 0.05 * math.sin(i / 3)


def test_trim_and_add_refills_the_position_on_the_next_ema_hold():
    res = run(add_day)
    adds = [e for e in res.events if e["event"] == "add"]
    assert adds and "re-up" in adds[0]["why"] and adds[0]["fraction"] == pytest.approx(2 / 3, abs=0.01)
    t = res.trades[0]
    assert t["adds"] == 1 and t["avgPremium"] > t["entryPremium"]          # the average moved up with the add
    assert t["added"][0]["avgPremium"] == t["avgPremium"]
    # the add happened AFTER a trim, never before ("free up room for adds")
    trims = [e for e in res.events if e["event"] == "trim"]
    assert trims and trims[0]["ts"] < adds[0]["ts"]
    off = run(add_day, add_on_retest=False)
    assert not [e for e in off.events if e["event"] == "add"] and off.trades[0]["adds"] == 0


def test_reentry_targets_the_high_of_day():
    res = run(hod_day)
    assert len(res.trades) >= 2
    first, second = res.trades[0], res.trades[1]
    assert first["targetKind"] == "plan"                                   # a first entry keeps the planned level
    assert second["targetKind"] == "hod" and "high of day" in second["exitReason"]
    fire2 = [e for e in res.events if e["event"] == "fire"][1]
    assert fire2["targetKind"] == "hod" and "high of day" in fire2["why"]
    # the HOD it targets is where the first push topped out
    assert second["target"] == pytest.approx(TOP + 3.2, abs=0.15)             # the first push topped at TOP+3.2
    off = run(hod_day, hod_target="off")
    assert all(t["targetKind"] == "plan" for t in off.trades)
    always = run(hod_day, hod_target="always")
    assert always.trades[0]["targetKind"] in ("plan", "hod")               # first entries may take it too


async def test_live_premium_trims_beat_the_model(rig, monkeypatch):
    eng, sim = rig
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    await persist_bars(eng.sf, prev)
    await persist_bars(eng.sf, filter_session(today, "pre"))
    out = await eng.team2.nightly_plans(DAY.isoformat(), arm=True)
    run_id = out["armed"][0]
    runner = eng.team2_runner
    ap = runner.get(run_id)
    rules = runner.rules()
    calls: list[tuple] = []

    async def fake_exit(ap_, tr, kind, qty, *, journal, force_market=False, reason=""):
        calls.append((kind, qty, reason))
        tr.remaining -= qty
        tr.exits.append({"kind": kind, "qty": qty, "status": "FILLED", "filledQty": qty})

    monkeypatch.setattr(runner, "_exit", fake_exit)
    tr = Trade(trigger_id="scenario_1@09:30#1", kind="scenario_1", fired_ts=1, window="team2", entry=570.0,
               stop=569.0, targets=[], status="open", setup_id="scenario_1@09:30", filled_qty=3, remaining=3,
               avg_fill=0.50, instrument="options", order_symbol="SPY260904C00573000", multiplier=100.0)
    ap.trades[tr.trigger_id] = tr
    runner._last_sim[run_id] = {"openPosition": {"setup": tr.setup_id}}
    trim1 = {"event": "trim", "why": "+53% ≥ +50% — first trim (V2)", "fraction": 1 / 3, "pnlPct": 53.0, "ts": 1}
    # the model says +53% but the contract is only +10% live → the trim is deferred to the live watch
    eng.quotes.on_quote(Quote(symbol=tr.order_symbol, bid=0.55, ask=0.57, last=0.56))
    await runner._exit_from_event(ap, trim1, journal=True)
    assert not calls and any(e["event"] == "trim_deferred_live" for e in ap.events)
    # the contract gets there: the live watch takes the first trim on its own
    eng.quotes.on_quote(Quote(symbol=tr.order_symbol, bid=0.80, ask=0.82, last=0.81))
    await runner._manage_live_trims(ap, rules, journal=True)
    assert calls and calls[0][0] == "tp1" and calls[0][1] == 1 and tr.trims_done == 1
    assert "live premium" in calls[0][2]
    # the model's own first trim arriving later is a no-op
    await runner._exit_from_event(ap, trim1, journal=True)
    assert len(calls) == 1 and any(e["event"] == "trim_already_live" for e in ap.events)
    # second trim live at +100%
    eng.quotes.on_quote(Quote(symbol=tr.order_symbol, bid=1.05, ask=1.07, last=1.06))
    await runner._manage_live_trims(ap, rules, journal=True)
    assert calls[-1][0] == "tp2" and tr.trims_done == 2 and tr.remaining == 1
    # price-based exits (the candle stop) still act on the model at once, whatever the premium
    await runner._exit_from_event(ap, {"event": "exit", "why": "2m close 571.0 through the EMA13 571.2 (S1 one-candle stop)",
                                       "fraction": 1.0, "pnlPct": 40.0, "ts": 2}, journal=True)
    assert calls[-1][0] == "stop" and calls[-1][1] == 1 and tr.remaining == 0
    # the Armed snapshot carries the live premium
    snap = runner.detail(run_id)
    assert snap["team2"]["live"] is None or isinstance(snap["team2"]["live"], list)


def pm_retest_day(i):
    """Inside yesterday's range all day: pre-market 566–568; the 09:45 15m closes under the PM low
    568... no — under PML 566: pm_break_down; 10:04 retests 566.00 exactly and rejects; then it falls."""
    m = 4 * 60 + i
    if m < 9 * 60 + 30:
        return 566 + 2.0 * (i / 330)
    x = m - 9 * 60 - 30
    if x < 15:
        return 568.0 - 2.4 * (x / 14)                 # 15m body closes at 565.6, under the PML 566
    if x < 34:
        return 565.6 + 0.4 * ((x - 15) / 19)          # drifts back up to the PML
    if x < 40:
        return 566.0 - 0.05 * (x - 34)                # rejects right at 566.00
    if x < 120:
        return 565.7 - 4.0 * ((x - 40) / 80)
    return 561.7 + 0.05 * math.sin(i / 3)


def test_pm_break_retest_of_its_own_level_enters_small():
    """F20: the PM-break setup's retest of the PM level IS the L2.6/L2.7 entry — small size, never
    refused as the no-trade zone (SPY 2026-09-04 10:44 was refused and ran through its target)."""
    res = run(pm_retest_day)
    pm = [s for s in res.setups if s["kind"] == "pm_break_down"]
    assert pm, [s["kind"] for s in res.setups]
    fires = [e for e in res.events if e["event"] == "fire" and e["setup"] == pm[0]["id"]]
    assert fires and fires[0]["bucket"] == "small", [e for e in res.events if e["event"] in ("fire", "skip_no_trade_zone", "pm_retest")][:4]
    assert any(e["event"] == "pm_retest" for e in res.events)
    assert res.trades and res.trades[0]["direction"] == "short"


def test_gap_day_pm_range_is_chop_and_pm_levels_are_the_setup():
    """F15: on a gap-up day the PM range above the PDH zone is the no-trade zone, and a 15m close
    beyond the PM level arms a pm_break setup even though price is outside yesterday's range."""
    top = TOP
    def f(i):
        m = 4 * 60 + i
        if m < 9 * 60 + 30:
            return top + 1.0 + 1.0 * math.sin(i / 60)      # pre-market ranges top+0 … top+2, all above the PDH zone
        x = m - 9 * 60 - 30
        if x < 15:
            return top + 1.2 + 1.3 * (x / 14)               # opens gap-up inside the PM range, 15m closes above the PMH
        if x < 30:
            return top + 2.5 - 0.6 * ((x - 15) / 15)        # dips toward the EMA / the PMH
        if x < 120:
            return top + 1.9 + 4.0 * ((x - 30) / 90)
        return top + 5.9 - 3.0 * ((x - 120) / 270)
    rules = make_rules()
    today = path_1m(DAY, (4, 0), (20, 0), f)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(PREV, 15), rules), today)
    assert plan["dayType"] == "gap_up" and plan["sizingAtOpen"] == "none"      # F15(a): inside the PM range
    res = simulate_session(plan, today, rules, sigma=0.2, warmup_1m=PREV)
    kinds = [s["kind"] for s in res.setups]
    assert "pm_break_up" in kinds, kinds                                        # F15(b): the PM level is a setup on a gap day
    for e in res.events:
        if e["event"] == "fire":
            assert not (plan["pml"] < e["spot"] < plan["pmh"]) or e.get("bucket") == "small", e


async def test_sizing_can_be_changed_on_an_armed_plan(rig):
    """The per-trade budget and risk % move in place (user 2026-09-04: 500 -> 2000), without re-arming."""
    eng, sim = rig
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    await persist_bars(eng.sf, prev)
    out = await eng.team2.nightly_plans(DAY.isoformat(), arm=True)
    run_id = out["armed"][0]
    runner = eng.team2_runner
    ap = runner.get(run_id)
    assert ap.config.premium_budget == 2000.0 and ap.config.risk_pct == 6.0     # tonight's defaults
    snap = await runner.set_mode(run_id, premium_budget=750.0, risk_pct=3.0)
    assert ap.config.premium_budget == 750.0 and ap.config.risk_pct == 3.0 and ap.config.mode == "alert"
    # in AUTO a risk % change re-derives the plan's dollar loss halt (QQQ 2026-09-04: $341 limit under a $2,000 budget)
    await runner.set_mode(run_id, "auto", risk_pct=3.0)
    lim3 = ap.config.daily_loss_limit
    await runner.set_mode(run_id, risk_pct=6.0)
    assert ap.config.daily_loss_limit == pytest.approx(lim3 * 2, rel=0.05) and ap.config.daily_loss_limit > 0
    await runner.set_mode(run_id, "alert")
    assert snap["config"]["premiumBudget"] == 750.0
    assert any(e["event"] == "mode_changed" and "premium budget" in str(e) for e in ap.events)
    restored = await runner.load_plan(run_id)
    assert restored is not None


async def test_never_chase_cap_is_the_premium_band(rig):
    """F14: the cap must bind when the live ask ran past the method's band, and stay at ask + tick inside it."""
    eng, sim = rig
    runner = eng.team2_runner
    rules = runner.rules()
    band = round(rules.target_premium * rules.chase_cap_mult, 2)
    ap = None
    trade = Trade(trigger_id="t", kind="scenario_1", fired_ts=1, window="team2", entry=1.0, stop=0.9, targets=[])
    inside = await runner.entry_limit_cap(ap, trade, {"ask": 0.55})
    assert inside == pytest.approx(0.55 + rules.tick)
    ran = await runner.entry_limit_cap(ap, trade, {"ask": 1.20})
    assert ran == pytest.approx(band) and ran < 1.20
    assert await runner.entry_limit_cap(ap, trade, {"ask": 0}) == pytest.approx(band)


async def test_small_positions_do_not_trim_and_adds_are_alerts_outside_auto(rig, monkeypatch):
    eng, sim = rig
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    await persist_bars(eng.sf, prev)
    await persist_bars(eng.sf, filter_session(today, "pre"))
    out = await eng.team2.nightly_plans(DAY.isoformat(), arm=True)
    run_id = out["armed"][0]
    runner = eng.team2_runner
    ap = runner.get(run_id)
    rules = runner.rules()
    calls: list[tuple] = []

    async def fake_exit(ap_, tr, kind, qty, *, journal, force_market=False, reason=""):
        calls.append((kind, qty, reason))
        tr.remaining -= qty

    monkeypatch.setattr(runner, "_exit", fake_exit)
    tr = Trade(trigger_id="scenario_1@09:30#1", kind="scenario_1", fired_ts=1, window="team2", entry=570.0,
               stop=569.0, targets=[], status="open", setup_id="scenario_1@09:30", filled_qty=1, remaining=1,
               avg_fill=0.50, instrument="options", order_symbol="SPY260904C00573000", multiplier=100.0)
    ap.trades[tr.trigger_id] = tr
    runner._last_sim[run_id] = {"openPosition": {"setup": tr.setup_id}}
    # one contract cannot be trimmed: +50% does nothing, +100% exits the whole position
    eng.quotes.on_quote(Quote(symbol=tr.order_symbol, bid=0.80, ask=0.82, last=0.81))
    await runner._manage_live_trims(ap, rules, journal=True)
    assert not calls and any(e["event"] == "too_small_to_trim" for e in ap.events)
    eng.quotes.on_quote(Quote(symbol=tr.order_symbol, bid=1.05, ask=1.07, last=1.06))
    await runner._manage_live_trims(ap, rules, journal=True)
    assert calls and calls[0][0] == "tp2" and calls[0][1] == 1
    # an add in alert mode is recorded, never ordered
    bar = filter_session(today, "rth")[40]
    await runner._add_from_event(ap, {"event": "add", "setup": tr.setup_id, "fraction": 0.33, "premium": 0.9,
                                      "adds": 1, "ts": bar.ts, "spot": bar.close, "why": "re-up"}, bar,
                                 halted=False, journal=True)
    assert any(e["event"] == "would_add" for e in ap.events)
    assert not [t for t in ap.trades.values() if getattr(t, "is_add", False)]
