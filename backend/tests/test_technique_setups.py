"""Structure, wedge geometry, and setup arithmetic.

Covers the breakout/fakeout discriminator (T3.3) and the two setup types from
spec §8 — the resolution of the book's own entry-timing contradiction.
"""
from __future__ import annotations

from zargar.domain import Bar
from zargar.technique.levels import Level
from zargar.technique.setups import (
    bounce_stop,
    build_bounce_setup,
    build_breakout_setup,
    build_ladder,
    classify_breakout,
    invalidation_low,
    risk_reward,
    stop_buffer,
)
from zargar.technique.structure import detect_wedge, fit_line, read_trend
from zargar.technique.volume import VolumeAssessment

MIN = 60_000


def bar(i: int, o: float, h: float, l: float, c: float, v: int = 1000) -> Bar:
    return Bar(symbol="TEST", tf="1m", ts=i * MIN, open=o, high=h, low=l, close=c, volume=v)


def leg(bars: list[Bar], idx: int, a: float, b: float, n: int = 5, vol: int = 1000) -> int:
    """Append `n` bars walking price from a to b. Real swings span several bars —
    compressed fixtures lose pivots to ties at the default pivot window."""
    for k in range(n):
        p = a + (b - a) * ((k + 1) / n)
        bars.append(bar(idx + k, o=p, h=p + 0.3, l=p - 0.3, c=p, v=vol))
    return idx + n


def swings(points: list[float], *, vol: int = 1000, decay: float = 1.0,
           per_leg: int = 5) -> list[Bar]:
    """Bars tracing a zig-zag through `points`, one leg per pair."""
    bars: list[Bar] = []
    idx = 0
    v = vol
    for a, b in zip(points, points[1:]):
        idx = leg(bars, idx, a, b, per_leg, v)
        v = int(v * decay)
    return bars


def vol_assess(*, spike=False, dryup=False, floor=False, trend="flat",
               ptrend="flat", rel=1.0) -> VolumeAssessment:
    return VolumeAssessment(
        relative=rel, trend=trend, price_trend=ptrend,
        is_spike=spike, is_dryup=dryup, below_floor=floor,
        rules=["T2.9"], note="",
    )


def level(price: float, kind="support", touches=3, sources=None) -> Level:
    return Level(price=price, kind=kind, touches=touches,
                 sources=sources or ["T1.3c"], touch_ts=[0] * touches)


# --- trendline fitting ----------------------------------------------------

def test_fit_line_recovers_known_slope():
    line = fit_line([(0, 100.0), (10, 110.0), (20, 120.0)])
    assert line is not None
    assert abs(line.slope - 1.0) < 1e-9
    assert abs(line.at(30) - 130.0) < 1e-6


def test_fit_line_needs_two_points():
    assert fit_line([(0, 100.0)]) is None


# --- trend reading --------------------------------------------------------

def test_read_trend_detects_uptrend():
    """Higher highs and higher lows (T3.5a)."""
    # Higher highs (13, 16, 19) and higher lows (10, 12, 14).
    bars = swings([8, 13, 10, 16, 12, 19, 14, 21])
    t = read_trend(bars)
    assert t.direction == "uptrend"
    assert "T3.5a" in t.rules


def test_read_trend_detects_downtrend():
    # Lower highs (19, 16, 13) and lower lows (14, 12, 10).
    bars = swings([21, 19, 14, 16, 12, 13, 10, 11])
    t = read_trend(bars)
    assert t.direction == "downtrend"
    assert "T3.5b" in t.rules


def test_read_trend_sideways_when_mixed():
    bars = swings([10, 12, 10, 12, 10, 12, 10, 12])
    assert read_trend(bars).direction == "sideways"


# --- wedge detection ------------------------------------------------------

def _falling_wedge_bars() -> list[Bar]:
    """A true falling wedge: BOTH lines fall, the upper one faster (T3.1a/b).

    Highs 110 -> 102.5 (steep), lows 100 -> 99.0 (shallow), so the lines converge
    while both slope down. Volume decays each swing to satisfy T3.1c.
    """
    bars: list[Bar] = []
    idx = 0
    vol = 4000
    highs = [110.0, 107.0, 104.5, 102.5]
    lows = [100.0, 99.5, 99.2, 99.0]
    prev = highs[0]
    for h, l in zip(highs, lows):
        idx = leg(bars, idx, prev, h, 5, vol)
        idx = leg(bars, idx, h, l, 5, vol)
        prev = l
        vol = int(vol * 0.75)
    return bars


def test_detect_wedge_finds_converging_falling_wedge():
    w = detect_wedge(_falling_wedge_bars())
    assert w is not None, "expected a falling wedge"
    assert "T3.1a" in w.rules and "T3.1b" in w.rules
    assert w.upper.slope < w.lower.slope < 0      # upper steeper, both falling
    assert w.widest_height > 0
    assert w.volume_declining and "T3.1c" in w.rules


def test_detect_wedge_rejects_short_window():
    bars = [bar(i, 100, 101, 99, 100) for i in range(5)]
    assert detect_wedge(bars) is None


def test_detect_wedge_rejects_rising_channel():
    """An ascending shape is not a falling wedge."""
    bars = swings([100, 106, 102, 110, 106, 114, 110, 118])
    assert detect_wedge(bars) is None


def test_wedge_breakout_level_tracks_upper_line():
    w = detect_wedge(_falling_wedge_bars())
    assert w is not None
    early, late = w.breakout_level(0), w.breakout_level(20)
    assert late < early     # the break threshold falls with the wedge


# --- risk / reward --------------------------------------------------------

def test_risk_reward_basic():
    assert risk_reward(100.0, 99.0, 103.0) == 3.0


def test_risk_reward_zero_when_stop_equals_entry():
    assert risk_reward(100.0, 100.0, 110.0) == 0.0


def test_build_ladder_uses_measured_move():
    targets = build_ladder(100.0, "long", measured_move=10.0)
    assert len(targets) == 3
    assert all(t.basis == "measured_move" for t in targets)
    assert abs(targets[-1].price - 110.0) < 1e-9
    assert abs(sum(t.trim_pct for t in targets) - 0.85) < 1e-9   # 15% runner left


def test_build_ladder_falls_back_to_pct():
    targets = build_ladder(100.0, "long")
    assert [round(t.price, 2) for t in targets] == [102.0, 104.0, 106.0]
    assert all(t.basis == "pct_ladder" for t in targets)


# --- breakout vs fakeout --------------------------------------------------

def _prior_bars(n=20, price=100.0) -> list[Bar]:
    return [bar(i, o=price, h=price + 0.3, l=price - 0.3, c=price) for i in range(n)]


def test_classify_breakout_accepts_confirmed_break():
    bars = _prior_bars()
    bars.append(bar(20, o=100.1, h=104.2, l=100.0, c=104.0, v=6000))
    bars += [bar(21, 104, 105, 103.9, 104.8, 3000), bar(22, 104.8, 105.5, 104.5, 105.2, 3000)]
    v = classify_breakout(bars, level(100.5, "resistance"), 20, vol_assess(spike=True))
    assert v.is_breakout and not v.is_fakeout
    assert v.has_volume and v.is_decisive and v.has_followthrough
    assert "T3.3a" in v.rules and "T2.5" in v.rules


def test_classify_breakout_rejects_low_volume_break():
    """T3.3d — the single most reliable fakeout tell."""
    bars = _prior_bars()
    bars.append(bar(20, o=100.1, h=104.2, l=100.0, c=104.0, v=900))
    bars += [bar(21, 104, 105, 103.9, 104.8), bar(22, 104.8, 105.5, 104.5, 105.2)]
    v = classify_breakout(bars, level(100.5, "resistance"), 20, vol_assess(spike=False))
    assert v.is_fakeout and not v.has_volume
    assert "T3.3d" in v.rules and "T2.6" in v.rules
    assert any("volume" in r for r in v.reasons)


def test_classify_breakout_rejects_long_upper_wick():
    """Price pierced the level then got sold — classic fakeout (T3.3e)."""
    bars = _prior_bars()
    bars.append(bar(20, o=100.1, h=106.0, l=100.0, c=100.6, v=6000))
    bars += [bar(21, 100.6, 100.9, 100.0, 100.2), bar(22, 100.2, 100.4, 99.5, 99.8)]
    v = classify_breakout(bars, level(100.5, "resistance"), 20, vol_assess(spike=True))
    assert v.is_fakeout and not v.is_decisive


def test_classify_breakout_flags_failure_to_hold():
    """T3.3f — bull trap: broke out, then fell back through."""
    bars = _prior_bars()
    bars.append(bar(20, o=100.1, h=104.2, l=100.0, c=104.0, v=6000))
    bars += [bar(21, 104, 104.2, 100.0, 100.2), bar(22, 100.2, 100.4, 99.0, 99.2)]
    v = classify_breakout(bars, level(100.5, "resistance"), 20, vol_assess(spike=True))
    assert v.is_fakeout and not v.holds_level
    assert "T3.3f" in v.rules


def test_classify_breakout_requires_close_beyond_level():
    """Merely touching the level is not a break (T3.3b)."""
    bars = _prior_bars()
    bars.append(bar(20, o=99.8, h=100.6, l=99.5, c=100.1, v=6000))
    v = classify_breakout(bars, level(100.5, "resistance"), 20, vol_assess(spike=True))
    assert v.is_fakeout
    assert any("close" in r for r in v.reasons)


def test_classify_breakout_handles_bad_index():
    v = classify_breakout([], level(100.0), 0, vol_assess())
    assert v.is_fakeout and "T3.3d" in v.rules


def test_classify_breakout_fails_when_price_fades_back_below_by_the_last_bar():
    """A break can pass its follow-through window and STILL be dead if price has
    since faded back through the level (COP 2026-08-21: 'holds=True' while the
    close sat below the level)."""
    bars = _prior_bars()
    bars.append(bar(20, o=100.1, h=104.2, l=100.0, c=104.0, v=6000))       # confirmed break
    bars += [bar(21, 104, 105, 103.9, 104.8, 3000), bar(22, 104.8, 105.5, 104.5, 105.2, 3000),
             bar(23, 105.2, 105.4, 104.9, 105.0, 2000)]                    # follow-through window holds
    bars += [bar(24, 105.0, 105.1, 100.0, 100.2), bar(25, 100.2, 100.4, 99.6, 99.8)]  # then the fade
    v = classify_breakout(bars, level(100.5, "resistance"), 20, vol_assess(spike=True))
    assert v.is_fakeout and not v.holds_level
    assert any("back below the level at the last close" in r for r in v.reasons)


# --- setup construction ---------------------------------------------------

def test_bounce_setup_enters_at_the_level():
    """Setup A — T4.1/T4.2: entry is the level itself, no confirmation."""
    bars = _prior_bars()
    s = build_bounce_setup("TEST", bars, level(100.0), vol_assess(dryup=True),
                           next_resistance=level(112.0, "resistance"))
    assert s.setup_type == "support_bounce"
    assert s.entry == 100.0
    assert s.entry_basis == "at_level"
    assert s.requires_confirmation is False
    assert s.stop < s.entry
    assert s.stop_kind == "mental"
    assert "T4.2" in s.rules


def test_bounce_setup_rejects_poor_risk_reward():
    """R2 — a level with resistance right above it is not tradeable."""
    bars = _prior_bars()
    s = build_bounce_setup("TEST", bars, level(100.0), vol_assess(),
                           next_resistance=level(100.4, "resistance"))
    assert not s.valid
    assert any("R2" in r for r in s.no_trade_reasons)


def test_bounce_setup_rejects_low_volume():
    bars = _prior_bars()
    s = build_bounce_setup("TEST", bars, level(100.0), vol_assess(floor=True),
                           next_resistance=level(120.0, "resistance"))
    assert not s.valid
    assert any("R3.1" in r for r in s.no_trade_reasons)


def test_bounce_setup_targets_sum_to_ladder():
    bars = _prior_bars()
    s = build_bounce_setup("TEST", bars, level(100.0), vol_assess(),
                           next_resistance=level(120.0, "resistance"))
    assert len(s.targets) == 3
    assert abs(sum(t.trim_pct for t in s.targets) + s.runner_pct - 1.0) < 1e-9


def test_bounce_stop_goes_below_the_invalidating_low():
    """T4.3d — with recent prints below the level, the stop clears them; a
    pristine level falls back to the book's buffer-below-the-level; prints
    deeper than the stop cap belong to another regime and are ignored."""
    bars = _prior_bars()                                   # lows at 99.7 under a 100 level
    inv = invalidation_low(bars, 100.0)
    assert inv == 99.7
    s = bounce_stop(100.0, invalidation=inv)
    assert s < 99.7 and abs((99.7 - s) - 99.7 * 0.005) < 1e-6   # buffer clears the ANCHOR
    assert invalidation_low([bar(0, 101, 101.3, 100.4, 101)], 100.0) is None
    assert invalidation_low([bar(0, 95, 95.3, 94.7, 95)], 100.0) is None


def test_bounce_setup_stop_references_the_invalidating_low():
    bars = _prior_bars()
    s = build_bounce_setup("TEST", bars, level(100.0), vol_assess(),
                           next_resistance=level(112.0, "resistance"))
    assert s.stop_reference == "below_invalidation_low"
    assert s.stop < 99.7


def test_bounce_setup_rejects_stop_wider_than_cap():
    """T4.3a/R1 — when the chart's invalidation is too far away, it's a no-trade,
    not a tighter arbitrary stop."""
    bars = _prior_bars() + [bar(20, 100.2, 100.4, 97.2, 100.1)]
    s = build_bounce_setup("TEST", bars, level(100.0), vol_assess(),
                           next_resistance=level(120.0, "resistance"))
    assert s.stop < 97.2
    assert not s.valid and any("T4.3a" in r for r in s.no_trade_reasons)


def test_bounce_setup_rejects_stop_inside_chop():
    """R3.2 — sideways trigger-tf trend + a stop under 2x its ATR = a noise stop."""
    bars = [bar(i, 100.4, 100.6, 100.2, 100.4) for i in range(20)]   # never below the level
    s = build_bounce_setup("TEST", bars, level(100.0), vol_assess(),
                           next_resistance=level(120.0, "resistance"),
                           atr_value=1.0, trend_direction="sideways")
    assert any("R3.2" in r for r in s.no_trade_reasons)
    s2 = build_bounce_setup("TEST", bars, level(100.0), vol_assess(),
                            next_resistance=level(120.0, "resistance"),
                            atr_value=1.0, trend_direction="uptrend")
    assert not any("R3.2" in r for r in s2.no_trade_reasons)


def test_breakout_setup_requires_confirmation():
    """Setup B — the other half of the spec §8 split."""
    bars = _prior_bars()
    bars.append(bar(20, o=100.1, h=104.2, l=100.0, c=104.0, v=6000))
    bars += [bar(21, 104, 105, 103.9, 104.8), bar(22, 104.8, 105.5, 104.5, 105.2)]
    lv = level(100.5, "resistance")
    v = classify_breakout(bars, lv, 20, vol_assess(spike=True))
    s = build_breakout_setup("TEST", bars, lv, v, vol_assess(spike=True))
    assert s.requires_confirmation is True
    assert s.entry_basis == "on_break"
    assert s.setup_type == "breakout"


def test_breakout_setup_carries_fakeout_reasons():
    bars = _prior_bars()
    bars.append(bar(20, o=100.1, h=104.2, l=100.0, c=104.0, v=900))
    lv = level(100.5, "resistance")
    v = classify_breakout(bars, lv, 20, vol_assess(spike=False))
    s = build_breakout_setup("TEST", bars, lv, v, vol_assess(spike=False))
    assert not s.valid
    assert any("fakeout" in r for r in s.no_trade_reasons)


def test_wedge_setup_uses_measured_move_and_wedge_low():
    """T3.1e stop, T3.1f measured-move target."""
    bars = _falling_wedge_bars()
    w = detect_wedge(bars)
    assert w is not None
    lv = level(w.breakout_level(len(bars) - 1), "resistance")
    v = classify_breakout(bars, lv, len(bars) - 1, vol_assess(spike=True))
    s = build_breakout_setup("TEST", bars, lv, v, vol_assess(spike=True), wedge=w)
    assert s.setup_type == "falling_wedge"
    # T3.1e — under the wedge low with the same clearance every chart stop gets
    # (never a bare per-mille of price); a stop wider than the cap is refused, not tightened
    assert abs(s.stop - (w.lowest_price - stop_buffer(w.lowest_price))) < 1e-6
    assert s.stop < w.lowest_price
    if (s.entry - s.stop) / s.entry > 0.03:
        assert any(r.startswith("T4.3a/R1") for r in s.no_trade_reasons)
    assert all(t.basis == "measured_move" for t in s.targets)
    assert "T3.1f" in s.rules


def test_breakout_stop_sits_under_the_break_base_not_a_fixed_percent():
    """T4.3d — a plain breakout's stop anchors below the most recent swing low
    under the level (the base the break launches from), never `level - 0.5 %`."""
    t0 = 1_700_000_000_000
    bars = []
    # base: a pullback low at 99.0 under a 100.0 shelf, then the break
    path = [(99.9, 100.0), (99.8, 100.0), (99.6, 99.9), (99.5, 99.9), (99.0, 99.4), (99.3, 99.8),
            (99.6, 100.0), (99.7, 100.0), (99.8, 100.0), (99.9, 100.4), (100.2, 100.9)]
    for i, (lo, hi) in enumerate(path):
        bars.append(Bar(symbol="T", tf="1m", ts=t0 + i * 60_000, open=lo + 0.05, high=hi, low=lo,
                        close=hi - 0.05, volume=1000))
    lv = level(100.0, "resistance")
    v = classify_breakout(bars, lv, len(bars) - 1, vol_assess(spike=True))
    s = build_breakout_setup("T", bars, lv, v, vol_assess(spike=True))
    assert s.stop_reference == "below_break_base"
    assert abs(s.stop - (99.0 - stop_buffer(99.0))) < 1e-6
    assert abs(s.stop - (100.0 - 0.5)) > 1e-3          # not the old fixed-percent costume


def test_setup_to_dict_is_wire_shaped():
    bars = _prior_bars()
    s = build_bounce_setup("TEST", bars, level(100.0), vol_assess(),
                           next_resistance=level(120.0, "resistance"))
    d = s.to_dict()
    assert d["setupType"] == "support_bounce"
    assert set(d["entry"]) == {"price", "basis", "requiresConfirmation"}
    assert "riskReward" in d and "noTradeReasons" in d
    assert isinstance(d["targets"][0]["trimPct"], float)
