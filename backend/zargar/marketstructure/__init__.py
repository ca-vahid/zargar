"""Shared market-structure library — pure functions over bars, for every technique.

Levels and touches, distance to a level, volume vs its time-of-day baseline,
candle geometry, trendlines/wedges, the session clock, the trigger-tracking
state machine and the forward walk that scores a plan. No I/O except
`history` (bars fetch), no settings reads: a technique passes a `MarketRules`.
See docs/TECHNIQUE-PLATFORM-PLAN.md §2.2.
"""
from .aggregate import aggregate, bar_session, bucket_start_ms, closed_bars, filter_session
from .candles import CandleMetrics, classify, is_decisive, metrics
from .dailylevels import Zone, premarket_range, prior_day_zones, session_extremes
from .indicators import EmaState, StackRead, ema_series, ema_stack, fan_state, fan_width
from .levels import Level, Pivot, atr, detect_levels, find_pivots, nearest_level, session_key
from .market_calendar import (
    is_early_close, is_trading_day, next_trading_day, previous_trading_day, session_close_minutes, trading_days,
)
from .outcome import simulate_plan
from .rules import (
    ALL_WINDOWS, DEFAULT_LADDER, DEFAULT_MARKET_RULES, DEFAULT_RUNNER_PCT, DEFAULT_TRIGGER_RULES, SESSION_WINDOWS,
    MarketRules, TriggerRules,
)
from .sessions import ET, PRIME_WINDOWS, is_prime, next_session_date, session_bounds, session_date, session_window
from .structure import detect_wedge, fit_line, read_trend
from .tracker import TriggerTracker, level_respect, score_trigger
from .volume import VolumeProfile, assess_volume, build_profile, relative_volume


def distance_pct(price: float, level: float) -> float:
    """Signed distance from `price` to `level`, in percent of price (+ = level above)."""
    return (float(level) - float(price)) / float(price) * 100.0 if price else 0.0


def count_touches(bars, price: float, tolerance: float, kind: str = "support") -> int:
    """In-band touches of `price` (± `tolerance`, absolute): the extreme reaches the
    band and the close holds the right side — the semantics the level detector uses."""
    from .levels import _count_touches
    return len(_count_touches(bars, price, tolerance, kind))


__all__ = [
    "CandleMetrics", "classify", "is_decisive", "metrics", "Level", "Pivot", "atr", "detect_levels", "find_pivots",
    "nearest_level", "session_key", "simulate_plan", "ALL_WINDOWS", "DEFAULT_LADDER", "DEFAULT_MARKET_RULES",
    "DEFAULT_RUNNER_PCT", "DEFAULT_TRIGGER_RULES", "SESSION_WINDOWS", "MarketRules", "TriggerRules", "ET",
    "PRIME_WINDOWS", "is_prime", "next_session_date", "session_bounds", "session_date", "session_window",
    "detect_wedge", "fit_line", "read_trend", "TriggerTracker", "level_respect", "score_trigger", "VolumeProfile",
    "assess_volume", "build_profile", "relative_volume", "distance_pct", "count_touches",
    # 2026-09-03 (Team2 desk): aggregation + extended-hours clock, EMA indicators, daily zones, market calendar
    "aggregate", "bar_session", "bucket_start_ms", "closed_bars", "filter_session",
    "Zone", "premarket_range", "prior_day_zones", "session_extremes",
    "EmaState", "StackRead", "ema_series", "ema_stack", "fan_state", "fan_width",
    "is_early_close", "is_trading_day", "next_trading_day", "previous_trading_day", "session_close_minutes",
    "trading_days",
]
