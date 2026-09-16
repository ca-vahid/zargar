"""2026-09-16 14:06 ET: BAC d1 fired (breakdown, puts only), the deterministic decision allowed it, and ONE CBOE
HTTP 429 killed the option pick with no retry - nothing was sent. The chain client now retries a 429 briefly
(bounded, Retry-After honoured up to 2 s) and gives up honestly; it never serves stale chain data for a pick."""
import asyncio

import pytest

from zargar.options import chain as chain_mod


class _Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


class _Http:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def get(self, url):
        self.calls += 1
        return self.responses.pop(0)


OK = {"data": {"options": [{"option": "BAC260918P00050000", "bid": 1.0, "ask": 1.1}]}}


def test_one_429_then_success_is_retried_within_the_budget(monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(chain_mod.asyncio, "sleep", fake_sleep)
    http = _Http([_Resp(429), _Resp(200, OK)])
    c = chain_mod.CboeClient(client=http)
    data = asyncio.run(c._payload("BAC"))
    assert data["options"] and http.calls == 2
    assert slept == [0.6]


def test_retry_after_header_is_honoured_but_capped(monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(chain_mod.asyncio, "sleep", fake_sleep)
    http = _Http([_Resp(429, headers={"Retry-After": "30"}), _Resp(200, OK)])
    asyncio.run(chain_mod.CboeClient(client=http)._payload("BAC"))
    assert slept == [2.0], "a long Retry-After must not blow the entry's latency budget"


def test_persistent_429_gives_up_honestly_and_never_serves_stale_data(monkeypatch):
    async def fake_sleep(s):
        return None

    monkeypatch.setattr(chain_mod.asyncio, "sleep", fake_sleep)
    http = _Http([_Resp(429), _Resp(429), _Resp(429)])
    c = chain_mod.CboeClient(client=http)
    c._cache["BAC"] = (0.0, OK["data"])                     # an EXPIRED cache entry must not be served for a live pick
    with pytest.raises(chain_mod.OptionsError) as ei:
        asyncio.run(c._payload("BAC"))
    assert "429" in str(ei.value) and "rate limited" in str(ei.value)
    assert http.calls == 3


def test_other_errors_are_not_retried(monkeypatch):
    http = _Http([_Resp(500)])
    with pytest.raises(chain_mod.OptionsError):
        asyncio.run(chain_mod.CboeClient(client=http)._payload("BAC"))
    assert http.calls == 1
