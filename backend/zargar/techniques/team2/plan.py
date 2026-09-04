"""Team2 session plans — the nightly skeleton and its 09:25 completion (PLAN §1, E11).

A plan is DATA the runner and the simulation act on:

    {"technique": "team2", "symbol": "SPY", "date": "2026-09-04", "version": 1,
     "zones": {"pdh": {...}, "pdl": {...}}, "prevSession": "2026-09-03",
     "targets": {"above": 775.29, "below": 756.10},
     "pmh": 767.78, "pml": 763.59, "dayType": "normal", "openPrice": 766.2,
     "sizingAtOpen": "small", "sheet": "SPY: PDH zone … room up to 775.29 …",
     "complete": True, "thresholds": {...Team2Rules...}}

- `build_skeleton(symbol, date, prev_bars_15m)` after the close: zones from the previous
  session's 15m RTH bars, targets from the lookback, no PM data yet (`complete=False`).
- `complete_plan(skeleton, today_bars_1m)` at 09:25 (or whenever the first bars of the day
  exist): PMH/PML, day type, the open (first RTH bar, else last pre-market close), sizing at
  the open, the sheet line. Idempotent; call again at 09:31 to lock the true open.
"""
from __future__ import annotations

import datetime as dt

from ...domain import Bar
from ...marketstructure.aggregate import aggregate, bar_session, filter_session
from ...marketstructure.dailylevels import premarket_range, prior_day_zones
from ...marketstructure.market_calendar import previous_trading_day
from ...marketstructure.sessions import session_date
from .levels import level_sheet, targets_beyond
from .rules import Team2Rules
from .scenario import classify_day, sizing_bucket

PLAN_VERSION = 1


def build_skeleton(symbol: str, date: str, prev_bars_15m: list[Bar], rules: Team2Rules) -> dict | None:
    """`prev_bars_15m`: 15m bars (RTH; extra sessions are used for targets) ending with the
    previous trading session. Returns None when the previous session has no bars."""
    prev = previous_trading_day(date).isoformat()
    rth = [b for b in prev_bars_15m if bar_session(b.ts) == "rth"]
    prev_day = [b for b in rth if session_date(b.ts) == prev]
    if not prev_day:
        # tolerate a plan built from bars whose last session differs from the calendar (data gap)
        dates = sorted({session_date(b.ts) for b in rth if session_date(b.ts) < date})
        if not dates:
            return None
        prev = dates[-1]
        prev_day = [b for b in rth if session_date(b.ts) == prev]
    zones = prior_day_zones(prev_day)
    if zones is None:
        return None
    targets = targets_beyond(rth, zones, lookback_sessions=rules.target_lookback_sessions)
    return {
        "technique": "team2", "symbol": symbol.upper(), "date": date, "version": PLAN_VERSION,
        "prevSession": prev,
        "zones": {"pdh": zones["pdh"].to_dict(), "pdl": zones["pdl"].to_dict()},
        "targets": {"above": targets["above"], "below": targets["below"]},
        "pmh": None, "pml": None, "dayType": None, "openPrice": None, "sizingAtOpen": None,
        "sheet": level_sheet(symbol.upper(), zones, None, None, targets),
        "complete": False, "thresholds": rules.to_dict(),
        "builtAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }


def complete_plan(skeleton: dict, today_bars_1m: list[Bar]) -> dict:
    from ...marketstructure.dailylevels import Zone
    plan = dict(skeleton)
    date = plan["date"]
    zones = {k: Zone(k, top=v["top"], bottom=v["bottom"], date=plan["prevSession"], anchor_ts=v.get("anchorTs") or 0)
             for k, v in plan["zones"].items()}
    today = [b for b in today_bars_1m if session_date(b.ts) == date]
    pmh, pml = premarket_range(today, date)
    rth = filter_session(today, "rth")
    if rth:
        open_price = sorted(rth, key=lambda b: b.ts)[0].open
        open_src = "rth_open"
    else:
        pre = filter_session(today, "pre")
        open_price = sorted(pre, key=lambda b: b.ts)[-1].close if pre else None
        open_src = "premarket_last" if pre else None
    plan.update({"pmh": pmh, "pml": pml})
    if open_price is not None:
        plan["openPrice"] = float(open_price)
        plan["openSource"] = open_src
        plan["dayType"] = classify_day(float(open_price), zones, pmh, pml)
        plan["sizingAtOpen"] = sizing_bucket(float(open_price), zones, pmh, pml)
    plan["sheet"] = level_sheet(plan["symbol"], zones, pmh, pml, plan["targets"], plan.get("dayType"))
    plan["complete"] = pmh is not None and open_price is not None
    plan["completedAt"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    return plan


def fifteen_from_1m(bars1m: list[Bar]) -> list[Bar]:
    """Convenience for callers holding 1m history: RTH 15m bars."""
    return [b for b in aggregate(bars1m, 15) if bar_session(b.ts) == "rth"]


__all__ = ["build_skeleton", "complete_plan", "fifteen_from_1m", "PLAN_VERSION"]
