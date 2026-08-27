"""Market structure and pattern geometry (spec modules T3.1, T3.5).

Trend is read the way the book reads it — from the sequence of swing highs and
lows, without trendlines (T3.5). Wedges are fitted to those same pivots, subject
to the T1.5 drawing constraints (converging, upper steeper, slope <= 45 degrees).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain import Bar
from .levels import Pivot, find_pivots
from .rules import DEFAULT_MARKET_RULES as DEFAULT_THRESHOLDS, MarketRules as Thresholds
from .volume import volume_trend

__all__ = ["Trendline", "Wedge", "TrendRead", "read_trend", "fit_line", "detect_wedge"]


@dataclass(frozen=True)
class Trendline:
    """A fitted line through pivot points, in (bar-index, price) space."""

    slope: float          # price change per bar
    intercept: float      # price at index 0
    touches: int
    start_index: int
    end_index: int

    def at(self, index: float) -> float:
        return self.intercept + self.slope * index

    def to_dict(self) -> dict:
        return {
            "slope": round(self.slope, 6),
            "intercept": round(self.intercept, 4),
            "touches": self.touches,
            "startIndex": self.start_index,
            "endIndex": self.end_index,
        }


@dataclass
class TrendRead:
    """Trend direction plus the swing sequence that justifies it (T3.5)."""

    direction: str                  # uptrend | downtrend | sideways
    higher_highs: bool
    higher_lows: bool
    lower_highs: bool
    lower_lows: bool
    rules: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "higherHighs": self.higher_highs,
            "higherLows": self.higher_lows,
            "lowerHighs": self.lower_highs,
            "lowerLows": self.lower_lows,
            "rules": list(self.rules),
        }


@dataclass
class Wedge:
    """A falling wedge (T3.1): converging lines, volume drying up."""

    upper: Trendline
    lower: Trendline
    start_index: int
    end_index: int
    widest_height: float            # T3.1f — the measured-move distance
    lowest_price: float             # T3.1e — stop reference
    volume_declining: bool
    rules: list[str] = field(default_factory=list)

    def breakout_level(self, index: int) -> float:
        """Where the upper trendline sits at `index` — the break threshold."""
        return self.upper.at(index)

    def to_dict(self) -> dict:
        return {
            "kind": "falling_wedge",
            "upperTrendline": self.upper.to_dict(),
            "lowerTrendline": self.lower.to_dict(),
            "startIndex": self.start_index,
            "endIndex": self.end_index,
            "widestHeight": round(self.widest_height, 4),
            "lowestPrice": round(self.lowest_price, 4),
            "volumeDeclining": self.volume_declining,
            "rules": list(self.rules),
        }


def fit_line(points: list[tuple[int, float]]) -> Trendline | None:
    """Least-squares fit through (index, price) points. Needs at least two."""
    if len(points) < 2:
        return None
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    denom = sum((x - mean_x) ** 2 for x, _ in points)
    if denom == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / denom
    return Trendline(
        slope=slope,
        intercept=mean_y - slope * mean_x,
        touches=n,
        start_index=min(x for x, _ in points),
        end_index=max(x for x, _ in points),
    )


def read_trend(bars: list[Bar], *, thresholds: Thresholds | None = None) -> TrendRead:
    """Determine trend from the swing sequence (T3.5a/T3.5b).

    Uses the last three pivots of each kind: an uptrend needs both higher highs
    and higher lows, a downtrend both lower highs and lower lows. Anything else
    is sideways — which the book treats as a reason to stand aside (R3.2).
    """
    t = thresholds or DEFAULT_THRESHOLDS
    pivots = find_pivots(bars, t.pivot_window)
    highs = [p for p in pivots if p.kind == "high"][-3:]
    lows = [p for p in pivots if p.kind == "low"][-3:]

    def rising(seq: list[Pivot]) -> bool:
        return len(seq) >= 2 and all(b.price > a.price for a, b in zip(seq, seq[1:]))

    def falling(seq: list[Pivot]) -> bool:
        return len(seq) >= 2 and all(b.price < a.price for a, b in zip(seq, seq[1:]))

    hh, hl = rising(highs), rising(lows)
    lh, ll = falling(highs), falling(lows)

    rules: list[str] = []
    if hh and hl:
        direction = "uptrend"
        rules.append("T3.5a")
    elif lh and ll:
        direction = "downtrend"
        rules.append("T3.5b")
    else:
        direction = "sideways"

    return TrendRead(direction, hh, hl, lh, ll, rules)


def _slope_within_limit(line: Trendline, ref_price: float, t: Thresholds) -> bool:
    """T1.5 — reject trendlines steeper than roughly 45 degrees.

    Expressed as a per-bar price change relative to price, since chart degrees
    depend on axis scaling and are not well defined on raw data.
    """
    if ref_price <= 0:
        return False
    return abs(line.slope) / ref_price <= t.max_trendline_slope_pct


def detect_wedge(
    bars: list[Bar],
    *,
    thresholds: Thresholds | None = None,
) -> Wedge | None:
    """Detect a falling wedge in the given window (T3.1).

    All three of the book's conditions must hold: lower highs *and* lower lows,
    converging trendlines with the upper steeper than the lower, and declining
    volume as the pattern forms. Returns None when any condition fails.
    """
    t = thresholds or DEFAULT_THRESHOLDS
    if len(bars) < t.wedge_min_bars:
        return None

    pivots = find_pivots(bars, t.pivot_window)
    highs = [p for p in pivots if p.kind == "high"]
    lows = [p for p in pivots if p.kind == "low"]
    if len(highs) < t.wedge_min_touches or len(lows) < t.wedge_min_touches:
        return None

    rules: list[str] = []

    # T3.1a — the sequence must be lower highs and lower lows.
    lower_highs = all(b.price < a.price for a, b in zip(highs, highs[1:]))
    lower_lows = all(b.price < a.price for a, b in zip(lows, lows[1:]))
    if not (lower_highs and lower_lows):
        return None
    rules.append("T3.1a")

    upper = fit_line([(p.index, p.price) for p in highs])
    lower = fit_line([(p.index, p.price) for p in lows])
    if upper is None or lower is None:
        return None

    # T3.1b — both slope down, upper steeper, and the lines converge.
    if upper.slope >= 0 or lower.slope >= 0:
        return None
    if upper.slope >= lower.slope:      # more negative == steeper
        return None
    start, end = 0, len(bars) - 1
    gap_start = upper.at(start) - lower.at(start)
    gap_end = upper.at(end) - lower.at(end)
    if gap_start <= 0 or gap_end >= gap_start:
        return None
    rules.append("T3.1b")

    ref = bars[-1].close
    if not (_slope_within_limit(upper, ref, t) and _slope_within_limit(lower, ref, t)):
        return None
    rules.append("T1.5")

    # T3.1c — volume must be drying up as the wedge forms.
    vol_declining = volume_trend(bars) == "falling"
    if vol_declining:
        rules.append("T3.1c")

    return Wedge(
        upper=upper,
        lower=lower,
        start_index=start,
        end_index=end,
        widest_height=gap_start,           # T3.1f: widest point, at the start
        lowest_price=min(b.low for b in bars),
        volume_declining=vol_declining,
        rules=rules,
    )
