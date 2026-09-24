"""2026-09-24 09:31 ET: four EM short entries (SLV, VRT in both books) died to CBOE 429s - puts only, no shares fallback.
Single flight (twin fires share one request), a longer entry retry, and a background quiet window at the open."""
import asyncio

import httpx
import pytest

from zargar.options import chain as ch
from zargar.options.chain import CboeClient, OptionsError, cboe_priority

PAYLOAD = {"data": {"options": [{"option": "VRT260925P00100000", "bid": 1.0, "ask": 1.1}]}}


def _client(handler):
    return CboeClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(CboeClient, "ENTRY_RETRIES", (0.01, 0.01, 0.01))
    monkeypatch.setattr(CboeClient, "RATE_LIMIT_RETRIES", (0.01, 0.01))


def test_twin_fires_share_one_request(monkeypatch):
    calls = []

    async def slow(request):
        calls.append(request.url.path)
        await asyncio.sleep(0.05)
        return httpx.Response(200, json=PAYLOAD)

    async def run():
        c = _client(slow)
        c.open_quiet = False
        with cboe_priority("entry"):
            a, b = await asyncio.gather(c._payload("VRT"), c._payload("VRT"))
        return c, a, b
    c, a, b = asyncio.run(run())
    assert a == b and len(calls) == 1 and c.shared_fetches == 1, "two books firing VRT together make ONE request"


def test_an_entry_retries_three_times_before_giving_up():
    calls = []

    def always_429(request):
        calls.append(1)
        return httpx.Response(429)

    async def run():
        c = _client(always_429)
        with cboe_priority("entry"):
            await c._payload("SLV")
    with pytest.raises(OptionsError, match="3 retries"):
        asyncio.run(run())
    assert len(calls) == 4, "one try + three retries for an entry"


def test_an_entry_rides_out_a_short_burst():
    seq = [429, 429, 429, 200]

    def burst(request):
        code = seq.pop(0)
        return httpx.Response(code, json=PAYLOAD if code == 200 else None)

    async def run():
        c = _client(burst)
        with cboe_priority("entry"):
            return await c._payload("SLV")
    assert asyncio.run(run())["options"], "the third retry succeeds - under the old two-retry schedule this entry died"


def test_background_stands_down_in_the_open_window_but_entries_do_not(monkeypatch):
    calls = []

    def ok(request):
        calls.append(1)
        return httpx.Response(200, json=PAYLOAD)
    monkeypatch.setattr(CboeClient, "_in_open_quiet", lambda self, now=None: True)

    async def bg():
        c = _client(ok)
        with cboe_priority("background"):
            await c._payload("IWM")
    with pytest.raises(OptionsError, match="open quiet"):
        asyncio.run(bg())
    assert calls == []

    async def entry():
        c = _client(ok)
        with cboe_priority("entry"):
            return await c._payload("IWM")
    assert asyncio.run(entry())["options"] and calls == [1]

    async def off():
        c = _client(ok)
        c.open_quiet = False
        with cboe_priority("background"):
            return await c._payload("QQQ")
    assert asyncio.run(off())["options"], "the setting switches the quiet window off"


def test_an_entry_does_not_inherit_a_failed_background_fetch():
    state = {"n": 0}

    async def handler(request):
        state["n"] += 1
        if state["n"] == 1:
            await asyncio.sleep(0.03)
            return httpx.Response(429)               # the background fetch fails fast on this
        return httpx.Response(200, json=PAYLOAD)

    async def run():
        c = _client(handler)
        c.open_quiet = False

        async def bg():
            with cboe_priority("background"):
                with pytest.raises(OptionsError):
                    await c._payload("MU")

        async def entry():
            await asyncio.sleep(0.01)
            with cboe_priority("entry"):
                return await c._payload("MU")
        _, got = await asyncio.gather(bg(), entry())
        return got
    assert asyncio.run(run())["options"], "the entry made its own attempt after the shared background fetch failed"


def test_quiet_window_is_09_29_to_09_34_et_on_weekdays():
    import datetime as dt
    from zoneinfo import ZoneInfo
    c = CboeClient(httpx.AsyncClient())
    at = lambda h, m, d=24: dt.datetime(2026, 9, d, h, m, tzinfo=ZoneInfo("America/New_York")).timestamp()
    assert c._in_open_quiet(at(9, 29)) and c._in_open_quiet(at(9, 33)) and not c._in_open_quiet(at(9, 34))
    assert not c._in_open_quiet(at(9, 28)) and not c._in_open_quiet(at(9, 31, d=26)), "Saturday"
    _ = ch
