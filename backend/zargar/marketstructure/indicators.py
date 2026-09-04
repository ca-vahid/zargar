"""Moving-average indicators and the EMA-stack regime read (pure).

Added 2026-09-03 for the Team2 technique (13/48/200 EMA on 2m bars, "ext hours on") and shared
by every technique. Nothing here reads settings: callers pass periods and thresholds.

- `ema_series(values, period)` — standard EMA (alpha = 2/(period+1)), seeded with the SMA of
  the first `period` values (TradingView-compatible); `None` until the seed is complete.
- `EmaState` — incremental EMA that carries across sessions/restarts (`to_dict`/`from_dict`), so
  a live 2m stream and a replay produce identical values.
- `ema_stack(price, fast, mid, slow)` — "bull" (fast > mid > slow), "bear" (fast < mid < slow),
  else "mixed"; `strength` = how many of the three EMAs price is beyond in the stack's
  direction (0–3; Team2: 1 = bullish, 2 = more, 3 = "mega").
- `fan_width(fast, mid, slow, scale)` — (max − min) of the three EMAs divided by `scale`
  (ATR or a % of price): small = braided/chop, large = fanned/trend. `fan_state` applies
  a threshold.
"""
from __future__ import annotations

from dataclasses import dataclass


def ema_series(values: list[float], period: int) -> list[float | None]:
    if period < 1:
        raise ValueError("period must be >= 1")
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1.0)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    e = seed
    for i in range(period, len(values)):
        e = (values[i] - e) * alpha + e
        out[i] = e
    return out


@dataclass
class EmaState:
    """Incremental EMA. `update(x)` returns the new value (None while seeding)."""
    period: int
    value: float | None = None
    seen: int = 0
    _seed_sum: float = 0.0

    def update(self, x: float) -> float | None:
        self.seen += 1
        if self.value is None:
            self._seed_sum += x
            if self.seen >= self.period:
                self.value = self._seed_sum / self.period
            return self.value
        alpha = 2.0 / (self.period + 1.0)
        self.value = (x - self.value) * alpha + self.value
        return self.value

    @property
    def ready(self) -> bool:
        return self.value is not None

    def to_dict(self) -> dict:
        return {"period": self.period, "value": self.value, "seen": self.seen, "seedSum": self._seed_sum}

    @classmethod
    def from_dict(cls, d: dict) -> "EmaState":
        return cls(period=int(d["period"]), value=d.get("value"), seen=int(d.get("seen", 0)),
                   _seed_sum=float(d.get("seedSum", 0.0)))


@dataclass(frozen=True)
class StackRead:
    stack: str          # "bull" | "bear" | "mixed"
    strength: int       # 0..3 EMAs price is beyond, in the stack's direction
    above_slow: bool | None

    def to_dict(self) -> dict:
        return {"stack": self.stack, "strength": self.strength, "aboveSlow": self.above_slow}


def ema_stack(price: float | None, fast: float | None, mid: float | None, slow: float | None) -> StackRead:
    if fast is None or mid is None or slow is None:
        return StackRead("mixed", 0, None if slow is None or price is None else price > slow)
    if fast > mid > slow:
        stack = "bull"
    elif fast < mid < slow:
        stack = "bear"
    else:
        stack = "mixed"
    strength = 0
    if price is not None:
        if stack == "bull":
            strength = sum(1 for e in (slow, mid, fast) if price > e)
        elif stack == "bear":
            strength = sum(1 for e in (slow, mid, fast) if price < e)
    return StackRead(stack, strength, None if price is None else price > slow)


def fan_width(fast: float | None, mid: float | None, slow: float | None, scale: float) -> float | None:
    """Spread of the three EMAs in units of `scale` (pass ATR, or price × pct)."""
    if fast is None or mid is None or slow is None or not scale or scale <= 0:
        return None
    return (max(fast, mid, slow) - min(fast, mid, slow)) / scale


def fan_state(width: float | None, *, trend_min: float) -> str:
    """'chop' when braided (width < trend_min), 'trend' when fanned, 'unknown' while warming."""
    if width is None:
        return "unknown"
    return "trend" if width >= trend_min else "chop"


def true_range(high: float, low: float, prev_close: float | None) -> float:
    if prev_close is None:
        return high - low
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


__all__ = ["ema_series", "EmaState", "StackRead", "ema_stack", "fan_width", "fan_state", "true_range"]
