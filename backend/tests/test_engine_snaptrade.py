"""Full-engine SnapTrade flow: routing, risk, fills, and safety gates."""
import pytest

import zargar.brokers.snaptrade as st_mod
from zargar.db import make_engine, make_session_factory
from zargar.engine import Engine
from zargar.models import Setting
from zargar.orders import OrderIntent
from zargar.orders import BracketSpec

from .conftest import TEST_DB_URL, make_test_config, wait_for
from .snaptrade_stub import StubSnapTrade, stub_account, stub_connection


@pytest.fixture
async def snaptrade_engine(fresh_db):
    stub = StubSnapTrade()
    stub.connections = [stub_connection()]
    stub.accounts = [stub_account(total=10_000.0)]
    stub.balances["acct-1"] = [{"currency": {"code": "CAD"}, "cash": 10_000.0}]
    stub.positions["acct-1"] = []
    st_mod.DEFAULT_TRANSPORT = stub.transport()

    db = make_engine(TEST_DB_URL)
    sf = make_session_factory(db)
    async with sf() as session:
        session.add(Setting(key="snaptrade.enabled", value={"v": True}))
        await session.commit()
    await db.dispose()

    eng = Engine(make_test_config(
        snaptrade_client_id="CID", snaptrade_consumer_key="KEY", quote_source="sim"))
    await eng.start()
    try:
        await wait_for(lambda: any(
            p.get("venue") == "snaptrade" for p in eng.positions.portfolios()))
        yield eng, stub
    finally:
        await eng.stop()
        st_mod.DEFAULT_TRANSPORT = None


def snaptrade_pid(eng: Engine) -> str:
    return next(p["id"] for p in eng.positions.portfolios()
                if p.get("venue") == "snaptrade")


async def wait_quote(eng, symbol):
    await eng.ensure_symbol(symbol)
    await wait_for(lambda: eng.quotes.get(symbol) is not None)


async def test_live_order_routes_and_fills(snaptrade_engine):
    eng, stub = snaptrade_engine
    pid = snaptrade_pid(eng)
    await eng.settings.set("trading.mode", "live")
    await wait_quote(eng, "AAPL")
    stub.place_response = {"brokerage_order_id": "bo-1", "status": "PENDING"}

    order = await eng.orders.place(OrderIntent(
        portfolio_id=pid, symbol="AAPL", side="BUY", qty=1, order_type="MKT"))
    assert order["status"] == "SUBMITTED", order
    assert len(stub.calls("/trade/place")) == 1

    async def accepted():
        rows = await eng.orders.list_orders(pid)
        return any(o["id"] == order["id"] and o["status"] == "ACCEPTED" for o in rows)
    await wait_for(accepted)

    last = eng.quotes.get("AAPL").last
    stub.recent_orders["acct-1"] = [{
        "brokerage_order_id": "bo-1", "status": "EXECUTED",
        "filled_quantity": 1.0, "execution_price": round(last, 2)}]
    await eng.snaptrade.poll_once()

    async def filled():
        rows = await eng.orders.list_orders(pid)
        return any(o["id"] == order["id"] and o["status"] == "FILLED" for o in rows)
    await wait_for(filled)
    assert eng.positions.position_qty(pid, "AAPL") == 1


async def test_mode_gate_blocks_snaptrade_outside_live(snaptrade_engine):
    eng, stub = snaptrade_engine
    pid = snaptrade_pid(eng)
    await wait_quote(eng, "AAPL")  # trading.mode defaults to "practice"

    order = await eng.orders.place(OrderIntent(
        portfolio_id=pid, symbol="AAPL", side="BUY", qty=1, order_type="MKT"))
    assert order["status"] == "REJECTED_RISK"
    assert "trading.mode=practice blocks" in order["rejectReason"]
    assert stub.calls("/trade/place") == []  # never reached the broker


async def test_bracket_rejected_on_snaptrade(snaptrade_engine):
    eng, stub = snaptrade_engine
    pid = snaptrade_pid(eng)
    await eng.settings.set("trading.mode", "live")
    await wait_quote(eng, "AAPL")

    order = await eng.orders.place(OrderIntent(
        portfolio_id=pid, symbol="AAPL", side="BUY", qty=1, order_type="MKT",
        bracket=BracketSpec(take_profit_pct=5.0, stop_loss_pct=2.0)))
    assert order["status"] == "REJECTED_RISK"
    assert "bracket" in order["rejectReason"].lower()
    assert stub.calls("/trade/place") == []


async def test_dry_run_preflight_does_not_burn_budget(snaptrade_engine):
    eng, stub = snaptrade_engine
    pid = snaptrade_pid(eng)
    await eng.settings.set("trading.mode", "live")
    await wait_quote(eng, "AAPL")
    stub.place_response = {"brokerage_order_id": "bo-2", "status": "PENDING"}

    preflight = await eng.orders.place(OrderIntent(
        portfolio_id=pid, symbol="AAPL", side="BUY", qty=1, order_type="MKT",
        dry_run=True))
    assert preflight["status"] == "DRY_RUN"

    # identical real order within the duplicate window must still route
    order = await eng.orders.place(OrderIntent(
        portfolio_id=pid, symbol="AAPL", side="BUY", qty=1, order_type="MKT"))
    assert order["status"] == "SUBMITTED", order


async def test_snapshot_exposes_snaptrade_state(snaptrade_engine):
    eng, stub = snaptrade_engine
    snap = await eng.snapshot()
    assert snap["broker"]["snaptradeConnected"] is True
    assert snap["broker"]["quoteSource"] == "sim"
    assert snap["brokerages"]["enabled"] is True
    providers = snap["brokerages"]["providers"]
    assert providers and providers[0]["broker"] == "Webull Canada"
    assert providers[0]["accounts"][0]["cash"] == 10_000.0
    pf = next(p for p in snap["portfolios"] if p.get("venue") == "snaptrade")
    assert pf["kind"] == "live" and pf["cash"] == 10_000.0
