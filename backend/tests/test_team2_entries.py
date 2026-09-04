"""Team2 entry mechanics added after the second image pass (METHOD T7/T8, E5, X1 cue, A6):
break & base, the EMA48 second line of defense, the range-day 200-EMA flush, the new-extreme
trim cue and the stalled-pullback rule. Synthetic days, no DB."""
from __future__ import annotations

import math

from zargar.marketstructure import aggregate
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.session import simulate_session

from .test_team2_session import DAY, make_rules, path_1m, prev_day_bars, trend_day, zones_of

PREV_BARS = prev_day_bars()
Z = zones_of(PREV_BARS)
TOP, BOT = Z["pdh"].top, Z["pdh"].bottom


def run(price_fn, **rule_kw):
    rules = make_rules(**rule_kw)
    today = path_1m(DAY, (4, 0), (20, 0), price_fn)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(PREV_BARS, 15), rules), today)
    return simulate_session(plan, today, rules, sigma=0.2, warmup_1m=PREV_BARS)


def _pre(i):
    return 566 + 2.0 * (i / 330)


def test_break_and_base_enters_at_the_level_without_an_ema_dip():
    def f(i):
        m = 4 * 60 + i
        if m < 9 * 60 + 30:
            return _pre(i)
        x = m - 9 * 60 - 30
        if x < 15:
            return 568.5 + (TOP + 0.6 - 568.5) * (x / 14)         # 15m closes just above the zone
        if x < 31:
            return TOP + 0.10 + 0.04 * math.sin(x)                 # tight base 0.06–0.14 above the top
        if x < 120:
            return TOP + 0.14 + 5.0 * ((x - 31) / 89)
        return TOP + 5.1 - 3.0 * ((x - 120) / 270)
    res = run(f, entry_at="level")                                 # EMA touches switched off: only the level counts
    fires = [e for e in res.events if e["event"] == "fire"]
    assert fires and fires[0]["entryKind"] in ("level", "base"), fires[:2]
    assert fires[0]["time"] <= "09:50"
    assert res.trades and res.trades[0]["win"]


def test_ema48_is_a_valid_second_line_of_defense():
    def f(i):
        m = 4 * 60 + i
        if m < 9 * 60 + 30:
            return _pre(i)
        x = m - 9 * 60 - 30
        if x < 15:
            return 568.5 + (TOP + 1.5 - 568.5) * (x / 14)
        if x < 45:
            return TOP + 1.5 + 1.0 * ((x - 15) / 30)
        if x < 51:
            return TOP + 2.5 - 1.7 * ((x - 45) / 6)               # sharp dip through the 13 toward the 48
        if x < 57:
            return TOP + 0.8 + 0.02 * math.sin(x)
        if x < 150:
            return TOP + 0.85 + 5.0 * ((x - 57) / 93)
        return TOP + 5.85 - 3.0 * ((x - 150) / 240)
    res = run(f, entry_at="ema", pullback_body_mult=100)
    kinds = [t["entryKind"] for t in res.trades]
    assert "ema48" in kinds, kinds
    off = run(f, entry_at="ema", pullback_body_mult=100, allow_ema48_entries=False)
    assert "ema48" not in [t["entryKind"] for t in off.trades]


def test_range_day_fires_on_the_200_ema_flush():
    def f(i):
        m = 4 * 60 + i
        if m < 9 * 60 + 30:
            return TOP - 0.6 + 0.3 * math.sin(i / 40)              # pre-market just under the PDH zone
        x = m - 9 * 60 - 30
        if x < 14:
            return TOP - 0.5 + 0.9 * (x / 13)                      # wick into the zone…
        if x < 15:
            return BOT - 0.3                                       # …and the 15m body closes below it: reject PDH
        if x < 40:
            return BOT - 0.3 - 0.3 * ((x - 15) / 25)               # drift: the 13 crosses under the 48
        if x < 60:
            return BOT - 0.6 - 1.4 * ((x - 40) / 20)               # the flush through the 200
        if x < 150:
            return BOT - 2.0 - 4.0 * ((x - 60) / 90)
        return BOT - 6.0 + 2.0 * ((x - 150) / 240)
    res = run(f)
    assert res.bias["scenario"] == 2
    fires = [e for e in res.events if e["event"] == "fire"]
    assert fires and fires[0]["entryKind"] == "ema200" and "200 EMA flush" in fires[0]["why"]
    assert res.trades and res.trades[0]["direction"] == "short"
    off = run(f, allow_ema200_flush=False)
    assert not [e for e in off.events if e["event"] == "fire" and e["entryKind"] == "ema200"]


def test_new_extreme_trim_cue_trims_on_the_first_new_high():
    today, _ = trend_day(PREV_BARS)
    rules = make_rules(trim_cue="new_extreme")
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(PREV_BARS, 15), rules), today)
    res = simulate_session(plan, today, rules, sigma=0.2, warmup_1m=PREV_BARS)
    assert res.trades
    first = res.trades[0]["exits"][0]
    assert "new-extreme" in first["reason"] and first["pnlPct"] > 0


def test_stalled_pullback_is_called_a_consolidation():
    def f(i):
        m = 4 * 60 + i
        if m < 9 * 60 + 30:
            return _pre(i)
        x = m - 9 * 60 - 30
        if x < 15:
            return 568.5 + (TOP + 1.5 - 568.5) * (x / 14)
        if x < 45:
            return TOP + 1.5 + 1.0 * ((x - 15) / 30)
        if x < 51:
            return TOP + 2.5 - 1.2 * ((x - 45) / 6)
        if x < 90:
            return TOP + 1.3 + 0.03 * math.sin(x)                  # sits under the 13 for 40 minutes
        if x < 150:
            return TOP + 1.3 + 4.0 * ((x - 90) / 60)
        return TOP + 5.3 - 3.0 * ((x - 150) / 240)
    res = run(f, entry_at="ema", allow_ema48_entries=False, pullback_body_mult=100)
    stalled = [e for e in res.events if e["event"] == "pullback_stalled"]
    assert stalled and "consolidation" in stalled[0]["why"]
    quiet = run(f, entry_at="ema", allow_ema48_entries=False, pullback_body_mult=100, pullback_max_bars=0)
    assert not [e for e in quiet.events if e["event"] == "pullback_stalled"]
