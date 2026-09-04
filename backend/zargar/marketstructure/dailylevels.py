"""Daily reference levels: prior-day high/low ZONES and the pre-market range (pure).

Added 2026-09-03 for the Team2 technique; usable by any technique that wants "yesterday's"
levels as zones rather than lines.

- `prior_day_zones(bars15m)` — from ONE regular session's 15-minute bars: the PDH zone runs from
  the high-of-day wick down to the body of the FOLLOWING 15m candle (its higher open/close);
  the PDL zone runs from the low-of-day wick up to the following candle's lower open/close.
  If the extreme is the session's last bar there is no following candle: the zone collapses to
  the body of the extreme bar itself (documented ambiguity — the author "connects it to a
  nearby candle body"). Width is data-defined, typically 0.1–0.2 % of price.
- `premarket_range(bars1m, date)` — highest high / lowest low of the 04:00–09:30 ET bars of
  `date`; `None`s when there are no pre-market bars.
- `session_extremes(bars, date)` — RTH high/low of a date (the plain PDH/PDL lines).
- `Zone.contains / above / below` with an optional tolerance.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain import Bar
from .aggregate import bar_session
from .sessions import session_date


@dataclass(frozen=True)
class Zone:
    kind: str           # "pdh" | "pdl" | "custom"
    top: float
    bottom: float
    date: str           # the session the zone was built from
    anchor_ts: int      # bar open of the extreme candle

    @property
    def width(self) -> float:
        return self.top - self.bottom

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    def contains(self, price: float, tol: float = 0.0) -> bool:
        return (self.bottom - tol) <= price <= (self.top + tol)

    def above(self, price: float, tol: float = 0.0) -> bool:
        return price > self.top + tol

    def below(self, price: float, tol: float = 0.0) -> bool:
        return price < self.bottom - tol

    def to_dict(self) -> dict:
        return {"kind": self.kind, "top": round(self.top, 4), "bottom": round(self.bottom, 4),
                "width": round(self.width, 4), "date": self.date, "anchorTs": self.anchor_ts}


def _body(b: Bar) -> tuple[float, float]:
    return (min(b.open, b.close), max(b.open, b.close))


def prior_day_zones(bars15m: list[Bar]) -> dict[str, Zone] | None:
    """PDH/PDL zones from one session's 15m bars (RTH only; pass what `filter_session` gives)."""
    bars = sorted((b for b in bars15m if bar_session(b.ts) == "rth"), key=lambda b: b.ts)
    if not bars:
        return None
    date = session_date(bars[0].ts)
    hi_i = max(range(len(bars)), key=lambda i: bars[i].high)
    lo_i = min(range(len(bars)), key=lambda i: bars[i].low)
    hb = bars[hi_i]
    nxt = bars[hi_i + 1] if hi_i + 1 < len(bars) else hb
    pdh = Zone("pdh", top=hb.high, bottom=_body(nxt)[1], date=date, anchor_ts=hb.ts)
    lb = bars[lo_i]
    nxt = bars[lo_i + 1] if lo_i + 1 < len(bars) else lb
    pdl = Zone("pdl", top=_body(nxt)[0], bottom=lb.low, date=date, anchor_ts=lb.ts)
    # guard degenerate data (a doji following the extreme): keep at least a hair of width
    if pdh.bottom > pdh.top:
        pdh = Zone("pdh", top=hb.high, bottom=hb.high, date=date, anchor_ts=hb.ts)
    if pdl.top < pdl.bottom:
        pdl = Zone("pdl", top=lb.low, bottom=lb.low, date=date, anchor_ts=lb.ts)
    return {"pdh": pdh, "pdl": pdl}


def premarket_range(bars1m: list[Bar], date: str) -> tuple[float | None, float | None]:
    pre = [b for b in bars1m if session_date(b.ts) == date and bar_session(b.ts) == "pre"]
    if not pre:
        return None, None
    return max(b.high for b in pre), min(b.low for b in pre)


def session_extremes(bars: list[Bar], date: str) -> tuple[float | None, float | None]:
    rth = [b for b in bars if session_date(b.ts) == date and bar_session(b.ts) == "rth"]
    if not rth:
        return None, None
    return max(b.high for b in rth), min(b.low for b in rth)


__all__ = ["Zone", "prior_day_zones", "premarket_range", "session_extremes"]
