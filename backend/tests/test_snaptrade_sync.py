"""SnapTradeSync: auto-provisioning, authoritative overwrite, journaling."""
import pytest
from sqlalchemy import func, select

from zargar import bus as topics
from zargar.brokers.snaptrade import SnapTradeClient, SnapTradeSync
from zargar.domain import Quote
from zargar.bus import Bus
from zargar.db import make_engine, make_session_factory
from zargar.events import Journal
from zargar.marketdata import QuoteCache
from zargar.models import BrokerageAccount, Event, Portfolio
from zargar.portfolio import PositionKeeper

from .conftest import TEST_DB_URL
from .snaptrade_stub import FakeSettings, StubSnapTrade, stub_account, stub_connection


@pytest.fixture
async def sf(fresh_db):
    engine = make_engine(TEST_DB_URL)
    yield make_session_factory(engine)
    await engine.dispose()


def make_sync(sf, stub: StubSnapTrade):
    bus = Bus()
    journal = Journal(sf, bus)
    positions = PositionKeeper(sf, bus, journal, QuoteCache(bus))
    client = SnapTradeClient("CID", "KEY", transport=stub.transport())
    watched: list[str] = []

    async def ensure_symbol(symbol: str) -> None:
        watched.append(symbol)

    sync = SnapTradeSync(client, sf, positions, journal, FakeSettings(), bus, ensure_symbol)
    return sync, positions, bus, client, watched


def tsx_position(sym="SHOP", units=5.0, avg=90.0, price=100.0):
    return {
        "symbol": {"symbol": {"symbol": sym, "exchange": {"code": "TSX"},
                              "currency": {"code": "CAD"}}},
        "units": units, "average_purchase_price": avg, "price": price,
    }


async def test_unified_positions_endpoint(sf):
    """New accounts get /positions/all (legacy /positions returns 410)."""
    stub = StubSnapTrade()
    stub.connections = [stub_connection()]
    stub.accounts = [stub_account(total=20_000.0)]
    stub.balances["acct-1"] = [{"currency": {"code": "CAD"}, "cash": 67.31}]
    stub.unified_positions = {"acct-1": [
        {"instrument": {"kind": "adr", "symbol": "AAPL.TO", "raw_symbol": "AAPL",
                        "currency": "CAD", "exchange": "XTSE"},
         "units": "89", "price": "44.61", "cost_basis": "32.86", "currency": "CAD"},
        {"instrument": {"kind": "stock", "symbol": "SPCX", "raw_symbol": "SPCX",
                        "currency": "USD", "exchange": "XNAS"},
         "units": "60", "price": "139.42", "cost_basis": "159.67", "currency": "USD"},
        {"instrument": {"kind": "crypto", "symbol": "BTC"},
         "units": "0.5", "price": "60000", "cost_basis": "50000"},  # skipped kind
    ]}
    sync, positions, bus, client, watched = make_sync(sf, stub)

    payload = await sync.sync_once()
    account = payload["providers"][0]["accounts"][0]
    assert account["name"] == "Webull CASH"  # institution not duplicated
    symbols = {p["symbol"] for p in account["positions"]}
    assert symbols == {"AAPL.TO", "SPCX"}
    pid = account["portfolioId"]
    assert positions.position_qty(pid, "AAPL.TO") == 89.0
    aapl = next(p for p in account["positions"] if p["symbol"] == "AAPL.TO")
    assert aapl["avgCost"] == 32.86
    assert stub.calls("/positions") == []  # legacy endpoint never hit


async def test_autoprovision_idempotent(sf):
    stub = StubSnapTrade()
    stub.connections = [stub_connection()]
    stub.accounts = [stub_account(total=20_000.0)]
    stub.balances["acct-1"] = [{"currency": {"code": "CAD"}, "cash": 20_000.0}]
    stub.positions["acct-1"] = [tsx_position()]
    sync, positions, bus, client, watched = make_sync(sf, stub)

    payload = await sync.sync_once()
    assert payload["providers"][0]["broker"] == "Webull Canada"
    account = payload["providers"][0]["accounts"][0]
    assert account["currency"] == "CAD"
    assert account["cash"] == 20_000.0
    assert account["positions"][0]["symbol"] == "SHOP.TO"  # TSX -> .TO
    assert "SHOP.TO" in watched

    pid = account["portfolioId"]
    pf = positions.portfolio(pid)
    assert pf is not None and pf["kind"] == "live" and pf["venue"] == "snaptrade"
    assert sync.account_for(pid) == "acct-1"
    assert positions.position_qty(pid, "SHOP.TO") == 5.0

    await sync.sync_once()  # second run must not duplicate anything
    async with sf() as session:
        n_portfolios = (await session.execute(
            select(func.count(Portfolio.id)))).scalar_one()
        n_links = (await session.execute(
            select(func.count(BrokerageAccount.id)))).scalar_one()
    assert n_portfolios == 1 and n_links == 1
    await client.aclose()


async def test_sync_overwrites_and_preserves_day_loss(sf):
    stub = StubSnapTrade()
    stub.connections = [stub_connection()]
    stub.accounts = [stub_account(total=10_000.0)]
    stub.balances["acct-1"] = [{"currency": {"code": "CAD"}, "cash": 10_000.0}]
    stub.positions["acct-1"] = [tsx_position(units=5.0, avg=90.0)]
    sync, positions, bus, client, _ = make_sync(sf, stub)

    payload = await sync.sync_once()
    pid = payload["providers"][0]["accounts"][0]["portfolioId"]
    # seed realized pnl to prove it survives the overwrite
    key = (pid, "SHOP.TO", "STK")
    positions._positions[key]["realizedPnl"] = 42.0
    # a live quote must exist before the day-start anchor is set
    positions._quotes.on_quote(Quote(symbol="SHOP.TO", bid=99.9, ask=100.1, last=100.0))
    assert await positions.daily_loss_pct(pid) == 0.0  # memoizes day-start equity

    # broker now reports more cash and a different position set
    stub.balances["acct-1"] = [{"currency": {"code": "CAD"}, "cash": 25_000.0}]
    stub.positions["acct-1"] = [tsx_position(sym="TD", units=10.0, avg=80.0)]
    await sync.sync_once()

    assert positions.position_qty(pid, "SHOP.TO") == 0.0
    assert positions.position_qty(pid, "TD.TO") == 10.0
    assert positions._positions[key]["realizedPnl"] == 42.0  # preserved
    pf = positions.portfolio(pid)
    assert pf["cash"] == 25_000.0
    # an authoritative level-set must not register as intraday P&L
    loss = await positions.daily_loss_pct(pid)
    assert abs(loss) < 0.01
    await client.aclose()


async def test_sync_mismatch_warning(sf):
    """Broker's FX-converted total far from our computed equity -> journaled once."""
    stub = StubSnapTrade()
    stub.connections = [stub_connection()]
    stub.accounts = [stub_account(total=20_000.0)]  # broker says 20k
    stub.balances["acct-1"] = [{"currency": {"code": "CAD"}, "cash": 100.0}]
    stub.positions["acct-1"] = []  # we compute equity = 100 -> huge mismatch
    sync, positions, bus, client, _ = make_sync(sf, stub)

    payload = await sync.sync_once()
    account = payload["providers"][0]["accounts"][0]
    assert account["mismatch"] is not None
    assert account["mismatch"]["brokerTotal"] == 20_000.0
    assert account["brokerTotal"] == 20_000.0

    await sync.sync_once()  # same day: warn once, not per cycle
    async with sf() as session:
        n = (await session.execute(
            select(func.count(Event.id)).where(
                Event.type == "BrokerSyncMismatch"))).scalar_one()
    assert n == 1
    await client.aclose()


async def test_sync_journals_and_publishes(sf):
    stub = StubSnapTrade()
    stub.connections = [stub_connection()]
    stub.accounts = [stub_account(total=10_000.0)]
    stub.balances["acct-1"] = [{"currency": {"code": "CAD"}, "cash": 10_000.0}]
    stub.positions["acct-1"] = [tsx_position()]
    sync, positions, bus, client, _ = make_sync(sf, stub)

    queue, unsubscribe = bus.subscribe(topics.SYSTEM)
    await sync.sync_once()
    unsubscribe()

    system_msgs = []
    while not queue.empty():
        system_msgs.append(queue.get_nowait())
    assert any(m.get("kind") == "brokerage" and m.get("providers") for m in system_msgs)

    async with sf() as session:
        types = {t for (t,) in (await session.execute(select(Event.type))).all()}
    assert "BrokerageAccountLinked" in types
    assert "BrokerSync" in types
    assert "PositionReconciled" in types

    # a second identical sync changes nothing — it must not journal again
    before = await _count_broker_syncs(sf)
    await sync.sync_once()
    assert await _count_broker_syncs(sf) == before
    await client.aclose()


async def _count_broker_syncs(sf) -> int:
    async with sf() as session:
        return (await session.execute(
            select(func.count(Event.id)).where(Event.type == "BrokerSync"))).scalar_one()
