"""Session plans, walk-forward validation, R6 session windows, and live arming
(docs/TECHNIQUE-WALKFORWARD-PLAN.md). No network, no real LLM: Yahoo fetchers
are monkeypatched with a continuous synthetic market; the Anthropic client is
faked only where a full-mode run is needed (R6 watch-only test)."""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import httpx
import pytest

from zargar.api.app import create_app
from zargar.domain import Bar
from zargar.engine import Engine
from zargar.technique import service as service_mod
from zargar.technique.analysis import AnalysisRequest, compute_facts
from zargar.technique.plans import analysis_from_trigger, build_session_plan, plan_summary_text
from zargar.technique.rulebook import (
    DEFAULT_THRESHOLDS,
    ET,
    is_prime,
    next_session_date,
    session_bounds,
    session_date,
    session_window,
)
from zargar.technique.service import attach_technique_layer
from zargar.technique.setups import bounce_stop
from zargar.technique.volume import build_profile
from zargar.technique.walkforward import (
    compute_symbol_rows,
    TriggerTracker,
    aggregate,
    level_respect,
    replay_plan,
    run_symbol,
)

from .conftest import TEST_DB_URL, make_test_config
from .test_technique_review import FakeClient, _analysis_from_plan, _script_for

MIN = 60_000


# --- synthetic continuous market ------------------------------------------------------------

def _ms(day: dt.date, h: int, m: int) -> int:
    return int(dt.datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp() * 1000)


def continuous_market(days: list[dt.date], *, lo=100.0, hi=104.0, period=40, symbol="TEST") -> dict[str, list[Bar]]:
    """Triangle wave that continues across sessions (no overnight gap), so plans
    built at a close see the next open where the previous close was."""
    bars: list[Bar] = []
    k_global = 0
    prev = lo
    for day in days:
        for i in range(390):
            k = k_global % period
            frac = k / (period / 2) if k < period / 2 else 2 - k / (period / 2)
            px = round(lo + (hi - lo) * frac, 2)
            o, c = prev, px
            bars.append(Bar(symbol=symbol, tf="1m", ts=_ms(day, 9, 30) + i * MIN, open=o,
                            high=round(max(o, c) + 0.02, 2), low=round(min(o, c) - 0.02, 2), close=c,
                            volume=900 + (i * 37) % 400))
            prev = px
            k_global += 1
    return {"1m": bars, "30m": _resample(bars, 30, "30m"), "1h": _resample(bars, 60, "1h")}


def _resample(bars: list[Bar], n: int, tf: str) -> list[Bar]:
    out = []
    for i in range(0, len(bars), n):
        seg = bars[i:i + n]
        out.append(Bar(symbol=seg[0].symbol, tf=tf, ts=seg[0].ts, open=seg[0].open, high=max(b.high for b in seg),
                       low=min(b.low for b in seg), close=seg[-1].close, volume=sum(b.volume for b in seg)))
    return out


def weekdays(n: int, *, ending_days_ago: int = 3) -> list[dt.date]:
    d = dt.datetime.now(ET).date() - dt.timedelta(days=ending_days_ago)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    out = [d]
    while len(out) < n:
        d -= dt.timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return sorted(out)


def by_day(bars: list[Bar]) -> dict[str, list[Bar]]:
    out: dict[str, list[Bar]] = {}
    for b in bars:
        out.setdefault(session_date(b.ts), []).append(b)
    return out


def plan_at_close(market: dict[str, list[Bar]], day: str):
    close_ts = session_bounds(day)[1]           # 16:00 ET
    win = {k: [b for b in v if b.ts <= close_ts] for k, v in market.items()}
    req = AnalysisRequest(symbol="TEST", as_of_ms=close_ts, primary_tf="1m", context_tfs=("1h", "30m"))
    facts = compute_facts(req, win, [])
    return build_session_plan(facts, structure_tfs=["1h", "30m"], trigger_tf="1m").to_dict(), facts


# --- rulebook -------------------------------------------------------------------------------------

def test_session_windows_follow_the_book():
    d = dt.date(2026, 8, 20)       # a Thursday
    assert session_window(_ms(d, 9, 30)) == "prime_open"
    assert session_window(_ms(d, 10, 29)) == "prime_open"
    assert session_window(_ms(d, 10, 30)) == "midday"
    assert session_window(_ms(d, 14, 44)) == "midday"
    assert session_window(_ms(d, 14, 45)) == "prime_close"
    assert session_window(_ms(d, 15, 59)) == "prime_close"
    assert session_window(_ms(d, 16, 0)) == "extended"
    assert session_window(_ms(d, 8, 0)) == "extended"
    assert session_window(_ms(dt.date(2026, 8, 22), 10, 0)) == "extended"     # Saturday
    assert is_prime(_ms(d, 9, 45)) and not is_prime(_ms(d, 12, 0))
    assert next_session_date(_ms(d, 16, 5)) == "2026-08-21"
    assert next_session_date(_ms(dt.date(2026, 8, 21), 16, 5)) == "2026-08-24"   # Friday -> Monday
    assert next_session_date(_ms(d, 8, 0)) == "2026-08-20"                       # pre-market = today
    o, c = session_bounds("2026-08-20")
    assert o == _ms(d, 9, 30) and c == _ms(d, 16, 0)


def test_bounce_stop_is_chart_anchored_and_volatility_aware():
    s0 = bounce_stop(100.0)
    assert 100.0 - s0 == pytest.approx(0.5, abs=0.01)          # book's $98 -> $97.50 = 0.5%
    s1 = bounce_stop(100.0, atr_value=4.0)                      # 0.25 ATR = 1.0 beats 0.5%
    assert 100.0 - s1 == pytest.approx(1.0, abs=0.01)
    s2 = bounce_stop(100.0, invalidation=99.0)                  # chart low below the level anchors
    assert s2 == pytest.approx(99.0 - 0.495, abs=0.01)


# --- plan building ------------------------------------------------------------------------------

def test_session_plan_has_conditional_triggers_not_fills():
    days = weekdays(5)
    market = continuous_market(days)
    plan, facts = plan_at_close(market, days[3].isoformat())
    assert plan["planFor"] == days[4].isoformat()
    assert plan["builtFromSession"] == days[3].isoformat()
    assert plan["structureTfs"] == ["1h", "30m"] and plan["triggerTf"] == "1m"
    assert plan["levels"] and any(l["priorDayExtreme"] for l in plan["levels"])
    kinds = {t["kind"] for t in plan["triggers"]}
    assert "bounce" in kinds
    b = next(t for t in plan["triggers"] if t["kind"] == "bounce")
    # conditions are stated, not assumed: touch + window + volume; no candle gate (T4.2)
    assert {c["kind"] for c in b["conditions"]} == {"touch", "window", "volume"}
    assert b["entry"]["basis"] == "at_level" and b["stop"]["price"] < b["entry"]["price"]
    assert b["valid"] and b["riskReward"] >= 3
    assert any("gapped past" in v for v in b["voidIf"]) and "R6.1" in b["rules"] and "T4.3d" in b["rules"]
    assert any(i["kind"] == "gap_void" for i in plan["invalidations"])
    txt = plan_summary_text(plan)
    assert "session plan for" in txt and "IF" in txt and "THEN" in txt
    # the analysis contract for a fired trigger round-trips through the schema
    a = analysis_from_trigger(b, "TEST", session_window="prime_open")
    assert a.verdict == "setup" and a.entry.price == b["entry"]["price"] and len(a.targets) == 3


def _facts_level(as_of: int, price: float, kind: str, touches: int,
                 sources=("T1.3c",), tfs=("1m",)) -> dict:
    return {"price": price, "kind": kind, "effectiveKind": kind, "touches": touches,
            "sources": list(sources), "timeframes": list(tfs),
            "position": "below" if kind == "support" else "above",
            "firstTs": as_of - 3 * 86_400_000, "lastTs": as_of}


def _mara_like_facts() -> dict:
    """The MARA 2026-08-21 close, distilled (run f055c5c6): three supports within
    0.9% + Friday's LOD below them, a 27-touch resistance at the close, and the
    faded gap's wick high as the prior-day extreme."""
    as_of = _ms(dt.date(2026, 8, 21), 16, 5)      # a Friday, after the close
    return {
        "symbol": "MARA", "asOf": as_of, "lastTs": as_of, "lastClose": 11.26,
        "primaryTf": "1m", "atr": {"1m": 0.035, "30m": 0.35, "1h": 0.36},
        "trend": {"1m": {"direction": "sideways"}, "30m": {"direction": "uptrend"},
                  "1h": {"direction": "uptrend"}},
        "volume": {}, "wedge": {}, "notes": [],
        "session": {"prev": {"hod": 11.19, "lod": 9.96, "close": 11.15, "date": "2026-08-20"},
                    "today": {"open": 11.715, "hod": 12.465, "lod": 11.02, "bars": 390}},
        "keyLevels": [
            _facts_level(as_of, 11.198, "support", 26, ("T1.3a", "T1.3c"), ("1m", "1h", "30m")),
            _facts_level(as_of, 11.1462, "support", 24),
            _facts_level(as_of, 11.1037, "support", 20),
            _facts_level(as_of, 11.258, "resistance", 27),
        ],
    }


def test_plan_merges_clustered_supports_and_stops_below_the_zone():
    """The review of run f055c5c6 pinned four defects: a fixed-% stop, a ladder
    of three triggers inside one zone, a target anchored at a rejected gap wick
    (R:R 22 'artifact'), and no honest R2 gate. All four in one regression."""
    plan = build_session_plan(_mara_like_facts(), structure_tfs=["1h", "30m"],
                              trigger_tf="1m").to_dict()
    bounces = [t for t in plan["triggers"] if t["kind"] == "bounce"]
    assert len(bounces) == 1                       # 11.20/11.15/11.10 + Friday's LOD = ONE zone
    b = bounces[0]
    assert b["entry"]["price"] == 11.198           # the strong prior-day level leads
    z = b["level"]["zone"]
    assert z["low"] == 11.02 and 11.02 in z["members"]     # carried LOD joins the zone
    assert b["stop"]["price"] < 11.02 and b["stop"]["reference"] == "below_zone_low"
    # targets anchor at the real 27-touch resistance overhead, not the gap wick
    assert abs(b["targets"][-1]["price"] - 11.258) < 1e-6
    # honest stop + honest target -> the R2 gate fails: not tradeable
    assert not b["valid"] and any("R2" in r for r in b["noTradeReasons"])
    assert plan["validTriggers"] == 0


def test_plan_triggers_carry_a_deterministic_grade_and_bottom_line():
    """The 'level of validity' the user reads before arming: every trigger gets
    an assessment (grade A/B/C for valid ones, strengths/cautions with rule
    citations for all), and the plan carries a plain-language bottom line."""
    facts = _mara_like_facts()
    plan = build_session_plan(facts, structure_tfs=["1h", "30m"], trigger_tf="1m").to_dict()
    b = plan["triggers"][0]
    a = b["assessment"]
    assert a["grade"] is None and not b["valid"]           # invalid -> no grade
    assert a["score"] > 0 and any("T1.3a" in s for s in a["strengths"])
    assert "Nothing to arm" in plan["bottomLine"] and "do not force a trade" in plan["bottomLine"]
    # a valid trigger gets a letter grade and the bottom line says how it fires
    days = weekdays(5)
    market = continuous_market(days)
    plan2, _ = plan_at_close(market, days[3].isoformat())
    valid = [t for t in plan2["triggers"] if t["valid"]]
    assert valid and all(t["assessment"]["grade"] in ("A", "B", "C") for t in valid)
    assert "fires only if" in plan2["bottomLine"] and "can arm" in plan2["bottomLine"]
    # deterministic: same facts -> same grades
    plan3, _ = plan_at_close(market, days[3].isoformat())
    assert [t["assessment"] for t in plan3["triggers"]] == [t["assessment"] for t in plan2["triggers"]]


def test_bounce_enters_at_the_zone_top_and_ladder_rr_cannot_grade_A():
    """WDAY 2026-08-24 regression (run a9fd6891, chat 4ed9f02d): the bounce
    entered at an 18-touch prior-day member near the BOTTOM of a 7-member zone
    (price had to break five supports to reach it — T3.4d) and graded A; the
    breakout graded A on a 2/4/6%-ladder R:R. Now: entry is always the zone's
    top member (here the wide zone honestly fails the stop cap), and a pct-ladder
    R:R caps the grade at B."""
    as_of = _ms(dt.date(2026, 8, 21), 16, 5)
    facts = {
        "symbol": "WDAY", "asOf": as_of, "lastTs": as_of, "lastClose": 200.01,
        "primaryTf": "1m", "atr": {"1m": 0.3, "30m": 2.4, "1h": 2.6},
        "trend": {"1m": {"direction": "sideways"}, "30m": {"direction": "uptrend"},
                  "1h": {"direction": "uptrend"}},
        "volume": {}, "wedge": {}, "notes": [],
        "session": {"prev": {"hod": 201.55, "lod": 194.78, "close": 199.9, "date": "2026-08-20"},
                    "today": {"open": 199.5, "hod": 201.55, "lod": 198.9, "bars": 390}},
        "keyLevels": [
            _facts_level(as_of, 199.3065, "support", 42),
            _facts_level(as_of, 198.1729, "support", 42),
            _facts_level(as_of, 196.835, "support", 33),
            _facts_level(as_of, 196.1717, "support", 20),
            _facts_level(as_of, 195.4575, "support", 19),
            _facts_level(as_of, 194.7833, "support", 18, ("T1.3a", "T1.3c"), ("1m", "1h", "30m")),
            _facts_level(as_of, 193.872, "support", 10),
            _facts_level(as_of, 200.4986, "resistance", 25, ("T1.3a", "T1.3c"), ("1m", "1h", "30m")),
            _facts_level(as_of, 201.5499, "resistance", 1, ("T1.3a",)),
        ],
    }
    plan = build_session_plan(facts, structure_tfs=["1h", "30m"], trigger_tf="1m").to_dict()
    b = next(t for t in plan["triggers"] if t["kind"] == "bounce")
    assert b["entry"]["price"] == 199.3065          # zone TOP, never a deep member
    assert not b["valid"]                            # 3%+ zone-wide stop fails the cap honestly
    assert any("T4.3a" in r or "R2" in r for r in b["noTradeReasons"])
    k = next(t for t in plan["triggers"] if t["kind"] == "breakout")
    assert k["valid"] and k["targets"][0]["basis"] == "pct_ladder"
    assert k["assessment"]["grade"] == "B"           # ladder R:R can never be an A
    assert any("capped at B" in c for c in k["assessment"]["cautions"])


def test_plan_skips_supports_inside_a_prior_triggers_risk_envelope():
    """A lower zone whose entry sits above the prior trigger's stop is churn
    (stop out, re-enter at the same price) — it is skipped, not emitted."""
    facts = _mara_like_facts()
    facts["lastClose"] = 100.5
    facts["atr"] = {"1m": 0.05, "30m": 4.4, "1h": 4.4}   # wide buffer: stop1 lands at 98.9
    facts["session"] = {"prev": {}, "today": {"open": 100.5, "hod": 104.0, "lod": 100.0}}
    as_of = facts["asOf"]
    facts["keyLevels"] = [_facts_level(as_of, 100.0, "support", 5),
                          _facts_level(as_of, 98.9, "support", 4)]
    plan = build_session_plan(facts, structure_tfs=["1h", "30m"], trigger_tf="1m").to_dict()
    bounces = [t for t in plan["triggers"] if t["kind"] == "bounce"]
    assert len(bounces) == 1 and bounces[0]["entry"]["price"] == 100.0
    assert any("risk envelope" in n for n in plan["notes"])


def test_plan_builder_has_no_look_ahead():
    days = weekdays(5)
    full = continuous_market(days)
    # the same plan must come out whether or not the future session's bars exist
    plan_a, _ = plan_at_close(full, days[3].isoformat())
    trimmed = {k: [b for b in v if session_date(b.ts) <= days[3].isoformat()] for k, v in full.items()}
    plan_b, _ = plan_at_close(trimmed, days[3].isoformat())
    assert plan_a["triggers"] == plan_b["triggers"] and plan_a["levels"] == plan_b["levels"]


# --- trigger tracking / replay --------------------------------------------------------------------

def _bounce_trigger(entry=100.0, stop=99.5, targets=(101.6, 103.0, 104.0)):
    return {"id": "b1", "kind": "bounce", "setupType": "support_bounce", "valid": True,
            "entry": {"price": entry, "basis": "at_level"}, "stop": {"price": stop},
            "targets": [{"price": t} for t in targets], "levelPrice": entry, "riskReward": 8.0}


def _bar(day, h, m, o, hi, lo, c, v=1000):
    return Bar(symbol="T", tf="1m", ts=_ms(day, h, m), open=o, high=hi, low=lo, close=c, volume=v)


def test_tracker_gap_rules_and_windows():
    d = weekdays(1)[0]
    tg = _bounce_trigger()
    # gap void: open far from prev close
    tr = TriggerTracker(tg, DEFAULT_THRESHOLDS, None, True, True, prev_close=102.0)
    assert tr.on_bar(_bar(d, 9, 30, 103.5, 103.6, 103.4, 103.5), 0) == "gap_void"
    # gapped through the stop
    tr = TriggerTracker(tg, DEFAULT_THRESHOLDS, None, True, True, prev_close=100.2)
    assert tr.on_bar(_bar(d, 9, 30, 99.2, 99.3, 99.1, 99.2), 0) == "gapped_through"
    # gapped past the level (below entry, above stop)
    tr = TriggerTracker(tg, DEFAULT_THRESHOLDS, None, True, True, prev_close=100.2)
    assert tr.on_bar(_bar(d, 9, 30, 99.8, 99.9, 99.7, 99.8), 0) == "gapped_past"
    # mid-day touch is observed, not fired; the same touch fires without the gate
    prof = build_profile([Bar(symbol="T", tf="1m", ts=_ms(d - dt.timedelta(days=1), 9, 30) + i * MIN, open=100,
                              high=100.1, low=99.9, close=100, volume=1000) for i in range(390)])
    gated = TriggerTracker(tg, DEFAULT_THRESHOLDS, prof, True, True, prev_close=100.6)
    free = TriggerTracker(tg, DEFAULT_THRESHOLDS, prof, False, True, prev_close=100.6)
    bars = [_bar(d, 9, 30, 100.6, 100.7, 100.5, 100.6)] + [_bar(d, 12, 0, 100.3, 100.4, 99.95, 100.1)]
    for i, b in enumerate(bars):
        gated.on_bar(b, i)
        free.on_bar(b, i)
    assert gated.status == "observed" and gated.observed_midday and free.status == "fired"
    assert free.fired_window == "midday"
    # prime-close touch fires when gated
    gated.on_bar(_bar(d, 15, 0, 100.2, 100.3, 99.9, 100.1), 2)
    assert gated.status == "fired" and gated.fired_window == "prime_close" and gated.fill_price == 100.0


def test_tracker_volume_floor_skips_then_fires():
    d = weekdays(1)[0]
    tg = _bounce_trigger()
    # baseline 1000/bar; a 300-volume touch is below the 50% floor
    prior = [Bar(symbol="T", tf="1m", ts=_ms(d - dt.timedelta(days=1), 9, 30) + i * MIN, open=100, high=100.1,
                 low=99.9, close=100, volume=1000) for i in range(390)]
    prof = build_profile(prior)
    tr = TriggerTracker(tg, DEFAULT_THRESHOLDS, prof, True, True, prev_close=100.5)
    assert tr.on_bar(_bar(d, 9, 31, 100.2, 100.3, 99.95, 100.1, v=300), 0) == "waiting"
    assert tr.skipped and "R3.1" in tr.skipped[0]["reason"]
    assert tr.on_bar(_bar(d, 9, 32, 100.1, 100.2, 99.95, 100.1, v=900), 1) == "fired"


def test_tracker_breakout_needs_confirmation():
    d = weekdays(1)[0]
    tg = {"id": "k1", "kind": "breakout", "setupType": "breakout", "valid": True,
          "entry": {"price": 104.0, "basis": "on_break"}, "stop": {"price": 103.5},
          "targets": [{"price": 105.0}, {"price": 106.0}, {"price": 107.0}], "levelPrice": 104.0, "riskReward": 6.0}
    prior = [Bar(symbol="T", tf="1m", ts=_ms(d - dt.timedelta(days=1), 9, 30) + i * MIN, open=103, high=103.2,
                 low=102.9, close=103.1, volume=1000) for i in range(390)]
    prof = build_profile(prior)
    tr = TriggerTracker(tg, DEFAULT_THRESHOLDS, prof, True, True, prev_close=103.8)
    bars = [_bar(d, 9, 30, 103.8, 103.9, 103.7, 103.85),
            _bar(d, 9, 31, 103.85, 104.6, 103.84, 104.55, v=2500),   # decisive close through on volume
            _bar(d, 9, 32, 104.55, 104.8, 104.5, 104.7),
            _bar(d, 9, 33, 104.7, 104.9, 104.6, 104.85),
            _bar(d, 9, 34, 104.85, 105.0, 104.8, 104.9)]
    for i, b in enumerate(bars):
        tr.on_bar(b, i)
    assert tr.status == "fired" and tr.fill_price == 104.9 and tr.fired_window == "prime_open"
    # a low-volume break is skipped (T3.3d)
    tr2 = TriggerTracker(tg, DEFAULT_THRESHOLDS, prof, True, True, prev_close=103.8)
    tr2.on_bar(bars[0], 0)
    tr2.on_bar(_bar(d, 9, 31, 103.85, 104.6, 103.84, 104.55, v=600), 1)
    assert tr2.status == "waiting" and "T3.3d" in tr2.skipped[0]["reason"]


def test_level_respect_statuses():
    d = weekdays(1)[0]
    lv = [{"price": 100.0, "effectiveKind": "support", "sources": ["T1.3a"], "touches": 3, "timeframes": ["1h"]},
          {"price": 110.0, "effectiveKind": "resistance", "sources": ["T1.3c"], "touches": 2, "timeframes": ["1h"]},
          {"price": 103.0, "effectiveKind": "resistance", "sources": ["T1.3c"], "touches": 2, "timeframes": ["30m"]}]
    bars = [_bar(d, 9, 30, 101, 101.2, 100.8, 101),
            _bar(d, 9, 31, 101, 101.1, 99.95, 100.1),      # touch support
            _bar(d, 9, 32, 100.1, 101.6, 100.0, 101.5),     # reverse >= 3 x tol  -> respected
            _bar(d, 9, 33, 101.5, 103.1, 101.4, 102.9),     # touch 103 resistance
            _bar(d, 9, 34, 102.9, 103.9, 102.8, 103.8)]     # close through -> broken
    res = {r["price"]: r["status"] for r in level_respect(lv, bars)}
    assert res[100.0] == "respected" and res[110.0] == "untested" and res[103.0] == "broken"


def test_replay_plan_scores_bounce_and_counterfactuals():
    days = weekdays(5)
    market = continuous_market(days)
    plan, _ = plan_at_close(market, days[3].isoformat())
    nxt = by_day(market["1m"])[days[4].isoformat()]
    prior = [b for b in market["1m"] if session_date(b.ts) < days[4].isoformat()]
    rep = replay_plan(plan, nxt, profile=build_profile(prior))
    b1 = next(t for t in rep["triggers"] if t["kind"] == "bounce")
    assert b1["status"] == "fired" and b1["firedWindow"] in ("prime_open", "prime_close")
    assert b1["sim"]["outcome"].startswith("tp") and b1["sim"]["rMultiple"] > 0
    assert "noWindowGate" in b1["counterfactual"] and "noGapRules" in b1["counterfactual"]
    assert rep["summary"]["fired"] >= 1 and rep["summary"]["levelsRespected"] >= 1
    assert all(l["status"] in ("respected", "broken", "flipped", "untested") for l in rep["levels"])


def test_history_clip_request_window_never_asks_for_the_future():
    # a chunk wholly in the future (the week after the last planned session) is a
    # Yahoo 400 — the window must end at "now"; 1m start is clamped to its lookback
    from zargar.technique.history import MAX_LOOKBACK, clip_request_window
    now = 1_787_000_000
    lo, hi = clip_request_window("1m", now - 40 * 86400, now + 7 * 86400, now)
    assert lo == now - MAX_LOOKBACK["1m"] and now <= hi <= now + 60
    lo, hi = clip_request_window("1h", now - 40 * 86400, now - 86400, now)
    assert (lo, hi) == (now - 40 * 86400, now - 86400)


def test_compute_symbol_rows_is_the_pure_half_of_run_symbol():
    days = weekdays(6)
    market = continuous_market(days)
    rows = compute_symbol_rows("TEST", days[1].isoformat(), days[4].isoformat(), structure_tfs=["1h", "30m"],
                               trigger_tf="1m", thresholds=DEFAULT_THRESHOLDS, bars_by_tf=market)
    assert [r["session"] for r in rows] == [d.isoformat() for d in days[1:5]]
    assert compute_symbol_rows("TEST", days[1].isoformat(), days[4].isoformat(), structure_tfs=["1h"],
                               trigger_tf="1m", thresholds=DEFAULT_THRESHOLDS, bars_by_tf={})[0]["error"]


async def test_run_symbol_sweep_and_aggregate():
    days = weekdays(6)
    market = continuous_market(days)
    rows = await run_symbol("TEST", days[1].isoformat(), days[4].isoformat(), structure_tfs=["1h", "30m"],
                            trigger_tf="1m", thresholds=DEFAULT_THRESHOLDS, bars_override=market)
    assert [r["session"] for r in rows] == [d.isoformat() for d in days[1:5]]
    assert all(r["planFor"] == days[i + 2].isoformat() for i, r in enumerate(rows))
    # the sweep's plan for day N is the plan a live analyse at N's close builds — same
    # triggers, same prices (a promoted run must not show a different plan)
    live, _ = plan_at_close(market, days[3].isoformat())
    swept = rows[2]["plan"]
    assert [(t["id"], t["kind"], t["entry"]["price"], t["stop"]["price"]) for t in swept["triggers"]] ==         [(t["id"], t["kind"], t["entry"]["price"], t["stop"]["price"]) for t in live["triggers"]]
    assert [l["price"] for l in swept["levels"]] == [l["price"] for l in live["levels"]]
    agg = aggregate(rows)
    assert agg["sessions"] == 4 and agg["symbols"] == ["TEST"]
    assert agg["triggers"]["byKind"]["bounce"]["fired"] >= 1
    assert agg["levels"]["priorDayVsOther"]["priorDay"]["n"] > 0
    names = {c["claim"] for c in agg["claims"]}
    assert "Prime windows beat mid-day" in names and "Gap rules help (ours)" in names
    assert agg["sample"]["target"] == 100


# --- service integration (plan runs, scoring, sweeps, arming, R6 watch-only) ------------------------

@pytest.fixture
async def rig(fresh_db, monkeypatch):
    config = make_test_config(anthropic_api_key="sk-test")
    eng = Engine(config)
    await eng.start()
    await attach_technique_layer(eng)
    await eng.settings.set("technique.options.enabled", False, journal=False)
    # the synthetic sim market is built around the book's TP3 arithmetic (R:R 3-4 to
    # the next resistance); the app's default gate is the exit rung (TP2 for one
    # contract) and is covered by its own unit tests
    await eng.settings.set("technique.rr_gate_target", "tp3", journal=False)
    await eng.settings.set("technique.long_only", True, journal=False)   # these fixtures encode the long-side plan; the short mirror has its own test
    app = create_app(config, eng)
    transport = httpx.ASGITransport(app=app)
    days = weekdays(6)
    market = continuous_market(days)
    sessions = by_day(market["1m"])

    async def fake_gather(req_):
        out = {}
        for tf in req_.timeframes:
            bars = market.get(tf) or []
            out[tf] = [b for b in bars if req_.as_of_ms is None or b.ts <= req_.as_of_ms]
        return {k: v for k, v in out.items() if v}, ["synthetic bars"]

    async def fake_session(symbol, tf, date, **kw):
        return [b for b in (market.get(tf) or []) if session_date(b.ts) == date]

    monkeypatch.setattr(service_mod, "gather_bars", fake_gather)
    monkeypatch.setattr(service_mod, "fetch_session", fake_session)
    monkeypatch.setattr(eng.technique, "_sweep_bars_override", lambda sym: market)
    # a fake LLM so full-mode runs work (plan mode never calls it)
    close_day = days[3].isoformat()
    plan, facts = plan_at_close(market, close_day)
    cand = (facts.get("candidateSetups") or [None])[0]
    fake = FakeClient(_script_for({"entry": {"price": cand["entry"]["price"], "basis": "at_level"},
                                   "stop": {"price": cand["stop"]["price"]},
                                   "targets": [{"price": t["price"]} for t in cand["targets"]],
                                   "riskReward": cand["riskReward"], "setupType": "support_bounce"},
                                  cand["levelPrice"] or cand["entry"]["price"], None))
    monkeypatch.setattr(eng.technique, "_get_client", lambda: fake)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(client=client, eng=eng, svc=eng.technique, days=days, market=market,
                              sessions=sessions, close_day=close_day, fake=fake, cand=cand)
    await eng.technique.stop()
    await eng.stop()


async def test_plan_run_auto_mode_trace_scoring_bundle_and_replay(rig, tmp_path):
    close_ts = session_bounds(rig.close_day)[1]
    run = await rig.svc.analyze("TEST", as_of_ms=close_ts, with_vision=False, wait=True)   # 16:00 ET -> plan mode
    assert run["status"] == "done", run.get("error")
    assert run["mode"] == "plan" and run["verdict"] == "plan"
    assert run["images"].get("annotated") and run["images"].get("1m")          # the map is drawn
    plan = run["result"]["plan"]
    assert plan["planFor"] == rig.days[4].isoformat() and plan["validTriggers"] >= 1
    assert run["config"]["planMode"]["structureTfs"] == ["1h", "30m"] and run["config"]["planMode"]["triggerTf"] == "1m"
    steps = {(t["stage"], t["step"]) for t in run["result"]["trace"]}
    assert ("plan", "mode") in steps and ("plan", "levels") in steps and ("loop", "skipped") in steps
    assert any(s[0] == "plan" and s[1].startswith("trigger_") for s in steps)
    assert run["result"]["grounding"]["passed"] is None and run["result"]["passes"] == []
    # scored immediately against the planned session (monkeypatched fetch_session)
    outs = {o["planSource"]: o for o in run["outcomes"]}
    assert "levels" in outs and outs["levels"]["status"] == "scored"
    trig = [o for k, o in outs.items() if k.startswith("trigger:")]
    assert trig and any(o["outcome"] and o["outcome"].startswith("tp") and (o["rMultiple"] or 0) > 0 for o in trig)
    # chat thread carries the plan summary; list shows the plan summary
    thread = await rig.eng.chat.get_thread(run["threadId"])
    assert any("session plan for" in (b.get("text") or "") for m in thread["messages"] for b in m["blocks"])
    rows = (await rig.client.get("/api/technique/runs")).json()
    assert rows[0]["id"] == run["id"] and rows[0]["plan"]["validTriggers"] >= 1 and rows[0]["verdict"] == "plan"
    # bundle has the plan; replay keeps plan mode
    jb = (await rig.client.get(f"/api/technique/runs/{run['id']}/bundle", params={"format": "json"})).json()
    assert jb["run"]["result"]["plan"]["planFor"] == plan["planFor"]
    rep = (await rig.client.post(f"/api/technique/runs/{run['id']}/replay", json={"wait": True})).json()
    assert rep["mode"] == "plan" and rep["parentRunId"] == run["id"]
    # explicit API plan endpoint + forcing plan=False inside the session
    r = await rig.client.post("/api/technique/plan", json={"symbol": "TEST", "asOf": close_ts, "wait": True})
    assert r.status_code == 200 and r.json()["mode"] == "plan"


async def test_full_run_outside_prime_window_is_watch_only(rig):
    # trough at minute 40 of the session (10:10 ET, prime_open) and at minute 280 (14:10, midday)
    day = rig.days[4]
    bars = rig.sessions[day.isoformat()]
    k0 = [i for i, b in enumerate(bars) if b.low <= 100.05 and i > 0]
    prime_i = next(i for i in k0 if session_window(bars[i].ts) == "prime_open")
    mid_i = next(i for i in k0 if session_window(bars[i].ts) == "midday")
    run_mid = await rig.svc.analyze("TEST", as_of_ms=bars[mid_i].ts, wait=True)
    assert run_mid["mode"] == "full" and run_mid["verdict"] == "setup"
    assert any("R6.3" in r for r in run_mid["result"]["analysis"]["noTradeReasons"])
    assert run_mid["setups"][0]["valid"] is False
    assert ("window", "watch_only") in {(t["stage"], t["step"]) for t in run_mid["result"]["trace"]}
    assert run_mid["result"]["sessionWindow"] == "midday"
    run_prime = await rig.svc.analyze("TEST", as_of_ms=bars[prime_i].ts, wait=True)
    assert run_prime["verdict"] == "setup" and run_prime["setups"][0]["valid"] is True
    assert not any("R6" in r for r in run_prime["result"]["analysis"]["noTradeReasons"])
    # turning enforcement off restores the old behaviour
    await rig.eng.settings.set("technique.enforce_session_windows", False, journal=False)
    run_off = await rig.svc.analyze("TEST", as_of_ms=bars[mid_i].ts, wait=True)
    assert run_off["setups"][0]["valid"] is True


async def test_sweep_many_symbols_run_in_parallel_thread_mode(rig):
    # workers=1 keeps it to a background thread (no process spawn in CI); several
    # symbols in flight, each persisted as it finishes, progress counts symbols
    await rig.eng.settings.set("technique.walkforward.workers", 1, journal=False)
    syms = ["AAA", "BBB", "CCC", "DDD"]
    d = await rig.svc.start_sweep(syms, rig.days[1].isoformat(), rig.days[4].isoformat(), wait=True)
    assert d["status"] == "done", d.get("error")
    assert d["progress"]["done"] == 4 and d["progress"]["workers"] == "thread"
    assert d["summary"]["sessions"] == 16 and sorted(d["summary"]["symbols"]) == syms
    got = (await rig.client.get(f"/api/technique/walkforward/{d['id']}")).json()
    assert len(got["rows"]) == 16 and [r["symbol"] for r in got["rows"]] == sorted(r["symbol"] for r in got["rows"])


def test_last_completed_session_rolls_back_over_weekends_and_open_sessions():
    from zargar.technique.walkforward import last_completed_session
    # Sunday noon ET -> Friday; Thursday 10:00 ET (session open) -> Wednesday; Thursday 17:00 -> Thursday
    assert last_completed_session(_ms(dt.date(2026, 8, 23), 12, 0)) == "2026-08-21"
    assert last_completed_session(_ms(dt.date(2026, 8, 20), 10, 0)) == "2026-08-19"
    assert last_completed_session(_ms(dt.date(2026, 8, 20), 17, 0)) == "2026-08-20"


async def test_plan_sheet_builds_pending_rows_and_scores_later(rig, monkeypatch):
    from zargar.technique import service as svc_mod
    # pretend "now" is the close of days[3]: the sheet plans days[4] from the synthetic market
    monkeypatch.setattr(svc_mod, "last_completed_session", lambda now_ms=None: rig.days[3].isoformat())
    await rig.eng.settings.set("technique.walkforward.workers", 1, journal=False)
    d = await rig.svc.start_plan_sheet(["TEST", "TEST2"], label="sheet", wait=True)
    assert d["status"] == "done" and d["params"]["kind"] == "next" and d["params"]["planFor"] == rig.days[4].isoformat()
    assert len(d["rows"]) == 2 and all(r["result"].get("pending") for r in d["rows"])
    live, _ = plan_at_close(rig.market, rig.days[3].isoformat())
    assert [t["id"] for t in d["rows"][0]["plan"]["triggers"]] == [t["id"] for t in live["triggers"]]
    assert d["summary"]["setups"] >= 1
    # the session has bars in the synthetic market -> scoring turns it into a validation
    s = await rig.svc.score_sheet(d["id"])
    assert not any(r["result"].get("pending") for r in s["rows"])
    assert s["summary"]["kind"] == "next" and s["summary"]["sessions"] == 2 and "claims" in s["summary"]
    r = await rig.client.post(f"/api/technique/walkforward/{d['id']}/score")
    assert r.status_code == 200


async def test_sweep_service_rows_promote_and_cli(rig):
    d = await rig.svc.start_sweep(["TEST"], rig.days[1].isoformat(), rig.days[4].isoformat(), wait=True)
    assert d["status"] == "done", d.get("error")
    assert d["summary"]["sessions"] == 4 and d["summary"]["triggers"]["byKind"]["bounce"]["fired"] >= 1
    got = (await rig.client.get(f"/api/technique/walkforward/{d['id']}")).json()
    assert len(got["rows"]) == 4 and got["rows"][0]["symbol"] == "TEST"
    lst = (await rig.client.get("/api/technique/walkforward")).json()
    assert lst[0]["id"] == d["id"]
    # promote one session to a full plan run
    pr = await rig.client.post(f"/api/technique/walkforward/{d['id']}/promote",
                               json={"symbol": "TEST", "session": rig.days[3].isoformat()})
    assert pr.status_code == 200, pr.text
    run = pr.json()
    assert run["mode"] == "plan" and run["trigger"] == "promote"
    # the promoted run carries the very plan the sweep scored (same triggers + levels)
    row = next(r for r in got["rows"] if r["session"] == rig.days[3].isoformat())
    rp, sp = run["result"]["plan"], row["plan"]
    assert [(t["id"], t["entry"]["price"]) for t in rp["triggers"]] == [(t["id"], t["entry"]["price"]) for t in sp["triggers"]]
    assert [l["price"] for l in rp["levels"]] == [l["price"] for l in sp["levels"]]
    got = (await rig.client.get(f"/api/technique/walkforward/{d['id']}")).json()
    assert any(r["promotedRunId"] == run["id"] for r in got["rows"])
    ev = (await rig.client.get("/api/events", params={"type": "TechniqueSweepCompleted"})).json()
    assert ev and ev[0]["payload"]["sweepId"] == d["id"]
    # CLI reads the same DB
    import os, subprocess, sys
    env = dict(os.environ, ZARGAR_REVIEW_DATABASE_URL=TEST_DB_URL, PYTHONUTF8="1")
    cwd = os.path.dirname(os.path.dirname(__file__))
    p = subprocess.run([sys.executable, "-m", "zargar.tools.technique_review", "--json", "sweeps"],
                       capture_output=True, text=True, env=env, cwd=cwd, timeout=120)
    assert p.returncode == 0 and json.loads(p.stdout)[0]["id"] == d["id"]
    p = subprocess.run([sys.executable, "-m", "zargar.tools.technique_review", "sweep-report", d["id"], "--rows"],
                       capture_output=True, text=True, env=env, cwd=cwd, timeout=120)
    assert p.returncode == 0 and "CLAIMS" in p.stdout and "LEVEL QUALITY" in p.stdout


async def test_arming_fires_trigger_and_persists_setup(rig):
    close_ts = session_bounds(rig.close_day)[1]
    run = await rig.svc.analyze("TEST", as_of_ms=close_ts, wait=True)
    plan_for = run["result"]["plan"]["planFor"]
    armed = (await rig.client.post(f"/api/technique/runs/{run['id']}/arm", json={"instrument": "shares"})).json()
    assert armed["runId"] == run["id"] and armed["planFor"] == plan_for and armed["triggers"]
    assert (await rig.client.get("/api/technique/armed")).json()[0]["runId"] == run["id"]
    # feed the planned session's bars by hand (the bus would do this live)
    bars = rig.sessions[plan_for]
    state = None
    for b in bars:
        state = await rig.svc.armer.on_bar(run["id"], b)
        if state and state["fired"]:
            break
    assert state and state["fired"], state
    f = state["fired"][0]
    assert f["kind"] == "bounce" and f["window"] in ("prime_open", "prime_close") and f["setupId"]
    full = (await rig.client.get(f"/api/technique/runs/{run['id']}")).json()
    assert full["setups"] and full["setups"][0]["valid"] is True and full["setups"][0]["setupType"] == "support_bounce"
    types = [e["type"] for e in (await rig.client.get("/api/events", params={"aggregate_id": run["id"]})).json()]
    assert "TechniquePlanArmed" in types and "TechniquePlanTriggerFired" in types
    # the rest of the session expires and disarms the plan
    for b in bars:
        await rig.svc.armer.on_bar(run["id"], b)
    assert (await rig.client.get("/api/technique/armed")).json() == []
    types = [e["type"] for e in (await rig.client.get("/api/events", params={"aggregate_id": run["id"]})).json()]
    assert "TechniquePlanDisarmed" in types
    # non-plan runs cannot be armed
    bad = await rig.client.post("/api/technique/runs/does-not-exist/arm")
    assert bad.status_code == 404


async def test_scan_respects_prime_windows(rig, monkeypatch):
    svc = rig.svc
    import zargar.technique.service as sm
    fake_now = {"ms": _ms(rig.days[4], 12, 0)}
    monkeypatch.setattr(sm.time, "time", lambda: fake_now["ms"] / 1000)
    assert svc._scan_allowed() is False
    fake_now["ms"] = _ms(rig.days[4], 9, 45)
    assert svc._scan_allowed() is True
    await rig.eng.settings.set("technique.enforce_session_windows", False, journal=False)
    fake_now["ms"] = _ms(rig.days[4], 12, 0)
    # rth_only fallback — _in_rth uses the real clock, so just assert it does not raise
    assert isinstance(svc._scan_allowed(), bool)


async def test_plan_with_vision_runs_the_passes(rig):
    """Default for manual plans: the 4-pass read runs on the structure charts and
    its analysis sits next to the deterministic plan (fake LLM in the rig)."""
    close_ts = session_bounds(rig.close_day)[1]
    run = await rig.svc.analyze("TEST", as_of_ms=close_ts, wait=True)          # with_vision defaults on
    assert run["mode"] == "plan" and run["status"] == "done"
    assert [p["name"] for p in run["result"]["passes"]][:3] == ["context", "pattern", "entry"]
    assert run["result"]["analysis"] is not None and run["result"]["plan"]["validTriggers"] >= 1
    assert run["config"]["planMode"]["withVision"] is True


async def test_deterministic_plan_needs_no_api_key(rig):
    rig.eng.config.anthropic_api_key = ""          # no model available
    rig.svc._client = None
    close_ts = session_bounds(rig.close_day)[1]
    run = await rig.svc.analyze("TEST", as_of_ms=close_ts, wait=True)         # default vision -> falls back
    assert run["status"] == "done" and run["mode"] == "plan" and run["result"]["plan"]["planFor"]
    assert run["result"]["passes"] == [] and run["config"]["planMode"]["withVision"] is False
    # but a live/full run still fails closed without a key
    with pytest.raises(RuntimeError):
        await rig.svc.analyze("TEST", as_of_ms=None, wait=True)
    # and so does a vision-backed plan
    with pytest.raises(RuntimeError):
        await rig.svc.analyze("TEST", as_of_ms=close_ts, with_vision=True, wait=True)


# --- 2026-08-26 review fixes -------------------------------------------------------------------------

def _prior_profile(d):
    return build_profile([Bar(symbol="T", tf="1m", ts=_ms(d - dt.timedelta(days=1), 9, 30) + i * MIN, open=100,
                              high=100.1, low=99.9, close=100, volume=1000) for i in range(390)])


def test_tracker_gap_rules_need_the_opening_bar():
    """A1 — the open-gap rules are judged on the 09:30 bar only. When the first bar the
    tracker sees is later (late start / restart: 08-26 the app came up at 09:50 and 22
    triggers were 'gap-voided' against the 09:50 bar) the gap is unknowable: the trigger
    runs without the gap rules and records `gap_unchecked` instead of voiding."""
    d = weekdays(1)[0]
    tg = _bounce_trigger()
    prof = _prior_profile(d)
    late = TriggerTracker(tg, DEFAULT_THRESHOLDS, prof, True, True, prev_close=102.0)
    # 09:50 print far from the previous close: NOT a gap decision
    assert late.on_bar(_bar(d, 9, 50, 103.5, 103.6, 103.4, 103.5), 0) == "waiting"
    assert late.gap_unchecked and any(e["event"] == "gap_unchecked" for e in late.events)
    # ... and the trigger is alive: a prime-window touch fires normally
    assert late.on_bar(_bar(d, 9, 51, 100.2, 100.3, 99.95, 100.1), 1) == "fired"
    # the 09:30 bar itself still carries the gap decision
    on_time = TriggerTracker(tg, DEFAULT_THRESHOLDS, prof, True, True, prev_close=102.0)
    assert on_time.on_bar(_bar(d, 9, 30, 103.5, 103.6, 103.4, 103.5), 0) == "gap_void"


def test_tracker_never_enters_on_unknown_volume():
    """A6 — one R3.1 policy: no baseline / no volume on the bar = no entry (the trigger
    stays alive and is re-judged next bar)."""
    d = weekdays(1)[0]
    tg = _bounce_trigger()
    tr = TriggerTracker(tg, DEFAULT_THRESHOLDS, None, True, True, prev_close=100.5)
    assert tr.on_bar(_bar(d, 9, 31, 100.2, 100.3, 99.95, 100.1, v=0), 0) == "waiting"
    assert tr.skipped and "volume unknown" in tr.skipped[-1]["reason"]
    # a baseline arrives (profile) -> the next touch fires
    tr.profile = _prior_profile(d)
    assert tr.on_bar(_bar(d, 9, 32, 100.1, 100.2, 99.95, 100.1, v=900), 1) == "fired"


def test_tracker_exhausts_a_level_after_two_false_breaks():
    """A10 / R3.2 — a level that failed to hold two breaks is done for the session."""
    d = weekdays(1)[0]
    tg = {"id": "k1", "kind": "breakout", "setupType": "breakout", "valid": True,
          "entry": {"price": 104.0, "basis": "on_break"}, "stop": {"price": 103.5},
          "targets": [{"price": 105.0}, {"price": 106.0}, {"price": 107.0}], "levelPrice": 104.0, "riskReward": 6.0}
    prof = _prior_profile(d)
    tr = TriggerTracker(tg, DEFAULT_THRESHOLDS, prof, True, True, prev_close=103.8)
    i = 0
    def feed(o, h, l, c, v=1000):
        nonlocal i
        st = tr.on_bar(_bar(d, 9, 31 + i, o, h, l, c, v=v), i)
        i += 1
        return st
    feed(103.8, 103.9, 103.7, 103.8)
    for attempt in range(2):
        # decisive close through on 2x volume, then three bars back below the level
        feed(103.9, 104.6, 103.9, 104.55, v=2500)
        for _ in range(3):
            feed(104.3, 104.4, 103.6, 103.7)
        feed(103.7, 103.8, 103.6, 103.7)
        if attempt == 0:
            assert tr.status == "waiting" and tr.failed_breaks == 1
    assert tr.status == "exhausted" and tr.failed_breaks == 2
    assert any("R3.2" in s["reason"] for s in tr.skipped)
    # terminal: a later clean break is ignored
    feed(103.9, 104.6, 103.9, 104.55, v=2500)
    assert tr.status == "exhausted"


def test_rr_gate_target_resolves_to_the_exit_rung():
    """A5 — R2 is measured where the position actually exits: one options contract
    leaves at TP2, so `auto` = TP2; shares or 3+ contracts keep the book's TP3."""
    from zargar.technique.rulebook import rr_gate_target_from_settings
    base = {"technique.rr_gate_target": "auto", "technique.arm.instrument": "options",
            "technique.arm.contracts": 1, "technique.arm.single_contract_exit": "tp2"}
    get = lambda k, dflt=None: base.get(k, dflt)
    assert rr_gate_target_from_settings(get) == 1
    base["technique.arm.contracts"] = 3
    assert rr_gate_target_from_settings(get) == 2
    base.update({"technique.arm.contracts": 1, "technique.arm.instrument": "shares"})
    assert rr_gate_target_from_settings(get) == 2
    base["technique.rr_gate_target"] = "tp1"
    assert rr_gate_target_from_settings(get) == 0


# --- short side (Q10 lifted, 2026-08-26) --------------------------------------------------------

def _reject_trigger(entry=100.0, stop=100.5, targets=(98.4, 97.0, 96.0)):
    return {"id": "r1", "kind": "reject", "direction": "short", "setupType": "resistance_reject", "valid": True,
            "entry": {"price": entry, "basis": "at_level"}, "stop": {"price": stop},
            "targets": [{"price": t} for t in targets], "levelPrice": entry, "riskReward": 8.0}


def test_tracker_reject_mirrors_the_bounce():
    d = weekdays(1)[0]
    prof = _prior_profile(d)
    tg = _reject_trigger()
    # gap rules mirrored: open above the stop = gapped through; open at/above entry = gapped past
    assert TriggerTracker(tg, DEFAULT_THRESHOLDS, prof, True, True, prev_close=99.8) \
        .on_bar(_bar(d, 9, 30, 100.8, 100.9, 100.7, 100.8), 0) == "gapped_through"
    assert TriggerTracker(tg, DEFAULT_THRESHOLDS, prof, True, True, prev_close=99.8) \
        .on_bar(_bar(d, 9, 30, 100.2, 100.3, 100.1, 100.2), 0) == "gapped_past"
    # a touch from below inside a prime window fires; the fill is the level
    tr = TriggerTracker(tg, DEFAULT_THRESHOLDS, prof, True, True, prev_close=99.6)
    assert tr.on_bar(_bar(d, 9, 30, 99.6, 99.7, 99.5, 99.6), 0) == "waiting"
    assert tr.on_bar(_bar(d, 9, 31, 99.7, 100.05, 99.6, 99.9), 1) == "fired"
    assert tr.fill_price == 100.0 and tr.direction == "short"


def test_tracker_breakdown_needs_confirmation_below():
    d = weekdays(1)[0]
    prof = _prior_profile(d)
    tg = {"id": "d1", "kind": "breakdown", "direction": "short", "setupType": "breakdown", "valid": True,
          "entry": {"price": 96.0, "basis": "on_break"}, "stop": {"price": 96.5},
          "targets": [{"price": 95.0}, {"price": 94.0}, {"price": 93.0}], "levelPrice": 96.0, "riskReward": 6.0}
    tr = TriggerTracker(tg, DEFAULT_THRESHOLDS, prof, True, True, prev_close=96.2)
    i = 0
    def feed(o, h, l, c, v=1000):
        nonlocal i
        st = tr.on_bar(_bar(d, 9, 31 + i, o, h, l, c, v=v), i)
        i += 1
        return st
    feed(96.2, 96.3, 96.1, 96.2)
    feed(96.1, 96.1, 95.4, 95.45, v=2500)                 # decisive bearish close through on volume
    assert tr.status == "waiting" and tr._break_index is not None
    for _ in range(3):
        feed(95.4, 95.5, 95.0, 95.1)                      # holds below, continues down
    assert tr.status == "fired" and tr.fill_price == 95.1


def test_simulate_plan_short_mirrors_long():
    from zargar.technique.outcome import simulate_plan
    def mk(ts, o, h, l, c):
        return Bar(symbol="T", tf="1m", ts=ts, open=o, high=h, low=l, close=c, volume=1)
    plan = {"setupType": "resistance_reject", "direction": "short", "entry": {"price": 100.0, "basis": "at_level"},
            "stop": {"price": 101.0}, "targets": [{"price": 99.0}, {"price": 98.0}, {"price": 97.0}]}
    bars = [mk(0, 99.5, 99.6, 99.4, 99.5), mk(1, 99.7, 100.1, 99.6, 99.9),          # fills at 100 (high >= entry)
            mk(2, 99.9, 100.0, 98.8, 98.9), mk(3, 98.9, 99.0, 97.7, 97.8), mk(4, 97.8, 97.9, 96.6, 96.7)]
    r = simulate_plan(bars, 0, plan, entry_window=3, horizon=10)
    assert r["filled"] and r["fillIndex"] == 1 and r["outcome"] == "tp3" and r["rMultiple"] > 1.5
    stopped = bars[:2] + [mk(2, 99.9, 101.2, 99.8, 101.2)]      # closes through the stop (high below the 0.25R brake)
    r = simulate_plan(stopped, 0, plan, entry_window=3, horizon=10)
    assert r["outcome"] == "stopped" and r["rMultiple"] == pytest.approx(-1.2)


async def test_plan_builds_short_triggers_when_not_long_only(rig):
    await rig.eng.settings.set("technique.long_only", False, journal=False)
    close_ts = session_bounds(rig.close_day)[1]
    run = await rig.svc.analyze("TEST", as_of_ms=close_ts, with_vision=False, wait=True)
    trig = run["result"]["plan"]["triggers"]
    kinds = {t["kind"] for t in trig}
    assert {"bounce", "breakout"} <= kinds
    shorts = [t for t in trig if t["direction"] == "short"]
    assert shorts and all(t["kind"] in ("reject", "breakdown") for t in shorts)
    for t in shorts:
        assert t["stop"]["price"] > t["entry"]["price"] and all(x["price"] < t["entry"]["price"] for x in t["targets"])
    await rig.eng.settings.set("technique.long_only", True, journal=False)
    run2 = await rig.svc.analyze("TEST", as_of_ms=close_ts, with_vision=False, wait=True)
    assert all(t["direction"] == "long" for t in run2["result"]["plan"]["triggers"])
