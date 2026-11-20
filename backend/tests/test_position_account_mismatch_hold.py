"""2026-11-19: while the gateway is on the OTHER account type, a managed exit is HELD (no order, no stop cancelled,
one alert) instead of looping on a refusal that cannot clear; it runs once the matching gateway is back."""
from sqlalchemy import select

from zargar.engine import Engine
from zargar.models import Event, Order
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config
from .test_position_venue_stop_resize import _adopt


async def test_an_exit_is_held_while_the_account_type_mismatches_and_runs_after(fresh_db, monkeypatch):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    try:
        mgr = eng.position_manager
        pos = await _adopt(eng, "HOLDX", qty=10, stop=1.0)
        p = mgr.get(pos["id"])
        stop_id = p.venue_stop_order_id
        why = {"v": "account type mismatch: a 'paper' book cannot route to an IBKR live account"}
        monkeypatch.setattr(eng.orders, "account_mismatch", lambda _pid: why["v"])

        async def sells():
            async with eng.sf() as s:
                return (await s.execute(select(Order).where(Order.symbol == "HOLDX", Order.side == "SELL",
                                                            Order.order_type != "STP"))).scalars().all()
        for _ in range(3):
            await mgr.close(p.id, reason="stop", kind="stop")
        assert await sells() == []                                    # nothing sent
        assert p.status == "open" and p.venue_stop_order_id == stop_id  # the resting stop is untouched
        async with eng.sf() as s:
            held = (await s.execute(select(Event).where(Event.type == "ManagedPositionAttention"))).scalars().all()
        assert len([e for e in held if (e.payload or {}).get("stage") == "exit_held"]) == 1   # one alert, not three

        why["v"] = None                                               # the matching gateway is back
        await mgr.close(p.id, reason="stop", kind="stop")
        assert len(await sells()) == 1
    finally:
        await eng.stop()


def test_the_order_guard_and_the_hold_share_one_rule():
    from types import SimpleNamespace
    from zargar.orders import OrderManager
    live = SimpleNamespace(account_kind=lambda: "live")
    assert OrderManager._kind_mismatch("paper", live, reduce_only=True)
    assert OrderManager._kind_mismatch("live", live, reduce_only=True) is None
    unknown = SimpleNamespace(account_kind=lambda: None)
    assert OrderManager._kind_mismatch("paper", unknown, reduce_only=True) is None        # exits allowed
    assert OrderManager._kind_mismatch("paper", unknown, reduce_only=False)               # entries refused


def test_a_disconnected_venue_is_held_like_a_mismatch():
    """2026-11-20: IB Gateway logged out after a reboot - the paper MRNA exit was refused 59 times in 15 minutes."""
    from types import SimpleNamespace
    from zargar.orders import OrderManager
    om = OrderManager.__new__(OrderManager)
    om._positions = SimpleNamespace(portfolio=lambda pid: {"id": pid, "kind": "paper"})
    om._executor_for = lambda pf: SimpleNamespace(connected=False, account_kind=lambda: None)
    assert "no connected execution venue" in om.account_mismatch("p1")
    om._executor_for = lambda pf: None
    assert "no connected execution venue" in om.account_mismatch("p1")
    om._executor_for = lambda pf: SimpleNamespace(connected=True, account_kind=lambda: "paper")
    assert om.account_mismatch("p1") is None
    om._positions = SimpleNamespace(portfolio=lambda pid: {"id": pid, "kind": "sim"})
    assert om.account_mismatch("p1") is None                       # sim books are never held
