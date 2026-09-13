"""C2 causal fixtures (spec v2 §6, 2026-09-13): the three key-level definitions on synthetic 15m tapes, the flip/expiry
state machine, the 17:00 zone mask and the 09:25/09:30 PM mask, and the proof that the knob OFF leaves the read
byte-identical. No sweep here — measurement is gated on C6."""
from __future__ import annotations

import datetime as dt

from zargar.domain import Bar
from zargar.marketstructure import aggregate, filter_session
from zargar.marketstructure.dailylevels import Zone
from zargar.techniques.team2.levels import (KEY_LEVEL_D2_AWAY_BARS, _episodes, active_key_levels, advance_flip, key_levels,
                                            ladder_with_key_levels, mask_pm)
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.rules import Team2Rules
from zargar.techniques.team2.session import simulate_session

from .test_team2_integrity import drift_day
from .test_team2_session import DAY, make_rules, path_1m, prev_day_bars, ts

ATR = 1.0
D = [dt.date(2026, 8, 24) + dt.timedelta(days=i) for i in (0, 1, 2, 3, 4, 7, 8, 9, 10, 11)]   # ten sessions, Mon..Fri x2
PLAN = dt.date(2026, 9, 8)
ZONES = {"pdh": Zone("pdh", 110.0, 109.7, D[-1].isoformat(), 0), "pdl": Zone("pdl", 90.3, 90.0, D[-1].isoformat(), 0)}


def b15(day: dt.date, h: int, m: int, o: float, hi: float, lo: float, c: float, sym="SPY") -> Bar:
    return Bar(sym, "15m", ts(day, h, m), o, hi, lo, c, 1000)


def flat_session(day: dt.date, level: float, *, high: float | None = None, low: float | None = None) -> list[Bar]:
    """26 quiet RTH bars around `level` (range 0.2), optionally with one bar printing the session high/low."""
    out = []
    for i in range(26):
        h, m = 9 + (30 + 15 * i) // 60, (30 + 15 * i) % 60
        o = c = level; hi = level + 0.1; lo = level - 0.1
        if i == 10 and high is not None:
            hi = high
        if i == 16 and low is not None:
            lo = low
        out.append(b15(day, h, m, o, hi, lo, c))
    return out


# ---------------------------------------------------------------- D1
def test_d1_clusters_session_extremes_to_the_median_and_ranks_by_score_then_recency():
    bars = []
    for i, d in enumerate(D):
        hi = 105.0 + (0.3 if i in (2, 5) else 0.0) if i in (2, 5, 8) else 112.0 + i * 0.7    # three highs near 105.0/105.3; the rest far above and apart
        lo = 95.0 if i in (3, 8) else 92.0 - i * 1.2
        bars += flat_session(d, 100.0, high=hi, low=lo)
    kl = key_levels(bars, definition="D1", atr_build=ATR, prev_close=100.0, zones=ZONES, plan_date=PLAN.isoformat())
    above = kl["above"]; below = kl["below"]
    top = above[0]
    assert top["reactions"] == 3 and top["members"] == [105.0, 105.3, 105.3] and top["price"] == 105.3    # median of 3
    assert top["originKind"] == "high" and top["role"] == "resistance"
    assert below[0]["price"] == 95.0 and below[0]["reactions"] == 2 and below[0]["role"] == "support"
    assert all(lv["maskedBy"] == "none" for lv in above + below)
    assert len(above) <= 3 and len(below) <= 3
    lone_old = [c for c in kl["candidates"] if c["reactions"] == 1 and c["originDate"] < D[-3].isoformat()]
    assert not lone_old                                                          # single members older than 3 sessions are dropped


def test_a_candidate_near_a_zone_is_masked_not_moved_and_stays_in_the_record():
    bars = []
    for i, d in enumerate(D):
        bars += flat_session(d, 100.0, high=(110.2 if i in (4, 7) else 103.0), low=96.0)
    kl = key_levels(bars, definition="D1", atr_build=ATR, prev_close=100.0, zones=ZONES, plan_date=PLAN.isoformat())
    masked = [c for c in kl["candidates"] if c["maskedBy"] == "pdh"]
    assert masked and masked[0]["price"] == 110.2 and all(lv["price"] != 110.2 for lv in kl["above"])


# ---------------------------------------------------------------- D2
def test_d2_episodes_count_once_while_lingering_and_again_after_four_clean_bars():
    day = D[0]
    def at(i):                                                        # i-th 15m RTH bar of the day
        return 9 + (30 + 15 * i) // 60, (30 + 15 * i) % 60
    bars = [b15(day, *at(0), 100.5, 100.6, 100.4, 100.5)]
    # three consecutive bars wicking into the band at 99.0 from above and closing back above it: ONE episode
    bars += [b15(day, *at(i), 100.2, 100.4, 98.9, 100.2) for i in (1, 2, 3)]
    # four clean bars fully above the band (low > 99.25)
    bars += [b15(day, *at(i), 100.5, 100.7, 100.3, 100.5) for i in (4, 5, 6, 7)]
    # another reaction: a second episode
    bars.append(b15(day, *at(8), 100.3, 100.4, 98.95, 100.3))
    eps = _episodes(bars, 99.0, 0.25, "support")
    assert len(eps) == 2 and eps[0][0] == (day.isoformat(), 1) and eps[1][0] == (day.isoformat(), 8)
    # only three clean bars between the visits: still one episode
    bars2 = bars[:4] + bars[4:7] + [b15(day, *at(7), 100.3, 100.4, 98.95, 100.3)]
    assert len(_episodes(bars2, 99.0, 0.25, "support")) == 1
    assert KEY_LEVEL_D2_AWAY_BARS == 4


def test_d2_level_needs_three_episodes_from_two_sessions_and_a_reaction_is_counted_once_after_clustering():
    bars = []
    for i, d in enumerate(D):
        s = flat_session(d, 100.0)
        if i in (6, 7, 8):                                            # three sessions each wick once into 97.0 from above
            s[5] = b15(d, 10, 45, 100.0, 100.1, 96.9, 100.0)
        bars += s
    kl = key_levels(bars, definition="D2", atr_build=ATR, prev_close=100.0, zones=ZONES, plan_date=PLAN.isoformat())
    sup = [lv for lv in kl["below"] if abs(lv["price"] - 96.9) < 0.3]
    assert len(sup) == 1 and sup[0]["reactions"] == 3                # neighbouring grid points merged; episodes de-duplicated
    assert sup[0]["role"] == "support" and len(sup[0]["episodes"]) == 3
    # two sessions only -> not a level
    bars2 = []
    for i, d in enumerate(D):
        s = flat_session(d, 100.0)
        if i in (7, 8):
            s[5] = b15(d, 10, 45, 100.0, 100.1, 96.9, 100.0)
        bars2 += s
    kl2 = key_levels(bars2, definition="D2", atr_build=ATR, prev_close=100.0, zones=ZONES, plan_date=PLAN.isoformat())
    assert not [lv for lv in kl2["below"] if abs(lv["price"] - 96.9) < 0.3]


# ---------------------------------------------------------------- D3
def test_d3_pivot_is_available_only_after_its_confirming_bars_and_retests_count_after_that():
    bars = []
    for i, d in enumerate(D):
        s = flat_session(d, 100.0)
        if i == 5:
            s[10] = b15(d, 12, 0, 100.0, 104.0, 99.9, 100.0)        # a pivot high at 104.0 (confirmed by bars 11, 12)
            s[20] = b15(d, 14, 30, 100.0, 103.9, 99.9, 100.0)       # a retest AFTER availability (wick up into the band, closes below)
        bars += s
    kl = key_levels(bars, definition="D3", atr_build=ATR, prev_close=100.0, zones=ZONES, plan_date=PLAN.isoformat())
    # the retest bar's own high (103.9) is a pivot too (window 2); the two pivots cluster to the median 103.95 and the
    # retest episode is counted once: reactions = 1 + 1
    piv = [lv for lv in kl["above"] if abs(lv["price"] - 103.95) < 1e-9]
    assert len(piv) == 1 and piv[0]["reactions"] == 2 and piv[0]["originKind"] == "pivot_high"
    assert sorted(piv[0]["members"]) == [103.9, 104.0] and piv[0]["originDate"] == D[5].isoformat()
    assert piv[0]["availableAt"] >= ts(D[5], 12, 30) + 15 * 60_000  # never before the second confirming bar's close
    # a pivot on the very last bars of the lookback has no confirming bars yet -> absent
    bars2 = []
    for i, d in enumerate(D):
        s = flat_session(d, 100.0)
        if i == 9:
            s[25] = b15(d, 15, 45, 100.0, 106.0, 99.9, 100.0)
        bars2 += s
    kl2 = key_levels(bars2, definition="D3", atr_build=ATR, prev_close=100.0, zones=ZONES, plan_date=PLAN.isoformat())
    assert not [lv for lv in kl2["above"] if lv["price"] == 106.0]


# ---------------------------------------------------------------- flip / expiry state machine
def _lv(price=100.0, role="support"):
    return {"levelId": "x", "price": price, "role": role, "flips": 0, "flipPending": False, "breakAt": None,
            "flipConfirmedAt": None, "retired": False, "maskedBy": "none"}


def test_break_then_reject_leaves_the_level_as_it_was():
    lv = _lv()
    assert advance_flip(lv, b15(D[0], 10, 0, 100.5, 100.6, 99.4, 99.6)) == "break" and lv["flipPending"]
    assert advance_flip(lv, b15(D[0], 10, 15, 99.6, 100.4, 99.5, 100.3)) == "reject"
    assert lv["role"] == "support" and lv["flips"] == 0 and not lv["flipPending"]


def test_break_then_confirm_swaps_the_role_and_a_second_flip_retires():
    lv = _lv()
    assert advance_flip(lv, b15(D[0], 10, 0, 100.5, 100.6, 99.4, 99.6)) == "break"
    assert advance_flip(lv, b15(D[0], 10, 15, 99.6, 99.7, 99.0, 99.2)) == "confirm"
    assert lv["role"] == "resistance" and lv["flips"] == 1 and lv["flipConfirmedAt"] == ts(D[0], 10, 15) + 15 * 60_000
    assert advance_flip(lv, b15(D[0], 10, 30, 99.2, 100.6, 99.1, 100.4)) == "break"
    assert advance_flip(lv, b15(D[0], 10, 45, 100.4, 100.9, 100.3, 100.8)) == "retire"
    assert lv["retired"] and lv["flips"] == 2
    assert active_key_levels({"above": [lv], "below": []}) == []


def test_pending_and_retired_levels_are_not_ladder_rungs():
    lv = _lv(price=105.0, role="resistance")
    kl = {"above": [lv], "below": []}
    assert ladder_with_key_levels({"highs": [108.0], "lows": []}, kl)["highs"] == [105.0, 108.0]
    advance_flip(lv, b15(D[0], 10, 0, 104.0, 106.0, 103.9, 105.5))
    assert ladder_with_key_levels({"highs": [108.0], "lows": []}, kl)["highs"] == [108.0]


def test_two_sessions_beyond_without_a_reaction_expire_the_level_at_the_next_build():
    bars = []
    for i, d in enumerate(D):
        lo = 95.0 if i in (2, 3, 4) else 97.0                         # a support at 95.0 (three sessions)
        base = 93.0 if i >= 8 else 100.0                              # the last two sessions closed 2 ATR BELOW it without touching it
        bars += flat_session(d, base, low=lo if i < 8 else 92.8)
    kl = key_levels(bars, definition="D1", atr_build=ATR, prev_close=93.0, zones=ZONES, plan_date=PLAN.isoformat())
    assert not [c for c in kl["candidates"] if abs(c["price"] - 95.0) < 0.6]
    # with the last two sessions still touching it, the level survives
    bars2 = []
    for i, d in enumerate(D):
        lo = 95.0 if i in (2, 3, 4, 8, 9) else 97.0
        bars2 += flat_session(d, 100.0, low=lo)
    kl2 = key_levels(bars2, definition="D1", atr_build=ATR, prev_close=100.0, zones=ZONES, plan_date=PLAN.isoformat())
    assert [c for c in kl2["candidates"] if abs(c["price"] - 95.0) < 0.6]


# ---------------------------------------------------------------- PM mask (09:25 provisional / 09:30 completed)
def test_pm_mask_is_reapplied_from_the_build_state_and_never_refilled():
    kl = {"atrBuild": 1.0, "above": [{"levelId": "a", "price": 105.0, "maskedBy": "none"}, {"levelId": "b", "price": 108.0, "maskedBy": "none"}],
          "below": [{"levelId": "c", "price": 95.0, "maskedBy": "none"}]}
    prov = mask_pm(kl, 105.3, 96.0, stage="provisional")
    assert [lv["maskedBy"] for lv in prov["above"]] == ["pmh", "none"] and prov["pmMasks"][0]["levelId"] == "a"
    done = mask_pm(prov, 107.0, 96.0, stage="completed")
    assert [lv["maskedBy"] for lv in done["above"]] == ["none", "none"] and done["pmMaskStage"] == "completed"
    assert len(done["above"]) == 2                                    # no refill, no removal


# ---------------------------------------------------------------- the knob off leaves everything unchanged
def _read(**rule_kw):
    rules = make_rules(**rule_kw)
    prev = prev_day_bars()
    today = path_1m(DAY, (4, 0), (20, 0), drift_day)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(prev, 15), rules, prev_bars_1m=prev), today)
    return plan, simulate_session(plan, today, rules, sigma=0.2, warmup_1m=prev)


def test_knob_off_by_default_no_key_levels_on_the_plan_and_the_read_is_unchanged():
    assert Team2Rules().key_levels == "off"
    plan_off, base = _read()
    assert plan_off.get("keyLevels") is None
    plan_on, on = _read(key_levels="D1")
    assert isinstance(plan_on.get("keyLevels"), dict) and plan_on["keyLevels"]["definition"] == "D1"
    assert plan_on["keyLevels"]["atrBuildSource"] == "2m" and plan_on["keyLevels"]["atrBuild"] > 0
    # the one-session synthetic history yields no multi-day level, so the FULL read (every event field, every setup,
    # every trade) must be identical with the knob on — not only the event names
    assert base.to_dict()["events"] == on.to_dict()["events"]
    assert base.to_dict()["setups"] == on.to_dict()["setups"] and base.to_dict()["trades"] == on.to_dict()["trades"]
    assert not [e for e in on.events if e["event"].startswith("key_level_")]
    # and with the knob on but an empty level set on the plan, the read is again the full-dict equal of the off read
    plan_empty, empty = _read(key_levels="D1")
    plan_empty["keyLevels"] = {"definition": "D1", "atrBuild": 0.5, "candidates": [], "above": [], "below": []}
    empty2 = simulate_session(plan_empty, path_1m(DAY, (4, 0), (20, 0), drift_day), make_rules(key_levels="D1"), sigma=0.2, warmup_1m=prev_day_bars())
    assert base.to_dict()["events"] == empty2.to_dict()["events"]


def test_no_2m_bars_means_insufficient_data_not_a_scaled_fallback():
    rules = make_rules(key_levels="D1")
    prev = prev_day_bars()
    plan = build_skeleton("SPY", DAY.isoformat(), aggregate(prev, 15), rules)      # no 1m bars supplied
    kl = plan["keyLevels"]
    assert kl["atrBuildSource"] == "none" and kl["atrBuild"] == 0.0 and kl["insufficientData"]
    assert kl["above"] == [] and kl["below"] == [] and kl["candidates"] == []


def test_cluster_diameter_is_a_hard_bound():
    import statistics
    from zargar.techniques.team2.levels import _cluster
    prices = [100.0]
    for _ in range(31):
        prices.append(statistics.median(prices) + 0.5)                       # the reviewers' chaining fixture
    cands = [{"price": p, "kind": "high", "origin_date": "2026-09-10", "available_at": 0, "last_reaction_at": 0, "episode_ids": []} for p in prices]
    spans = [max(c["members"]) - min(c["members"]) for c in _cluster(cands, 0.5)]
    assert max(spans) <= 0.5 + 1e-9


def _two_levels_plan(confirm_first: bool, reject_second: bool):
    """Two resistance levels breaking on the same 09:45 bar; the second's fate is set by the 10:00 bar."""
    level_a, level_b = TOP + 1.0, TOP + 1.5
    def fn(i):
        m = 4 * 60 + i
        if m < 9 * 60 + 30:
            return level_a - 0.6 + 0.4 * (i / 330)
        x = m - 9 * 60 - 30
        if x < 15:
            return level_a - 0.2 + 2.2 * (x / 14)                             # through both levels by 09:44
        if x < 30:
            return (level_b + 0.6) if not reject_second else (level_b - 0.2)   # 10:00 close: above both / between them
        return (level_b + 0.6 if not reject_second else level_b - 0.2) + 0.01 * (x % 7)
    rules = make_rules(key_levels="D1")
    today = path_1m(DAY, (4, 0), (20, 0), fn)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(PREV, 15), rules, prev_bars_1m=PREV), today)
    def lv(i, p):
        return {"levelId": f"level-{i}", "definition": "D1", "originKind": "high", "originDate": "2026-09-02", "availableAt": 0,
                "price": p, "role": "resistance", "score": 2.55, "reactions": 3, "lastReactionAt": 0, "members": [p],
                "episodes": [], "maskedBy": "none", "flips": 0, "flipPending": False, "breakAt": None, "flipConfirmedAt": None, "retired": False}
    plan["keyLevels"] = {"definition": "D1", "atrBuild": 0.5, "candidates": [lv(0, level_a), lv(1, level_b)],
                         "above": [lv(0, level_a), lv(1, level_b)], "below": []}
    return simulate_session(plan, today, rules, sigma=0.2, warmup_1m=PREV), level_a, level_b


def test_two_levels_breaking_on_one_bar_are_two_setups_and_rejecting_one_leaves_the_other():
    res, a, b = _two_levels_plan(confirm_first=True, reject_second=True)
    setups = [s for s in res.setups if s["kind"] == "key_break_up"]
    assert len(setups) == 2 and len({s["id"] for s in setups}) == 2
    by_anchor = {s["anchor"]: s for s in setups}
    assert not by_anchor[round(a, 4)]["dead"]                                  # the lower level confirmed (10:00 close above it)
    assert by_anchor[round(b, 4)]["dead"] and "rejected" in by_anchor[round(b, 4)]["deadReason"]
    flips = [e for e in res.events if e["event"] == "key_level_flip"]
    rejected = [e for e in res.events if e["event"] == "key_level_rejected"]
    assert [e["levelId"] for e in flips] == ["level-0"] and [e["levelId"] for e in rejected] == ["level-1"]


def test_precedence_among_same_bar_setups_is_the_nearest_confirmed_anchor():
    res, a, b = _two_levels_plan(confirm_first=True, reject_second=False)
    setups = [s for s in res.setups if s["kind"] == "key_break_up"]
    assert len(setups) == 2 and all(not s["dead"] for s in setups)
    # price sits above both after 10:00; the nearer anchor below price is level b — every pullback event names it
    ev = [e for e in res.events if e.get("setup") and e["event"] in ("fire", "same_pullback", "skip_no_trade_zone", "skip_no_contract", "key_level_pending", "pullback_stalled")]
    assert ev and all(e["setup"].endswith(f":{b:.2f}") for e in ev), [(e["event"], e["setup"]) for e in ev][:5]


# ---------------------------------------------------------------- the read: break -> pending -> confirm / reject, causally
from .test_team2_integrity import PREV, TOP


def _gap_day_through(level: float, *, confirm: bool):
    """Pre-market above the PDH zone, then a 15m body close through `level` at 09:45; the 10:00 bar either closes
    through again (confirm) or back below (reject); then a drift."""
    def fn(i):
        m = 4 * 60 + i
        if m < 9 * 60 + 30:
            return level - 0.6 + 0.4 * (i / 330)                          # gap up: above the zone, under the level
        x = m - 9 * 60 - 30
        if x < 15:
            return level - 0.2 + 0.9 * (x / 14)                           # 09:30-09:44 rises through the level
        if x < 30:
            return (level + 0.8) if confirm else (level - 0.5)            # 09:45-09:59 holds above (confirm) / falls back (reject)
        return (level + 0.8 if confirm else level - 0.5) + 0.01 * (x % 7)
    return fn


def _read_with_level(level: float, *, confirm: bool):
    rules = make_rules(key_levels="D1")
    today = path_1m(DAY, (4, 0), (20, 0), _gap_day_through(level, confirm=confirm))
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(PREV, 15), rules, prev_bars_1m=PREV), today)
    lv = {"levelId": "SPY:D1:test:high:%.4f" % level, "definition": "D1", "originKind": "high", "originDate": PREV[0].symbol and "2026-09-02",
          "availableAt": 0, "price": level, "role": "resistance", "score": 2.55, "reactions": 3, "lastReactionAt": 0,
          "members": [level], "episodes": [], "maskedBy": "none", "flips": 0, "flipPending": False, "breakAt": None,
          "flipConfirmedAt": None, "retired": False}
    plan["keyLevels"] = {"definition": "D1", "atrBuild": 0.5, "candidates": [lv], "above": [lv], "below": []}
    return simulate_session(plan, today, rules, sigma=0.2, warmup_1m=PREV)


def test_a_key_level_break_beyond_the_zone_mints_a_setup_pending_until_the_second_close_then_confirms():
    level = TOP + 1.0
    res = _read_with_level(level, confirm=True)
    kinds = [e["event"] for e in res.events]
    assert "key_level_break" in kinds and "key_level_setup" in kinds and "key_level_flip" in kinds
    brk = next(e for e in res.events if e["event"] == "key_level_break")
    flip = next(e for e in res.events if e["event"] == "key_level_flip")
    assert brk["beyondZone"] is True and flip["ts"] > brk["ts"] and flip["role"] == "support"
    setup = next(s for s in res.setups if s["kind"] == "key_break_up")
    assert setup["anchor"] == round(level, 4) and setup["direction"] == "long" and not setup["dead"]
    assert not [e for e in res.events if e["event"] == "key_level_rejected"]


def test_a_rejected_break_kills_the_key_level_setup_and_the_level_keeps_its_role():
    level = TOP + 1.0
    res = _read_with_level(level, confirm=False)
    kinds = [e["event"] for e in res.events]
    assert "key_level_break" in kinds and "key_level_rejected" in kinds and "key_level_flip" not in kinds
    setup = next(s for s in res.setups if s["kind"] == "key_break_up")
    assert setup["dead"] and "rejected" in (setup["deadReason"] or "")
    assert not [e for e in res.events if e["event"] == "fire" and e.get("keyLevel")]
