"""US equity market calendar — NYSE holidays and 13:00 early closes (pure, rule-based).

Added 2026-09-03 for the Team2 technique (its prior-day levels and its flatten time depend on
the real session), shared by everyone: `sessions.session_bounds` consults `session_close_minutes`
so a half day closes at 13:00 for every technique, and `sessions.next_session_date` skips
holidays. Rules are NYSE's published ones; no network. Verified against the 2024–2026 NYSE
schedule when written. If the exchange announces a special closure (e.g. a national day of
mourning) add the date to `SPECIAL_CLOSURES`.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

# one-off closures the rules cannot derive (YYYY-MM-DD)
SPECIAL_CLOSURES: frozenset[str] = frozenset({
    "2025-01-09",   # National Day of Mourning (President Carter)
})

RTH_CLOSE_MIN = 16 * 60
EARLY_CLOSE_MIN = 13 * 60


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """n-th (1-based) `weekday` (Mon=0) of a month; n=-1 → last."""
    if n > 0:
        d = dt.date(year, month, 1)
        off = (weekday - d.weekday()) % 7
        return d + dt.timedelta(days=off + 7 * (n - 1))
    d = dt.date(year + (month == 12), (month % 12) + 1, 1) - dt.timedelta(days=1)
    off = (d.weekday() - weekday) % 7
    return d - dt.timedelta(days=off)


def _observed(d: dt.date) -> dt.date:
    """Weekend holidays: Saturday → Friday, Sunday → Monday (NYSE rule; a Saturday
    New Year's Day is NOT observed on the prior Friday — handled by the caller)."""
    if d.weekday() == 5:
        return d - dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + dt.timedelta(days=1)
    return d


def easter(year: int) -> dt.date:
    """Gregorian Easter Sunday (Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(year, month, day)


@lru_cache(maxsize=64)
def holidays(year: int) -> frozenset[dt.date]:
    out: set[dt.date] = set()
    ny = dt.date(year, 1, 1)
    if ny.weekday() == 6:
        out.add(ny + dt.timedelta(days=1))
    elif ny.weekday() < 5:
        out.add(ny)                                  # a Saturday Jan 1 is not observed
    out.add(_nth_weekday(year, 1, 0, 3))             # MLK Day
    out.add(_nth_weekday(year, 2, 0, 3))             # Presidents' Day
    out.add(easter(year) - dt.timedelta(days=2))     # Good Friday
    out.add(_nth_weekday(year, 5, 0, -1))            # Memorial Day
    if year >= 2022:
        out.add(_observed(dt.date(year, 6, 19)))     # Juneteenth
    out.add(_observed(dt.date(year, 7, 4)))          # Independence Day
    out.add(_nth_weekday(year, 9, 0, 1))             # Labor Day
    out.add(_nth_weekday(year, 11, 3, 4))            # Thanksgiving
    out.add(_observed(dt.date(year, 12, 25)))        # Christmas
    for s in SPECIAL_CLOSURES:
        d = dt.date.fromisoformat(s)
        if d.year == year:
            out.add(d)
    return frozenset(out)


@lru_cache(maxsize=64)
def early_closes(year: int) -> frozenset[dt.date]:
    """13:00 ET closes: July 3 (when a weekday and July 4 is not a weekend-observed
    Monday/Friday shift onto it), the day after Thanksgiving, Christmas Eve (weekday)."""
    out: set[dt.date] = set()
    j3 = dt.date(year, 7, 3)
    if j3.weekday() < 5 and j3 not in holidays(year):
        out.add(j3)
    out.add(_nth_weekday(year, 11, 3, 4) + dt.timedelta(days=1))
    ce = dt.date(year, 12, 24)
    if ce.weekday() < 5 and ce not in holidays(year):
        out.add(ce)
    return frozenset(out)


def is_trading_day(d: dt.date | str) -> bool:
    d = dt.date.fromisoformat(d) if isinstance(d, str) else d
    return d.weekday() < 5 and d not in holidays(d.year)


def is_early_close(d: dt.date | str) -> bool:
    d = dt.date.fromisoformat(d) if isinstance(d, str) else d
    return is_trading_day(d) and d in early_closes(d.year)


def session_close_minutes(d: dt.date | str) -> int:
    """Minutes after ET midnight when the regular session closes (960 or 780)."""
    return EARLY_CLOSE_MIN if is_early_close(d) else RTH_CLOSE_MIN


def previous_trading_day(d: dt.date | str) -> dt.date:
    d = dt.date.fromisoformat(d) if isinstance(d, str) else d
    d -= dt.timedelta(days=1)
    while not is_trading_day(d):
        d -= dt.timedelta(days=1)
    return d


def next_trading_day(d: dt.date | str) -> dt.date:
    d = dt.date.fromisoformat(d) if isinstance(d, str) else d
    d += dt.timedelta(days=1)
    while not is_trading_day(d):
        d += dt.timedelta(days=1)
    return d


def trading_days(start: dt.date | str, end: dt.date | str) -> list[dt.date]:
    a = dt.date.fromisoformat(start) if isinstance(start, str) else start
    b = dt.date.fromisoformat(end) if isinstance(end, str) else end
    out = []
    d = a
    while d <= b:
        if is_trading_day(d):
            out.append(d)
        d += dt.timedelta(days=1)
    return out


__all__ = ["holidays", "early_closes", "is_trading_day", "is_early_close", "session_close_minutes",
           "previous_trading_day", "next_trading_day", "trading_days", "easter", "SPECIAL_CLOSURES",
           "RTH_CLOSE_MIN", "EARLY_CLOSE_MIN"]
