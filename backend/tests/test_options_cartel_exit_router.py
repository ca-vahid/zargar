"""Venue cancellation acknowledgements, late fills and outstanding exit budgets."""
import pytest

from zargar.execution.positions import PositionManager
from zargar.models import Order
from zargar.orders import order_dict
from zargar.techniques.options_cartel.position_adapter import CartelPositionAdapter

from .cartel_orders import RecordedOrders
from .test_options_cartel_position_adapter import prepared


class DeferredCancel(RecordedOrders):
    async def place(self, intent):
        if intent.order_type == "STP":
            self.script.setdefault(self.n, {"status": "ACCEPTED"})
        return await super().place(intent)

    async def cancel(self, order_id):
        self.cancelled.append(order_id)
        return {"id": order_id, "status": "CANCELLED"}  # not an acknowledgement in the order ledger


async def rig_with_stop(engine):
    rig = await prepared(engine)
    engine.orders = DeferredCancel(engine)
    rig.p.overnight = "venue_stop"
    await rig.pm._ensure_venue_stop(rig.p)
    return rig


async def report(engine, oid, status, qty=0, price=None):
    async with engine.sf() as session, session.begin():
        order = await session.get(Order, oid)
        order.status, order.filled_qty, order.avg_fill_price = status, qty, price


async def test_stop_replacement_waits_for_terminal_record(engine):
    rig = await rig_with_stop(engine)
    rig.p.state.stop = 96
    await rig.pm._ensure_venue_stop(rig.p)
    await rig.pm._ensure_venue_stop(rig.p)
    assert len(engine.orders.placed) == 1 and engine.orders.cancelled == ["o0"]
    assert rig.p.venue_stop_order_id == "o0" and rig.p.venue_stop_at == 95
    await report(engine, "o0", "CANCELLED")
    await rig.pm._ensure_venue_stop(rig.p)
    assert len(engine.orders.placed) == 2
    assert engine.orders.placed[1].qty == 8 and engine.orders.placed[1].stop_price == 96
    assert not any(m.startswith("Cartel exit cancellation") for m in rig.p.attention)


async def test_forced_close_applies_cancel_time_fills_before_selling_remainder(engine):
    rig = await rig_with_stop(engine)
    await rig.pm.close(rig.p.id, force_market=True, reason="protective close")
    await rig.pm.close(rig.p.id, force_market=True, reason="repeated callback")
    assert len(engine.orders.placed) == 1 and rig.p.legs[0].qty == 8
    await report(engine, "o0", "CANCELLED", qty=3, price=95)
    await rig.pm._policy_adapter(rig.p).on_watch(rig.pm, rig.p)
    assert rig.p.status == "closed"
    assert engine.orders.placed[-1].qty == 5 and engine.orders.placed[-1].reduce_only
    assert rig.p.policy["cartel"]["state"]["remaining_qty"] == 0
    assert sum(r.get("filledQty", 0) for r in rig.p.exits) == 8


async def test_pending_profit_order_and_stop_share_the_available_quantity(engine):
    rig = await rig_with_stop(engine)
    engine.orders.script[1] = {"status": "ACCEPTED"}
    await rig.pm.close(rig.p.id, fraction=.25, kind="cartel:target1")
    assert len(engine.orders.placed) == 1
    await report(engine, "o0", "CANCELLED")
    await rig.pm._policy_adapter(rig.p).on_watch(rig.pm, rig.p)
    assert [o.qty for o in engine.orders.placed] == [8, 2, 6]
    assert rig.pm._inflight_exit_qty(rig.p, "TEST") == 8
    await report(engine, "o1", "PARTIALLY_FILLED", qty=1, price=110)
    await rig.pm._policy_adapter(rig.p).on_watch(rig.pm, rig.p)
    assert rig.p.legs[0].qty == 7 and rig.pm._inflight_exit_qty(rig.p, "TEST") == 7
    assert len(engine.orders.placed) == 3


@pytest.mark.parametrize("persisted", [True, False])
async def test_unknown_stop_submission_is_reconciled_not_blindly_repeated(engine, monkeypatch, persisted):
    rig = await prepared(engine)
    rig.p.overnight = "venue_stop"
    engine.orders = DeferredCancel(engine)
    original = engine.orders.place
    calls = []
    async def lost(intent):
        calls.append(intent)
        if persisted:
            await original(intent)
        raise ConnectionError("lost response")
    monkeypatch.setattr(engine.orders, "place", lost)
    await rig.pm._ensure_venue_stop(rig.p)
    rig.pm._now = lambda: (rig.opens+2_000_000)/1000
    await rig.pm._ensure_venue_stop(rig.p)
    await rig.pm._policy_adapter(rig.p).on_watch(rig.pm, rig.p)
    assert len(calls) == 1 and engine.orders.cancelled == []
    if persisted:
        assert rig.p.venue_stop_order_id == "o0"
    else:
        assert any("outcome is unresolved" in message for message in rig.p.attention)


async def test_restart_resumes_pending_close_without_repeating_cancel(engine, monkeypatch):
    rig = await rig_with_stop(engine)
    await rig.pm.close(rig.p.id, force_market=True)
    async def ensure(symbol):
        return None
    monkeypatch.setattr(engine, "ensure_symbol", ensure)
    restored = PositionManager(engine)
    restored._now = rig.pm._now
    restored.register_policy_adapter("options_cartel", CartelPositionAdapter())
    await restored.restore()
    try:
        p = restored.get(rig.p.id)
        assert p.policy["cartel"]["closeRequest"]["remaining"] == 0
        await restored._watch_once()
        assert engine.orders.cancelled == ["o0"] and len(engine.orders.placed) == 1
        await report(engine, "o0", "CANCELLED", qty=2, price=95)
        await restored._watch_once()
        assert p.status == "closed" and engine.orders.placed[-1].qty == 6
    finally:
        await restored.stop()


async def test_rejected_venue_stops_retry_with_delay_and_stop_after_five_attempts(engine):
    rig = await prepared(engine)
    rig.p.overnight = "venue_stop"
    engine.orders = DeferredCancel(engine)
    engine.orders.script = {i: {"status": "REJECTED"} for i in range(10)}
    await rig.pm._ensure_venue_stop(rig.p)
    await rig.pm._ensure_venue_stop(rig.p)
    assert len(engine.orders.placed) == 1
    for step in range(1, 7):
        rig.pm._now = lambda n=step: (rig.opens+n*31_000+60_000)/1000
        await rig.pm._ensure_venue_stop(rig.p)
    assert len(engine.orders.placed) == 5
    assert any("stop exhausted five" in m for m in rig.p.attention)


async def test_completed_async_trim_does_not_swallow_the_next_close_request(engine):
    rig = await rig_with_stop(engine)
    engine.orders.script[1] = {"status": "ACCEPTED"}
    await rig.pm.close(rig.p.id, fraction=.25, kind="cartel:target1")
    await report(engine, "o0", "CANCELLED")
    await rig.pm._policy_adapter(rig.p).on_watch(rig.pm, rig.p)
    await report(engine, "o1", "FILLED", qty=2, price=110)
    async with engine.sf() as session:
        filled = order_dict(await session.get(Order, "o1"))
    await rig.pm.on_order_update(filled)
    # Submit the next request before the polling loop has retired the old one.
    await rig.pm.close(rig.p.id, fraction=1/6, reason="second trim")
    assert rig.p.policy["cartel"]["closeRequest"]["remaining"] == 5
    await report(engine, "o2", "CANCELLED")
    await rig.pm._policy_adapter(rig.p).on_watch(rig.pm, rig.p)
    assert rig.p.legs[0].qty == 5
    assert [o.qty for o in engine.orders.placed] == [8, 2, 6, 1, 5]
