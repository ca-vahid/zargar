"""ONE exit authority (MRNA 2026-09-15): once the manager adopts a fill, the
entry order's bracket children (the proposal's GTC take-profit + stop-loss) are
cancelled - left resting beside the manager's stop and ladder they doubled every
exit (7 MRNA held, 14 resting to sell at the stop: the RKT short, one bug class
over). Restore releases records adopted before the rule; a bracket that would
spawn AFTER adoption (the rest of a partial fill) is refused."""
from sqlalchemy import select

from zargar.brokers.base import ExecReport
from zargar.engine import Engine
from zargar.models import Event, Order
from zargar.orders import BracketSpec, OrderIntent
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config, wait_for
from .test_tip_geometry_wiring import _quote


async def _orders_for(eng, sym: str) -> list:
    async with eng.sf() as session:
        return (await session.execute(select(Order).where(Order.symbol == sym)
                                      .order_by(Order.created_at))).scalars().all()


async def _events(eng, kind: str) -> list:
    async with eng.sf() as session:
        return (await session.execute(select(Event).where(Event.type == kind))).scalars().all()


async def _bracket_entry(eng, sym: str, *, qty: int, order_type: str = "MKT", limit: float | None = None) -> dict:
    pid = next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")
    order = await eng.orders.place(OrderIntent(
        portfolio_id=pid, symbol=sym, side="BUY", qty=qty, order_type=order_type, limit_price=limit,
        bracket=BracketSpec(take_profit_pct=50.0, stop_loss_pct=10.0)))
    assert order["status"] not in ("REJECTED_RISK", "REJECTED"), order.get("rejectReason")
    return order


def _qty(q) -> int:
    """A lot inside the sim book's RiskGate caps ($1,000 / 10% of equity) whatever the symbol's random price."""
    return max(1, int(600 / float(q.last)))


async def _children(eng, parent_id: str) -> list:
    async with eng.sf() as session:
        return (await session.execute(select(Order).where(Order.parent_id == parent_id))).scalars().all()


def _spec(eng, sym: str, order: dict, *, qty: int, stop: float) -> dict:
    pid = order["portfolioId"]
    fill = float(order.get("avgFillPrice") or order.get("limitPrice") or 0) or 1.0
    return {"portfolioId": pid, "symbol": sym, "direction": "long", "techniqueId": "tip",
            "entry": fill, "risk": max(fill - stop, 0.01),
            "legs": [{"symbol": sym, "secType": "STK", "qty": qty, "avgFill": fill, "origin": "adoption",
                      "entryOrderId": order["id"]}],
            "overnight": "venue_stop",
            "policy": {"timeframe": "15m", "stop": {"kind": "fixed", "price": stop},
                       "ladder": {"targets": [round(fill * 1.3, 2)], "fractions": [0.35]}}}


async def test_adoption_releases_the_entry_brackets_and_rests_exactly_one_stop(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    try:
        mgr = eng.position_manager
        q = await _quote(eng, "BRKA")
        qty = _qty(q)
        order = await _bracket_entry(eng, "BRKA", qty=qty)

        async def two_children():
            ch = await _children(eng, order["id"])
            return ch if len(ch) == 2 else None
        children = await wait_for(two_children, timeout=10)
        assert sorted(c.order_type for c in children) == ["LMT", "STP"]
        async with eng.sf() as session:
            filled = await session.get(Order, order["id"])
        stop = round(float(filled.avg_fill_price) * 0.95, 2)
        pos = await mgr.adopt(_spec(eng, "BRKA", {**order, "avgFillPrice": filled.avg_fill_price}, qty=qty, stop=stop))
        p = mgr.get(pos["id"])

        async def released():
            ch = await _children(eng, order["id"])
            return ch if all(c.status == "CANCELLED" for c in ch) else None
        await wait_for(released, timeout=10)
        # the manager's venue stop is the ONLY working stop on the lot
        rows = await _orders_for(eng, "BRKA")
        working = [o for o in rows if o.status in ("NEW", "SUBMITTED", "ACCEPTED", "WORKING", "PARTIALLY_FILLED")]
        assert len(working) == 1 and working[0].order_type == "STP" and working[0].id == p.venue_stop_order_id, \
            [(o.order_type, o.source, o.status) for o in rows]
        assert working[0].qty == qty and working[0].source != "bracket"
        ev = await _events(eng, "ManagedPositionBracketReleased")
        assert len(ev) == 1 and ev[0].payload["phase"] == "adopt"
        assert sorted(o["type"] for o in ev[0].payload["orders"]) == ["LMT", "STP"]
        assert all(o["parentId"] == order["id"] for o in ev[0].payload["orders"])
        assert any(e["event"] == "bracket_released" for e in p.events)
    finally:
        await eng.stop()


async def test_restore_releases_brackets_left_by_an_older_adoption(fresh_db, monkeypatch):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    try:
        mgr = eng.position_manager
        q = await _quote(eng, "BRKB")
        qty = _qty(q)
        order = await _bracket_entry(eng, "BRKB", qty=qty)

        async def two_children():
            ch = await _children(eng, order["id"])
            return ch if len(ch) == 2 else None
        await wait_for(two_children, timeout=10)
        async with eng.sf() as session:
            filled = await session.get(Order, order["id"])
        stop = round(float(filled.avg_fill_price) * 0.95, 2)

        # a record adopted before the rule: the brackets stayed beside the venue stop
        async def _noop(p, *, phase):
            return 0
        monkeypatch.setattr(mgr, "_release_bracket_children", _noop)
        pos = await mgr.adopt(_spec(eng, "BRKB", {**order, "avgFillPrice": filled.avg_fill_price}, qty=qty, stop=stop))
        monkeypatch.undo()
        ch = await _children(eng, order["id"])
        assert all(c.status in ("SUBMITTED", "ACCEPTED", "WORKING") for c in ch), [c.status for c in ch]
        stop_id = mgr.get(pos["id"]).venue_stop_order_id
        assert stop_id

        # the restart: restore releases them before the first bar is judged
        mgr._pos.clear()
        mgr._order_index.clear()
        await mgr.restore()

        async def released():
            rows = await _children(eng, order["id"])
            return rows if all(c.status == "CANCELLED" for c in rows) else None
        await wait_for(released, timeout=10)
        assert mgr.get(pos["id"]).venue_stop_order_id == stop_id
        async with eng.sf() as session:
            venue_stop = await session.get(Order, stop_id)
        assert venue_stop.status in ("SUBMITTED", "ACCEPTED", "WORKING"), "the manager's own stop is never released"
        ev = await _events(eng, "ManagedPositionBracketReleased")
        assert len(ev) == 1 and ev[0].payload["phase"] == "restore" and len(ev[0].payload["orders"]) == 2
    finally:
        await eng.stop()


async def test_a_bracket_never_spawns_under_an_entry_the_manager_already_owns(fresh_db):
    """Partial-fill adoption: the manager owns the entry before it fills fully;
    the completing fill must not spawn the bracket children."""
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    try:
        mgr = eng.position_manager
        q = await _quote(eng, "BRKC")
        # a resting limit below the market (inside the gate's 5% band): written ahead, accepted, unfilled
        qty = _qty(q)
        order = await _bracket_entry(eng, "BRKC", qty=qty, order_type="LMT", limit=round(q.last * 0.96, 2))
        assert order["status"] in ("SUBMITTED", "ACCEPTED", "NEW")
        pid = order["portfolioId"]
        await eng.positions.apply_fill(pid, "BRKC", "STK", "BUY", float(qty), float(q.last), 0.0)
        pos = await mgr.adopt(_spec(eng, "BRKC", {**order, "avgFillPrice": q.last}, qty=qty, stop=round(q.last * 0.95, 2)))
        assert mgr.owns_entry_order(order["id"]) is True
        # the venue reports the (rest of the) fill: the OrderManager completes the
        # parent and asks the guard before spawning any child
        await eng.orders.on_report(ExecReport(kind="fill", order_id=order["id"], fill_qty=qty,
                                              fill_price=float(q.last), exec_id="late-fill"))

        async def skipped():
            ev = await _events(eng, "OrderBracketSkipped")
            return ev or None
        ev = await wait_for(skipped, timeout=10)
        assert ev[0].aggregate_id == order["id"]
        assert await _children(eng, order["id"]) == []
        assert mgr.get(pos["id"]).venue_stop_order_id
    finally:
        await eng.stop()
