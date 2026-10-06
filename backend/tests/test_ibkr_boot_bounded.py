"""2026-10-05 21:36 PT: at 00:36 ET (IBKR's nightly maintenance) a gateway request never answered and held the whole
boot - the API never came up. Boot no longer waits on the gateway, and the awaited gateway requests are bounded."""
import asyncio

import pytest

from zargar.brokers import ibkr as ib_mod


class _HangingIB:
    def isConnected(self):
        return True

    def openTrades(self):
        return []

    async def reqExecutionsAsync(self):
        await asyncio.sleep(3600)

    async def accountSummaryAsync(self):
        await asyncio.sleep(3600)

    def positions(self):
        return []


@pytest.fixture
def broker(monkeypatch):
    monkeypatch.setattr(ib_mod, "REQUEST_TIMEOUT_S", 0.2)
    b = ib_mod.IBKRBroker(host="127.0.0.1", port=1, client_id=99, on_quote=lambda q: None)
    b._ib = _HangingIB()
    return b


async def test_catch_up_is_bounded_when_the_gateway_never_answers(broker):
    out = await asyncio.wait_for(broker.catch_up(), timeout=5)
    assert out["replayed"] == 0


async def test_account_state_is_bounded_when_the_gateway_never_answers(broker):
    assert await asyncio.wait_for(broker.account_state(cash_currency="USD"), timeout=5) is None


async def test_engine_boot_does_not_wait_for_the_gateway(monkeypatch):
    """The engine starts the IBKR adapter in the background: a start() that never returns cannot hold the boot."""
    import inspect
    from zargar import engine as eng_mod
    src = inspect.getsource(eng_mod.Engine.start)
    assert "create_task(self.ibkr.start()" in src
    assert "await self.ibkr.start()          # retries" not in src
