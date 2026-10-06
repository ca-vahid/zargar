"""2026-10-05 (MU 0DTE short leg, shadow book): an unfilled exit older than the in-flight TTL stopped blocking a new
exit but was never cancelled - the DTE close re-issued every 15 min and 20 buy-to-close orders stacked on 3 contracts.
A stale exit is now CANCELLED before its replacement; a fresh one still blocks."""
import pytest

from zargar.engine import Engine
from zargar.orders import OrderIntent
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config, wait_for
from .test_tip_geometry_wiring import _quote

MIN = 60_000


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


async def _status(eng, pid, oid):
    rows = await eng.orders.list_orders(pid)
    return next(o["status"] for o in rows if o["id"] == oid)


async def _resting_exit(eng, mgr, p, pid, q, *, age_ms):
    """A far-away reduce-only SELL limit the position records as its exit (it will not fill)."""
    order = await eng.orders.place(OrderIntent(portfolio_id=pid, symbol=p.symbol, side="SELL", qty=10,
                                               order_type="LMT", limit_price=round(q.last * 1.5, 2),
                                               reduce_only=True))

    async def accepted():
        return await _status(eng, pid, order["id"]) == "ACCEPTED"
    await wait_for(accepted)
    p.exits.append({"orderId": order["id"], "leg": p.symbol, "qty": 10.0, "filledQty": 0.0, "status": "ACCEPTED",
                    "kind": "dte", "ts": mgr.now_ms() - age_ms})
    mgr._register_exit_order(p, order["id"])
    return order["id"]


async def _position(eng, mgr, symbol):
    q = await _quote(eng, symbol)
    pid = next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")
    await eng.positions.apply_fill(pid, symbol, "STK", "BUY", 10.0, float(q.last), 0.0)
    pos = await mgr.adopt({"portfolioId": pid, "symbol": symbol, "direction": "long", "techniqueId": "tip",
                           "entry": q.last, "risk": q.last * 0.05,
                           "legs": [{"symbol": symbol, "secType": "STK", "qty": 10, "avgFill": q.last,
                                     "origin": "adoption"}],
                           "overnight": "venue_stop",
                           "policy": {"timeframe": "15m", "stop": {"kind": "fixed", "price": round(q.last * 0.9, 2)}}})
    return q, pid, mgr.get(pos["id"])


async def test_a_stale_unfilled_exit_is_cancelled_before_its_replacement(rig):
    eng, mgr = rig, rig.position_manager
    q, pid, p = await _position(eng, mgr, "SUPA")
    old = await _resting_exit(eng, mgr, p, pid, q, age_ms=20 * MIN)       # past the 15-min TTL
    await mgr.close(p.id, fraction=1.0, kind="dte", reason="test: replace a stale exit")
    rec = next(r for r in p.exits if r.get("orderId") == old)
    assert rec["status"] == "CANCELLED" and rec.get("superseded")

    async def cancelled():
        return await _status(eng, pid, old) == "CANCELLED"
    await wait_for(cancelled)
    working = [o for o in await eng.orders.list_orders(pid)
               if o["symbol"] == "SUPA" and o["side"] == "SELL" and o["status"] in ("NEW", "SUBMITTED", "ACCEPTED")]
    assert len(working) <= 1, working          # never two exits stacked on the same shares


async def test_a_fresh_unfilled_exit_still_blocks_a_second_one(rig):
    eng, mgr = rig, rig.position_manager
    q, pid, p = await _position(eng, mgr, "SUPB")
    old = await _resting_exit(eng, mgr, p, pid, q, age_ms=2 * MIN)        # inside the TTL
    n_before = len(p.exits)
    await mgr.close(p.id, fraction=1.0, kind="dte", reason="test: fresh exit in flight")
    assert await _status(eng, pid, old) == "ACCEPTED"
    assert len(p.exits) == n_before, "the in-flight exit covers the qty - no new exit"
