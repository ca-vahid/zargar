"""Rules — the numbers the shared market-structure library is parameterised by.

A technique builds ONE of these (EM: `rulebook.thresholds_from_settings()` returns
its superset `Thresholds`, which is duck-compatible) and passes it to the library.
The library never reads a technique's rulebook or the settings store itself.
"""
from __future__ import annotations

from dataclasses import dataclass

from .sessions import PRIME_WINDOWS

# exit ladder shares for a three-target plan (30 / 40 / 15, the rest rides)
DEFAULT_LADDER: tuple[float, ...] = (0.30, 0.40, 0.15)
DEFAULT_RUNNER_PCT = 0.15
ALL_WINDOWS: tuple[str, ...] = ("prime_open", "midday", "prime_close", "extended")
SESSION_WINDOWS: tuple[str, ...] = ("prime_open", "midday", "prime_close")


@dataclass
class MarketRules:
    """Every knob the library functions read. Field names match EM's `Thresholds`
    so the technique's superset object can be passed straight through."""
    # levels: how close counts as a touch (fraction of price / ATR multiple), touches for a level
    level_tolerance_pct: float = 0.0015
    level_tolerance_atr: float = 0.25
    min_touches: int = 2
    strong_touches: int = 3
    pivot_window: int = 3
    lookback_sessions: int = 3
    seed_window_extremes: bool = False   # also seed the window's highest high / lowest low as levels (MU 968, 2026-09-04)
    round_number_steps: tuple[float, ...] = (1.0, 5.0, 10.0, 50.0, 100.0)
    # volume vs the time-of-day baseline
    volume_spike_mult: float = 1.5
    volume_dryup_mult: float = 0.7
    volume_floor_mult: float = 0.5
    # candles
    decisive_body_ratio: float = 0.60
    decisive_size_mult: float = 1.5
    max_breakout_wick_ratio: float = 0.25
    long_wick_ratio: float = 0.5
    # breaks: follow-through N of M bars
    followthrough_bars: int = 3
    followthrough_required: int = 2
    # structure
    wedge_min_bars: int = 8
    wedge_min_touches: int = 2
    max_trendline_slope_pct: float = 0.01
    # trigger tracking
    respect_mult: float = 3.0
    gap_void_r: float = 1.0
    gap_through_continuation: bool = False   # T-13: a level the open gapped through arms a continuation break in the gap direction (SPY 2026-09-09)
    gap_continuation_confirm: bool = True    # T-13b: False = fire on the first close through the opening bar's extreme (the author's tempo), no surge/decisive/follow-through
    plan_entry_window_bars: int = 12
    max_false_breaks: int = 2
    stop_on_close: bool = True
    scratch_r: float = 0.0        # T-14: after the trade is this many R in favour, trim `scratch_trim` and move the stop to breakeven (0 = off)
    scratch_trim: float = 0.5     # fraction sold at the scratch point
    scratch_only_far_tp1: bool = False   # C4: apply the scratch rule only when TP1 sits >= far_tp1_r R away (re-planned gap-day geometry)
    far_tp1_r: float = 3.0
    gap_day_pct: float = 0.0             # C3: |open - prev close| / prev close * 100 >= this = a gap day for this symbol (0 = off)
    gap_day_wait_minutes: int = 30       # C3: on a gap day no entry fires in the first N minutes ("give the open time")
    gap_day_continuation: bool = False   # C3: on a gap day a gapped bounce/reject re-aims as a continuation break (T-13, loose)
    range_break: bool = False            # C5: a break out of a tight consolidation fires on the break close (no follow-through wait)
    range_break_bars: int = 6            # C5: the consolidation = the last N closed bars before the break
    range_break_max_range_mult: float = 1.0   # C5: their high-low span <= this x the mean bar range of the prior 20 bars
    # the windows an entry may fire in (a technique with no schedule rule passes SESSION_WINDOWS)
    windows: tuple[str, ...] = PRIME_WINDOWS


TriggerRules = MarketRules
DEFAULT_MARKET_RULES = MarketRules()
DEFAULT_TRIGGER_RULES = DEFAULT_MARKET_RULES
