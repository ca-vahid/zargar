"""2026-11-19: releasing a managed position hands it back to the user - the venue stop is cancelled, nothing is
evaluated or restored afterwards, and the shares stay in the book."""
from sqlalchemy import select

from zargar.engine import Engine
from zargar.models import Order
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config
from .test_position_venue_stop_resize import _adopt


async def test_a_released_position_has_no_stop_and_never_exits_or_restores(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    try:
        mgr = eng.position_manager
        pos = await _adopt(eng, "RELX", qty=10, stop=1.0)
        p = mgr.get(pos["id"])
        stop_id = p.venue_stop_order_id
        assert stop_id
        out = await mgr.release(p.id, reason="user holds through the swings")
        assert out["status"] == "released" and p.venue_stop_order_id is None
        async with eng.sf() as s:
            stop = await s.get(Order, stop_id)
        assert stop.status in ("CANCELLED", "PENDING_CANCEL")
        assert abs(eng.positions.position_qty(p.portfolio_id, "RELX", "STK") - 10) < 1e-9   # shares kept
        await mgr.check_exits() if hasattr(mgr, "check_exits") else None
        async with eng.sf() as s:
            sells = (await s.execute(select(Order).where(Order.symbol == "RELX", Order.side == "SELL",
                                                         Order.order_type != "STP"))).scalars().all()
        assert sells == []
        mgr._pos.clear()
        await mgr.restore()
        assert mgr.get(p.id) is None                                  # never managed again
    finally:
        await eng.stop()
