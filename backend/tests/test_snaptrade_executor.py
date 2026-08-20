"""SnapTradeBroker: submit, cancel, poll deltas, reconcile, throttle."""
import asyncio
import time

import pytest
from sqlalchemy import select

import httpx

from zargar.brokers.base import BrokerOrder
from zargar.brokers.snaptrade import SnapTradeBroker, SnapTradeClient, dashed_uuid
from zargar.bus import Bus
from zargar.db import make_engine, make_session_factory
from zargar.domain import OrderSide, OrderType, TimeInForce, new_id
from zargar.events import Journal
from zargar.models import Event, Order, Portfolio

from .conftest import TEST_DB_URL
from .snaptrade_stub import FakeSettings, StubSnapTrade
from .test_sim_executor import Collector


@pytest.fixture
async def sf(fresh_db):
    engine = make_engine(TEST_DB_URL)
    yield make_session_factory(engine)
    await engine.dispose()


async def seed_order(sf, order_id: str, pid: str = "p1", **kw) -> None:
    async with sf() as session:
        if await session.get(Portfolio, pid) is None:
            session.add(Portfolio(id=pid, name="Webull CASH", kind="live",
                                  starting_cash=0.0, cash=10_000.0))
            await session.commit()
        row = dict(id=order_id, portfolio_id=pid, symbol="AAPL", sec_type="STK",
                   side="BUY", qty=2.0, order_type="MKT", status="SUBMITTED")
        row.update(kw)
        session.add(Order(**row))
        await session.commit()


def make_broker(sf, stub: StubSnapTrade, **settings):
    client = SnapTradeClient("CID", "KEY", transport=stub.transport())
    journal = Journal(sf, Bus())
    broker = SnapTradeBroker(client, sf, journal, FakeSettings(**settings),
                             account_for=lambda pid: "acct-1")
    collector = Collector()
    broker.on_report = collector
    return broker, collector, client


def border(order_id: str, **kw) -> BrokerOrder:
    base = dict(id=order_id, symbol="AAPL", sec_type="STK", side=OrderSide.BUY,
                qty=2.0, order_type=OrderType.MKT, tif=TimeInForce.DAY,
                portfolio_id="p1")
    base.update(kw)
    return BrokerOrder(**base)


async def test_submit_happy_path(sf):
    stub = StubSnapTrade()
    stub.place_response = {"brokerage_order_id": "bo-77", "status": "PENDING"}
    broker, col, client = make_broker(sf, stub)
    oid = new_id()
    await seed_order(sf, oid)

    await broker.submit(border(oid, order_type=OrderType.LMT, limit_price=101.5,
                               tif=TimeInForce.GTC))

    method, path, params, body = stub.calls("/trade/place")[0]
    assert body["account_id"] == "acct-1"
    assert body["action"] == "BUY"
    assert body["order_type"] == "Limit"
    assert body["time_in_force"] == "GTC"
    assert body["symbol"] == "AAPL"
    assert body["units"] == 2.0
    assert body["price"] == 101.5
    assert body["client_order_id"] == dashed_uuid(oid)

    assert [r.kind for r in col.reports] == ["accepted"]
    async with sf() as session:
        order = await session.get(Order, oid)
    assert order.broker_order_id == "bo-77"
    await client.aclose()


async def test_submit_rejection(sf):
    stub = StubSnapTrade()
    stub.place_error = 400
    broker, col, client = make_broker(sf, stub)
    oid = new_id()
    await seed_order(sf, oid)

    await broker.submit(border(oid))
    assert len(stub.calls("/trade/place")) == 1  # exactly one POST, no retry
    assert [r.kind for r in col.reports] == ["rejected"]
    assert "broker says no" in col.reports[0].reason
    await client.aclose()


async def test_cancel_sends_broker_order_id(sf):
    stub = StubSnapTrade()
    stub.place_response = {"brokerage_order_id": "bo-9", "status": "PENDING"}
    broker, col, client = make_broker(sf, stub)
    oid = new_id()
    await seed_order(sf, oid)
    await broker.submit(border(oid))

    await broker.cancel(oid)
    method, path, params, body = stub.calls("/trading/cancel")[0]
    assert "acct-1" in path
    assert body == {"brokerage_order_id": "bo-9"}
    # no local terminal transition — final state arrives via poll
    assert [r.kind for r in col.reports] == ["accepted"]
    await client.aclose()


async def test_poll_partial_then_executed_delta_dedup(sf):
    stub = StubSnapTrade()
    stub.place_response = {"brokerage_order_id": "bo-5", "status": "PENDING"}
    broker, col, client = make_broker(sf, stub)
    oid = new_id()
    await seed_order(sf, oid)
    await broker.submit(border(oid))

    partial = {"brokerage_order_id": "bo-5", "status": "PARTIAL",
               "filled_quantity": 1.0, "execution_price": 100.0}
    stub.recent_orders["acct-1"] = [partial]
    await broker.poll_once()
    await broker.poll_once()  # identical payload — must not re-emit
    fills = col.fills()
    assert len(fills) == 1
    assert fills[0].fill_qty == 1.0 and fills[0].fill_price == 100.0

    stub.recent_orders["acct-1"] = [{
        "brokerage_order_id": "bo-5", "status": "EXECUTED",
        "filled_quantity": 2.0, "execution_price": 100.5}]
    await broker.poll_once()
    fills = col.fills()
    assert len(fills) == 2
    assert fills[1].fill_qty == 1.0
    assert fills[1].fill_price == pytest.approx(101.0)  # (2*100.5 - 1*100)/1
    # deterministic exec ids, distinct per cumulative level
    assert fills[0].exec_id != fills[1].exec_id
    await broker.poll_once()  # untracked now — no further reports
    assert len(col.fills()) == 2
    await client.aclose()


async def test_poll_cancel_after_partial(sf):
    stub = StubSnapTrade()
    stub.place_response = {"brokerage_order_id": "bo-6", "status": "PENDING"}
    broker, col, client = make_broker(sf, stub)
    oid = new_id()
    await seed_order(sf, oid)
    await broker.submit(border(oid))

    stub.recent_orders["acct-1"] = [{
        "brokerage_order_id": "bo-6", "status": "PARTIAL_CANCELED",
        "filled_quantity": 1.0, "execution_price": 99.0}]
    await broker.poll_once()
    kinds = [r.kind for r in col.reports]
    assert kinds == ["accepted", "fill", "cancelled"]  # delta lands before cancel
    await client.aclose()


async def test_unknown_outcome_reconcile_found(sf):
    stub = StubSnapTrade()
    stub.place_error = httpx.ConnectError("wire cut mid-flight")
    broker, col, client = make_broker(sf, stub)
    oid = new_id()
    await seed_order(sf, oid)
    # the order DID reach the broker; recentOrders reveals it by client_order_id
    stub.recent_orders["acct-1"] = [{
        "brokerage_order_id": "bo-ghost", "status": "ACCEPTED",
        "client_order_id": dashed_uuid(oid), "filled_quantity": 0.0}]

    await broker.submit(border(oid))
    assert len(stub.calls("/trade/place")) == 1  # never resubmitted
    assert [r.kind for r in col.reports] == ["accepted"]
    async with sf() as session:
        order = await session.get(Order, oid)
        unknown_events = (await session.execute(
            select(Event).where(Event.type == "BrokerSubmitUnknown"))).scalars().all()
    assert order.broker_order_id == "bo-ghost"
    assert len(unknown_events) == 1
    await client.aclose()


async def test_unknown_outcome_reconcile_not_found(sf):
    stub = StubSnapTrade()
    stub.place_error = httpx.ConnectError("wire cut mid-flight")
    broker, col, client = make_broker(sf, stub, **{"snaptrade.reconcile_seconds": 0.3})
    oid = new_id()
    await seed_order(sf, oid)
    stub.recent_orders["acct-1"] = []  # broker never saw it

    await broker.submit(border(oid))
    assert len(stub.calls("/trade/place")) == 1
    assert [r.kind for r in col.reports] == ["rejected"]
    assert "unknown" in col.reports[0].reason
    await client.aclose()


async def test_per_account_throttle(sf):
    stub = StubSnapTrade()
    broker, col, client = make_broker(sf, stub)
    o1, o2 = new_id(), new_id()
    await seed_order(sf, o1)
    await seed_order(sf, o2)

    start = time.monotonic()
    await asyncio.gather(broker.submit(border(o1)), broker.submit(border(o2)))
    elapsed = time.monotonic() - start
    assert elapsed >= 1.0  # second place waited for the 1.1s spacing
    assert len(stub.calls("/trade/place")) == 2
    await client.aclose()
