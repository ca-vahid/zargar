"""The EMA regime read (METHOD module E) — incremental, over 2-minute closed bars.

Extended-hours bars are fed too ("ext hours on", E1): the three EMAs and the 2m ATR carry
state across pre-market, the session, after-hours and into the next day (Q6/D8), exactly like
a TradingView 2m chart with extended hours enabled. `RegimeReader.update(bar2m)` returns the
read for that bar; `snapshot()`/`restore()` make it restart-safe.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...domain import Bar
from ...marketstructure.indicators import EmaState, ema_stack, fan_state, fan_width, true_range
from .rules import Team2Rules


@dataclass(frozen=True)
class RegimeRead:
    ts: int
    close: float
    ema_fast: float | None
    ema_mid: float | None
    ema_slow: float | None
    stack: str            # bull | bear | mixed
    strength: int         # 0..3 (E2 ladder)
    fan: str              # trend | chop | unknown (E4)
    fan_width: float | None
    atr: float | None

    @property
    def ready(self) -> bool:
        return self.ema_slow is not None

    def favours(self, direction: str) -> bool:
        """E3: calls only in a bullish stack, puts only in a bearish one."""
        return (direction == "long" and self.stack == "bull") or (direction == "short" and self.stack == "bear")

    def to_dict(self) -> dict:
        return {"ts": self.ts, "close": self.close, "ema13": _r(self.ema_fast), "ema48": _r(self.ema_mid),
                "ema200": _r(self.ema_slow), "stack": self.stack, "strength": self.strength, "fan": self.fan,
                "fanWidth": _r(self.fan_width, 3), "atr": _r(self.atr)}


def _r(v, nd=4):
    return None if v is None else round(float(v), nd)


@dataclass
class RegimeReader:
    rules: Team2Rules
    fast: EmaState = field(init=False)
    mid: EmaState = field(init=False)
    slow: EmaState = field(init=False)
    _atr: float | None = None
    _prev_close: float | None = None
    _tr_seen: int = 0
    last: RegimeRead | None = None

    def __post_init__(self) -> None:
        self.fast = EmaState(self.rules.ema_fast)
        self.mid = EmaState(self.rules.ema_mid)
        self.slow = EmaState(self.rules.ema_slow)

    def update(self, bar: Bar) -> RegimeRead:
        c = float(bar.close)
        f = self.fast.update(c)
        m = self.mid.update(c)
        s = self.slow.update(c)
        tr = true_range(bar.high, bar.low, self._prev_close)
        n = self.rules.atr_period
        self._tr_seen += 1
        if self._atr is None:
            self._atr = tr
        else:
            # Wilder smoothing after the first bar; the first `n` bars ramp in
            k = min(self._tr_seen, n)
            self._atr = (self._atr * (k - 1) + tr) / k if k < n else (self._atr * (n - 1) + tr) / n
        self._prev_close = c
        st = ema_stack(c, f, m, s)
        w = fan_width(f, m, s, self._atr if self._atr and self._atr > 0 else None)
        self.last = RegimeRead(ts=bar.ts, close=c, ema_fast=f, ema_mid=m, ema_slow=s, stack=st.stack,
                               strength=st.strength, fan=fan_state(w, trend_min=self.rules.fan_trend_min_atr),
                               fan_width=w, atr=self._atr)
        return self.last

    @property
    def atr(self) -> float | None:
        return self._atr

    def snapshot(self) -> dict:
        return {"fast": self.fast.to_dict(), "mid": self.mid.to_dict(), "slow": self.slow.to_dict(),
                "atr": self._atr, "prevClose": self._prev_close, "trSeen": self._tr_seen}

    def restore(self, snap: dict) -> None:
        self.fast = EmaState.from_dict(snap["fast"])
        self.mid = EmaState.from_dict(snap["mid"])
        self.slow = EmaState.from_dict(snap["slow"])
        self._atr = snap.get("atr")
        self._prev_close = snap.get("prevClose")
        self._tr_seen = int(snap.get("trSeen", 0))


__all__ = ["RegimeRead", "RegimeReader"]
