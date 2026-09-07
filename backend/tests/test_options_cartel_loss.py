"""Daily price/fee attribution, carried marks, FX and persistent loss latches."""
import asyncio
import datetime as dt
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from zargar.api.app import create_app
from zargar.domain import Quote
from zargar.engine import Engine
from zargar.marketstructure.market_calendar import previous_trading_day
from zargar.marketstructure.sessions import session_bounds
from zargar.models import BarRow, Event, Execution, ManagedPositionRow, Order, Portfolio
from zargar.techniques.options_cartel.loss import daily_loss_report, loss_gate

from .conftest import make_test_config

DAY = dt.date(2026, 5, 5)
OPEN, _ = session_bounds(DAY.isoformat())
PREVIOUS_OPEN, _ = session_bounds(previous_trading_day(DAY).isoformat())
NOW = OPEN+2*60*60_000


@pytest.fixture
async def ledger(fresh_db):
    engine = Engine(make_test_config())
    async with engine.sf() as session, session.begin():
        session.add(Portfolio(id="pf", name="test", kind="sim", cash=10000, starting_cash=10000, base_currency="USD"))
    await engine.positions.load()
    yield engine
    await engine.db.dispose()


async def fill(engine, key, side, qty, price, at, *, fee=0., symbol="TEST", sec_type="STK", technique="options_cartel"):
    async with engine.sf() as session, session.begin():
        session.add(Order(id=key, portfolio_id="pf", technique=technique, symbol=symbol, sec_type=sec_type,
                          side=side, qty=qty, order_type="MKT", status="FILLED", filled_qty=qty, avg_fill_price=price))
        await session.flush()
        session.add(Execution(id=f"fill-{key}", order_id=key, portfolio_id="pf", symbol=symbol, side=side,
                              qty=qty, price=price, commission=fee, ts=dt.datetime.fromtimestamp(at/1000, dt.UTC)))


async def holding(engine, qty, *, symbol="TEST", sec_type="STK"):
    async with engine.sf() as session, session.begin():
        session.add(ManagedPositionRow(id=f"held-{symbol}", portfolio_id="pf", technique="options_cartel",
                    symbol="TEST", status="open", config={}, state={},
                    legs=[{"symbol": symbol, "secType": sec_type, "qty": qty}]))


async def mark(engine, price, *, symbol="TEST"):
    async with engine.sf() as session, session.begin():
        session.add(BarRow(symbol=symbol, tf="1d", ts=PREVIOUS_OPEN, open=price, high=price,
                           low=price, close=price, volume=1000))


async def test_same_day_closed_trade_counts_fees_without_needing_quotes(ledger):
    await fill(ledger, "buy", "BUY", 2, 100, OPEN, fee=1)
    await fill(ledger, "sell", "SELL", 2, 110, OPEN+60_000, fee=1)
    await fill(ledger, "other", "BUY", 100, 100, OPEN, technique="team2")
    report = await daily_loss_report(ledger, "pf", now_ms=NOW)
    assert report["available"] and report["pnl"] == 18
    assert report["assets"][0]["openingQty"] == report["assets"][0]["currentQty"] == 0


async def test_carried_gain_before_today_is_excluded_from_today_result(ledger):
    await fill(ledger, "old", "BUY", 2, 80, PREVIOUS_OPEN, fee=1)
    await fill(ledger, "trim", "SELL", 1, 105, OPEN, fee=1)
    await holding(ledger, 1)
    await mark(ledger, 100)
    ledger.quotes.on_quote(Quote("TEST", bid=110, ask=110.1, last=110, ts=NOW))
    report = await daily_loss_report(ledger, "pf", now_ms=NOW)
    assert report["available"] and report["pnl"] == 14  # 105 + 110 - 2*100 - today's $1 fee


async def test_option_requires_its_own_prior_close_and_uses_contract_multiplier(ledger):
    symbol = "TEST261016C00100000"
    await fill(ledger, "old", "BUY", 2, 1, PREVIOUS_OPEN, symbol=symbol, sec_type="OPT")
    await fill(ledger, "trim", "SELL", 1, 2.5, OPEN, fee=.5, symbol=symbol, sec_type="OPT")
    await holding(ledger, 1, symbol=symbol, sec_type="OPT")
    await mark(ledger, 100)  # an underlying close is not an option mark
    ledger.quotes.on_quote(Quote(symbol, bid=3, ask=3.1, last=3, ts=NOW, source="opra"))
    assert not (await daily_loss_report(ledger, "pf", now_ms=NOW))["available"]
    await mark(ledger, 2, symbol=symbol)
    report = await daily_loss_report(ledger, "pf", now_ms=NOW)
    assert report["available"] and report["pnl"] == 149.5


@pytest.mark.parametrize("issue", ["stale", "delayed", "missing", "crossed"])
async def test_missing_or_invalid_marks_are_unknown_not_zero(ledger, issue):
    await fill(ledger, "buy", "BUY", 1, 100, OPEN)
    await holding(ledger, 1)
    if issue != "missing":
        ledger.quotes.on_quote(Quote("TEST", bid=100, ask=99 if issue == "crossed" else 100.1, last=100,
                                    ts=NOW-60_000 if issue == "stale" else NOW, source="chain" if issue == "delayed" else "sim"))
    report = await daily_loss_report(ledger, "pf", now_ms=NOW)
    assert not report["available"] and report["pnl"] is None


async def test_fx_conversion_is_explicit_and_missing_fx_blocks_measurement(ledger):
    await fill(ledger, "buy", "BUY", 1, 100, OPEN, symbol="TEST.TO")
    await fill(ledger, "sell", "SELL", 1, 90, OPEN+60_000, symbol="TEST.TO", fee=1)
    assert not (await daily_loss_report(ledger, "pf", now_ms=NOW))["available"]
    ledger.quotes.on_quote(Quote("CADUSD=X", last=.75, ts=NOW))
    report = await daily_loss_report(ledger, "pf", now_ms=NOW)
    assert report["available"] and report["nativePnlByCurrency"]["CAD"] == -11 and report["pnl"] == -8.25
    assert "FX translation excluded" in report["basis"]


async def test_latched_day_loss_survives_recovery_and_does_not_leak_to_next_day(ledger):
    await ledger.settings.set("techniques.options_cartel.daily_loss_halt_pct", 1.)
    await fill(ledger, "buy", "BUY", 2, 100, OPEN, fee=1)
    await fill(ledger, "sell", "SELL", 2, 50, OPEN+60_000, fee=1)
    a, b = await asyncio.gather(loss_gate(ledger, "pf", now_ms=NOW), loss_gate(ledger, "pf", now_ms=NOW))
    assert not a["passed"] and not b["passed"]
    async with ledger.sf() as session:
        events = (await session.scalars(select(Event).where(Event.type == "TechniqueCartelLossHalt"))).all()
    assert len(events) == 1
    await fill(ledger, "winbuy", "BUY", 1, 100, OPEN+120_000)
    await fill(ledger, "winsell", "SELL", 1, 200, OPEN+180_000)
    assert (await daily_loss_report(ledger, "pf", now_ms=NOW))["pnl"] == -2
    # Fresh Engine object has no in-memory latch and must still see the persisted event.
    restored = Engine(make_test_config())
    await restored.settings.load()
    await restored.positions.load()
    try:
        assert not (await loss_gate(restored, "pf", now_ms=NOW))["passed"]
        next_open, _ = session_bounds((DAY+dt.timedelta(days=1)).isoformat())
        assert (await loss_gate(restored, "pf", now_ms=next_open+60_000))["passed"]
    finally:
        await restored.db.dispose()


async def test_ledger_gaps_and_future_fills_cannot_manufacture_available_pnl(ledger):
    await fill(ledger, "future", "BUY", 1, 100, NOW+60_000)
    result = await daily_loss_report(ledger, "pf", now_ms=NOW)
    assert not result["available"] and result["pnl"] is None
    assert any("future-dated" in s for s in result["issues"])


async def test_known_average_price_correction_requires_reconciled_executions(ledger):
    await fill(ledger, "buy", "BUY", 1, 100, OPEN)
    await fill(ledger, "sell", "SELL", 1, 101, OPEN+60_000)
    async with ledger.sf() as session, session.begin():
        order = await session.get(Order, "sell")
        order.avg_fill_price = 102
    result = await daily_loss_report(ledger, "pf", now_ms=NOW)
    assert not result["available"] and result["pnl"] is None
    assert any("average fill price" in issue for issue in result["issues"])


async def test_risk_report_is_authenticated_and_does_not_latch_on_get(ledger, monkeypatch):
    await fill(ledger, "buy", "BUY", 2, 100, OPEN, fee=1)
    await fill(ledger, "sell", "SELL", 2, 50, OPEN+60_000, fee=1)
    await ledger.settings.set("techniques.options_cartel.daily_loss_halt_pct", 1.)
    from zargar.api import routes_options_cartel
    monkeypatch.setattr(routes_options_cartel, "time", SimpleNamespace(time=lambda: NOW/1000))
    ledger.config.auth_token = "risk-test"
    app = create_app(ledger.config, ledger)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/options-cartel/risk/pf")).status_code == 401
        result = await client.get("/api/options-cartel/risk/pf", headers={"Authorization": "Bearer risk-test"})
        assert result.status_code == 200 and result.json()["pnl"] == -102
        assert result.json()["limitPct"] == 1 and not result.json()["halted"]
    async with ledger.sf() as session:
        assert not (await session.scalars(select(Event).where(Event.type == "TechniqueCartelLossHalt"))).all()
    await loss_gate(ledger, "pf", now_ms=NOW)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.get("/api/options-cartel/risk/pf", headers={"Authorization": "Bearer risk-test"})
        assert result.json()["halted"]
