"""2026-10-05 (CYRX, IBKR paper): a share position adopted while its entry's bracket children were still cancelling
got no venue GTC stop and nothing retried. The watch loop now re-places a missing venue stop."""
import pytest

from zargar.engine import Engine
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config
from .test_tip_geometry_wiring import _quote


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


async def test_watch_loop_replaces_a_missing_venue_stop(rig):
    eng = rig
    mgr = eng.position_manager
    q = await _quote(eng, "HEAL")
    pid = next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")
    stop = round(q.last * 0.95, 2)
    await eng.positions.apply_fill(pid, "HEAL", "STK", "BUY", 10.0, float(q.last), 0.0)
    pos = await mgr.adopt({"portfolioId": pid, "symbol": "HEAL", "direction": "long", "techniqueId": "tip",
                           "entry": q.last, "risk": q.last - stop,
                           "legs": [{"symbol": "HEAL", "secType": "STK", "qty": 10, "avgFill": q.last, "origin": "adoption"}],
                           "overnight": "venue_stop", "policy": {"timeframe": "15m", "stop": {"kind": "fixed", "price": stop}}})
    p = mgr.get(pos["id"])
    first = p.venue_stop_order_id
    assert first, "adoption rests a venue stop"
    p.venue_stop_order_id = None                       # the stop went missing
    p.venue_stop_at = None
    await mgr._watch_position(p, now=mgr.now_ms(), excess=0.25, need=2, stale_ms=10_000)
    assert p.venue_stop_order_id and p.venue_stop_order_id != first
    again = p.venue_stop_order_id
    await mgr._watch_position(p, now=mgr.now_ms(), excess=0.25, need=2, stale_ms=10_000)
    assert p.venue_stop_order_id == again, "a healthy stop is left alone"
