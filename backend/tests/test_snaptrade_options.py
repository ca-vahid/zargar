"""SnapTrade options: order bodies, executor routing, polling, impact, positions,
and the engine-level capability gate (Webull CA supported / Wealthsimple 1156).
"""
import datetime as dt

import pytest
from sqlalchemy import select

import zargar.brokers.snaptrade as st_mod
import zargar.risk as risk_mod
from zargar.brokers.base import BrokerOrder
from zargar.brokers.snaptrade import (
    SnapTradeBroker, extract_unified_position, option_order_body,
)
from zargar.db import make_engine, make_session_factory
from zargar.domain import OrderSide, OrderType, TimeInForce, new_id
from zargar.engine import Engine
from zargar.models import Event, Order, Setting
from zargar.orders import OrderIntent

from .conftest import TEST_DB_URL, make_test_config, wait_for
from .snaptrade_stub import StubSnapTrade, stub_account, stub_connection
from .test_options_service import EXP1, _occ, make_cboe
from .test_snaptrade_executor import make_broker, seed_order

SYM = _occ("XYZ", EXP1, "C", 100)          # XYZ <EXP1> 100 C, unpadded
PADDED = f"XYZ   {dt.date.fromisoformat(EXP1):%y%m%d}C00100000"


# --- request bodies ------------------------------------------------------------------

def test_option_order_body_shapes():
    bo = BrokerOrder(id="x", symbol=SYM, sec_type="OPT", side=OrderSide.BUY, qty=2,
                     order_type=OrderType.LMT, limit_price=2.1, tif=TimeInForce.DAY,
                     option_action="BUY_TO_OPEN")
    body = option_order_body(bo)
    assert body == {
        "order_type": "LIMIT", "time_in_force": "Day", "price_effect": "DEBIT",
        "limit_price": "2.10",
        "legs": [{"instrument": {"symbol": PADDED, "instrument_type": "OPTION"},
                  "action": "BUY_TO_OPEN", "units": 2}],
    }
    sell = BrokerOrder(id="y", symbol=SYM, sec_type="OPT", side=OrderSide.SELL, qty=1,
                       order_type=OrderType.MKT, tif=TimeInForce.GTC, option_action="SELL_TO_CLOSE")
    b2 = option_order_body(sell)
    assert b2["order_type"] == "MARKET" and b2["price_effect"] == "CREDIT"
    assert b2["time_in_force"] == "GTC" and "limit_price" not in b2
    stop = BrokerOrder(id="z", symbol=SYM, sec_type="OPT", side=OrderSide.SELL, qty=1,
                       order_type=OrderType.STP, stop_price=1.5, option_action="SELL_TO_CLOSE")
    assert option_order_body(stop)["order_type"] == "STOP_LOSS_MARKET"
    assert option_order_body(stop)["stop_price"] == "1.50"
    with pytest.raises(ValueError):
        option_order_body(BrokerOrder(id="q", symbol="AAPL", sec_type="OPT", side=OrderSide.BUY,
                                      qty=1, order_type=OrderType.MKT))
    with pytest.raises(ValueError):
        option_order_body(BrokerOrder(id="q", symbol=SYM, sec_type="OPT", side=OrderSide.BUY,
                                      qty=1.5, order_type=OrderType.MKT))


# --- executor ---------------------------------------------------------------------------

@pytest.fixture
async def sf(fresh_db):
    engine = make_engine(TEST_DB_URL)
    yield make_session_factory(engine)
    await engine.dispose()


def oborder(order_id: str, **kw) -> BrokerOrder:
    base = dict(id=order_id, symbol=SYM, sec_type="OPT", side=OrderSide.BUY, qty=1.0,
                order_type=OrderType.LMT, limit_price=2.1, tif=TimeInForce.DAY,
                portfolio_id="p1", option_action="BUY_TO_OPEN")
    base.update(kw)
    return BrokerOrder(**base)


async def test_submit_option_goes_to_options_endpoint(sf):
    stub = StubSnapTrade()
    stub.option_place_response = {"brokerage_order_id": "obo-7", "orders": [
        {"brokerage_order_id": "obo-7", "status": "PENDING"}]}
    broker, col, client = make_broker(sf, stub)
    oid = new_id()
    await seed_order(sf, oid, symbol=SYM, sec_type="OPT", qty=1.0, order_type="LMT")

    await broker.submit(oborder(oid))
    assert stub.calls("/trade/place") == []
    method, path, params, body = stub.calls("/trading/options")[0]
    assert path == "/api/v1/accounts/acct-1/trading/options"
    assert body["legs"][0]["instrument"]["symbol"] == PADDED
    assert body["legs"][0]["action"] == "BUY_TO_OPEN" and body["legs"][0]["units"] == 1
    assert body["limit_price"] == "2.10" and body["price_effect"] == "DEBIT"
    assert [r.kind for r in col.reports] == ["accepted"]
    async with sf() as session:
        order = await session.get(Order, oid)
    assert order.broker_order_id == "obo-7"

    # fills arrive through recentOrders rows keyed by option_symbol.ticker (padded)
    stub.recent_orders["acct-1"] = [{
        "brokerage_order_id": "obo-7", "status": "EXECUTED", "action": "BUY_OPEN",
        "option_symbol": {"ticker": PADDED, "option_type": "CALL", "strike_price": 100,
                          "expiration_date": f"{EXP1}T00:00:00.000Z"},
        "universal_symbol": None, "filled_quantity": "1", "execution_price": "2.05"}]
    await broker.poll_once()
    fills = col.fills()
    assert len(fills) == 1 and fills[0].fill_qty == 1.0 and fills[0].fill_price == 2.05
    await client.aclose()


async def test_submit_option_rejected_by_broker(sf):
    stub = StubSnapTrade()
    stub.option_place_error = 400
    broker, col, client = make_broker(sf, stub)
    oid = new_id()
    await seed_order(sf, oid, symbol=SYM, sec_type="OPT", qty=1.0)
    await broker.submit(oborder(oid))
    assert len(stub.calls("/trading/options")) == 1
    assert [r.kind for r in col.reports] == ["rejected"]
    assert "options" in col.reports[0].reason
    await client.aclose()


async def test_row_symbol_reads_option_symbol():
    row = {"option_symbol": {"ticker": PADDED}, "universal_symbol": None}
    assert SnapTradeBroker._row_symbol(row) == SYM
    assert SnapTradeBroker._row_symbol({"universal_symbol": {"symbol": "AAPL"}}) == "AAPL"


async def test_option_impact_parses_numbers(sf):
    stub = StubSnapTrade()
    broker, col, client = make_broker(sf, stub)
    res = await broker.option_impact("acct-1", symbol=SYM, side="BUY", qty=1,
                                     order_type="LMT", limit_price=0.2, action="BUY_TO_OPEN")
    assert res["estimatedCashChange"] == 21.04 and res["direction"] == "DEBIT"
    assert res["estimatedFees"] == 1.04
    method, path, params, body = stub.calls("/trading/options/impact")[0]
    assert body["legs"][0]["instrument"]["symbol"] == PADDED and body["limit_price"] == "0.20"
    await client.aclose()


# --- positions -------------------------------------------------------------------------

def test_extract_unified_option_position_from_occ_ticker():
    raw = {"instrument": {"kind": "option", "symbol": PADDED, "currency": "USD", "id": "u-1"},
           "units": "2", "price": "2.30", "cost_basis": "2.05", "currency": "USD"}
    p = extract_unified_position(raw)
    assert p == {"symbol": SYM, "secType": "OPT", "qty": 2.0, "avgCost": 2.05,
                 "price": 2.3, "currency": "USD", "universalId": "u-1"}


def test_extract_unified_option_position_from_fields_and_mini_skip():
    raw = {"instrument": {"kind": "option", "symbol": "XYZ 100 CALL", "option_type": "CALL",
                          "strike_price": "100", "expiration_date": f"{EXP1}T00:00:00Z",
                          "underlying": {"symbol": "XYZ"}},
           "units": "-1", "price": "1.1", "cost_basis": "1.5"}
    p = extract_unified_position(raw)
    assert p["symbol"] == SYM and p["qty"] == -1.0 and p["secType"] == "OPT"
    mini = {"instrument": {"kind": "option", "symbol": PADDED, "is_mini_option": True},
            "units": "1", "price": "1", "cost_basis": "1"}
    assert extract_unified_position(mini) is None
    junk = {"instrument": {"kind": "option", "symbol": "???"}, "units": "1", "price": "1",
            "cost_basis": "1"}
    assert extract_unified_position(junk) is None


# --- engine-level capability gate ------------------------------------------------------

@pytest.fixture
async def two_broker_engine(fresh_db, monkeypatch):
    stub = StubSnapTrade()
    stub.connections = [stub_connection("conn-wb", "Webull Canada"),
                        stub_connection("conn-ws", "Wealthsimple")]
    stub.accounts = [
        stub_account("acct-wb", institution="Webull Canada", name="CASH", conn="conn-wb",
                     total=10_000.0),
        stub_account("acct-ws", institution="Wealthsimple Trade", name="PERSONAL",
                     conn="conn-ws", total=5_000.0),
    ]
    stub.balances["acct-wb"] = [{"currency": {"code": "CAD"}, "cash": 10_000.0}]
    stub.balances["acct-ws"] = [{"currency": {"code": "CAD"}, "cash": 5_000.0}]
    stub.positions["acct-wb"] = []
    stub.positions["acct-ws"] = []
    stub.option_impact_errors["acct-ws"] = (400, {
        "detail": "Option Trade impact is not supported for this brokerage.",
        "status_code": 400, "code": "1156"})
    st_mod.DEFAULT_TRANSPORT = stub.transport()

    db = make_engine(TEST_DB_URL)
    sf = make_session_factory(db)
    async with sf() as session:
        session.add(Setting(key="snaptrade.enabled", value={"v": True}))
        await session.commit()
    await db.dispose()
    monkeypatch.setattr(risk_mod, "is_us_market_hours", lambda now=None: True)

    eng = Engine(make_test_config(
        snaptrade_client_id="CID", snaptrade_consumer_key="KEY", quote_source="sim"))
    await eng.start()
    eng.options.use_client(make_cboe())
    try:
        await wait_for(lambda: len([p for p in eng.positions.portfolios()
                                    if p.get("venue") == "snaptrade"]) == 2
                       and bool(eng.snaptrade_sync.providers))
        yield eng, stub
    finally:
        await eng.stop()
        st_mod.DEFAULT_TRANSPORT = None


def pid_for(eng: Engine, account_id: str) -> str:
    return next(pid for pid, aid in eng.snaptrade_sync._portfolio_to_account.items()
                if aid == account_id)


async def test_capability_gate_and_routing(two_broker_engine):
    eng, stub = two_broker_engine
    await eng.settings.set("trading.mode", "live")
    await eng.ensure_symbol(SYM)
    await wait_for(lambda: eng.quotes.get(SYM) is not None)
    wb, ws = pid_for(eng, "acct-wb"), pid_for(eng, "acct-ws")

    # allowlist verdicts before any probe
    caps = eng.options.capabilities()
    assert caps["acct-wb"]["allowlisted"] is True and caps["acct-wb"]["supported"] is True
    assert caps["acct-ws"]["allowlisted"] is False and caps["acct-ws"]["supported"] is None

    # Wealthsimple: not allowlisted -> the gate rejects before routing (dry run shows it)
    dry = await eng.orders.place(OrderIntent(
        portfolio_id=ws, symbol=SYM, sec_type="OPT", side="BUY", qty=1,
        order_type="LMT", limit_price=2.1, dry_run=True))
    assert dry["status"] == "REJECTED_RISK" and "options unavailable" in dry["rejectReason"]
    assert stub.calls("/trading/options") == []

    # live probe on Wealthsimple returns 1156 -> cached as unsupported + journaled
    res = await eng.options.impact(ws, symbol=SYM, side="BUY", qty=1, limit_price=2.1)
    assert res["supported"] is False and res["code"] == "1156"
    assert eng.options.capability("acct-ws")["supported"] is False
    async with eng.sf() as session:
        evs = (await session.execute(
            select(Event).where(Event.type == "BrokerCapabilityChecked"))).scalars().all()
    assert len(evs) == 1 and evs[0].payload["supported"] is False

    # Webull: probe succeeds, order routes to /trading/options and is accepted
    res = await eng.options.impact(wb, symbol=SYM, side="BUY", qty=1, limit_price=2.1)
    assert res["supported"] is True and res["estimatedFees"] == 1.04
    stub.option_place_response = {"brokerage_order_id": "obo-9", "orders": []}
    order = await eng.orders.place(OrderIntent(
        portfolio_id=wb, symbol=SYM, sec_type="OPT", side="BUY", qty=1,
        order_type="LMT", limit_price=2.1))
    assert order["status"] == "SUBMITTED", order
    assert order["optionAction"] == "BUY_TO_OPEN"
    assert len(stub.calls("/trading/options")) == 1
    _, path, _, body = stub.calls("/trading/options")[0]
    assert path == "/api/v1/accounts/acct-wb/trading/options"
    assert body["legs"][0]["instrument"]["symbol"] == PADDED

    async def accepted():
        rows = await eng.orders.list_orders(wb)
        return any(o["id"] == order["id"] and o["status"] == "ACCEPTED" for o in rows)
    await wait_for(accepted)

    # the REST capability view reflects both verdicts
    from zargar.api.app import create_app
    import httpx
    app = create_app(eng.config, eng)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        r = await client.get("/api/options/capabilities")
        by = {a["accountId"]: a for a in r.json()["accounts"]}
        assert by["acct-wb"]["supported"] is True and by["acct-wb"]["probed"] is True
        assert by["acct-ws"]["supported"] is False
        r = await client.post("/api/options/impact", json={
            "portfolio_id": wb, "symbol": SYM, "side": "BUY", "qty": 1, "limit_price": 2.1})
        assert r.status_code == 200 and r.json()["supported"] is True
