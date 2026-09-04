"""Day type, the four bias scenarios and the 15-minute confirmation (METHOD modules L/B/C).

Pure. Inputs are the prior-day zones (`marketstructure.dailylevels.Zone`), the pre-market
range and 15-minute CLOSED bars of the session; output is a `Bias` the plan/simulation act on.

Scenarios (B1): 1 break PDH → long · 2 reject PDH → short · 3 bounce PDL → long · 4 break
PDL → short. 1/4 are trend days (B2), 2/3 range days (B3) needing extra confirmation.
Confirmation (C1): a level "breaks" only when a 15m candle BODY closes beyond it. Flip (D10):
the bias flips only when a 15m close goes through the zone the other way.
"""
from __future__ import annotations

from dataclasses import dataclass

from ...domain import Bar
from ...marketstructure.dailylevels import Zone

DAY_GAP_UP, DAY_GAP_DOWN, DAY_INSIDE, DAY_NORMAL = "gap_up", "gap_down", "inside", "normal"
SCENARIO_LABEL = {1: "break PDH", 2: "reject PDH", 3: "bounce PDL", 4: "break PDL"}
SCENARIO_DIRECTION = {1: "long", 2: "short", 3: "long", 4: "short"}
TREND_SCENARIOS = (1, 4)


def classify_day(open_price: float, zones: dict[str, Zone], pmh: float | None, pml: float | None) -> str:
    """A1: where the 09:30 open sits relative to yesterday's range (and the PM range)."""
    pdh, pdl = zones["pdh"], zones["pdl"]
    if open_price > pdh.top:
        return DAY_GAP_UP
    if open_price < pdl.bottom:
        return DAY_GAP_DOWN
    if pmh is not None and pml is not None and pdl.top < pml and pmh < pdh.bottom:
        return DAY_INSIDE
    return DAY_NORMAL


def sizing_bucket(price: float, zones: dict[str, Zone], pmh: float | None, pml: float | None) -> str:
    """V6: 'full' beyond the PDH/PDL zones · 'small' between a prior-day zone and the PM level
    · 'none' inside the PM range. With no PM range, inside yesterday's range is 'small'."""
    pdh, pdl = zones["pdh"], zones["pdl"]
    # F15 (2026-09-04): the PM range is chop wherever it sits — on a gap day it lies beyond the PDH/PDL
    # zone, and "full" there was buying the middle of the pre-market range (QQQ 10:02, 0.62 under the PMH)
    if pmh is not None and pml is not None and pml <= price <= pmh:
        return "none"
    if price > pdh.top or price < pdl.bottom:
        return "full"
    return "small"


def body_closed_beyond(bar: Bar, level: float, direction: str) -> bool:
    """C1: the candle BODY closed beyond the level (close beyond, in the trade's direction)."""
    return bar.close > level if direction == "long" else bar.close < level


@dataclass
class Bias:
    scenario: int | None = None          # 1..4 or None
    direction: str | None = None         # long | short
    level: float | None = None           # the price the scenario is anchored on (zone edge)
    since_ts: int | None = None
    range_day: bool = False
    history: list[dict] | None = None

    @property
    def active(self) -> bool:
        return self.scenario is not None

    def to_dict(self) -> dict:
        return {"scenario": self.scenario, "label": SCENARIO_LABEL.get(self.scenario or 0),
                "direction": self.direction, "level": self.level, "sinceTs": self.since_ts,
                "rangeDay": self.range_day, "history": list(self.history or [])[-6:]}


class ScenarioTracker:
    """Feed 15m CLOSED bars in order. Reads the four scenarios off the PDH/PDL zones:

    - break PDH: a 15m body close above the zone top → scenario 1
    - break PDL: a 15m body close below the zone bottom → scenario 4
    - reject PDH: a bar whose high reached into the zone and whose body closed below the zone
      bottom → scenario 2 (range day)
    - bounce PDL: a bar whose low reached into the zone and whose body closed above the zone
      top → scenario 3 (range day)
    Flip rule (D10): once set, a scenario changes only when a later 15m close goes through
    the *other* side of the range (or back through its own zone), never on a wick.
    """

    def __init__(self, zones: dict[str, Zone], *, flip_on_close: bool = True) -> None:
        self.pdh, self.pdl = zones["pdh"], zones["pdl"]
        self.flip_on_close = flip_on_close
        self.bias = Bias(history=[])

    def _set(self, n: int, level: float, bar: Bar) -> Bias:
        if self.bias.scenario != n:
            self.bias.history.append({"ts": bar.ts, "scenario": n, "label": SCENARIO_LABEL[n], "close": bar.close})
        self.bias.scenario, self.bias.direction, self.bias.level = n, SCENARIO_DIRECTION[n], level
        self.bias.since_ts = bar.ts
        self.bias.range_day = n not in TREND_SCENARIOS
        return self.bias

    def on_close(self, bar: Bar, *, tol: float = 0.0, min_body_ratio: float = 0.0) -> Bias:
        """F27 (2026-09-04): a scenario is set/flipped on a 15m body close beyond the zone edge by more
        than `tol` (zone_tol_atr x ATR) on a candle whose body is at least `min_body_ratio` of its range
        (flip_body_ratio). Both ship at 0 = the bare close, unchanged; the walk-forward picks the values
        (QQQ 2026-09-04 12:30 flipped on a 0.025 margin, 0.55 body, and flipped back 30 min later)."""
        pdh, pdl = self.pdh, self.pdl
        rng = max(bar.high - bar.low, 1e-9)
        if min_body_ratio > 0 and abs(bar.close - bar.open) / rng < min_body_ratio:
            return self.bias                            # an indecisive candle changes no mind
        if self.bias.scenario is None:
            if bar.close > pdh.top + tol:
                return self._set(1, pdh.top, bar)
            if bar.close < pdl.bottom - tol:
                return self._set(4, pdl.bottom, bar)
            if bar.high >= pdh.bottom and bar.close < pdh.bottom:
                return self._set(2, pdh.bottom, bar)
            if bar.low <= pdl.top and bar.close > pdl.top:
                return self._set(3, pdl.top, bar)
            return self.bias
        # flips: a 15m close through the other side (D10; `flip_on_close=False` keeps the first read all day)
        if not self.flip_on_close:
            return self.bias
        s = self.bias.scenario
        if s == 1 and bar.close < pdh.bottom - tol:
            return self._set(2, pdh.bottom, bar)        # failed breakout = rejection (R20: same tolerance both ways)
        if s == 4 and bar.close > pdl.top + tol:
            return self._set(3, pdl.top, bar)           # failed breakdown = bounce
        if s in (2, 3) and bar.close > pdh.top + tol:
            return self._set(1, pdh.top, bar)
        if s in (2, 3) and bar.close < pdl.bottom - tol:
            return self._set(4, pdl.bottom, bar)
        return self.bias


def confirmed_break(bars15m: list[Bar], level: float, direction: str) -> Bar | None:
    """The first 15m closed bar whose body closed beyond `level` in `direction` (C1)."""
    for b in bars15m:
        if body_closed_beyond(b, level, direction):
            return b
    return None


__all__ = ["classify_day", "sizing_bucket", "body_closed_beyond", "Bias", "ScenarioTracker", "confirmed_break",
           "SCENARIO_LABEL", "SCENARIO_DIRECTION", "TREND_SCENARIOS", "DAY_GAP_UP", "DAY_GAP_DOWN", "DAY_INSIDE",
           "DAY_NORMAL"]
