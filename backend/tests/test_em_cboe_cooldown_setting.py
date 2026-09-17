"""PFU-04: `options.cboe_cooldown_seconds` is CONNECTED - the provider follows the effective setting (non-default value),
and the client uses that value, not the class constant, when a 429 starts the background cooldown."""
import asyncio
import time
from types import SimpleNamespace

import pytest

from zargar.options import chain as chain_mod
from zargar.options.chain import OptionsError, cboe_priority
from zargar.options.service import OptionsService


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


def test_provider_reads_a_non_default_cooldown_and_follows_later_edits():
    settings = {"options.provider": "cboe", "options.cboe_cooldown_seconds": 5.0}
    eng = SimpleNamespace(settings=SimpleNamespace(get=lambda k, d=None: settings.get(k, d)), config=SimpleNamespace(tradier_token=""))
    svc = OptionsService.__new__(OptionsService)
    svc.engine = eng; svc._cboe = None; svc._tradier = None
    client = svc.provider()
    assert isinstance(client, chain_mod.CboeClient) and client.cooldown_s == 5.0 and client.cooldown_s != chain_mod.CboeClient.COOLDOWN_S
    settings["options.cboe_cooldown_seconds"] = 7.5
    assert svc.provider() is client and client.cooldown_s == 7.5, "a live setting edit reaches the existing client"


def test_background_cooldown_uses_the_configured_seconds(monkeypatch):
    async def fake_sleep(s):
        return None
    monkeypatch.setattr(chain_mod.asyncio, "sleep", fake_sleep)
    c = chain_mod.CboeClient(client=_Http([_Resp(429)]), cooldown_s=5.0)
    t0 = time.time()
    with cboe_priority("background"):
        with pytest.raises(OptionsError):
            asyncio.run(c._payload("BAC"))
    assert 4.0 <= c.cooling_down() <= 5.0 and c._cooldown_until - t0 < 6.0, "the cooldown is the configured 5 s, not the 20 s constant"
