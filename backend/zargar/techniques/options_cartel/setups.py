"""Measured weekly/daily Cartel candidates, with explicit uncalibrated definitions.

This produces reviewable geometry, not automatic order authority. A pattern
label never overrides a failed context, freshness or relative-strength check.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ...marketstructure.indicators import ema_series
from .data import DailyBar, complete_weeks, completed_daily, require_contiguous


class SetupParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    base_sessions: int = Field(default=10, ge=3, le=60)
    weekly_context_weeks: int = Field(default=8, ge=2, le=52)
    relative_strength_sessions: int = Field(default=20, ge=2, le=252)
    max_base_range_pct: float = Field(default=15, gt=0)
    max_weekly_range_pct: float = Field(default=50, gt=0)
    max_distance_from_extreme_pct: float = Field(default=15, ge=0)
    max_volume_ratio: float = Field(default=.8, gt=0)
    min_impulse_pct: float = Field(default=5, ge=0)
    line_flat_pct_per_bar: float = Field(default=.10, ge=0)
    touch_tolerance_pct: float = Field(default=.5, ge=0)
    triangle_min_touches: int = Field(default=3, ge=3, le=20)


def _slope(values: list[float]) -> float:
    center = (len(values)-1)/2
    mean = sum(values)/len(values)
    denom = sum((i-center)**2 for i in range(len(values)))
    return sum((i-center)*(v-mean) for i, v in enumerate(values))/denom if denom else 0


def _range(bars: list[DailyBar]) -> float:
    return (max(b.high for b in bars)-min(b.low for b in bars))/min(b.low for b in bars)*100


def _targets(history: list[DailyBar], trigger: float, direction: str, tolerance: float) -> list[float]:
    # Only already-confirmed historical pivots; no invented Fibonacci anchor.
    pivots = []
    for left, bar, right in zip(history, history[1:], history[2:]):
        if direction == "long" and bar.high > max(left.high, right.high) and bar.high > trigger:
            pivots.append(bar.high)
        elif direction == "short" and bar.low < min(left.low, right.low) and bar.low < trigger:
            pivots.append(bar.low)
    ordered = sorted(set(pivots), reverse=direction == "short")
    chosen = []
    for price in ordered:
        if not chosen or abs(price-chosen[-1])/chosen[-1]*100 > tolerance:
            chosen.append(price)
    return chosen[:3]


def analyze_setups(history: list[DailyBar], benchmark: list[DailyBar], screen: dict,
                   parameters: SetupParameters, as_of_ms: int,
                   *, direction: Literal["long", "short"] = "long") -> dict:
    if direction not in ("long", "short"):
        raise ValueError("invalid setup direction")
    bars = completed_daily(history, as_of_ms)
    index = completed_daily(benchmark, as_of_ms)
    require_contiguous(bars)
    require_contiguous(index)
    if screen.get("asOfMs") != as_of_ms or screen.get("direction") != direction:
        raise ValueError("screen must have the same as-of time and direction")
    if bars and screen.get("symbol") != bars[-1].symbol:
        raise ValueError("screen and daily history symbol mismatch")
    out = {"symbol": screen.get("symbol"), "asOfMs": as_of_ms, "direction": direction,
           "parameters": parameters.model_dump(mode="json"), "candidates": [], "checks": [],
           "sources": ["S01", "S02", "S04", "S05", "S06", "S18"],
           "definitionStatus": "Engineering pattern measurements; not calibrated author thresholds."}

    def check(name, passed, value=None):
        out["checks"].append({"name": name, "status": "unknown" if passed is None else "pass" if passed else "fail",
                              "value": value})

    check("Market/universe screen", screen.get("screenPassed") is True)
    n = parameters.base_sessions
    lookback = parameters.relative_strength_sessions
    if len(bars) < max(2*n+1, lookback+1, 50):
        check("Daily history warm-up", None, len(bars))
        return out
    check("Daily history warm-up", True, len(bars))
    weeks = complete_weeks(bars, as_of_ms)[-parameters.weekly_context_weeks:]
    check("Complete weekly history", len(weeks) == parameters.weekly_context_weeks, len(weeks))
    sign = 1 if direction == "long" else -1
    latest = bars[-1]
    if weeks:
        weekly_hi, weekly_lo = max(w["high"] for w in weeks), min(w["low"] for w in weeks)
        weekly_range = (weekly_hi-weekly_lo)/weekly_lo*100
        distance = ((weekly_hi-latest.close)/weekly_hi if sign == 1
                    else (latest.close-weekly_lo)/weekly_lo)*100
        check("Weekly base range", weekly_range <= parameters.max_weekly_range_pct, weekly_range)
        check("Near directional weekly extreme", distance <= parameters.max_distance_from_extreme_pct, distance)
    # Compare aligned dates, not equally-sized arrays that could cover different sessions.
    by_date = {b.session: b for b in index}
    start = bars[-lookback-1]
    if start.session in by_date and latest.session in by_date:
        stock_return = latest.close/start.close-1
        benchmark_return = by_date[latest.session].close/by_date[start.session].close-1
        rs = (stock_return-benchmark_return)*100
        check("Relative strength versus benchmark", rs*sign > 0, rs)
    else:
        check("Relative strength versus benchmark", None)

    base, previous = bars[-n:], bars[-2*n:-n]
    base_volume = sum(b.volume for b in base)/n
    prior_volume = sum(b.volume for b in previous)/n
    volume_ratio = base_volume/prior_volume if prior_volume > 0 else None
    check("Volume dries up in consolidation", volume_ratio <= parameters.max_volume_ratio
          if volume_ratio is not None else None, volume_ratio)
    check("Daily base tightness", _range(base) <= parameters.max_base_range_pct, _range(base))
    upper = _slope([b.high for b in base])/latest.close*100
    lower = _slope([b.low for b in base])/latest.close*100
    impulse = (previous[-1].close/previous[0].close-1)*100*sign
    tightens = _range(base[-max(2, n//2):]) < _range(base[:max(2, n//2)])
    flat = parameters.line_flat_pct_per_bar
    kinds = ["base"]
    ceiling = max(b.high for b in base)
    ceiling_touches = [i for i, b in enumerate(base)
                       if (ceiling-b.high)/ceiling*100 <= parameters.touch_tolerance_pct]
    if sign == 1 and abs(upper) <= flat and lower > flat and tightens \
            and len(ceiling_touches) >= parameters.triangle_min_touches \
            and ceiling_touches[0] <= n//3 and ceiling_touches[-1] >= 2*n//3:
        kinds.append("ascending_triangle")
    if impulse >= parameters.min_impulse_pct and (upper+lower)*sign <= 0:
        kinds.append("flag")
    if upper < -flat and lower > flat and tightens:
        kinds.append("pennant")
    if tightens and ((upper < lower < -flat and sign == 1) or (lower > upper > flat and sign == -1)):
        kinds.append("wedge")
    mother = bars[-2]
    if latest.high <= mother.high and latest.low >= mother.low \
            and (latest.high < mother.high or latest.low > mother.low):
        kinds.append("inside_day")
    ema = {p: ema_series([b.close for b in bars], p)[-1] for p in (8, 21, 50)}
    touched = [p for p, value in ema.items() if value is not None
               and latest.low <= value*(1+parameters.touch_tolerance_pct/100)
               and latest.high >= value*(1-parameters.touch_tolerance_pct/100)
               and (latest.close-value)*sign > 0]
    if touched:
        kinds.append("ma_pullback")
    # Retest of a previously completed base, not a resistance fitted using its breakout.
    older = bars[-n-2:-2]
    old_level = max(b.high for b in older) if sign == 1 else min(b.low for b in older)
    tol = old_level*parameters.touch_tolerance_pct/100
    if (mother.close-old_level)*sign > 0 and latest.low <= old_level+tol \
            and latest.high >= old_level-tol and (latest.close-old_level)*sign > 0:
        kinds.append("breakout_retest")
    passed = all(c["status"] == "pass" for c in out["checks"])
    for kind in kinds:
        trigger = max(b.high for b in base) if sign == 1 else min(b.low for b in base)
        invalidation = min(b.low for b in base) if sign == 1 else max(b.high for b in base)
        if kind in ("inside_day", "ma_pullback"):
            boundary = mother if kind == "inside_day" else latest
            trigger = boundary.high if sign == 1 else boundary.low
            invalidation = boundary.low if sign == 1 else boundary.high
        if kind == "breakout_retest":
            # The next confirmation must clear the retest candle; its old level stays evidence.
            trigger = latest.high if sign == 1 else latest.low
            invalidation = latest.low if sign == 1 else latest.high
        targets = _targets(bars[:-n], trigger, direction, parameters.touch_tolerance_pct)
        out["candidates"].append({"setup": kind, "trigger": trigger, "invalidation": invalidation,
                                  "targets": targets, "contextPassed": passed,
                                  "reviewRequired": True,
                                  "needsTargets": not targets,
                                  "evidence": {"baseStart": base[0].session.isoformat(),
                                               "baseEnd": latest.session.isoformat(), "volumeRatio": volume_ratio,
                                               "upperSlopePct": upper, "lowerSlopePct": lower,
                                               "impulsePct": impulse, "tightens": tightens,
                                               "ceilingTouches": len(ceiling_touches),
                                               "touchedEmas": touched, "retestLevel": old_level},
                                  "reason": f"Measured {kind} geometry; review source context and target levels before arming."})
    return out
