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
    plan_entry_window_bars: int = 12
    max_false_breaks: int = 2
    stop_on_close: bool = True
    # the windows an entry may fire in (a technique with no schedule rule passes SESSION_WINDOWS)
    windows: tuple[str, ...] = PRIME_WINDOWS


TriggerRules = MarketRules
DEFAULT_MARKET_RULES = MarketRules()
DEFAULT_TRIGGER_RULES = DEFAULT_MARKET_RULES
