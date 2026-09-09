"""Session validation for everything Team2 reads out of the shared `bars` table (F75, 2026-09-09).

The table is not all real market data: the app once ran on the sim feed and banked a random walk as
SPY (08-14..08-19), and it formed flat one-price "sessions" whenever it ran on a closed day
(weekends, Labor Day). `targets_beyond` / `level_ladder` / the 200-EMA warm-up used to take the last
N *dates present*, so a weekend ate a lookback slot and a flat session could contribute a pivot.

This module is the consumer-side guard: every prior-session tape the desk plans, warms up, replays
or sweeps on passes through `validate_sessions` first, and the plan records what was used and what
was excluded (and why). It FLAGS — flatness alone marks a session suspect and keeps it out of the
read; classifying it as synthetic and removing it from the table is the repair tool's job
(`zargar.tools.bars_repair`), on the user's call, with the original rows preserved in quarantine.
"""
from __future__ import annotations

import datetime as dt

from ...domain import Bar
from ...marketstructure.aggregate import filter_session
from ...marketstructure.market_calendar import is_trading_day
from ...marketstructure.sessions import session_date

FLAT_TOL = 1e-4          # RTH range <= this x price: a one-price session (the app ran on a closed day)
OUTLIER_RANGE = 0.15     # RTH range > this x price: not a US index ETF's day (SPY 08-19 "ran" 769–1459)
MIN_RTH_BARS = 30        # fewer regular-session bars than this: the app was down most of the day


def validate_sessions(bars: list[Bar], *, flat_tol: float = FLAT_TOL, outlier_range: float = OUTLIER_RANGE,
                      min_rth_bars: int = MIN_RTH_BARS) -> tuple[list[Bar], dict]:
    """Split prior-session bars into the sessions a read may use and the ones it must not.

    Returns (valid_bars, report) with report = {"used": [dates], "excluded": [{date, reason, rows}]}.
    Reasons: `closed_day` (not a trading day on the NYSE calendar), `thin_rth` (< min_rth_bars
    regular-session bars), `degenerate_flat` (RTH range <= flat_tol x price), `outlier_range`
    (RTH range > outlier_range x price). A session's OWN bars decide — no neighbour heuristics, so
    a slow random walk that drifts through plausible prices is caught by its intraday range, not
    by a day-over-day jump test that it would pass."""
    by_day: dict[str, list[Bar]] = {}
    for b in bars:
        by_day.setdefault(session_date(b.ts), []).append(b)
    used: list[str] = []
    excluded: list[dict] = []
    for d in sorted(by_day):
        rows = by_day[d]
        reason = None
        if not is_trading_day(dt.date.fromisoformat(d)):
            reason = "closed_day"
        else:
            rth = filter_session(rows, "rth")
            if len(rth) < min_rth_bars:
                reason = "thin_rth"
            else:
                hi = max(x.high for x in rth)
                lo = min(x.low for x in rth)
                ref = rth[-1].close or hi
                rng = hi - lo
                if ref <= 0 or rng <= flat_tol * ref:
                    reason = "degenerate_flat"
                elif rng > outlier_range * ref:
                    reason = "outlier_range"
        if reason:
            excluded.append({"date": d, "reason": reason, "rows": len(rows)})
        else:
            used.append(d)
    keep = set(used)
    return [b for b in bars if session_date(b.ts) in keep], {"used": used, "excluded": excluded}
