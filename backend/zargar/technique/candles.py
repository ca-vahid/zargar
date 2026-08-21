"""Candlestick geometry and named patterns (spec module T3.4).

These are the measurable half of the book's candle chapter. "A large, solid
candle that closes clearly above the resistance… with minimal wicks" (T3.3b) and
"long wicks show rejection" (T3.4b) become numbers here so the breakout/fakeout
discriminator can be evaluated rather than eyeballed.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain import Bar
from .rulebook import DEFAULT_THRESHOLDS, Thresholds

__all__ = ["CandleMetrics", "metrics", "classify", "is_decisive", "avg_body"]


@dataclass(frozen=True)
class CandleMetrics:
    """Normalised geometry of a single candle. Ratios are shares of the range."""

    ts: int
    bullish: bool
    range_: float
    body: float
    body_ratio: float
    upper_wick_ratio: float
    lower_wick_ratio: float
    close_position: float   # 0.0 = closed at the low, 1.0 = closed at the high

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "bullish": self.bullish,
            "range": round(self.range_, 4),
            "body": round(self.body, 4),
            "bodyRatio": round(self.body_ratio, 3),
            "upperWickRatio": round(self.upper_wick_ratio, 3),
            "lowerWickRatio": round(self.lower_wick_ratio, 3),
            "closePosition": round(self.close_position, 3),
        }


def metrics(bar: Bar) -> CandleMetrics:
    """Geometry for one bar. A zero-range bar yields all-zero ratios."""
    rng = bar.high - bar.low
    body = abs(bar.close - bar.open)
    bullish = bar.close >= bar.open
    if rng <= 0:
        return CandleMetrics(bar.ts, bullish, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5)
    upper = bar.high - max(bar.open, bar.close)
    lower = min(bar.open, bar.close) - bar.low
    return CandleMetrics(
        ts=bar.ts,
        bullish=bullish,
        range_=rng,
        body=body,
        body_ratio=body / rng,
        upper_wick_ratio=upper / rng,
        lower_wick_ratio=lower / rng,
        close_position=(bar.close - bar.low) / rng,
    )


def avg_body(bars: list[Bar], lookback: int = 20) -> float:
    """Mean candle body over the trailing window, for size comparisons."""
    window = bars[-lookback:] if bars else []
    if not window:
        return 0.0
    return sum(abs(b.close - b.open) for b in window) / len(window)


def is_decisive(
    bar: Bar,
    recent: list[Bar],
    *,
    direction: str = "long",
    thresholds: Thresholds | None = None,
) -> tuple[bool, list[str]]:
    """The T3.3b test: large solid candle, closing clearly beyond, minimal wicks.

    `direction` picks which wick must be small — for a bullish breakout it is the
    upper wick that would signal rejection. Returns the verdict and the rule ids
    that justify it.
    """
    t = thresholds or DEFAULT_THRESHOLDS
    m = metrics(bar)
    base = avg_body(recent)
    reasons: list[str] = []

    big_body = m.body_ratio >= t.decisive_body_ratio
    big_size = base <= 0 or m.body >= base * t.decisive_size_mult
    lead_wick = m.upper_wick_ratio if direction == "long" else m.lower_wick_ratio
    small_wick = lead_wick <= t.max_breakout_wick_ratio
    right_way = m.bullish if direction == "long" else not m.bullish

    ok = big_body and big_size and small_wick and right_way
    if ok:
        reasons.append("T3.3b")
    else:
        if not big_body or not big_size:
            reasons.append("T3.3e")   # indecisive body — fakeout signature
        if not small_wick:
            reasons.append("T3.4b")   # rejection wick
    return ok, reasons


def classify(bars: list[Bar], index: int = -1,
             *, thresholds: Thresholds | None = None) -> list[str]:
    """Named candle patterns at `index`, as a list of labels.

    Covers the four the book names: doji, hammer, hanging man, and engulfing.
    Context (uptrend vs downtrend) is applied by the caller — T3.4d is explicit
    that context overrides the pattern.
    """
    t = thresholds or DEFAULT_THRESHOLDS
    if not bars:
        return []
    idx = index if index >= 0 else len(bars) + index
    if idx < 0 or idx >= len(bars):
        return []

    bar = bars[idx]
    m = metrics(bar)
    out: list[str] = []
    if m.range_ <= 0:
        return out

    if m.body_ratio <= 0.1:
        out.append("doji")

    # Hammer / hanging man: small body at the top, long lower wick.
    if m.lower_wick_ratio >= t.long_wick_ratio and m.body_ratio <= 0.35 \
            and m.upper_wick_ratio <= 0.2:
        out.append("hammer" if m.bullish else "hanging_man")

    # Inverted hammer / shooting star: long upper wick.
    if m.upper_wick_ratio >= t.long_wick_ratio and m.body_ratio <= 0.35 \
            and m.lower_wick_ratio <= 0.2:
        out.append("shooting_star")

    # Engulfing: this body fully covers the previous one, opposite colour.
    if idx > 0:
        prev = bars[idx - 1]
        prev_hi, prev_lo = max(prev.open, prev.close), min(prev.open, prev.close)
        cur_hi, cur_lo = max(bar.open, bar.close), min(bar.open, bar.close)
        opposite = (bar.close >= bar.open) != (prev.close >= prev.open)
        if opposite and cur_hi >= prev_hi and cur_lo <= prev_lo and m.body > 0:
            out.append("bullish_engulfing" if m.bullish else "bearish_engulfing")

    if m.close_position >= 0.75:
        out.append("closed_near_high")
    elif m.close_position <= 0.25:
        out.append("closed_near_low")

    return out
