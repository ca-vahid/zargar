"""Team2 technique — pure reads and the session simulation on synthetic days (no DB, no network).

Covers: rules from settings, the regime reader, the scenario tracker (four scenarios + flip),
day types and sizing buckets, targets and the level sheet, plan skeleton + completion, and the
whole session walk: a trend day (scenario 1 → EMA13 pullback fire → trims → target), a stop-out
(one-candle close through the EMA), the third-touch rule, the engulfing filter, the no-trade
zone, the flatten time, and live≡replay parity when the day is truncated at `now_ms`.
"""
from __future__ import annotations

import datetime as dt
import collections
import math

import pytest

from zargar.domain import Bar
from zargar.marketstructure import aggregate, filter_session, prior_day_zones
from zargar.marketstructure.sessions import ET
from zargar.techniques.team2.levels import level_sheet, targets_beyond
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.premium import PremiumModel, bs_price, implied_vol, pnl_pct, years_to_expiry
from zargar.techniques.team2.regime import RegimeReader
from zargar.techniques.team2.rules import Team2Rules, rules_from_settings
from zargar.techniques.team2.scenario import ScenarioTracker, classify_day, sizing_bucket
from zargar.techniques.team2.session import simulate_session

PREV = dt.date(2026, 9, 2)     # Wednesday
DAY = dt.date(2026, 9, 3)      # Thursday


def ts(day: dt.date, h: int, m: int) -> int:
    return int(dt.datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp() * 1000)


def path_1m(day: dt.date, start_hm: tuple[int, int], end_hm: tuple[int, int], price_fn, *, sym="SPY",
            spread=0.05, vol=1000) -> list[Bar]:
    """1m bars from start to end (exclusive) with close = price_fn(minute_index), tiny wicks."""
    out = []
    t0 = ts(day, *start_hm)
    t1 = ts(day, *end_hm)
    i = 0
    prev = price_fn(0)
    t = t0
    while t < t1:
        c = price_fn(i)
        o = prev
        hi = max(o, c) + spread
        lo = min(o, c) - spread
        out.append(Bar(sym, "1m", t, round(o, 4), round(hi, 4), round(lo, 4), round(c, 4), vol))
        prev = c
        t += 60_000
        i += 1
    return out


def prev_day_bars(day: dt.date = PREV) -> list[Bar]:
    """Previous session: 04:00–20:00, range roughly 560–570 with a clear HOD at 13:00 and LOD at 10:30."""
    def f(i):
        m = 4 * 60 + i
        if m < 9 * 60 + 30:
            return 565.0 + 0.3 * math.sin(i / 20)
        x = m - 9 * 60 - 30                       # minutes into RTH
        if x < 60:
            return 565 - 3.3 * (x / 60)           # down to ~561.7 by 10:30
        if x < 210:
            return 561.7 + 8.6 * ((x - 60) / 150) # up to ~570.3 by 13:00
        if x < 390:
            return 570.3 - 4.0 * ((x - 210) / 180)
        return 566.3 + 0.1 * math.sin(i / 7)
    return path_1m(day, (4, 0), (20, 0), f)


def make_rules(**kw) -> Team2Rules:
    r = Team2Rules()
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def zones_of(prev: list[Bar]):
    return prior_day_zones([b for b in aggregate(prev, 15) if b.ts])


# ----------------------------------------------------------------- rules / regime
def test_rules_from_settings_and_snapshot_roundtrip():
    class S:
        def __init__(self, d): self.d = d
        def get(self, k, default=None): return self.d.get(k, default)
    s = S({"techniques.team2.target_premium": 0.5, "techniques.team2.flatten_min": "15:40",
           "techniques.team2.max_reentries": 1, "techniques.team2.dte_policy": "1dte",
           "options.fee_per_contract": 0.99, "sim.reg_fee_per_contract": 0.05})
    r = rules_from_settings(s)
    assert r.target_premium == 0.5 and r.flatten_min == 15 * 60 + 40 and r.max_reentries == 1
    assert r.dte_policy == "1dte" and r.fee_per_contract == pytest.approx(1.04)
    assert r.volume_floor_mult == 0 and r.stop_on_close is True
    d = r.to_dict()
    assert Team2Rules.from_dict(d).flatten_min == r.flatten_min
    assert isinstance(d["windows"], list)


def test_regime_reader_carries_state_and_reads_stack():
    rules = make_rules()
    rr = RegimeReader(rules)
    bars = aggregate(prev_day_bars(), 2)
    last = None
    for b in bars:
        last = rr.update(b)
    assert last.ready and last.atr and last.atr > 0
    snap = rr.snapshot()
    rr2 = RegimeReader(rules)
    rr2.restore(snap)
    nxt = Bar("SPY", "2m", bars[-1].ts + 120_000, 566.4, 566.6, 566.3, 566.5, 100)
    assert rr.update(nxt).to_dict() == rr2.update(nxt).to_dict()
    # a rising tail flips the stack to bull with strength 3
    rr3 = RegimeReader(rules)
    for i, b in enumerate(aggregate(path_1m(PREV, (4, 0), (20, 0), lambda i: 500 + i * 0.02), 2)):
        r = rr3.update(b)
    assert r.stack == "bull" and r.strength == 3 and r.fan in ("trend", "chop")


# ----------------------------------------------------------------- scenarios / day type
def test_scenario_tracker_four_scenarios_and_flip():
    z = zones_of(prev_day_bars())
    pdh, pdl = z["pdh"], z["pdl"]
    def b15(o, h, l, c, minute=45):
        return Bar("SPY", "15m", ts(DAY, 9, minute), o, h, l, c, 1)
    t = ScenarioTracker(z)
    assert t.on_close(b15(565, 566, 564, 565.5)).scenario is None
    # reject PDH: wick into the zone, body closes below the zone bottom
    bias = t.on_close(b15(569, pdh.bottom + 0.05, 568, pdh.bottom - 0.3))
    assert bias.scenario == 2 and bias.direction == "short" and bias.range_day
    # flip to 1 on a 15m close above the zone top
    bias = t.on_close(b15(569.5, pdh.top + 0.6, 569.4, pdh.top + 0.5))
    assert bias.scenario == 1 and bias.direction == "long" and not bias.range_day
    # a wick back into the zone does NOT flip; a close below the zone bottom flips to 2
    assert t.on_close(b15(pdh.top + 0.4, pdh.top + 0.8, pdh.bottom - 0.1, pdh.top + 0.2)).scenario == 1
    assert t.on_close(b15(pdh.top, pdh.top, pdh.bottom - 1, pdh.bottom - 0.5)).scenario == 2
    t2 = ScenarioTracker(z)
    assert t2.on_close(b15(563, 563.5, pdl.top - 0.05, pdl.top + 0.4)).scenario == 3
    assert t2.on_close(b15(562, 562.2, pdl.bottom - 1, pdl.bottom - 0.6)).scenario == 4
    assert len(t2.bias.history) == 2


def test_day_type_and_sizing_bucket():
    z = zones_of(prev_day_bars())
    pdh, pdl = z["pdh"], z["pdl"]
    pmh, pml = pdh.bottom - 1.0, pdl.top + 1.0
    assert classify_day(pdh.top + 1, z, pmh, pml) == "gap_up"
    assert classify_day(pdl.bottom - 1, z, pmh, pml) == "gap_down"
    assert classify_day((pmh + pml) / 2, z, pmh, pml) == "inside"
    assert classify_day((pmh + pml) / 2, z, None, None) == "normal"
    assert sizing_bucket(pdh.top + 0.5, z, pmh, pml) == "full"
    # F15: a gap-day PM range that sits ABOVE the PDH zone is still the no-trade zone
    assert sizing_bucket(pdh.top + 0.5, z, pdh.top + 1.0, pdh.top + 0.2) == "none"
    assert sizing_bucket(pdh.top + 1.5, z, pdh.top + 1.0, pdh.top + 0.2) == "full"
    assert sizing_bucket(pdl.bottom - 0.5, z, pmh, pml) == "full"
    assert sizing_bucket((pmh + pml) / 2, z, pmh, pml) == "none"
    assert sizing_bucket(pmh + 0.2, z, pmh, pml) == "small"
    assert sizing_bucket(pmh + 0.2, z, None, None) == "small"


def test_targets_beyond_and_sheet():
    prev = prev_day_bars()
    older = prev_day_bars(dt.date(2026, 9, 1))
    # give the older day a pivot high well above the PDH and a pivot low below the PDL
    def et_min(b):
        t = dt.datetime.fromtimestamp(b.ts / 1000, ET)
        return t.hour * 60 + t.minute
    older = [Bar(b.symbol, b.tf, b.ts, b.open + 6, b.high + 6, b.low + 6, b.close + 6, b.volume) if 13 * 60 <= et_min(b) <= 13 * 60 + 30 else b for b in older]
    older = [Bar(b.symbol, b.tf, b.ts, b.open - 5, b.high - 5, b.low - 5, b.close - 5, b.volume) if 10 * 60 + 20 <= et_min(b) <= 10 * 60 + 40 else b for b in older]
    fifteen = [b for b in aggregate(older + prev, 15)]
    z = prior_day_zones([b for b in fifteen if dt.datetime.fromtimestamp(b.ts / 1000, ET).date() == PREV])
    t = targets_beyond(fifteen, z, lookback_sessions=5)
    assert t["above"] is not None and t["above"] > z["pdh"].top
    assert t["below"] is not None and t["below"] < z["pdl"].bottom
    sheet = level_sheet("SPY", z, 567.9, 564.2, t, "normal")
    assert "PDH zone" in sheet and "room up to" in sheet and "PM 564.20–567.90" in sheet


# ----------------------------------------------------------------- plan
def test_plan_skeleton_and_completion():
    rules = make_rules()
    prev = prev_day_bars()
    fifteen = aggregate(prev, 15)
    sk = build_skeleton("spy", DAY.isoformat(), fifteen, rules)
    assert sk and sk["symbol"] == "SPY" and sk["prevSession"] == PREV.isoformat() and sk["complete"] is False
    assert sk["zones"]["pdh"]["top"] > sk["zones"]["pdl"]["bottom"] and sk["thresholds"]["ema_fast"] == 13
    pre = path_1m(DAY, (4, 0), (9, 30), lambda i: 566 + 0.6 * math.sin(i / 30))
    plan = complete_plan(sk, pre)
    assert plan["pmh"] > plan["pml"] and plan["openSource"] == "premarket_last" and plan["complete"] is True
    rth = path_1m(DAY, (9, 30), (9, 32), lambda i: 571.0)
    plan2 = complete_plan(sk, pre + rth)
    assert plan2["openSource"] == "rth_open" and plan2["dayType"] == "gap_up" and plan2["sizingAtOpen"] == "full"
    assert "gap up day" in plan2["sheet"]
    assert build_skeleton("SPY", DAY.isoformat(), [], rules) is None


# ----------------------------------------------------------------- premium model
def test_premium_model_prices_and_picks_strike_by_premium():
    m = PremiumModel(sigma=0.18)
    t = ts(DAY, 10, 10)
    assert years_to_expiry(t) == pytest.approx((5 * 3600 + 50 * 60) / (365 * 86400))
    pick = m.pick_strike(708.9, t, "long", target_premium=0.60, premium_floor=0.20, step=1.0)
    assert pick is not None
    strike, mark = pick
    assert strike > 708.9 and mark <= 0.60 and mark >= 0.20
    put = m.pick_strike(708.9, t, "short", target_premium=0.60, premium_floor=0.20)
    assert put is not None and put[0] < 708.9
    # too-tight target → None (nothing between floor and target)
    assert PremiumModel(sigma=0.18).pick_strike(708.9, t, "long", target_premium=0.10, premium_floor=0.20) is None
    f_in, f_out = m.buy(0.50), m.sell(1.00)
    assert f_in.premium == pytest.approx(0.51) and f_out.premium == pytest.approx(0.99)
    pct = pnl_pct(f_in, f_out)
    assert 85 < pct < 96                                 # ≈ +94% before fees → fees + slippage bite


def test_premium_model_calibrates_to_the_authors_trades():
    """The author's fully documented trades (entry premium + entry/exit spot from his charts, METHOD §7b).
    Flat-IV BS reproduces the direction and order of magnitude and is consistently a little optimistic
    (F8: chart-read spots, exits before the extreme) — the band below is the honesty check that must
    keep passing when the model changes."""
    cases = [
        # date, entry (h, m), spot in, strike, call, premium in, exit (h, m), spot out, reported %
        (dt.date(2026, 4, 17), (10, 10), 708.9, 711, True, 0.60, (10, 46), 711.16, 122),   # SPY 711c "pushing ITM, +120%"
        (dt.date(2025, 3, 10), (10, 15), 480.3, 472, False, 0.55, (10, 57), 474.7, 166),   # QQQ 472p, +$4,389
        (dt.date(2024, 7, 9), (9, 45), 201.8, 201, False, 0.20, (10, 32), 200.8, 157),     # IWM 201p, new LOD
        (dt.date(2025, 8, 27), (13, 24), 647.4, 648, True, 0.54, (14, 33), 648.9, 100),    # SPY 648c, afternoon flag
    ]
    for d, tin, s_in, k, call, p_in, tout, s_out, reported in cases:
        t_in, t_out = ts(d, *tin), ts(d, *tout)
        iv = implied_vol(p_in, s_in, k, years_to_expiry(t_in), call=call)
        assert iv is not None and 0.10 < iv < 0.80, (d, iv)           # a sane 0DTE IV for an index ETF
        out = bs_price(s_out, k, years_to_expiry(t_out), iv, call=call)
        gain = (out - p_in) / p_in * 100
        assert reported * 0.9 < gain < reported * 1.6, (d, gain, reported)


# ----------------------------------------------------------------- the session walk
def trend_day(prev: list[Bar]):
    """Today: pre-market drifts 566→568, open 568.5, 09:30–09:45 pushes through the PDH zone and the
    15m bar closes above it; 09:46–10:00 dips back to the EMA13 and holds; 10:00–11:30 rallies ~5;
    afternoon fades back through the EMA (stops any runner) and flattens."""
    z = zones_of(prev)
    top = z["pdh"].top
    def f(i):
        m = 4 * 60 + i
        if m < 9 * 60 + 30:
            return 566.0 + 2.0 * (i / 330)                # 566 → 568 pre-market (PMH ≈ 568, PML ≈ 566)
        x = m - 9 * 60 - 30
        if x < 15:
            return 568.5 + (top + 1.2 - 568.5) * (x / 14)  # break the zone, 15m closes above
        if x < 30:
            return top + 1.2 - 1.0 * ((x - 15) / 15)       # dip toward the EMA
        if x < 120:
            return top + 0.2 + 5.5 * ((x - 30) / 90)       # rally
        if x < 300:
            return top + 5.7 - 5.0 * ((x - 120) / 180)     # fade through the EMA
        return top + 0.7 + 0.05 * math.sin(i / 3)
    return path_1m(DAY, (4, 0), (20, 0), f), z


def run(prev, today, **rule_kw):
    rules = make_rules(**rule_kw)
    fifteen = aggregate(prev, 15)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), fifteen, rules), today)
    res = simulate_session(plan, today, rules, sigma=0.20, warmup_1m=prev)
    return plan, res


def test_trend_day_scenario_1_fires_on_the_pullback_and_pays():
    prev = prev_day_bars()
    today, z = trend_day(prev)
    plan, res = run(prev, today)
    kinds = [e["event"] for e in res.events]
    assert "scenario" in kinds, res.events[:5]
    sc = next(e for e in res.events if e["event"] == "scenario")
    assert sc["scenario"] == 1 and sc["time"] == "09:30"    # the 09:30 15m bar closed above the zone (event ts = bar open)
    fires = [e for e in res.events if e["event"] == "fire"]
    assert fires, [e for e in res.events][:12]
    f = fires[0]
    assert f["strike"] > f["spot"] and 0.2 <= f["premium"] <= 0.62 and f["bucket"] == "full"
    assert "09:45" <= f["time"] < "10:30"
    assert res.trades and res.trades[0]["win"] and res.trades[0]["pnlPct"] > 30
    reasons = " ".join(x["reason"] for x in res.trades[0]["exits"])
    assert "trim" in reasons
    assert res.summary["openAtEnd"] is False
    assert res.bias["scenario"] == 1 and res.summary["fifteenMinBars"] > 20


def test_parity_truncated_day_matches_prefix_of_full_day():
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    rules = make_rules()
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(prev, 15), rules), today)
    full = simulate_session(plan, today, rules, sigma=0.20, warmup_1m=prev)
    cut = ts(DAY, 11, 0)
    part = simulate_session(plan, today, rules, sigma=0.20, warmup_1m=prev, now_ms=cut)
    full_prefix = [e for e in full.events if e["ts"] < cut - 120_000]
    part_prefix = [e for e in part.events if e["ts"] < cut - 120_000]
    assert part_prefix == full_prefix
    assert all(e["ts"] < cut for e in part.events)


def test_stop_out_is_one_candle_close_through_the_ema_and_reentry_is_capped():
    prev = prev_day_bars()
    z = zones_of(prev)
    top = z["pdh"].top
    def f(i):
        m = 4 * 60 + i
        if m < 9 * 60 + 30:
            return 566.0 + 2.0 * (i / 330)
        x = m - 9 * 60 - 30
        if x < 15:
            return 568.5 + (top + 1.2 - 568.5) * (x / 14)
        # chop around the EMA: dip, hold, then collapse through it; repeat
        cyc = (x - 15) % 24
        base = top + 0.9
        if cyc < 8:
            return base - 0.9 * (cyc / 8)
        if cyc < 12:
            return base - 0.9 + 0.5 * ((cyc - 8) / 4)
        return base - 0.4 - 2.2 * ((cyc - 12) / 12)
    today = path_1m(DAY, (4, 0), (20, 0), f)
    plan, res = run(prev, today, max_reentries=1, max_losses_per_day=2)
    losses = [t for t in res.trades if not t["win"]]
    assert losses, res.events[:20]
    assert any("stop" in t["exitReason"] for t in losses)
    assert res.summary["losses"] <= 2                        # D-3 cap
    fires = [e for e in res.events if e["event"] == "fire"]
    assert 1 <= len(fires) <= 2                              # A8: one re-entry at most per setup


def test_third_touch_is_watch_only_and_engulfing_touch_is_skipped():
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    _, res = run(prev, today, pullback_max_touches=0)        # every touch is "late"
    assert not [e for e in res.events if e["event"] == "fire"]
    assert [e for e in res.events if e["event"] == "late_touch"]
    _, res2 = run(prev, today, pullback_body_mult=0.0001)    # every touching bar is "engulfing"
    assert not [e for e in res2.events if e["event"] == "fire"]
    assert [e for e in res2.events if e["event"] == "skip_engulfing"]


def test_flatten_time_closes_the_position():
    prev = prev_day_bars()
    z = zones_of(prev)
    top = z["pdh"].top
    def f(i):                                                 # break, dip, then a slow grind up all day
        m = 4 * 60 + i
        if m < 9 * 60 + 30:
            return 566.0 + 2.0 * (i / 330)
        x = m - 9 * 60 - 30
        if x < 15:
            return 568.5 + (top + 1.2 - 568.5) * (x / 14)
        if x < 30:
            return top + 1.2 - 1.0 * ((x - 15) / 15)
        return top + 0.2 + 6.0 * ((x - 30) / 360)          # strong enough that theta never trips the premium stop
    today = path_1m(DAY, (4, 0), (20, 0), f)
    plan, res = run(prev, today, target_exit=False, trim_1_pct=1e9, trim_2_pct=1e9, premium_stop_pct=95.0)
    assert res.trades and res.trades[-1]["exitReason"].startswith("flatten")
    last = dt.datetime.fromtimestamp(res.trades[-1]["exitTs"] / 1000, ET)
    assert last.hour * 60 + last.minute <= 15 * 60 + 46


def test_no_trade_zone_blocks_entries_inside_the_premarket_range():
    prev = prev_day_bars()
    z = zones_of(prev)
    # pre-market range wide enough to contain the whole day; a PM-break setup cannot form
    def f(i):
        m = 4 * 60 + i
        if m < 9 * 60 + 30:
            return 563.5 + 5.0 * abs(math.sin(i / 60))      # PM range ≈ 563.5–568.5 spans the day
        return 566.0 + 0.8 * math.sin((m - 570) / 25)
    today = path_1m(DAY, (4, 0), (20, 0), f)
    plan, res = run(prev, today)
    assert plan["dayType"] in ("inside", "normal")
    assert not [e for e in res.events if e["event"] == "fire"]


def test_no_trade_zone_skip_is_said_once_per_setup():
    # F23: the skip holds for as long as price sits in the zone, so re-stating it on every 2m close buries
    # the read — and the append-only journal — under identical rows (IWM printed 37 on 2026-09-04).
    prev = prev_day_bars()
    def f(i):
        m = 4 * 60 + i
        if m < 9 * 60 + 30:
            return 564.0 + 2.0 * math.sin(i / 45)      # PM range ≈ 562.0–566.0
        x = m - 9 * 60 - 30
        if x < 8:
            return 562.3                               # dip into the PDL zone (top ≈ 562.50)
        if x < 15:
            return 562.3 + 1.2 * ((x - 8) / 7)         # 09:30 15m body closes above it → scenario 3
        return 564.3 + 0.75 * math.sin((x - 15) / 9)   # then drift inside the PM range all day
    today = path_1m(DAY, (4, 0), (20, 0), f)
    _, res = run(prev, today)
    skips = [e for e in res.events if e["event"] == "skip_no_trade_zone"]
    assert skips, "the fixture no longer reaches the no-trade-zone gate"
    per_setup = collections.Counter(e["setup"] for e in skips)
    assert max(per_setup.values()) == 1, per_setup
    assert not [e for e in res.events if e["event"] == "fire"]


def test_event_day_gate_blocks_entries_when_enabled():
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    rules = make_rules(avoid_event_days=True)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(prev, 15), rules), today)
    plan["eventDay"], plan["eventDayName"] = True, "FOMC decision"
    res = simulate_session(plan, today, rules, sigma=0.20, warmup_1m=prev)
    assert not [e for e in res.events if e["event"] == "fire"]
    assert [e for e in res.events if e["event"] == "skip_event_day"]
    off = simulate_session(plan, make_rules(avoid_event_days=False), sigma=0.20, warmup_1m=prev) if False else None
    res2 = simulate_session(plan, today, make_rules(), sigma=0.20, warmup_1m=prev)
    assert [e for e in res2.events if e["event"] == "fire"]


def test_entry_cutoff_and_loss_cap_say_why_the_read_went_quiet():
    """F26: both gates used to stop entries in silence — the read has to name the discipline."""
    prev = prev_day_bars()
    today, _ = trend_day(prev)

    # last-entry cutoff: pull it back to 10:00 so the trend day's later touches fall past it
    _, res = run(prev, today, last_entry_min=10 * 60)
    cut = [e for e in res.events if e["event"] == "skip_last_entry"]
    assert len(cut) == 1, [e["event"] for e in res.events]          # said ONCE, not per 2m close
    assert "10:00" in cut[0]["why"] and "flatten" in cut[0]["why"]
    assert all(e["ts"] >= cut[0]["ts"] for e in res.events
               if e["event"] == "fire" and e["ts"] > cut[0]["ts"])  # nothing fires after it
    assert not [e for e in res.events if e["event"] == "fire" and e["ts"] >= cut[0]["ts"]]

    # a normal day says it once too, at the real 15:30 cutoff — one row per session, not per bar
    _, wide = run(prev, today)
    normal = [e for e in wide.events if e["event"] == "skip_last_entry"]
    assert len(normal) == 1 and normal[0]["time"] == "15:30"

    # loss cap: zero losses allowed → the first loss closes the symbol for the day, out loud
    _, capped = run(prev, today, max_losses_per_day=0)
    cap = [e for e in capped.events if e["event"] == "skip_loss_cap"]
    assert len(cap) == 1 and "max 0" in cap[0]["why"]
    assert not [e for e in capped.events if e["event"] == "fire"]
