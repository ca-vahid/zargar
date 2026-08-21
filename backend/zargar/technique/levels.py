"""Support & resistance detection (spec module T1).

Levels are found deterministically from OHLCV bars so the prices we report are
exact. The vision layer decides which of these levels *matter*; it never invents
new ones — `grounding.py` rejects any level that does not appear here.

Method: find swing pivots, cluster them by price proximity, count how many times
price actually touched each cluster, and keep clusters meeting the touch minimum
(T1.2). Prior-session extremes (T1.3a/b) and round numbers (T1.3d) are seeded as
additional candidates because the book weights them specially.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..domain import Bar
from .rulebook import DEFAULT_THRESHOLDS, Thresholds

__all__ = ["Level", "Pivot", "find_pivots", "detect_levels", "atr", "session_key"]


@dataclass(frozen=True)
class Pivot:
    """A local extreme in the bar series."""

    index: int
    ts: int
    price: float
    kind: str  # "high" | "low"


@dataclass
class Level:
    """A horizontal price level with the evidence that produced it."""

    price: float
    kind: str                       # "support" | "resistance"
    touches: int
    sources: list[str] = field(default_factory=list)   # rule ids, e.g. ["T1.3a"]
    touch_ts: list[int] = field(default_factory=list)
    first_ts: int | None = None
    last_ts: int | None = None
    timeframe: str = "1m"

    @property
    def strong(self) -> bool:
        return self.touches >= DEFAULT_THRESHOLDS.strong_touches

    def to_dict(self) -> dict:
        return {
            "price": round(self.price, 4),
            "kind": self.kind,
            "touches": self.touches,
            "strong": self.strong,
            "sources": list(self.sources),
            "touchTs": list(self.touch_ts),
            "firstTs": self.first_ts,
            "lastTs": self.last_ts,
            "timeframe": self.timeframe,
        }


def atr(bars: list[Bar], period: int = 14) -> float:
    """Average true range. 0.0 when there is not enough history."""
    if len(bars) < 2:
        return 0.0
    trs: list[float] = []
    for prev, cur in zip(bars, bars[1:]):
        trs.append(max(
            cur.high - cur.low,
            abs(cur.high - prev.close),
            abs(cur.low - prev.close),
        ))
    window = trs[-period:] if len(trs) >= period else trs
    return sum(window) / len(window) if window else 0.0


def session_key(ts_ms: int) -> str:
    """UTC date of a bar, used to group bars into sessions."""
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def find_pivots(bars: list[Bar], window: int | None = None) -> list[Pivot]:
    """Swing highs/lows: a bar whose extreme exceeds `window` bars either side.

    Ties are resolved in favour of the earliest bar, so a flat top yields one
    pivot rather than several.
    """
    w = window if window is not None else DEFAULT_THRESHOLDS.pivot_window
    if w < 1 or len(bars) < 2 * w + 1:
        return []
    out: list[Pivot] = []
    for i in range(w, len(bars) - w):
        left = bars[i - w:i]
        right = bars[i + 1:i + 1 + w]
        b = bars[i]
        if all(b.high > o.high for o in left) and all(b.high >= o.high for o in right):
            out.append(Pivot(i, b.ts, b.high, "high"))
        if all(b.low < o.low for o in left) and all(b.low <= o.low for o in right):
            out.append(Pivot(i, b.ts, b.low, "low"))
    return out


def _tolerance(price: float, bars: list[Bar], t: Thresholds) -> float:
    """Absolute price tolerance for "same level" (spec Q1).

    The larger of a percentage band and an ATR-relative band, so the detector
    stays sane on both a $3 stock and a $600 one.
    """
    pct_band = abs(price) * t.level_tolerance_pct
    atr_band = atr(bars) * t.level_tolerance_atr
    return max(pct_band, atr_band, 1e-9)


def _count_touches(bars: list[Bar], price: float, tol: float, kind: str) -> list[int]:
    """Timestamps of bars that actually touched `price` within `tol`.

    A touch requires the bar's *extreme* to reach the band — for support the low,
    for resistance the high. Consecutive bars inside the band count once, so a
    long consolidation on the level is a single touch, not twenty.
    """
    hits: list[int] = []
    in_band = False
    for b in bars:
        if kind == "support":
            touching = b.low <= price + tol and b.high >= price - tol
        else:
            touching = b.high >= price - tol and b.low <= price + tol
        if touching and not in_band:
            hits.append(b.ts)
        in_band = touching
    return hits


def _cluster(prices: list[tuple[float, int]], tol_for) -> list[list[tuple[float, int]]]:
    """Greedy 1-D clustering of (price, ts) pairs by proximity."""
    if not prices:
        return []
    ordered = sorted(prices, key=lambda p: p[0])
    clusters: list[list[tuple[float, int]]] = [[ordered[0]]]
    for price, ts in ordered[1:]:
        anchor = clusters[-1][0][0]
        if abs(price - anchor) <= tol_for(anchor):
            clusters[-1].append((price, ts))
        else:
            clusters.append([(price, ts)])
    return clusters


def _round_number_candidates(lo: float, hi: float, t: Thresholds) -> list[float]:
    """Psychologically significant round prices inside the range (T1.3d).

    Picks the coarsest step that yields at least one but not more than a handful
    of levels in the window, so a $600 stock gets $50s rather than every dollar.
    """
    span = hi - lo
    if span <= 0:
        return []
    for step in sorted(t.round_number_steps, reverse=True):
        first = math.ceil(lo / step) * step
        vals = []
        v = first
        while v <= hi:
            vals.append(round(v, 6))
            v += step
        if 1 <= len(vals) <= 6:
            return vals
    return []


def detect_levels(
    bars: list[Bar],
    *,
    thresholds: Thresholds | None = None,
    prior_session_bars: list[Bar] | None = None,
    timeframe: str = "1m",
) -> list[Level]:
    """Detect support and resistance levels from a bar window (T1).

    `prior_session_bars` supplies the previous session so its HOD/LOD can be
    seeded as high-priority candidates (T1.3a/T1.3b). When omitted, sessions are
    inferred from `bars` itself.

    Returns levels sorted by descending strength (touches, then recency).
    """
    t = thresholds or DEFAULT_THRESHOLDS
    if len(bars) < 3:
        return []

    def tol_for(p: float) -> float:
        return _tolerance(p, bars, t)
    lo = min(b.low for b in bars)
    hi = max(b.high for b in bars)

    # --- seed candidates -------------------------------------------------
    # (price, ts, kind, source-rule)
    seeds: list[tuple[float, int, str, str]] = []

    pivots = find_pivots(bars, t.pivot_window)
    for p in pivots:
        seeds.append((p.price, p.ts, "resistance" if p.kind == "high" else "support", "T1.3c"))

    prior = prior_session_bars
    if prior is None:
        by_session: dict[str, list[Bar]] = {}
        for b in bars:
            by_session.setdefault(session_key(b.ts), []).append(b)
        keys = sorted(by_session)
        prior = by_session[keys[-2]] if len(keys) >= 2 else []
    if prior:
        hod = max(prior, key=lambda b: b.high)
        lod = min(prior, key=lambda b: b.low)
        seeds.append((hod.high, hod.ts, "resistance", "T1.3a"))
        seeds.append((lod.low, lod.ts, "support", "T1.3a"))

    for rn in _round_number_candidates(lo, hi, t):
        kind = "support" if rn <= bars[-1].close else "resistance"
        seeds.append((rn, bars[0].ts, kind, "T1.3d"))

    # --- cluster and score ------------------------------------------------
    levels: list[Level] = []
    for kind in ("support", "resistance"):
        subset = [(price, ts) for price, ts, k, _ in seeds if k == kind]
        sources_by_price = {
            round(price, 6): src for price, _, k, src in seeds if k == kind
        }
        for cluster in _cluster(subset, tol_for):
            price = sum(p for p, _ in cluster) / len(cluster)
            tol = tol_for(price)
            touch_ts = _count_touches(bars, price, tol, kind)
            if len(touch_ts) < t.min_touches:
                continue
            srcs = sorted({
                sources_by_price.get(round(p, 6), "T1.3c") for p, _ in cluster
            })
            levels.append(Level(
                price=price,
                kind=kind,
                touches=len(touch_ts),
                sources=srcs,
                touch_ts=touch_ts,
                first_ts=min(touch_ts),
                last_ts=max(touch_ts),
                timeframe=timeframe,
            ))

    # Prior-day extremes outrank everything else (T1.3a), then touch count.
    def rank(lv: Level) -> tuple:
        return (
            0 if "T1.3a" in lv.sources else 1,
            -lv.touches,
            -(lv.last_ts or 0),
        )

    levels.sort(key=rank)
    return levels


def nearest_level(
    levels: list[Level],
    price: float,
    kind: str | None = None,
    *,
    side: str | None = None,
) -> Level | None:
    """Closest level to `price`.

    `kind` filters to support or resistance. `side` constrains direction:
    "above" for the first overhead obstacle (a bounce target), "below" for the
    first level underneath (a stop reference). Without `side` a resistance that
    sits *below* the entry could be returned as a target, which is meaningless.
    """
    pool = [lv for lv in levels if kind is None or lv.kind == kind]
    if side == "above":
        pool = [lv for lv in pool if lv.price > price]
    elif side == "below":
        pool = [lv for lv in pool if lv.price < price]
    return min(pool, key=lambda lv: abs(lv.price - price)) if pool else None
