"""Shared market-structure primitives added for the Team2 technique (2026-09-03):
timeframe aggregation on wall-clock buckets, the extended-hours session clock, the market
calendar (holidays + 13:00 closes), EMA series/stack/fan, prior-day zones and the
pre-market range, plus the macro-calendar placeholder. Pure functions — no DB, no network."""
from __future__ import annotations

import datetime as dt

import pytest

from zargar.domain import Bar
from zargar.marketstructure import (
    EmaState, Zone, aggregate, bar_session, bucket_start_ms, closed_bars, ema_series, ema_stack, fan_state,
    fan_width, filter_session, is_early_close, is_trading_day, next_session_date, next_trading_day,
    premarket_range, previous_trading_day, prior_day_zones, session_bounds, session_close_minutes,
    session_extremes,
)
from zargar.marketstructure.market_calendar import easter, holidays
from zargar.marketstructure.sessions import ET
from zargar.research.macro_calendar import MacroCalendar

# 2026-09-02 (Wed) is an ordinary trading day
DAY = dt.date(2026, 9, 2)


def ms(h: int, m: int, day: dt.date = DAY) -> int:
    return int(dt.datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp() * 1000)


def bar(h: int, m: int, o=100.0, hi=None, lo=None, c=None, v=10, day: dt.date = DAY, sym="SPY") -> Bar:
    c = o if c is None else c
    return Bar(sym, "1m", ms(h, m, day), o, hi if hi is not None else max(o, c) + 0.5,
               lo if lo is not None else min(o, c) - 0.5, c, v)


# ---------------------------------------------------------------- market calendar
def test_calendar_holidays_and_early_closes_match_nyse():
    assert easter(2026) == dt.date(2026, 4, 5)
    h = holidays(2026)
    for d in ("2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
              "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"):
        assert dt.date.fromisoformat(d) in h, d
    # 2026-07-04 is a Saturday → observed Friday July 3; so July 3 is a holiday, not an early close
    assert not is_early_close("2026-07-03")
    assert is_early_close("2026-11-27")           # day after Thanksgiving
    assert is_early_close("2026-12-24")           # Thursday
    assert session_close_minutes("2026-11-27") == 13 * 60
    assert session_close_minutes("2026-09-02") == 16 * 60
    assert not is_trading_day("2026-09-07")       # Labor Day
    assert not is_trading_day("2026-09-05")       # Saturday
    assert is_trading_day("2026-09-04")
    assert dt.date(2025, 1, 9) in holidays(2025)  # special closure
    # Saturday Jan 1 (2022) is NOT observed on Friday Dec 31 2021
    assert dt.date(2021, 12, 31) not in holidays(2021)
    assert dt.date(2022, 1, 1) not in holidays(2022)


def test_calendar_neighbours_skip_holidays():
    assert previous_trading_day("2026-09-08") == dt.date(2026, 9, 4)    # over Labor Day + weekend
    assert next_trading_day("2026-09-04") == dt.date(2026, 9, 8)
    # sessions clock now honours the calendar
    assert next_session_date(ms(16, 30, dt.date(2026, 9, 4))) == "2026-09-08"
    o, c = session_bounds("2026-11-27")
    assert dt.datetime.fromtimestamp(c / 1000, ET).hour == 13
    o, c = session_bounds("2026-09-02")
    assert dt.datetime.fromtimestamp(c / 1000, ET).hour == 16


# ---------------------------------------------------------------- session clock
def test_bar_session_classification():
    assert bar_session(ms(4, 0)) == "pre"
    assert bar_session(ms(9, 29)) == "pre"
    assert bar_session(ms(9, 30)) == "rth"
    assert bar_session(ms(15, 59)) == "rth"
    assert bar_session(ms(16, 0)) == "post"
    assert bar_session(ms(19, 59)) == "post"
    assert bar_session(ms(20, 0)) == "closed"
    assert bar_session(ms(3, 59)) == "closed"
    assert bar_session(ms(10, 0, dt.date(2026, 9, 5))) == "closed"     # Saturday
    assert bar_session(ms(10, 0, dt.date(2026, 9, 7))) == "closed"     # Labor Day
    # early close: 13:30 is post-market on Black Friday
    assert bar_session(ms(13, 30, dt.date(2026, 11, 27))) == "post"
    assert bar_session(ms(12, 59, dt.date(2026, 11, 27))) == "rth"


def test_filter_session_keeps_only_requested():
    bars = [bar(9, 0), bar(9, 30), bar(12, 0), bar(16, 5)]
    assert [b.ts for b in filter_session(bars, "rth")] == [bars[1].ts, bars[2].ts]
    assert [b.ts for b in filter_session(bars, {"pre", "post"})] == [bars[0].ts, bars[3].ts]


# ---------------------------------------------------------------- aggregation
def test_aggregate_2m_wall_clock_buckets_survive_missing_minutes():
    # 09:30, 09:31 form one 2m bar; 09:32 alone (09:33 missing) forms the next; 09:35 → 09:34 bucket
    bars = [bar(9, 30, 100, 101, 99.5, 100.5, v=1), bar(9, 31, 100.5, 102, 100, 101.5, v=2),
            bar(9, 32, 101.5, 101.8, 101, 101.2, v=3), bar(9, 35, 101.2, 101.4, 100.9, 101.0, v=4)]
    out = aggregate(bars, 2)
    assert [dt.datetime.fromtimestamp(b.ts / 1000, ET).strftime("%H:%M") for b in out] == ["09:30", "09:32", "09:34"]
    first = out[0]
    assert (first.open, first.high, first.low, first.close, first.volume) == (100, 102, 99.5, 101.5, 3)
    assert out[0].tf == "2m"
    # order-independent
    assert aggregate(list(reversed(bars)), 2) == out


def test_aggregate_15m_grid_is_30_45_00_15_and_pre_market_bucket_does_not_leak_into_rth():
    bars = [bar(9, 20), bar(9, 29), bar(9, 30), bar(9, 44), bar(9, 45)]
    out = aggregate(bars, 15)
    stamps = [dt.datetime.fromtimestamp(b.ts / 1000, ET).strftime("%H:%M") for b in out]
    assert stamps == ["09:15", "09:30", "09:45"]
    assert bar_session(out[0].ts) == "pre" and bar_session(out[1].ts) == "rth"


def test_closed_bars_excludes_the_forming_bucket():
    bars = [bar(9, 30), bar(9, 31), bar(9, 32)]
    assert len(closed_bars(bars, 2, now_ms=ms(9, 33))) == 1     # 09:32 bucket closes at 09:34
    assert len(closed_bars(bars, 2, now_ms=ms(9, 34))) == 2


def test_aggregate_rejects_mixed_symbols_and_odd_sizes():
    with pytest.raises(ValueError):
        aggregate([bar(9, 30), bar(9, 31, sym="QQQ")], 2)
    with pytest.raises(ValueError):
        aggregate([bar(9, 30)], 7)
    assert bucket_start_ms(ms(9, 33), 2) == ms(9, 32)
    assert bucket_start_ms(ms(9, 59), 15) == ms(9, 45)


# ---------------------------------------------------------------- indicators
def test_ema_series_matches_incremental_state_and_seeds_with_sma():
    closes = [float(x) for x in (10, 11, 12, 13, 14, 15, 16, 15, 14, 13, 12)]
    series = ema_series(closes, 3)
    assert series[:2] == [None, None]
    assert series[2] == pytest.approx(11.0)             # SMA seed
    assert series[3] == pytest.approx((13 - 11) * 0.5 + 11)
    st = EmaState(3)
    inc = [st.update(c) for c in closes]
    for a, b in zip(series, inc):
        assert (a is None and b is None) or a == pytest.approx(b)
    # state survives a round trip (restart / next session)
    st2 = EmaState.from_dict(st.to_dict())
    assert st2.update(11.0) == pytest.approx(EmaState.from_dict(st.to_dict()).update(11.0))


def test_ema_stack_and_fan():
    r = ema_stack(price=101.0, fast=100.5, mid=100.0, slow=99.0)
    assert r.stack == "bull" and r.strength == 3 and r.above_slow is True
    r = ema_stack(price=100.2, fast=100.5, mid=100.0, slow=99.0)
    assert r.stack == "bull" and r.strength == 2               # above slow + mid, below fast
    r = ema_stack(price=98.0, fast=99.0, mid=100.0, slow=101.0)
    assert r.stack == "bear" and r.strength == 3
    assert ema_stack(100.0, 100.0, 101.0, 99.0).stack == "mixed"
    assert ema_stack(100.0, None, 101.0, 99.0).stack == "mixed"
    w = fan_width(100.5, 100.0, 99.0, scale=0.5)
    assert w == pytest.approx(3.0)
    assert fan_state(w, trend_min=1.0) == "trend"
    assert fan_state(0.4, trend_min=1.0) == "chop"
    assert fan_state(None, trend_min=1.0) == "unknown"


# ---------------------------------------------------------------- daily levels
def _session_15m(day: dt.date) -> list[Bar]:
    """A synthetic RTH day on 15m bars: high-of-day wick at 13:00 (bar body 569.9-570.2,
    wick 570.31), next bar body 569.0-569.6; low-of-day wick at 10:30 (561.70), next body 562.3-562.9."""
    rows = []
    t = dt.datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET)
    while t.hour * 60 + t.minute < 16 * 60:
        rows.append(Bar("SPY", "15m", int(t.timestamp() * 1000), 565, 565.8, 564.4, 565.2, 100))
        t += dt.timedelta(minutes=15)
    by = {dt.datetime.fromtimestamp(b.ts / 1000, ET).strftime("%H:%M"): b for b in rows}
    by["13:00"].open, by["13:00"].close, by["13:00"].high = 569.9, 570.2, 570.31
    by["13:15"].open, by["13:15"].close = 569.6, 569.0
    by["10:30"].open, by["10:30"].close, by["10:30"].low = 562.6, 562.1, 561.70
    by["10:45"].open, by["10:45"].close = 562.3, 562.9
    return rows


def test_prior_day_zones_wick_to_following_body():
    z = prior_day_zones(_session_15m(DAY))
    assert z is not None
    pdh, pdl = z["pdh"], z["pdl"]
    assert pdh.top == pytest.approx(570.31) and pdh.bottom == pytest.approx(569.6)   # following candle's higher body edge
    assert pdl.bottom == pytest.approx(561.70) and pdl.top == pytest.approx(562.3)   # following candle's lower body edge
    assert pdh.date == "2026-09-02" and pdh.width > 0 and pdl.width > 0
    assert pdh.above(570.5) and not pdh.above(570.0) and pdh.contains(570.0)
    assert pdl.below(561.5) and pdl.contains(562.0)
    assert isinstance(pdh.to_dict()["width"], float)


def test_prior_day_zones_extreme_on_last_bar_collapses_to_its_body():
    rows = _session_15m(DAY)
    last = rows[-1]
    last.high, last.open, last.close = 575.0, 574.2, 574.8
    z = prior_day_zones(rows)
    assert z["pdh"].top == pytest.approx(575.0) and z["pdh"].bottom == pytest.approx(574.8)


def test_premarket_range_and_session_extremes():
    bars = [bar(4, 5, 100, 100.4, 99.8, 100.2), bar(8, 0, 100.2, 101.3, 100.1, 101.0),
            bar(9, 15, 101.0, 101.1, 99.2, 99.5), bar(9, 30, 99.5, 103.0, 99.4, 102.0),
            bar(15, 59, 102.0, 102.5, 98.0, 98.5)]
    pmh, pml = premarket_range(bars, "2026-09-02")
    assert (pmh, pml) == (101.3, 99.2)
    assert premarket_range(bars, "2026-09-03") == (None, None)
    hi, lo = session_extremes(bars, "2026-09-02")
    assert (hi, lo) == (103.0, 98.0)


# ---------------------------------------------------------------- macro calendar placeholder
class _Settings:
    def __init__(self, rows):
        self.rows = rows

    def get(self, key, default=None):
        return self.rows if key == "research.macro_events" else default


def test_macro_calendar_manual_list():
    cal = MacroCalendar(_Settings([
        {"date": "2026-09-17", "name": "FOMC decision", "kind": "fomc", "time": "14:00"},
        {"date": "2026-09-11", "name": "CPI", "kind": "cpi"},
        {"date": "not-a-date", "name": "junk"},
        {"date": "2026-09-11", "name": "odd", "kind": "weird"},
    ]))
    assert cal.is_event_day("2026-09-17") and cal.is_event_day(dt.date(2026, 9, 11))
    assert not cal.is_event_day("2026-09-16")
    assert cal.is_event_day("2026-09-17", kinds=("fomc",)) and not cal.is_event_day("2026-09-11", kinds=("fomc",))
    kinds = {e.kind for e in cal.events_on("2026-09-11")}
    assert kinds == {"cpi", "other"}
    assert [e.date for e in cal.upcoming("2026-09-10", days=10)] == ["2026-09-11", "2026-09-11", "2026-09-17"]
    d = cal.describe()
    assert d["source"] == "manual" and d["events"] == 3
    assert MacroCalendar(_Settings([])).describe()["next"] is None
