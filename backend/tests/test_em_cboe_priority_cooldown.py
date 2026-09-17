"""2026-09-16 provider-rate-limit recovery: after a CBOE 429, BACKGROUND chain fetches (enrichment, the nightly
liquidity screen, research) fail fast and stand down for a cooldown; a live ENTRY pick and a HELD POSITION's read
retry briefly and are never held back. Freshness checks and risk limits are untouched - this only decides who asks
the provider and when."""
import asyncio
import time

import pytest

from zargar.options import chain as chain_mod
from zargar.options.chain import OptionsError, cboe_priority


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status; self._payload = payload; self.headers = {}

    def json(self):
        return self._payload


class _Http:
    def __init__(self, responses):
        self.responses = list(responses); self.calls = 0

    async def get(self, url):
        self.calls += 1
        return self.responses.pop(0)


OK = {"data": {"options": [{"option": "BAC260918P00050000", "bid": 1.0, "ask": 1.1}]}}


def _quiet_sleep(monkeypatch):
    async def fake_sleep(s):
        return None
    monkeypatch.setattr(chain_mod.asyncio, "sleep", fake_sleep)


def test_background_fetch_fails_fast_on_429_and_starts_the_cooldown(monkeypatch):
    _quiet_sleep(monkeypatch)
    http = _Http([_Resp(429)])
    c = chain_mod.CboeClient(client=http)
    with cboe_priority("background"):
        with pytest.raises(OptionsError) as ei:
            asyncio.run(c._payload("BAC"))
    assert "not retried" in str(ei.value) and http.calls == 1
    assert c.cooling_down() > 0 and c.rate_limited == 1


def test_background_fetch_is_skipped_without_a_request_during_the_cooldown(monkeypatch):
    _quiet_sleep(monkeypatch)
    http = _Http([_Resp(200, OK)])
    c = chain_mod.CboeClient(client=http)
    c._cooldown_until = time.time() + 10
    with cboe_priority("background"):
        with pytest.raises(OptionsError) as ei:
            asyncio.run(c._payload("NVDA"))
    assert "cooling down" in str(ei.value) and http.calls == 0, "no request may be spent from the back of the queue"


@pytest.mark.parametrize("level", ["entry", "position", "normal"])
def test_entry_and_position_reads_ignore_the_cooldown_and_retry(monkeypatch, level):
    _quiet_sleep(monkeypatch)
    http = _Http([_Resp(429), _Resp(200, OK)])
    c = chain_mod.CboeClient(client=http)
    c._cooldown_until = time.time() + 10
    with cboe_priority(level):
        data = asyncio.run(c._payload("BAC"))
    assert data["options"] and http.calls == 2


def test_cooldown_expires_and_the_priority_context_is_task_local(monkeypatch):
    _quiet_sleep(monkeypatch)
    http = _Http([_Resp(200, OK)])
    c = chain_mod.CboeClient(client=http)
    c._cooldown_until = time.time() - 1                 # expired
    with cboe_priority("background"):
        assert asyncio.run(c._payload("BAC"))["options"]
    assert chain_mod.CBOE_PRIORITY.get() == "normal", "the context is restored after the block"
