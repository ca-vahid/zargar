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


async def test_a_failed_catch_up_is_retried_and_holds_the_sync(broker, monkeypatch):
    """A catch-up the gateway did not answer is not 'done': caught_up stays False (the account sync waits) and the
    replay is retried until it succeeds; then the broker reports ready."""
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        return {"openOrders": 0, "replayed": 0, **({"ok": False} if calls["n"] == 1 else {})}

    seen = []

    async def notify(kind, data):
        seen.append(kind)

    monkeypatch.setattr(broker, "catch_up", flaky)
    monkeypatch.setattr(broker, "_notify", notify)
    broker._stopping = False
    broker.caught_up = False
    broker._schedule_catch_up_retry(every_s=0.01)
    assert broker.caught_up is False
    await asyncio.wait_for(broker._catch_up_task, timeout=5)
    assert broker.caught_up is True and "ready" in seen and calls["n"] == 2   # failed once, retried once


async def test_a_new_session_clears_a_stale_link_lost_flag(monkeypatch):
    """A gateway restart never sends 1101/1102: the new connection must not inherit the old session's 1100 flag."""
    class _Evt:
        def __iadd__(self, _h):
            return self

    class _FreshIB(_HangingIB):
        def __init__(self):
            for n in ("orderStatusEvent", "execDetailsEvent", "commissionReportEvent", "errorEvent",
                      "disconnectedEvent", "pendingTickersEvent"):
                setattr(self, n, _Evt())

        async def connectAsync(self, *a, **k):
            return None

        def managedAccounts(self):
            return ["DU1"]

        async def reqExecutionsAsync(self):
            return []

    monkeypatch.setattr(ib_mod, "REQUEST_TIMEOUT_S", 0.2)
    b = ib_mod.IBKRBroker(host="127.0.0.1", port=1, client_id=99, on_quote=lambda q: None)
    b._link_down = True                                # left over from the previous session's 1100
    monkeypatch.setattr(b, "_new_ib", lambda: _FreshIB())
    await b._connect()
    assert b.connected is True and b.caught_up is True
