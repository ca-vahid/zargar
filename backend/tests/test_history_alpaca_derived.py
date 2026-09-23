"""2026-09-23: 1h and 1d history come from Alpaca (1h derived from 30m bars, session-aligned; 1d native, stamped at the open);
Yahoo stays the fallback and the provider for non-US symbols and extended-session requests."""
import asyncio

import pytest

from zargar.domain import Bar
from zargar.marketstructure import history as h
from zargar.marketstructure.sessions import session_bounds

DAY = "2026-09-22"
OPEN = session_bounds(DAY)[0]


def _b(minutes_after_open, o, hi, lo, c, v, tf="30m"):
    return Bar(symbol="SPY", tf=tf, ts=OPEN + minutes_after_open * 60_000, source="exchange", provider="alpaca",
               open=o, high=hi, low=lo, close=c, volume=v)


def test_hours_are_session_aligned_and_the_last_hour_is_the_last_half_hour():
    bars = [_b(30 * i, 100 + i, 101 + i, 99 + i, 100.5 + i, 10 * (i + 1)) for i in range(13)]     # 09:30 .. 15:30
    hours = h.hours_from_30m(bars)
    assert [(b.ts - OPEN) // 60_000 for b in hours] == [0, 60, 120, 180, 240, 300, 360], "09:30, 10:30 ... 15:30 - never clock-aligned"
    first = hours[0]
    assert (first.open, first.high, first.low, first.close, first.volume) == (100, 102, 99, 101.5, 30)
    last = hours[-1]
    assert (last.open, last.close, last.volume) == (112, 112.5, 130) and last.tf == "1h", "15:30-16:00 alone, like Yahoo's last hour"


def test_an_hour_missing_its_first_half_keeps_its_session_stamp():
    hours = h.hours_from_30m([_b(90, 5, 6, 4, 5.5, 7)])                                               # 11:00 only (a halt at 10:30)
    assert [(b.ts - OPEN) // 60_000 for b in hours] == [60]


def test_daily_rows_are_stamped_at_the_session_open_with_official_values():
    days = h.days_from_rows("spy", [{"t": "2026-09-22T04:00:00Z", "o": 774.03, "h": 775.14, "l": 772.57, "c": 773.38, "v": 34_900_000}])
    assert len(days) == 1 and days[0].ts == OPEN and days[0].symbol == "SPY" and days[0].provider == "alpaca"
    assert (days[0].close, days[0].volume) == (773.38, 34_900_000)


@pytest.mark.parametrize("tf", ["1h", "1d"])
def test_routing_alpaca_first_yahoo_for_foreign_and_extended(monkeypatch, tf):
    calls = []

    async def fake_derived(symbol, tf_, s, e, http):
        calls.append(("alpaca", symbol, tf_))
        return [Bar(symbol=symbol, tf=tf_, ts=OPEN, source="exchange", provider="alpaca", open=1, high=1, low=1, close=1, volume=1)]

    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"chart": {"result": [{"timestamp": [OPEN // 1000], "indicators": {"quote": [{"open": [2], "high": [2], "low": [2], "close": [2], "volume": [2]}]}}]}}

    class Http:
        async def get(self, url, params=None, headers=None, timeout=None):
            calls.append(("yahoo", url))
            return Resp()
    monkeypatch.setattr(h, "_alpaca_derived", fake_derived)
    monkeypatch.setitem(h._ALPACA, "key", "k")
    start, end = OPEN - 86_400_000, OPEN + 86_400_000

    async def run(sym, session="rth"):
        h._cache.clear()
        return await h.fetch_window_ex(sym, tf, start, end, client=Http(), session=session)
    import time as _t
    monkeypatch.setattr(h.time, "time", lambda: (OPEN + 2 * 86_400_000) / 1000)
    bars, prov = asyncio.run(run("SPY"))
    assert prov == "alpaca" and calls[-1][0] == "alpaca"
    bars, prov = asyncio.run(run("SHOP.TO"))
    assert prov == "yahoo" and calls[-1][0] == "yahoo", "a foreign listing stays on Yahoo"
    bars, prov = asyncio.run(run("SPY", session="ext"))
    assert prov == "yahoo" and calls[-1][0] == "yahoo", "extended-session 1h/1d stay on Yahoo"
    _ = _t


def test_alpaca_failure_falls_back_to_yahoo(monkeypatch):
    async def boom(*a, **k):
        raise h.HistoryError("Alpaca HTTP 500")

    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"chart": {"result": [{"timestamp": [OPEN // 1000], "indicators": {"quote": [{"open": [2], "high": [2], "low": [2], "close": [2], "volume": [2]}]}}]}}

    class Http:
        async def get(self, *a, **k):
            return Resp()
    monkeypatch.setattr(h, "_alpaca_derived", boom)
    monkeypatch.setitem(h._ALPACA, "key", "k")
    monkeypatch.setattr(h.time, "time", lambda: (OPEN + 2 * 86_400_000) / 1000)
    h._cache.clear()
    bars, prov = asyncio.run(h.fetch_window_ex("SPY", "1d", OPEN - 86_400_000, OPEN + 86_400_000, client=Http()))
    assert prov == "yahoo" and len(bars) == 1


def test_index_symbols_never_try_alpaca():
    """^VIX / ^VIX1D (Team2's sigma, the research VIX snapshot) go straight to Yahoo - Alpaca answers 400 for them."""
    assert not h._alpaca_symbol("^VIX") and not h._alpaca_symbol("^VIX1D") and h._alpaca_symbol("SPY") and h._alpaca_symbol("BRK.B")
