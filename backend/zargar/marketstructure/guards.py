"""Trigger GUARDS — conditional entries (tips, ARM-PLAN P4).

A guard gates a trigger: bars are only shown to the trigger's tracker while
every guard passes on that bar, so "buy the retest IF it reclaims the 8-EMA"
or "only while SPY holds 640" become data, evaluated by the same pure code
live and in replay (change one, change both).

Guard documents (plain dicts on `Trigger.guards`):

    {"kind": "ema_reclaim", "period": 8}                 # close beyond the EMA in the trade's direction
    {"kind": "holds_above", "price": 640.0, "bars": 3}   # last N closes above the price
    {"kind": "holds_below", "price": 640.0, "bars": 3}
    {"kind": "guard_symbol", "symbol": "SPY", "op": ">=", "price": 640.0}
    {"kind": "time_at", "et": "09:45"}                   # bar's ET wall-clock at/after

Pure: no I/O, no settings — closes/bar arrive as arguments; cross-symbol
guards read through the injected `quote_of` (None in replay: the guard reports
itself unsupported and the caller degrades to watch-only, journaled).
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from ..domain import Bar

ET = ZoneInfo("America/New_York")

SUPPORTED = {"ema_reclaim", "holds_above", "holds_below", "guard_symbol", "time_at"}


def ema(closes: list[float], period: int) -> float | None:
    """Standard EMA over the trailing closes; None until `period` closes exist."""
    if period <= 0 or len(closes) < period:
        return None
    k = 2.0 / (period + 1)
    val = sum(closes[:period]) / period          # SMA seed
    for c in closes[period:]:
        val = c * k + val * (1 - k)
    return val


def evaluate_guards(guards: list[dict] | None, *, direction: str, bar: Bar,
                    closes: list[float], quote_of=None) -> tuple[bool, list[str]]:
    """(all_pass, reasons_for_the_blocked_ones). `closes` is the trailing
    window INCLUDING `bar`'s close, oldest first."""
    if not guards:
        return True, []
    long = direction != "short"
    reasons: list[str] = []
    for g in guards:
        kind = str((g or {}).get("kind") or "")
        if kind == "ema_reclaim":
            period = int(g.get("period") or 8)
            e = ema(closes, period)
            if e is None:
                reasons.append(f"ema_reclaim: warming up ({len(closes)}/{period} bars)")
            elif not (bar.close > e if long else bar.close < e):
                reasons.append(f"ema_reclaim: close {bar.close:g} not "
                               f"{'above' if long else 'below'} EMA{period} {e:.2f}")
        elif kind in ("holds_above", "holds_below"):
            price = float(g.get("price") or 0)
            n = max(1, int(g.get("bars") or 3))
            window = closes[-n:]
            above = kind == "holds_above"
            if len(window) < n:
                reasons.append(f"{kind}: warming up ({len(window)}/{n} bars)")
            elif not all((c > price) if above else (c < price) for c in window):
                reasons.append(f"{kind} {price:g}: not held for {n} bar(s)")
        elif kind == "guard_symbol":
            if quote_of is None:
                reasons.append("guard_symbol: unsupported here (no live quotes) — watch-only")
                continue
            sym = str(g.get("symbol") or "").upper()
            q = quote_of(sym)
            px = float(getattr(q, "last", 0) or 0) if q is not None else 0.0
            if px <= 0:
                reasons.append(f"guard_symbol: no quote for {sym}")
                continue
            price = float(g.get("price") or 0)
            op = str(g.get("op") or ">=")
            ok = px >= price if op in (">=", ">") else px <= price
            if not ok:
                reasons.append(f"guard_symbol: {sym} {px:g} not {op} {price:g}")
        elif kind == "time_at":
            want = str(g.get("et") or "09:30")
            try:
                hh, mm = (int(x) for x in want.split(":"))
            except ValueError:
                reasons.append(f"time_at: bad time {want!r} — watch-only")
                continue
            t = dt.datetime.fromtimestamp(bar.ts / 1000, ET)
            if (t.hour, t.minute) < (hh, mm):
                reasons.append(f"time_at: waiting for {want} ET")
        else:
            reasons.append(f"unsupported guard {kind!r} — watch-only")
    return (not reasons), reasons
