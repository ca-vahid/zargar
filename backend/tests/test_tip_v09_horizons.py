"""Tips v0.9 V2 (horizon at entry), V3 (ATR stops at equal risk, close-judged) and V4 (profit taking by horizon),
2026-10-05. Plan: docs/techniques/tip/research/2026-10-04-v09/PLAN.md. No LLM calls; the engine tests run offline."""
import datetime as dt

import pytest

from zargar.domain import Bar, new_id
from zargar.execution.policies import (
    PolicyState,
    PositionView,
    apply_moves,
    effective_policy,
    evaluate,
    promotion_due,
    validate_policy,
)
from zargar.techniques.tip import horizon_class as hc
from zargar.techniques.tip import horizon_policy as hp
from zargar.techniques.tip.geometry import fit_expression
from zargar.techniques.tip.lifecycle import check_exit_geometry, policy_from_exit_plan


class _S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


S = _S({})


def _bar(close, *, high=None, low=None, tf="15m", ts=1_790_000_000_000):
    return Bar(symbol="X", tf=tf, ts=ts, open=close, high=high if high is not None else close,
               low=low if low is not None else close, close=close, volume=1)


def _daily(closes):
    return [Bar(symbol="X", tf="1d", ts=1_780_000_000_000 + i * 86_400_000, open=c, high=c, low=c, close=c, volume=1)
            for i, c in enumerate(closes)]


# ------------------------------------------------------------------------------------------- V2.1 classifier
def _cls(**kw):
    base = dict(direction="long", entry=100.0, prior_close=100.0, session_open=100.0, atr=4.0, catalyst=None,
                source="eva", settings=S)
    base.update(kw)
    return hc.classify(**base)


def test_classifier_default_is_swing():
    c = _cls()
    assert c["horizon"] == "swing" and not c["shortFlags"] and not c["extendedFlags"]
    assert c["facts"]["atrPct"] == 4.0 and c["version"] == hc.VERSION


@pytest.mark.parametrize("kw,needle", [
    ({"entry": 102.5}, "chased"),                       # +2.5% over the prior close
    ({"session_open": 102.0}, "gap"),                   # +2% gap at the open
    ({"atr": 2.0}, "low-ATR"),                          # 2% of price < 2.5%
    ({"catalyst": "earnings beat"}, "catalyst"),
])
def test_classifier_short_flags(kw, needle):
    c = _cls(**kw)
    assert c["horizon"] == "short" and needle in c["reason"]


def test_classifier_extended_flags_and_short_wins():
    assert _cls(entry=97.5)["horizon"] == "extended"                       # a down-day entry
    assert _cls(source="neal")["horizon"] == "extended"                    # a graded multi-week source
    both = _cls(source="neal", catalyst="FDA")                             # short flag beats extended
    assert both["horizon"] == "short" and both["extendedFlags"]
    unknown = _cls(prior_close=None, session_open=None, atr=None)
    assert unknown["horizon"] == "swing" and set(unknown["unknown"]) == {"entry vs prior close", "gap", "ATR"}


def test_resolve_keeps_a_consistent_analyst_horizon_and_records_disagreement():
    swing = _cls()
    r = hc.resolve(swing, "extended", "trend name, base breakout")
    assert r["horizon"] == "extended" and r["source"] == "analyst" and r["consistent"] is True
    chased = _cls(entry=103.0)
    r2 = hc.resolve(chased, "extended")
    assert r2["horizon"] == "short" and r2["source"] == "classifier" and r2["consistent"] is False
    assert hc.resolve(chased, "short")["consistent"] is True
    assert hc.resolve(swing, None)["source"] == "classifier"
    assert hc.resolve(swing, "monthly")["analyst"] is None                 # unknown vocabulary = no choice


# ------------------------------------------------------------------------------------------- V3.1 stops
def _plan(stop=None, horizon="swing", atr=3.0, applied=True, atr_stop=True, targets=()):
    p = {"targets": list(targets), "fractions": [], "horizon": horizon, "horizonApplied": applied,
         "atrDaily": atr, "atrStop": atr_stop}
    if stop is not None:
        p["underlyingStop"] = stop
    return p


def test_atr_stop_floor_replaces_the_percent_floor_and_keeps_wide_stops():
    tight, rep = check_exit_geometry(_plan(98.0), direction="long", entry_ref=100.0, bars=[], settings=S,
                                     vehicle="shares")
    assert tight["underlyingStop"] == 91.0 and any("daily ATR" in r for r in rep)   # 2 wide < 2x3 -> 3x3
    kept, rep2 = check_exit_geometry(_plan(93.0), direction="long", entry_ref=100.0, bars=[], settings=S,
                                     vehicle="shares")
    assert kept["underlyingStop"] == 93.0 and not rep2                               # 7 >= 2x ATR: never tightened
    short_h, _ = check_exit_geometry(_plan(99.0, horizon="short"), direction="long", entry_ref=100.0, bars=[],
                                     settings=S, vehicle="shares")
    assert short_h["underlyingStop"] == 94.0                                         # short default 2x ATR
    none, rep3 = check_exit_geometry(_plan(None), direction="long", entry_ref=100.0, bars=[], settings=S,
                                     vehicle="shares")
    assert none["underlyingStop"] == 91.0 and "no stop declared" in rep3[0]
    opt, _ = check_exit_geometry(_plan(None), direction="long", entry_ref=100.0, bars=[], settings=S,
                                 vehicle="option")
    assert opt.get("underlyingStop") is None                                         # options keep their guard
    legacy, _ = check_exit_geometry(_plan(99.5, atr_stop=False), direction="long", entry_ref=100.0, bars=[],
                                    settings=S, vehicle="shares")
    assert legacy["underlyingStop"] == 99.25                                         # the 0.75% floor stands


def test_short_direction_stop_mirrors():
    p, _ = check_exit_geometry(_plan(101.0), direction="short", entry_ref=100.0, bars=[], settings=S,
                               vehicle="option")
    assert p["underlyingStop"] == 109.0


def test_feasibility_and_gate_size_the_wider_stop_at_the_same_dollar_risk():
    # the analyst's 2-point stop would size 45 shares at $90; the gate re-places it at 3x ATR (9 points): 10 shares
    final, fit = fit_expression(direction="long", vehicle="shares", entry_ref=100.0, exit_plan=_plan(98.0),
                                bars=[], settings=S, premium=100.0, budget=90.0)
    assert fit["finalStop"] == 91.0 and fit["qtyByRisk"] == 10 and fit["horizon"] == "swing"
    assert fit["qtyByRisk"] * fit["unitLoss"] <= 90.0 + 1e-9
    legacy_final, legacy = fit_expression(direction="long", vehicle="shares", entry_ref=100.0,
                                          exit_plan={"underlyingStop": 98.0}, bars=[], settings=S, premium=100.0,
                                          budget=90.0)
    assert legacy["qtyByRisk"] == 45 and legacy["finalStop"] == 98.0


# ------------------------------------------------------------------------------------------- V4 ladder
def test_horizon_ladder_by_class_with_analyst_extras_and_a_runner():
    sw = hp.horizon_ladder(_plan(91.0, targets=[105.0, 115.0, 120.0]), entry_ref=100.0, direction="long",
                           settings=S)
    assert sw[0] == [109.0, 115.0, 120.0]                                            # 105 is inside +1R: dropped
    assert abs(sw[1][0] - 1 / 3) < 1e-3 and sum(sw[1]) <= 1 - 1 / 3 + 1e-3           # a third always runs
    sh = hp.horizon_ladder(_plan(94.0, horizon="short"), entry_ref=100.0, direction="long", settings=S)
    assert sh == ([106.0], [0.5])
    ex = hp.horizon_ladder(_plan(91.0, horizon="extended"), entry_ref=100.0, direction="long", settings=S)
    assert ex[0] == [113.5] and abs(ex[1][0] - 1 / 3) < 1e-3
    put = hp.horizon_ladder(_plan(109.0), entry_ref=100.0, direction="short", settings=S)
    assert put[0] == [91.0]
    assert hp.horizon_ladder(_plan(None), entry_ref=100.0, direction="long", settings=S) is None


def test_geometry_rebuilds_the_ladder_on_the_final_stop_idempotently():
    p1, _ = check_exit_geometry(_plan(98.0, targets=[130.0]), direction="long", entry_ref=100.0, bars=[],
                                settings=S, vehicle="shares")
    assert p1["targets"] == [109.0, 130.0] and p1["analystTargets"] == [130.0]
    p2, _ = check_exit_geometry(p1, direction="long", entry_ref=100.0, bars=[], settings=S, vehicle="shares")
    assert p2["targets"] == p1["targets"] and p2["fractions"] == p1["fractions"]
    obs, _ = check_exit_geometry(_plan(93.0, applied=False, targets=[130.0]), direction="long", entry_ref=100.0,
                                 bars=[], settings=S, vehicle="shares")
    assert obs["targets"] == [130.0]                                                  # observe: plan untouched


# ------------------------------------------------------------------------------------------- V2.2 policies
def test_swing_share_policy_shape():
    pol = policy_from_exit_plan(_plan(91.0, targets=[130.0]), is_option=False, settings=S, entry_ref=100.0)
    assert validate_policy(pol) == []
    assert pol["horizon"] == "swing" and pol["timeframe"] == "15m"
    assert pol["ladder"]["targets"] == [109.0, 130.0]
    assert pol["trailing"] == {"mode": "atr", "value": 3.0, "after_r": 1.0, "atr_abs": 3.0}
    assert pol["breakeven_on_trim"] is True and "breakeven_after_r" not in pol
    assert pol["stale"] == {"sessions": 10, "min_r": 0.5} and "time_stop_sessions" not in pol
    assert pol["quote_brake_r"] == 0.5 and pol["venue_stop_beyond_r"] == 0.5 and pol["gap_exit"] is True
    pr = pol["promote"]
    assert (pr["by_session"], pr["min_r"], pr["above_ma"]) == (5, 2.0, 20)
    assert pr["overlay"]["timeframe"] == "1d" and pr["overlay"]["stale"] is None
    assert pr["overlay"]["time_stop_sessions"] == 20 and pr["overlay"]["time_stop_unless_above_ma"] == 20


def test_short_and_extended_policy_shapes_and_option_caps():
    sh = policy_from_exit_plan(_plan(94.0, horizon="short"), is_option=False, settings=S, entry_ref=100.0)
    assert sh["ladder"] == {"targets": [106.0], "fractions": [0.5]} and sh["time_stop_sessions"] == 3
    assert sh["trailing"]["value"] == 2.0 and "breakeven_on_trim" not in sh and "quote_brake_r" not in sh
    ex = policy_from_exit_plan(_plan(91.0, horizon="extended"), is_option=False, settings=S, entry_ref=100.0)
    assert ex["timeframe"] == "1d" and ex["time_stop_sessions"] == 20 and ex["time_stop_unless_above_ma"] == 20
    assert ex["ladder"]["targets"] == [113.5] and validate_policy(ex) == []
    opt = policy_from_exit_plan({**_plan(91.0), "maxHoldSessions": 7}, is_option=True, settings=S, entry_ref=100.0)
    assert opt["time_stop_sessions"] == 7 and "venue_stop_beyond_r" not in opt      # never outlive the contract
    assert opt["premium_stop_pct"] and "promote" in opt and "time_stop_sessions" not in opt["promote"]["overlay"]


def test_legacy_and_observe_plans_keep_the_old_shape_but_shares_hold_two_sessions():
    legacy = policy_from_exit_plan({"underlyingStop": 99.0, "targets": [102.0], "fractions": [1.0],
                                    "maxHoldSessions": 1}, is_option=False, settings=S)
    assert legacy["trailing"]["mode"] == "structure" and "horizon" not in legacy
    assert legacy["time_stop_sessions"] == 2                                          # V2.4: never same-day
    observe = policy_from_exit_plan(_plan(91.0, applied=False), is_option=False, settings=S, entry_ref=100.0)
    assert "horizon" not in observe and observe["trailing"]["mode"] == "structure"
    lotto = policy_from_exit_plan({**_plan(91.0), "lotto": True}, is_option=True, settings=S, entry_ref=100.0)
    assert "horizon" not in lotto and lotto["expiry_day_flatten_et"]


# ------------------------------------------------------------------------------------------- generic evaluator
def _view(close, *, held=1, high=None, daily=(), risk=9.0, entry=100.0):
    return PositionView(direction="long", entry=entry, risk=risk, bar=_bar(close, high=high), bars=[_bar(close)],
                        sessions_held=held, daily_bars=_daily(daily) if daily else [])


def test_breakeven_only_with_the_partial():
    pol = {"stop": {"kind": "fixed", "price": 91.0}, "ladder": {"targets": [109.0], "fractions": [1 / 3]},
           "breakeven_on_trim": True}
    d, m = evaluate(pol, PolicyState(), _view(108.0))                       # +0.9R close, no trim: nothing
    assert d == [] and m == []
    d, m = evaluate(pol, PolicyState(), _view(108.0, high=109.5))           # TP1 touched: trim + breakeven
    assert [x.kind for x in d] == ["trim"] and [x.new_stop for x in m] == [100.0]
    st = apply_moves(PolicyState(), _view(108.0, high=109.5), d, m, pol)
    assert st.stop == 100.0 and st.breakeven_done and st.trims_done == 1
    # a quote-watch trim (trims_done advanced outside the bar) brings breakeven on the next bar
    d2, m2 = evaluate(pol, PolicyState(trims_done=1), _view(104.0))
    assert [x.new_stop for x in m2] == [100.0]
    # a bare breakeven_after_r policy (other desks) is unchanged
    d3, m3 = evaluate({"stop": {"kind": "fixed", "price": 91.0}, "breakeven_after_r": 1.0}, PolicyState(),
                      _view(110.0))
    assert [x.new_stop for x in m3] == [100.0]


def test_atr_trail_uses_the_fixed_daily_atr_after_one_r_and_only_ratchets():
    pol = {"stop": {"kind": "fixed", "price": 91.0},
           "trailing": {"mode": "atr", "value": 3.0, "after_r": 1.0, "atr_abs": 3.0}}
    assert evaluate(pol, PolicyState(), _view(105.0))[1] == []              # +0.56R: not active
    _d, m = evaluate(pol, PolicyState(), _view(112.0))                      # +1.33R: 112 - 9 = 103
    assert [round(x.new_stop, 4) for x in m] == [103.0]
    st = PolicyState(stop=106.0, trailing_active=True, peak_favorable=15.0)
    assert evaluate(pol, st, _view(110.0))[1] == []                          # 115 peak - 9 = 106: no loosening


def test_time_stop_waived_above_the_ma_and_promotion():
    pol = {"stop": {"kind": "fixed", "price": 91.0}, "time_stop_sessions": 20, "time_stop_unless_above_ma": 3}
    above = _view(120.0, held=20, daily=[100.0, 101.0, 102.0])
    assert evaluate(pol, PolicyState(), above)[0] == []
    below = _view(95.0, held=20, daily=[100.0, 101.0, 102.0])
    assert [x.kind for x in evaluate(pol, PolicyState(), below)[0]] == ["time"]
    unknown = _view(120.0, held=20)
    assert [x.kind for x in evaluate(pol, PolicyState(), unknown)[0]] == ["time"]   # no MA known: time stop runs

    swing = policy_from_exit_plan(_plan(91.0), is_option=False, settings=S, entry_ref=100.0)
    swing["promote"]["above_ma"] = 3
    v = _view(119.0, held=4, daily=[100.0, 104.0, 108.0])                   # +2.1R by session 4, above the MA
    assert promotion_due(swing, PolicyState(), v)
    st = apply_moves(PolicyState(), v, [], [], swing)
    assert st.promoted is True
    eff = effective_policy(swing, st)
    assert eff["timeframe"] == "1d" and "stale" not in eff and eff["horizon"] == "extended"
    assert eff["trailing"]["atr_abs"] == 3.0
    assert promotion_due(swing, PolicyState(), _view(119.0, held=6, daily=[100.0, 104.0, 108.0])) is None
    assert promotion_due(swing, PolicyState(), _view(119.0, held=4)) is None          # MA unknown
    assert promotion_due(swing, PolicyState(), _view(110.0, held=4, daily=[100.0, 104.0, 108.0])) is None
    assert PolicyState.from_dict(st.to_dict()).promoted is True
    assert validate_policy({"promote": {"overlay": {"stop": {"kind": "fixed", "price": 1}}}})


# ------------------------------------------------------------------------------------------- manager (engine)
@pytest.fixture
async def pm_rig(engine):
    from zargar.execution.positions import PositionManager
    from .test_position_chaos import FakeOrders
    pm = PositionManager(engine)
    fo = FakeOrders()
    engine.orders = fo
    pf = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")["id"]
    return pm, fo, pf


def _spec(pf, policy, *, risk=2.0, overnight="venue_stop", sym="HZNX"):
    return {"portfolioId": pf, "symbol": sym, "direction": "long", "techniqueId": "tip", "entry": 100.0,
            "risk": risk, "overnight": overnight, **({"overnightAck": True} if overnight == "app_managed" else {}),
            "policy": policy, "legs": [{"symbol": sym, "secType": "STK", "qty": 10, "avgFill": 100.0}]}


@pytest.mark.usefixtures("fresh_db")
async def test_venue_stop_rests_beyond_the_close_judged_stop(pm_rig):
    pm, fo, pf = pm_rig
    await pm.adopt(_spec(pf, {"timeframe": "15m", "stop": {"kind": "fixed", "price": 98.0},
                              "venue_stop_beyond_r": 0.5}))
    stp = [i for i in fo.placed if i.order_type == "STP"]
    assert stp and stp[-1].stop_price == 97.0                              # 98 - 0.5 x 2
    await pm.adopt(_spec(pf, {"timeframe": "15m", "stop": {"kind": "fixed", "price": 98.0}}, sym="HZNY"))
    assert [i for i in fo.placed if i.order_type == "STP"][-1].stop_price == 98.0    # default: at the stop
    await pm.stop()


@pytest.mark.usefixtures("fresh_db")
async def test_quote_brake_distance_is_per_policy(pm_rig, engine, monkeypatch):
    from zoneinfo import ZoneInfo
    pm, fo, pf = pm_rig
    d = await pm.adopt(_spec(pf, {"timeframe": "15m", "stop": {"kind": "fixed", "price": 99.0},
                                  "quote_brake_r": 0.5}, risk=1.0, overnight="app_managed"))
    clock = [int(dt.datetime(2026, 9, 24, 11, 0, tzinfo=ZoneInfo("America/New_York")).timestamp() * 1000)]
    pm.now_ms = lambda: clock[0]
    monkeypatch.setenv("ZARGAR_TEST_NOW", "2026-09-24T11:00:00-04:00")
    px = [98.7]

    class Q:
        bid = ask = 0.0

        @property
        def last(self):
            return px[0]

        @property
        def ts(self):
            return clock[0]
    engine.quotes.get = lambda s: Q()
    n = len(fo.placed)
    for _ in range(4):                                                      # 0.3R beyond: inside a 0.5R brake
        await pm._watch_once()
        clock[0] += 2000
    assert len(fo.placed) == n
    px[0] = 98.4                                                            # 0.6R beyond: the brake fires once
    for _ in range(4):
        await pm._watch_once()
        clock[0] += 2000
    assert len(fo.placed) == n + 1 and fo.placed[-1].side == "SELL" and fo.placed[-1].reduce_only
    await pm.stop()


def _rth(day, minute, px, *, open_=None):
    from zargar.marketstructure.sessions import session_bounds
    o, _ = session_bounds(day)
    return Bar(symbol="HZNX", tf="1m", ts=o + minute * 60_000, open=open_ if open_ is not None else px,
               high=max(px, open_ or px) + 0.1, low=min(px, open_ or px) - 0.1, close=px, volume=100)


@pytest.mark.usefixtures("fresh_db")
async def test_gap_through_the_stop_exits_at_the_open(pm_rig, engine):
    from zargar.marketstructure.sessions import session_bounds
    pm, fo, pf = pm_rig
    engine.quotes.get = lambda s: None
    o, _ = session_bounds("2026-08-24")
    pm._now = lambda: (o + 60_000) / 1000.0                                  # opened in Monday's session
    d = await pm.adopt(_spec(pf, {"timeframe": "15m", "stop": {"kind": "fixed", "price": 98.0}, "gap_exit": True},
                             overnight="app_managed"))
    p = pm.get(d["id"])
    await pm.on_minute_bar(p, _rth("2026-08-24", 3, 100.0))
    n = len(p.exits)
    await pm.on_minute_bar(p, _rth("2026-08-25", 0, 97.5, open_=97.5))       # Tuesday opens through 98
    assert len(p.exits) == n + 1 and p.exits[-1]["kind"] == "stop" and "gap" in (p.exits[-1].get("reason") or "")
    await pm.stop()


@pytest.mark.usefixtures("fresh_db")
async def test_no_gap_exit_when_the_open_holds(pm_rig, engine):
    from zargar.marketstructure.sessions import session_bounds
    pm, fo, pf = pm_rig
    engine.quotes.get = lambda s: None
    o, _ = session_bounds("2026-08-24")
    pm._now = lambda: (o + 60_000) / 1000.0
    d = await pm.adopt(_spec(pf, {"timeframe": "15m", "stop": {"kind": "fixed", "price": 98.0}, "gap_exit": True},
                             overnight="app_managed"))
    p = pm.get(d["id"])
    await pm.on_minute_bar(p, _rth("2026-08-24", 3, 100.0))
    n = len(p.exits)
    await pm.on_minute_bar(p, _rth("2026-08-25", 0, 98.5, open_=98.5))
    assert len(p.exits) == n
    await pm.stop()


@pytest.mark.usefixtures("fresh_db")
async def test_manager_promotes_and_journals(pm_rig, engine, monkeypatch):
    from zargar.marketstructure.sessions import session_bounds
    pm, fo, pf = pm_rig
    engine.quotes.get = lambda s: None
    o, _ = session_bounds("2026-08-24")
    pm._now = lambda: (o + 60_000) / 1000.0
    pol = {"timeframe": "5m", "stop": {"kind": "fixed", "price": 98.0},
           "promote": {"by_session": 5, "min_r": 2.0, "above_ma": 3, "label": "extended",
                       "overlay": {"timeframe": "1d", "stale": None}}, "stale": {"sessions": 10, "min_r": 0.5}}
    d = await pm.adopt(_spec(pf, pol, risk=1.0, overnight="app_managed"))
    p = pm.get(d["id"])

    async def daily(sym, day=None):
        return _daily([100.0, 100.5, 101.0])
    monkeypatch.setattr(pm, "_daily_bars", daily)
    monkeypatch.setattr(engine.bars, "bars", lambda *a, **k: [])             # the sim feed's own bars stay out
    await pm.on_minute_bar(p, _rth("2026-08-24", 4, 103.0))                # closes the 5m bar at +3R
    assert p.state.promoted is True
    assert effective_policy(p.policy, p.state)["timeframe"] == "1d"
    assert any(e.get("what") == "promoted" or "promoted" in str(e) for e in p.events)
    await pm.stop()


@pytest.mark.usefixtures("fresh_db")
async def test_daily_policy_is_judged_on_the_sessions_own_bar(pm_rig, engine, monkeypatch):
    """A 1d policy decides on the last RTH minute with the SESSION's high/low (a rung touched at 11:00 counts), not
    the last 5m bar alone."""
    from zargar.marketstructure.sessions import session_bounds
    pm, fo, pf = pm_rig
    engine.quotes.get = lambda s: None
    o, _ = session_bounds("2026-08-24")
    pm._now = lambda: (o + 60_000) / 1000.0
    d = await pm.adopt(_spec(pf, {"timeframe": "1d", "stop": {"kind": "fixed", "price": 95.0},
                                  "ladder": {"targets": [105.0], "fractions": [0.3333]}},
                             risk=5.0, overnight="app_managed"))
    p = pm.get(d["id"])
    five = [Bar(symbol="HZNX", tf="5m", ts=o + i * 300_000, open=100.0, high=(106.0 if i == 18 else 101.0),
                low=99.5, close=100.5, volume=10) for i in range(77)]
    monkeypatch.setattr(engine.bars, "bars", lambda *a, **k: five)

    async def daily(sym, day=None):
        return []
    monkeypatch.setattr(pm, "_daily_bars", daily)
    n = len(p.exits)
    await pm.on_minute_bar(p, _rth("2026-08-24", 389, 103.0))               # the closing minute
    assert len(p.exits) == n + 1 and p.exits[-1]["kind"] == "trim"
    await pm.stop()


# ------------------------------------------------------------------------------------------- proposal wiring
@pytest.fixture
async def rig(fresh_db):
    from zargar.engine import Engine
    from zargar.signals.service import attach_signal_layer
    from .conftest import make_test_config
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


async def _tip(eng, sym, px, *, direction="long", stop_pct=1.0, catalyst=None, source="HzSrc"):
    from zargar.models import Signal
    from zargar.signals.schemas import TradeSignal
    stop = round(px * (1 - stop_pct / 100.0), 2) if direction == "long" else round(px * (1 + stop_pct / 100.0), 2)
    row = Signal(id=new_id(), source_name=source, ticker=sym, direction=direction, action="open",
                 instrument="shares", entry_price=px, target_price=round(px * 1.06, 2), stop_price=stop,
                 status="verified", extraction={}, thesis_summary="horizon test", confidence="explicit_call",
                 catalyst=catalyst)
    sig = TradeSignal(ticker=sym, direction=direction, instrument="shares", entry_price=px,
                      target_price=row.target_price, stop_price=stop, thesis_summary="horizon test",
                      confidence="explicit_call", evidence_quotes=["horizon test"], is_actionable=True)
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    return row, sig


async def _events(eng, kind):
    from sqlalchemy import select
    from zargar.models import Event
    async with eng.sf() as session:
        return list((await session.execute(select(Event.payload).where(Event.type == kind)
                                           .order_by(Event.id))).scalars().all())


async def test_card_carries_the_horizon_and_sizes_the_atr_stop_at_equal_risk(rig, monkeypatch):
    from .conftest import wait_for
    eng = rig
    await eng.ensure_symbol("HZNA")
    await wait_for(lambda: eng.quotes.get("HZNA") is not None and eng.quotes.get("HZNA").last > 0, timeout=5)
    px = float(eng.quotes.get("HZNA").ask or eng.quotes.get("HZNA").last)
    atr = round(px * 0.04, 4)

    async def facts(_eng, sym):
        return {"priorClose": px, "sessionOpen": px, "atrDaily": atr}          # flat day, 4% ATR: swing
    monkeypatch.setattr(hc, "daily_facts", facts)
    await eng.settings.set("techniques.tip.budget_per_tip", 100000.0, journal=False)
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 300.0, journal=False)
    row, sig = await _tip(eng, "HZNA", px, stop_pct=1.0)                      # a 1% stop: inside 2x ATR (8%)
    p = await eng.proposals.create_from_signal(row, sig, {})
    assert p is not None
    ctx = p["context"]
    assert ctx["horizon"] == "swing" and ctx["horizonApplied"] is True
    plan, rp = ctx["exitPlan"], ctx["riskPlan"]
    assert plan["atrStop"] is True and plan["horizon"] == "swing"
    lim = p["limitPrice"]
    assert abs(rp["finalStop"] - (lim - 3 * atr)) < 0.02                       # re-placed at 3x daily ATR
    assert p["qty"] * rp["unitLoss"] <= 300.0 + 1e-6                          # same dollar risk, fewer shares
    r = lim - rp["finalStop"]
    assert abs(plan["targets"][0] - (lim + r)) < 0.02 and abs(plan["fractions"][0] - 1 / 3) < 1e-3
    ev = await _events(eng, "TipHorizonDecided")
    assert ev and ev[-1]["horizon"] == "swing" and ev[-1]["applied"] is True and ev[-1]["facts"]["atrDaily"] == atr


async def test_chased_tip_is_short_with_a_two_atr_stop(rig, monkeypatch):
    from .conftest import wait_for
    eng = rig
    await eng.ensure_symbol("HZNB")
    await wait_for(lambda: eng.quotes.get("HZNB") is not None and eng.quotes.get("HZNB").last > 0, timeout=5)
    px = float(eng.quotes.get("HZNB").ask or eng.quotes.get("HZNB").last)
    atr = round(px * 0.04, 4)

    async def facts(_eng, sym):
        return {"priorClose": round(px / 1.03, 4), "sessionOpen": px, "atrDaily": atr}   # +3% chased, gapped
    monkeypatch.setattr(hc, "daily_facts", facts)
    await eng.settings.set("techniques.tip.budget_per_tip", 100000.0, journal=False)
    await eng.settings.set("techniques.tip.geometry_gate", "enforce", journal=False)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 300.0, journal=False)
    row, sig = await _tip(eng, "HZNB", px, stop_pct=0.5)
    p = await eng.proposals.create_from_signal(row, sig, {})
    assert p["context"]["horizon"] == "short" and "chased" in p["context"]["horizonReason"]
    rp = p["context"]["riskPlan"]
    assert abs(rp["finalStop"] - (p["limitPrice"] - 2 * atr)) < 0.02


async def test_short_tips_are_watch_only(rig):
    eng = rig
    row, sig = await _tip(eng, "HZNC", 50.0, direction="short")
    assert await eng.proposals.create_for_books(row, sig, {}) == []
    ev = await _events(eng, "TipShortWatchOnly")
    assert ev and ev[-1]["signalId"] == row.id and ev[-1]["lane"] == "proposal"
    await eng.settings.set("techniques.tip.shorts_watch_only", False, journal=False)
    await eng.proposals.create_for_books(row, sig, {})                     # the old path (no put -> nothing)
    assert len(await _events(eng, "TipShortWatchOnly")) == len(ev)


async def test_observe_mode_labels_without_changing_exits(rig, monkeypatch):
    from .conftest import wait_for
    eng = rig
    await eng.ensure_symbol("HZND")
    await wait_for(lambda: eng.quotes.get("HZND") is not None and eng.quotes.get("HZND").last > 0, timeout=5)
    px = float(eng.quotes.get("HZND").last)

    async def facts(_eng, sym):
        return {"priorClose": px, "sessionOpen": px, "atrDaily": round(px * 0.04, 4)}
    monkeypatch.setattr(hc, "daily_facts", facts)
    await eng.settings.set("techniques.tip.horizon_mode", "observe", journal=False)
    row, sig = await _tip(eng, "HZND", px, stop_pct=1.0)
    p = await eng.proposals.create_from_signal(row, sig, {})
    plan = p["context"]["exitPlan"]
    assert plan["horizon"] == "swing" and plan["horizonApplied"] is False
    assert plan["targets"] == [row.target_price]                              # the tip's own ladder stands
    pol = policy_from_exit_plan(plan, is_option=False, settings=eng.settings, entry_ref=px)
    assert "horizon" not in pol
