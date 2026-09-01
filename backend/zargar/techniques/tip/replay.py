"""Replay a STALE tip on history instead of trading it.

A tip whose content shows a post date older than `techniques.tip.max_tip_age_hours`
must not enter the books (it would trade today's price against a weeks-old
thesis) — but it is still evidence. This module answers "what would both books
have done had the tip arrived on time": the armed book via the real plan
builder + the real walk-forward simulator, the immediate book via a plain
bar walk from the tip-time price. The result rides on the signal
(`extraction.replay`) for the UI and any scorecard discussion; no orders, no
journal money events, no shadow portfolios touched.

1h bars (Yahoo keeps ~2 years) — coarse enough to reach back, fine enough for
level-touch fills. The fetcher is injectable for tests.
"""
from __future__ import annotations

import datetime as dt
import logging

from ...domain import Bar
from ...marketstructure.history import fetch_window
from ...marketstructure.outcome import simulate_plan
from .plan import build_tip_plan

log = logging.getLogger(__name__)

BARS_PER_SESSION = 7          # RTH 1h bars
LOOKBACK_DAYS = 45            # history before the tip for levels/ATR


async def replay_tip(
    *,
    symbol: str,
    direction: str,
    stated_at_ms: int,
    tip_entry: float | None = None,
    tip_stop: float | None = None,
    tip_targets: tuple[float, ...] | list[float] = (),
    horizon_sessions: int = 15,
    source: str | None = None,
    thesis: str = "",
    stated_premium: float | None = None,
    fetch=fetch_window,
) -> dict:
    """Both books' counterfactuals for a tip stated at `stated_at_ms`."""
    now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    start_ms = stated_at_ms - LOOKBACK_DAYS * 86_400_000
    try:
        bars: list[Bar] = await fetch(symbol, "1h", start_ms, now_ms)
    except Exception as exc:
        return {"ok": False, "note": f"no history for the replay: {exc}"}
    past_idx = [i for i, b in enumerate(bars) if b.ts <= stated_at_ms]
    if not past_idx or len(bars) - past_idx[-1] < 2:
        return {"ok": False, "note": "tip time is outside the available 1h history"}
    start = past_idx[-1]
    ref = float(bars[start].close)
    long = direction == "long"
    sgn = 1.0 if long else -1.0

    # F4 (batch-1): an option tip's stated numbers are often the PREMIUM ladder,
    # not underlying levels — loading them as underlying targets fabricated
    # +99% prints (MU 850P). When a premium is stated and EVERY stated number
    # sits far below the reference and near the premium, they are premium-basis:
    # the underlying plan builds from structure alone, and the record says so.
    premium_basis = False
    if stated_premium:
        nums = [x for x in (tip_entry, tip_stop, *tuple(tip_targets or ())) if x]
        if nums and all(x < ref * 0.3 and x <= stated_premium * 8 for x in nums):
            premium_basis = True
            tip_entry = tip_stop = None
            tip_targets = ()

    # --- armed book: the exact machinery the live path uses -----------------
    plan = build_tip_plan(
        symbol=symbol, direction=direction, reference_price=ref,
        bars=bars[: start + 1], as_of_ms=stated_at_ms, entry_mode="level_touch",
        tip_entry=tip_entry, tip_stop=tip_stop, tip_targets=tuple(tip_targets or ()),
        horizon_sessions=horizon_sessions, source=source, thesis=thesis)
    trg = plan.triggers[0]
    window = horizon_sessions * BARS_PER_SESSION
    plan_dict = {"setupType": trg.kind, "direction": direction,
                 "entry": {"price": trg.entry_price, "basis": trg.entry_basis},
                 "stop": {"price": trg.stop_price},
                 "targets": [{"price": t["price"]} for t in trg.targets]}
    if trg.kind in ("breakout", "breakdown"):
        # emulate the live tracker: a breakout fills on the first CLOSE through
        # the level (raw on_break would fill at the tip bar, at_level would
        # phantom-fill a level that is above/below the market)
        last_i = min(start + window, len(bars) - 1)
        cross = next((i for i in range(start + 1, last_i + 1)
                      if (bars[i].close >= trg.entry_price if long
                          else bars[i].close <= trg.entry_price)), None)
        if cross is None:
            sim = {"filled": False, "outcome": "not_filled", "rMultiple": 0.0,
                   "mfeR": 0.0, "resolved": (len(bars) - 1) >= start + window}
        else:
            sim = simulate_plan(bars, cross, plan_dict,
                                entry_window=window, horizon=window)
    else:
        sim = simulate_plan(bars, start, plan_dict,
                            entry_window=window, horizon=window)

    # --- immediate book: buy the tip-time price, tip bracket else time exit --
    cap = start + horizon_sessions * BARS_PER_SESSION
    exit_px, exit_reason, exit_i = None, "horizon", min(cap, len(bars) - 1)
    for i in range(start + 1, min(cap, len(bars) - 1) + 1):
        b = bars[i]
        if tip_stop is not None and (b.low <= tip_stop if long else b.high >= tip_stop):
            exit_px, exit_reason, exit_i = float(tip_stop), "stop", i
            break
        first_t = (tip_targets or [None])[0]
        if first_t is not None and (b.high >= first_t if long else b.low <= first_t):
            exit_px, exit_reason, exit_i = float(first_t), "target", i
            break
    if exit_px is None:
        exit_px = float(bars[exit_i].close)
    last = float(bars[-1].close)
    immediate = {
        "entry": round(ref, 4), "exit": round(exit_px, 4), "reason": exit_reason,
        "pnlPct": round(sgn * (exit_px / ref - 1) * 100, 2),
        "toTodayPct": round(sgn * (last / ref - 1) * 100, 2),
        "barsHeld": exit_i - start,
    }
    return {
        "ok": True,
        "asOf": dt.datetime.fromtimestamp(stated_at_ms / 1000, dt.timezone.utc).isoformat(),
        "referencePrice": round(ref, 4),
        "lastPrice": round(last, 4),
        "armed": {
            "entry": trg.entry_price, "stop": trg.stop_price,
            "targets": [t["price"] for t in trg.targets],
            "filled": sim["filled"], "outcome": sim["outcome"],
            "rMultiple": sim["rMultiple"], "mfeR": sim["mfeR"],
            "resolved": sim["resolved"], "notes": trg.notes,
            # F6: a plan the replay CONSTRUCTED (no structural level — ATR
            # pullback) is not the tip's own plan; its ±R is not tip evidence
            "constructed": any("no structural level" in str(n)
                               for n in (trg.notes or [])),
            "premiumBasis": premium_basis,
        },
        "immediate": immediate,
    }
