"""US equity session clock (ET): the four windows of a trading day, session
dates and bounds. Shared by every technique — a schedule rule (EM's R6) is a
*choice* of windows (`MarketRules.windows`), not a property of the clock."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
WINDOW_RULE = {"prime_open": "R6.1", "prime_close": "R6.2", "midday": "R6.3", "extended": "R6.4"}
PRIME_WINDOWS = ("prime_open", "prime_close")


def session_window(ts_ms: int) -> str:
    """Classify an instant by the book's trading schedule (pp. 114-115):
    prime_open 09:30-10:30, midday 10:30-14:45, prime_close 14:45-16:00,
    extended for pre-market / after-hours / weekends. Times are ET."""
    t = dt.datetime.fromtimestamp(ts_ms / 1000, ET)
    if t.weekday() >= 5:
        return "extended"
    m = t.hour * 60 + t.minute
    if 9 * 60 + 30 <= m < 10 * 60 + 30:
        return "prime_open"
    if 10 * 60 + 30 <= m < 14 * 60 + 45:
        return "midday"
    if 14 * 60 + 45 <= m < 16 * 60:
        return "prime_close"
    return "extended"


def is_prime(ts_ms: int) -> bool:
    return session_window(ts_ms) in PRIME_WINDOWS


def session_date(ts_ms: int) -> str:
    """ET calendar date (YYYY-MM-DD) of an instant."""
    return dt.datetime.fromtimestamp(ts_ms / 1000, ET).strftime("%Y-%m-%d")


def session_bounds(date: str) -> tuple[int, int]:
    """(open_ms, close_ms) of the regular session on an ET date. Early-close days
    (13:00 ET: July 3, Black Friday, Christmas Eve) come from the market calendar
    (2026-09-03, Team2 desk — every technique's clock-driven close now honours them)."""
    from .market_calendar import session_close_minutes
    y, m, d = (int(x) for x in date.split("-"))
    o = dt.datetime(y, m, d, 9, 30, tzinfo=ET)
    close_min = session_close_minutes(dt.date(y, m, d))
    c = dt.datetime(y, m, d, close_min // 60, close_min % 60, tzinfo=ET)
    return int(o.timestamp() * 1000), int(c.timestamp() * 1000)


def next_session_date(ts_ms: int) -> str:
    """The next regular session after `ts_ms` — skips weekends AND exchange
    holidays (market calendar, 2026-09-03; before that a holiday yielded a
    session with no bars)."""
    from .market_calendar import is_trading_day
    t = dt.datetime.fromtimestamp(ts_ms / 1000, ET)
    d = t.date()
    # before the open counts as "today's" session
    if t.hour * 60 + t.minute < 9 * 60 + 30 and is_trading_day(d):
        return d.strftime("%Y-%m-%d")
    d = d + dt.timedelta(days=1)
    while not is_trading_day(d):
        d += dt.timedelta(days=1)
    return d.strftime("%Y-%m-%d")

