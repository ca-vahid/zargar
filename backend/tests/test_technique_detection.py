"""Deterministic technique primitives: levels, volume, candle geometry.

These are pure functions over Bar lists — no DB, no engine. Bars are built by
hand so each test asserts against a shape we constructed deliberately.
"""
from __future__ import annotations

from datetime import datetime, timezone

from zargar.domain import Bar
from zargar.technique.candles import classify, is_decisive, metrics
from zargar.technique.levels import atr, detect_levels, find_pivots
from zargar.technique.rulebook import RULES, Thresholds, rule
from zargar.technique.volume import (
    assess_volume,
    build_profile,
    price_trend,
    relative_volume,
    volume_trend,
)

MIN = 60_000


def ts_at(day: str, hh: int, mm: int) -> int:
    dt = datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def bar(ts: int, o: float, h: float, l: float, c: float, v: int = 1000,
        sym: str = "TEST", tf: str = "1m") -> Bar:
    return Bar(symbol=sym, tf=tf, ts=ts, open=o, high=h, low=l, close=c, volume=v)


def zigzag(start_ts: int, pattern: list[tuple[float, float]], vol: int = 1000) -> list[Bar]:
    """Build bars from (low, high) pairs, one bar per minute."""
    out = []
    for i, (lo, hi) in enumerate(pattern):
        out.append(bar(start_ts + i * MIN, o=(lo + hi) / 2, h=hi, l=lo,
                       c=(lo + hi) / 2, v=vol))
    return out


# --- rulebook -------------------------------------------------------------

def test_rule_ids_resolve():
    assert rule("T1.2").startswith("A level needs")
    assert "T3.3d" in RULES and "R2" in RULES


def test_unknown_rule_id_raises():
    try:
        rule("T9.9")
    except KeyError:
        return
    raise AssertionError("unknown rule id should raise")


# --- pivots & levels ------------------------------------------------------

def test_find_pivots_marks_local_extremes():
    t0 = ts_at("2026-08-18", 14, 0)
    # A clean up-down-up shape: index 3 is a peak, index 7 a trough.
    lows = [10, 11, 12, 13, 12, 11, 10, 9, 10, 11, 12]
    bars = [bar(t0 + i * MIN, o=v, h=v + 0.5, l=v - 0.5, c=v) for i, v in enumerate(lows)]
    pivots = find_pivots(bars, window=3)
    highs = [p for p in pivots if p.kind == "high"]
    troughs = [p for p in pivots if p.kind == "low"]
    assert any(p.index == 3 for p in highs)
    assert any(p.index == 7 for p in troughs)


def test_find_pivots_needs_enough_bars():
    t0 = ts_at("2026-08-18", 14, 0)
    assert find_pivots([bar(t0, 1, 1, 1, 1)], window=3) == []


def test_detect_levels_finds_twice_touched_support():
    """Price dips to 100.0 three separate times — that is a support level."""
    t0 = ts_at("2026-08-18", 14, 0)
    pattern = []
    for _ in range(3):
        pattern += [(100.0, 100.4), (100.6, 101.4), (101.0, 102.0),
                    (100.6, 101.4), (100.0, 100.4)]
    bars = zigzag(t0, pattern)
    levels = detect_levels(bars, timeframe="1m")
    supports = [lv for lv in levels if lv.kind == "support"]
    assert supports, "expected at least one support level"
    near = [lv for lv in supports if abs(lv.price - 100.0) < 0.35]
    assert near, f"no support near 100.0; got {[round(l.price, 2) for l in supports]}"
    assert near[0].touches >= 2


def test_detect_levels_respects_min_touches():
    """A single dip is not a level."""
    t0 = ts_at("2026-08-18", 14, 0)
    bars = zigzag(t0, [(105.0, 105.5)] * 4 + [(100.0, 100.5)] + [(105.0, 105.5)] * 4)
    strict = Thresholds(min_touches=3)
    levels = detect_levels(bars, thresholds=strict)
    assert not [lv for lv in levels if abs(lv.price - 100.0) < 0.2]


def test_detect_levels_prioritises_prior_day_extremes():
    """T1.3a — yesterday's HOD outranks an ordinary intraday swing."""
    prior_day = ts_at("2026-08-17", 14, 0)
    today = ts_at("2026-08-18", 14, 0)
    prior = zigzag(prior_day, [(99.0, 99.5), (99.5, 103.0), (99.0, 99.5)])
    # Today revisits 103.0 twice.
    pattern = [(100.0, 100.5), (102.5, 103.0), (100.0, 100.5),
               (102.5, 103.0), (100.0, 100.5)]
    bars = zigzag(today, pattern)
    levels = detect_levels(bars, prior_session_bars=prior)
    assert levels, "expected levels"
    assert "T1.3a" in levels[0].sources, f"prior-day level should rank first: {levels[0].sources}"


def test_detect_levels_empty_for_short_input():
    assert detect_levels([]) == []


def test_level_to_dict_is_wire_shaped():
    t0 = ts_at("2026-08-18", 14, 0)
    bars = zigzag(t0, [(100.0, 100.4), (101.0, 101.5), (100.0, 100.4),
                       (101.0, 101.5), (100.0, 100.4)])
    levels = detect_levels(bars)
    assert levels
    d = levels[0].to_dict()
    assert {"price", "kind", "touches", "strong", "sources"} <= set(d)
    assert "touchTs" in d  # camelCase on the wire


def test_atr_positive_for_ranging_bars():
    t0 = ts_at("2026-08-18", 14, 0)
    bars = zigzag(t0, [(100.0, 101.0)] * 20)
    assert atr(bars) > 0


# --- volume ---------------------------------------------------------------

def test_build_profile_averages_by_minute_of_day():
    """Same clock minute across two sessions averages together."""
    b = []
    for day, vol in (("2026-08-17", 1000), ("2026-08-18", 3000)):
        b.append(bar(ts_at(day, 14, 30), 100, 101, 99, 100, v=vol))
    prof = build_profile(b)
    assert prof.sessions == 2
    assert prof.baseline(ts_at("2026-08-19", 14, 30)) == 2000


def test_build_profile_can_exclude_todays_session():
    b = [
        bar(ts_at("2026-08-17", 14, 30), 100, 101, 99, 100, v=1000),
        bar(ts_at("2026-08-18", 14, 30), 100, 101, 99, 100, v=9999),
    ]
    prof = build_profile(b, exclude_session="2026-08-18")
    assert prof.baseline(ts_at("2026-08-18", 14, 30)) == 1000


def test_relative_volume_against_baseline():
    prof = build_profile([bar(ts_at("2026-08-17", 14, 30), 100, 101, 99, 100, v=1000)])
    hot = bar(ts_at("2026-08-18", 14, 30), 100, 101, 99, 100, v=2500)
    assert relative_volume(hot, prof) == 2.5


def test_volume_and_price_trend_detection():
    t0 = ts_at("2026-08-18", 14, 0)
    rising = [bar(t0 + i * MIN, 100 + i, 101 + i, 99 + i, 100.5 + i, v=100 * (i + 1))
              for i in range(9)]
    assert volume_trend(rising) == "rising"
    assert price_trend(rising) == "rising"
    falling_vol = [bar(t0 + i * MIN, 100 + i, 101 + i, 99 + i, 100.5 + i,
                       v=1000 - 100 * i) for i in range(9)]
    assert volume_trend(falling_vol) == "falling"


def test_assess_volume_flags_bearish_divergence():
    """T2.2 — price making ground on shrinking volume."""
    t0 = ts_at("2026-08-18", 14, 0)
    bars = [bar(t0 + i * MIN, 100 + i, 101 + i, 99 + i, 100.8 + i, v=1000 - 100 * i)
            for i in range(9)]
    prof = build_profile(bars, exclude_session="2026-08-18")
    prof.overall = 800.0   # give it a baseline to measure against
    a = assess_volume(bars, prof)
    assert "T2.2" in a.rules
    assert a.price_trend == "rising" and a.trend == "falling"


def test_assess_volume_flags_no_trade_floor():
    """R3.1 — volume below half the baseline means stand aside."""
    t0 = ts_at("2026-08-18", 14, 0)
    bars = [bar(t0 + i * MIN, 100, 100.2, 99.8, 100, v=100) for i in range(9)]
    prof = build_profile([bar(ts_at("2026-08-17", 14, i), 100, 101, 99, 100, v=1000)
                          for i in range(9)])
    a = assess_volume(bars, prof)
    assert a.below_floor and "R3.1" in a.rules


def test_assess_volume_detects_spike():
    t0 = ts_at("2026-08-18", 14, 0)
    bars = [bar(t0 + i * MIN, 100, 101, 99, 100, v=1000) for i in range(8)]
    bars.append(bar(t0 + 8 * MIN, 100, 103, 99, 102.8, v=5000))
    prof = build_profile([bar(ts_at("2026-08-17", 14, i), 100, 101, 99, 100, v=1000)
                          for i in range(9)])
    a = assess_volume(bars, prof)
    assert a.is_spike and "T2.4" in a.rules


def test_assess_volume_skips_forming_zero_volume_bar():
    """Live feeds append a partial bar with 0 volume; it must not be the reference."""
    t0 = ts_at("2026-08-18", 14, 0)
    bars = [bar(t0 + i * MIN, 100, 101, 99, 100, v=3000) for i in range(8)]
    bars.append(bar(t0 + 8 * MIN, 100, 101, 99, 100, v=0))   # forming
    prof = build_profile([bar(ts_at("2026-08-17", 14, i), 100, 101, 99, 100, v=1000)
                          for i in range(9)])
    a = assess_volume(bars, prof)
    assert a.skipped_forming
    assert a.measurable and a.relative == 3.0     # measured the last real bar
    assert a.is_spike


def test_assess_volume_reports_unmeasurable_without_baseline():
    """No baseline must read as 'cannot confirm', not as a quiet zero."""
    t0 = ts_at("2026-08-18", 14, 0)
    bars = [bar(t0 + i * MIN, 100, 101, 99, 100, v=1000) for i in range(5)]
    a = assess_volume(bars, build_profile([]))
    assert not a.measurable
    assert not a.is_spike and not a.below_floor


def test_assess_volume_all_zero_volume_is_unmeasurable():
    t0 = ts_at("2026-08-18", 14, 0)
    bars = [bar(t0 + i * MIN, 100, 101, 99, 100, v=0) for i in range(5)]
    a = assess_volume(bars, build_profile([]))
    assert not a.measurable and a.relative == 0.0


def test_nearest_level_respects_side():
    from zargar.technique.levels import Level, nearest_level
    def lv(p, k):
        return Level(price=p, kind=k, touches=3)
    pool = [lv(95.0, "resistance"), lv(105.0, "resistance"), lv(90.0, "support")]
    # Without a side filter the 95 resistance is nearer to 100 - but it is below,
    # so it is useless as an upside target.
    assert nearest_level(pool, 100.0, "resistance").price == 95.0
    assert nearest_level(pool, 100.0, "resistance", side="above").price == 105.0
    assert nearest_level(pool, 100.0, "support", side="below").price == 90.0
    assert nearest_level(pool, 100.0, "support", side="above") is None


def test_assess_volume_handles_empty():
    a = assess_volume([], build_profile([]))
    assert a.relative == 0.0 and a.trend == "flat"


# --- candles --------------------------------------------------------------

def test_metrics_geometry():
    b = bar(0, o=100, h=110, l=98, c=108)
    m = metrics(b)
    assert m.bullish
    assert m.range_ == 12
    assert m.body == 8
    assert abs(m.body_ratio - 8 / 12) < 1e-9
    assert abs(m.upper_wick_ratio - 2 / 12) < 1e-9
    assert abs(m.lower_wick_ratio - 2 / 12) < 1e-9


def test_metrics_zero_range_is_safe():
    m = metrics(bar(0, 100, 100, 100, 100))
    assert m.range_ == 0 and m.body_ratio == 0


def test_is_decisive_accepts_large_clean_breakout_candle():
    """T3.3b — big solid body, closing near the high."""
    recent = [bar(i * MIN, 100, 100.5, 99.5, 100.1) for i in range(20)]
    breakout = bar(20 * MIN, o=100, h=104.2, l=99.9, c=104.0)
    ok, reasons = is_decisive(breakout, recent, direction="long")
    assert ok and "T3.3b" in reasons


def test_is_decisive_rejects_long_upper_wick():
    """A big move that gets sold into is the fakeout signature (T3.4b)."""
    recent = [bar(i * MIN, 100, 100.5, 99.5, 100.1) for i in range(20)]
    rejected = bar(20 * MIN, o=100, h=106, l=99.8, c=101.0)
    ok, reasons = is_decisive(rejected, recent, direction="long")
    assert not ok and "T3.4b" in reasons


def test_is_decisive_rejects_tiny_body():
    recent = [bar(i * MIN, 100, 102, 98, 100.1) for i in range(20)]
    doji = bar(20 * MIN, o=100, h=102, l=98, c=100.05)
    ok, reasons = is_decisive(doji, recent, direction="long")
    assert not ok and "T3.3e" in reasons


def test_classify_hammer():
    bars = [bar(0, o=100, h=100.6, l=96, c=100.3)]
    assert "hammer" in classify(bars)


def test_classify_doji():
    bars = [bar(0, o=100, h=102, l=98, c=100.05)]
    assert "doji" in classify(bars)


def test_classify_bullish_engulfing():
    bars = [
        bar(0, o=101, h=101.2, l=100, c=100.2),      # red
        bar(MIN, o=100.0, h=102.0, l=99.8, c=101.5),  # green, engulfs
    ]
    assert "bullish_engulfing" in classify(bars)


def test_classify_close_position_labels():
    assert "closed_near_high" in classify([bar(0, o=100, h=101, l=99.8, c=100.95)])
    assert "closed_near_low" in classify([bar(0, o=101, h=101.2, l=100, c=100.05)])


def test_classify_out_of_range_index_is_safe():
    assert classify([], 0) == []
    assert classify([bar(0, 100, 101, 99, 100)], 5) == []


def test_touch_requires_the_extreme_to_test_the_level_without_closing_through():
    """A3 (2026-08-26) — a bar that blows straight through a level is a break, not a
    touch; before the fix support and resistance used the same band-overlap test and
    counted it, inflating every touch count the grades rest on."""
    from zargar.technique.levels import _count_touches
    t0 = ts_at("2026-08-18", 14, 0)
    tol = 0.15
    # two real tests of 100.0 support (low reaches the band, close holds above) ...
    tests = [bar(t0, 100.5, 100.6, 100.05, 100.4), bar(t0 + MIN, 100.6, 100.8, 100.5, 100.7),
             bar(t0 + 2 * MIN, 100.4, 100.5, 99.95, 100.3)]
    assert len(_count_touches(tests, 100.0, tol, "support")) == 2
    # ... and a bar that opens above and closes well below is NOT a touch
    smash = [bar(t0 + 3 * MIN, 100.6, 100.7, 99.0, 99.1)]
    assert _count_touches(smash, 100.0, tol, "support") == []
    # resistance mirrors it: the high must reach the band and the close must stay under
    assert len(_count_touches([bar(t0, 99.5, 100.05, 99.4, 99.6)], 100.0, tol, "resistance")) == 1
    assert _count_touches([bar(t0, 99.5, 101.0, 99.4, 100.9)], 100.0, tol, "resistance") == []


def test_yahoo_symbol_maps_share_classes_but_not_exchanges():
    from zargar.brokers.yahoo import yahoo_symbol
    assert yahoo_symbol("BRK.B") == "BRK-B" and yahoo_symbol("bf.b") == "BF-B"
    assert yahoo_symbol("SHOP.TO") == "SHOP.TO" and yahoo_symbol("XYZ.V") == "XYZ.V" and yahoo_symbol("AAPL") == "AAPL"
