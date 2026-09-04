"""Timeframe aggregation and the extended-hours session clock (pure functions).

Built for the Team2 technique (2026-09-03) and shared by every technique:

- `bar_session(ts_ms)` → "pre" (04:00–09:30 ET) | "rth" (09:30–16:00) | "post" (16:00–20:00)
  | "closed". The regular-session close respects early-close days via
  `market_calendar.session_close_minutes`.
- `aggregate(bars, minutes)` → closed N-minute bars on WALL-CLOCK buckets anchored at ET
  midnight, so a missing 1m bar (pre-market is sparse) never shifts the grid: the 2m grid is
  :30/:32/…, the 15m grid :30/:45/:00/:15. A bucket never spans a session boundary
  (pre → rth → post) because 04:00, 09:30, 16:00 and 20:00 all fall on 2/5/10/15/30-minute
  boundaries. Volume sums; open = first bar's open, close = last bar's close.
- `closed_bars(bars, minutes, now_ms)` → the same, minus the bucket still forming at `now_ms`
  (a live consumer must judge only CLOSED bars — PLATFORM-RULES: decisions happen on closed bars).
- `filter_session(bars, sessions)` keeps bars whose session is in the given set — RTH-only
  readers (EM's detectors) call `filter_session(bars, {"rth"})` and see exactly what they saw
  before extended-hours bars existed.
"""
from __future__ import annotations

import datetime as dt

from ..domain import Bar
from .market_calendar import session_close_minutes
from .sessions import ET

PRE_OPEN_MIN = 4 * 60           # 04:00 ET
RTH_OPEN_MIN = 9 * 60 + 30      # 09:30 ET
POST_CLOSE_MIN = 20 * 60        # 20:00 ET
SUPPORTED_MINUTES = (1, 2, 3, 5, 10, 15, 30, 60)


def _et(ts_ms: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts_ms / 1000, ET)


def minute_of_day(ts_ms: int) -> int:
    t = _et(ts_ms)
    return t.hour * 60 + t.minute


def bar_session(ts_ms: int) -> str:
    """Which session a bar OPEN belongs to (ET wall clock; weekends are closed;
    holidays are closed via the market calendar)."""
    t = _et(ts_ms)
    from .market_calendar import is_trading_day
    if t.weekday() >= 5 or not is_trading_day(t.date()):
        return "closed"
    m = t.hour * 60 + t.minute
    close_min = session_close_minutes(t.date())
    if PRE_OPEN_MIN <= m < RTH_OPEN_MIN:
        return "pre"
    if RTH_OPEN_MIN <= m < close_min:
        return "rth"
    if close_min <= m < POST_CLOSE_MIN:
        return "post"
    return "closed"


def filter_session(bars: list[Bar], sessions: set[str] | tuple[str, ...] | str) -> list[Bar]:
    want = {sessions} if isinstance(sessions, str) else set(sessions)
    return [b for b in bars if bar_session(b.ts) in want]


def bucket_start_ms(ts_ms: int, minutes: int) -> int:
    """Start of the wall-clock bucket (ET midnight anchored) containing `ts_ms`."""
    t = _et(ts_ms)
    m = t.hour * 60 + t.minute
    start_min = (m // minutes) * minutes
    day = t.replace(hour=0, minute=0, second=0, microsecond=0)
    return int((day + dt.timedelta(minutes=start_min)).timestamp() * 1000)


def aggregate(bars: list[Bar], minutes: int, *, tf_label: str | None = None) -> list[Bar]:
    """Closed N-minute bars from 1m (or finer-grained) bars. Input need not be sorted or
    contiguous; bars from different symbols are not mixed (the first bar's symbol is used
    and mismatches raise)."""
    if minutes not in SUPPORTED_MINUTES:
        raise ValueError(f"unsupported aggregation: {minutes} minutes")
    if not bars:
        return []
    label = tf_label or (f"{minutes}m" if minutes < 60 else "1h")
    symbol = bars[0].symbol
    out: list[Bar] = []
    cur: Bar | None = None
    cur_start = -1
    for b in sorted(bars, key=lambda x: x.ts):
        if b.symbol != symbol:
            raise ValueError(f"mixed symbols in aggregate: {symbol} vs {b.symbol}")
        start = bucket_start_ms(b.ts, minutes)
        if cur is None or start != cur_start:
            if cur is not None:
                out.append(cur)
            cur = Bar(symbol=symbol, tf=label, ts=start, open=b.open, high=b.high, low=b.low,
                      close=b.close, volume=int(b.volume or 0))
            cur_start = start
        else:
            cur.high = max(cur.high, b.high)
            cur.low = min(cur.low, b.low)
            cur.close = b.close
            cur.volume = int(cur.volume or 0) + int(b.volume or 0)
    if cur is not None:
        out.append(cur)
    return out


def closed_bars(bars: list[Bar], minutes: int, now_ms: int, *, tf_label: str | None = None) -> list[Bar]:
    """Aggregated bars whose bucket has fully elapsed by `now_ms`."""
    agg = aggregate(bars, minutes, tf_label=tf_label)
    span = minutes * 60_000
    return [b for b in agg if b.ts + span <= now_ms]


def bucket_is_closed(bucket_start: int, minutes: int, now_ms: int) -> bool:
    return bucket_start + minutes * 60_000 <= now_ms


__all__ = ["bar_session", "filter_session", "bucket_start_ms", "aggregate", "closed_bars",
           "bucket_is_closed", "minute_of_day", "SUPPORTED_MINUTES", "PRE_OPEN_MIN", "RTH_OPEN_MIN",
           "POST_CLOSE_MIN"]
