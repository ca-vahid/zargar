"""Team2 level work beyond the shared primitives: targets and the daily level sheet.

- `targets_beyond(bars15m_history, zones, lookback_sessions)` (L3.1): the next resistance
  above the PDH zone = the most recent 15m pivot high above it within the lookback; the next
  support below the PDL zone = the most recent pivot low below it. `None` when the history
  has none (then the target is "open" and the runner rides the EMA).
- `level_sheet(...)` — the one-line-per-symbol plan text the author posts every morning
  (V9): "Main watch … break above and we focus on calls … room up to X".
"""
from __future__ import annotations

from ...domain import Bar
from ...marketstructure.aggregate import bar_session
from ...marketstructure.dailylevels import Zone
from ...marketstructure.levels import find_pivots
from ...marketstructure.sessions import session_date


def targets_beyond(bars15m: list[Bar], zones: dict[str, Zone], *, lookback_sessions: int = 10,
                   pivot_window: int = 2) -> dict[str, float | None]:
    rth = sorted((b for b in bars15m if bar_session(b.ts) == "rth"), key=lambda b: b.ts)
    if not rth:
        return {"above": None, "below": None}
    dates = sorted({session_date(b.ts) for b in rth})
    keep = set(dates[-lookback_sessions:])
    hist = [b for b in rth if session_date(b.ts) in keep and session_date(b.ts) != zones["pdh"].date]
    pdh, pdl = zones["pdh"], zones["pdl"]
    above = below = None
    for p in reversed(find_pivots(hist, window=pivot_window)):
        if above is None and p.kind == "high" and p.price > pdh.top:
            above = p.price
        if below is None and p.kind == "low" and p.price < pdl.bottom:
            below = p.price
        if above is not None and below is not None:
            break
    return {"above": above, "below": below}


def level_ladder(bars15m: list[Bar], zones: dict[str, Zone], *, lookback_sessions: int = 10,
                 pivot_window: int = 2) -> dict[str, list[float]]:
    """F72 (2026-09-09): every structural level the lookback knows, ordered outward, so a target can
    be re-derived against CURRENT PRICE instead of against the zone.

    `targets_beyond` answers "what is the next pivot beyond the PDH/PDL zone" — anchored on the
    zone, and therefore fixed when the plan is built. On a gap that opens straight THROUGH the zone
    that answer is already behind price before the 15m confirmation arrives (SPY 2026-09-09:
    target 764.75, price 763.7). This returns the same pivots, unfiltered by the zone:
    `highs` ascending and `lows` descending, so the first entry beyond a given price in the trade's
    direction is the next structural level from there. Selection is the caller's job, at entry.
    """
    rth = sorted((b for b in bars15m if bar_session(b.ts) == "rth"), key=lambda b: b.ts)
    if not rth:
        return {"highs": [], "lows": []}
    dates = sorted({session_date(b.ts) for b in rth})
    keep = set(dates[-lookback_sessions:])
    hist = [b for b in rth if session_date(b.ts) in keep and session_date(b.ts) != zones["pdh"].date]
    highs = sorted({round(float(p.price), 4) for p in find_pivots(hist, window=pivot_window) if p.kind == "high"})
    lows = sorted({round(float(p.price), 4) for p in find_pivots(hist, window=pivot_window) if p.kind == "low"},
                  reverse=True)
    return {"highs": highs, "lows": lows}


def next_structural_level(ladder: dict[str, list[float]] | None, price: float, direction: str) -> float | None:
    """The first level in `ladder` strictly beyond `price` in the trade's direction, or None."""
    if not ladder:
        return None
    if direction == "long":
        return next((float(x) for x in (ladder.get("highs") or []) if float(x) > price), None)
    return next((float(x) for x in (ladder.get("lows") or []) if float(x) < price), None)


def level_sheet(symbol: str, zones: dict[str, Zone], pmh: float | None, pml: float | None,
                targets: dict[str, float | None], day_type: str | None = None) -> str:
    pdh, pdl = zones["pdh"], zones["pdl"]
    up = f"{targets['above']:.2f}" if targets.get("above") else "open"
    dn = f"{targets['below']:.2f}" if targets.get("below") else "open"
    pm = f" · PM {pml:.2f}–{pmh:.2f}" if pmh is not None and pml is not None else ""
    dt_ = f" · {day_type.replace('_', ' ')} day" if day_type else ""
    return (f"{symbol}: PDH zone {pdh.bottom:.2f}–{pdh.top:.2f} → break above and we focus on calls, room up to {up}; "
            f"PDL zone {pdl.bottom:.2f}–{pdl.top:.2f} → break below and we focus on puts, room down to {dn}{pm}{dt_}")


__all__ = ["targets_beyond", "level_ladder", "next_structural_level", "level_sheet"]
