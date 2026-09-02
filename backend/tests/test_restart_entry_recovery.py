"""A restart must not strand a working entry (PLATFORM-RULES, 2026-09-02, NOW):
after restore the trade has no bar index (the entry-window cancel went silent),
the sim executor's book is empty (nothing can fill or cancel the order) and the
contract is no longer watched. Pins: wall-clock entry timeout + cancel of an
order the executor no longer holds -> CANCELLED, not ACCEPTED forever."""
import datetime as dt

from zargar.domain import Bar
from zargar.execution.planrunner import Trade
from zargar.orders import OrderIntent
from zargar.technique.rulebook import ET

from .conftest import wait_for
from .test_engine_flow import sim_portfolio, wait_quote
from .test_technique_walkforward import rig  # noqa: F401

MIN = 60_000


async def _accepted_far_limit(engine, pid, symbol="AAPL", qty=1):
    q = await wait_quote(engine, symbol)
    order = await engine.orders.place(OrderIntent(
        portfolio_id=pid, symbol=symbol, side="BUY", qty=qty, order_type="LMT",
        limit_price=round(q.bid * 0.98, 2)))       # 2% below: accepted, does not fill
    assert order["status"] == "SUBMITTED", (order["status"], order.get("rejectReason"))

    async def accepted():
        rows = await engine.orders.list_orders(pid)
        return any(o["id"] == order["id"] and o["status"] == "ACCEPTED" for o in rows)
    await wait_for(accepted)
    return order["id"]


async def _status(engine, pid, oid):
    rows = await engine.orders.list_orders(pid)
    return next(o["status"] for o in rows if o["id"] == oid)


async def test_cancel_of_an_order_the_executor_lost_in_a_restart(engine):
    pid = sim_portfolio(engine)["id"]
    oid = await _accepted_far_limit(engine, pid)
    executor = engine.orders._executor_for(engine.positions.portfolio(pid))
    executor._working.clear()                     # what a restart does to the sim book
    out = await engine.orders.cancel(oid)
    assert out["status"] == "CANCELLED", out
    assert "restart" in (out.get("rejectReason") or "")
    assert await _status(engine, pid, oid) == "CANCELLED"
    # the normal path is untouched: a held order is cancelled through the executor's report
    oid2 = await _accepted_far_limit(engine, pid, qty=2)   # not a 10s duplicate of the first
    await engine.orders.cancel(oid2)
    async def gone():
        return await _status(engine, pid, oid2) == "CANCELLED"
    await wait_for(gone)


async def test_restored_working_entry_times_out_on_wall_clock(rig):
    run = await rig.svc.analyze("TEST", as_of_ms=rig.sessions[rig.close_day][-1].ts, plan=True, wait=True)
    armed = await rig.svc.arm_plan(run["id"], {"instrument": "shares"})
    assert armed["status"] == "armed"
    ap = rig.svc.armer._armed[run["id"]]
    pid = next(p["id"] for p in rig.eng.positions.portfolios() if p["kind"] == "sim")
    oid = await _accepted_far_limit(rig.eng, pid, "TEST")
    executor = rig.eng.orders._executor_for(rig.eng.positions.portfolio(pid))
    executor._working.clear()                     # restart: the sim book is gone
    day = dt.date.fromisoformat(ap.plan_for)
    ts = int(dt.datetime(day.year, day.month, day.day, 10, 0, tzinfo=ET).timestamp() * 1000)
    # the shape restore() leaves behind: working, no bar index, fired 20 minutes ago
    ap.trades["r1"] = Trade(trigger_id="r1", kind="reject", fired_ts=ts - 20 * MIN, window="am",
                            entry=102.0, stop=102.6, targets=[101.0, 100.5, 100.0],
                            status="working", entry_order_id=oid, instrument="shares")
    bar = Bar(symbol="TEST", tf="1m", ts=ts, open=102.0, high=102.05, low=101.95, close=102.0, volume=1000)
    snap = await rig.svc.armer.on_bar(run["id"], bar)
    tr = ap.trades["r1"]
    assert tr.status == "cancelled", (tr.status, tr.reason, snap and snap.get("status"))
    assert await _status(rig.eng, pid, oid) == "CANCELLED"
    await rig.svc.armer.disarm(run["id"], reason="test")
