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
    """(open_ms, close_ms) of the regular session on an ET date."""
    y, m, d = (int(x) for x in date.split("-"))
    o = dt.datetime(y, m, d, 9, 30, tzinfo=ET)
    c = dt.datetime(y, m, d, 16, 0, tzinfo=ET)
    return int(o.timestamp() * 1000), int(c.timestamp() * 1000)


def next_session_date(ts_ms: int) -> str:
    """The next regular session after `ts_ms` (skips weekends; holidays are not
    modelled — a holiday simply yields a session with no bars)."""
    t = dt.datetime.fromtimestamp(ts_ms / 1000, ET)
    d = t.date()
    # before the open counts as "today's" session
    if t.hour * 60 + t.minute < 9 * 60 + 30 and d.weekday() < 5:
        return d.strftime("%Y-%m-%d")
    d = d + dt.timedelta(days=1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d.strftime("%Y-%m-%d")

