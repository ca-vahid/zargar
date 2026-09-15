"""The resting venue GTC stop follows the held quantity (RKT 2026-09-15):
a trim resizes it, and a restart re-registers it so its fill reaches the
position instead of leaving a phantom long."""
from sqlalchemy import select

from zargar.engine import Engine
from zargar.models import Order
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config, wait_for
from .test_tip_geometry_wiring import _quote


async def _adopt(eng, sym: str, *, qty: int, stop: float) -> dict:
    q = await _quote(eng, sym)
    pid = next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")
    spec = {"portfolioId": pid, "symbol": sym, "direction": "long", "techniqueId": "tip",
            "entry": q.last, "risk": max(q.last - stop, 0.01),
            "legs": [{"symbol": sym, "secType": "STK", "qty": qty, "avgFill": q.last, "origin": "adoption"}],
            "overnight": "venue_stop",
            "policy": {"timeframe": "15m", "stop": {"kind": "fixed", "price": stop},
                       "ladder": {"targets": [round(q.last * 1.5, 2)], "fractions": [0.4]}},
            "extras": {}}
    await eng.positions.apply_fill(pid, sym, "STK", "BUY", float(qty), float(q.last), 0.0)
    return await eng.position_manager.adopt(spec)


async def _venue_stops(eng, sym: str) -> list:
    async with eng.sf() as session:
        rows = (await session.execute(select(Order).where(Order.symbol == sym, Order.order_type == "STP")
                                      .order_by(Order.created_at))).scalars().all()
    return rows


async def test_venue_stop_resizes_after_a_trim_and_survives_a_restart(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    try:
        mgr = eng.position_manager
        q = await _quote(eng, "VSTP")
        stop = round(q.last * 0.9, 2)
        pos = await _adopt(eng, "VSTP", qty=100, stop=stop)
        p = mgr.get(pos["id"])
        assert p.venue_stop_order_id and p.venue_stop_qty == 100.0
        stops = await _venue_stops(eng, "VSTP")
        assert stops[-1].qty == 100 and stops[-1].status != "CANCELLED"
        # a 40% trim fills on the sim; the resting stop must then cover 60, not 100
        await mgr.close(pos["id"], fraction=0.4, reason="test trim")

        async def resized():
            p2 = mgr.get(pos["id"])
            return p2 if p2 and abs((p2.venue_stop_qty or 0) - 60.0) < 1e-9 else None
        p2 = await wait_for(resized, timeout=10)
        stops = await _venue_stops(eng, "VSTP")
        live = [o for o in stops if o.status in ("SUBMITTED", "ACCEPTED", "WORKING")]
        assert len(live) == 1 and live[0].qty == 60 and live[0].id == p2.venue_stop_order_id, \
            [(o.qty, o.status) for o in stops]
        assert all(o.status == "CANCELLED" for o in stops if o.id != p2.venue_stop_order_id)
        # a restart re-registers the resting stop as this position's exit order
        stop_id = p2.venue_stop_order_id
        mgr._pos.clear()
        mgr._order_index.clear()
        await mgr.restore()
        assert mgr._order_index.get(stop_id) == pos["id"], "the venue stop must reach the position after a restart"
        p3 = mgr.get(pos["id"])
        assert p3.venue_stop_qty == 60.0
    finally:
        await eng.stop()
