"""End-to-end engine tests on the sim broker + real Postgres."""
import pytest
from sqlalchemy import func, select

from zargar.models import Event
from zargar.orders import BracketSpec, OrderIntent
from .conftest import wait_for


def sim_portfolio(engine):
    return next(p for p in engine.positions.portfolios() if p["kind"] == "sim")


async def wait_quote(engine, symbol):
    await engine.ensure_symbol(symbol)
    await wait_for(lambda: engine.quotes.get(symbol) is not None)
    return engine.quotes.get(symbol)


async def test_market_order_fills_and_updates_position(engine):
    pid = sim_portfolio(engine)["id"]
    await wait_quote(engine, "AAPL")
    order = await engine.orders.place(OrderIntent(
        portfolio_id=pid, symbol="AAPL", side="BUY", qty=2, order_type="MKT"))
    assert order["status"] == "SUBMITTED", order

    async def filled():
        rows = await engine.orders.list_orders(pid)
        return any(o["id"] == order["id"] and o["status"] == "FILLED" for o in rows)
    await wait_for(filled)

    assert engine.positions.position_qty(pid, "AAPL") == 2
    pf = engine.positions.portfolio(pid)
    assert pf["cash"] < 10_000  # paid for shares + commission
    executions = await engine.orders.list_executions(pid)
    assert len(executions) == 1
    assert executions[0]["qty"] == 2


async def test_risk_rejection_persists_reason(engine):
    pid = sim_portfolio(engine)["id"]
    await wait_quote(engine, "AAPL")
    order = await engine.orders.place(OrderIntent(
        portfolio_id=pid, symbol="AAPL", side="BUY", qty=500, order_type="MKT"))
    assert order["status"] == "REJECTED_RISK"
    assert "cap" in (order["rejectReason"] or "") or "%" in (order["rejectReason"] or "")
    # journal has the risk verdict
    async with engine.sf() as session:
        count = (await session.execute(
            select(func.count(Event.id)).where(Event.type == "RiskCheckFailed",
                                               Event.aggregate_id == order["id"]))).scalar_one()
    assert count == 1


async def test_kill_switch_blocks_and_persists(engine):
    pid = sim_portfolio(engine)["id"]
    await wait_quote(engine, "MSFT")
    await engine.engage_halt("test halt")
    order = await engine.orders.place(OrderIntent(
        portfolio_id=pid, symbol="MSFT", side="BUY", qty=1, order_type="MKT"))
    assert order["status"] == "REJECTED_RISK"
    assert "halt" in order["rejectReason"].lower()
    await engine.release_halt()
    order2 = await engine.orders.place(OrderIntent(
        portfolio_id=pid, symbol="MSFT", side="BUY", qty=1, order_type="MKT"))
    assert order2["status"] == "SUBMITTED"


async def test_mode_aliases_and_order_level_dry_run(engine):
    pid = sim_portfolio(engine)["id"]
    await wait_quote(engine, "AAPL")
    # legacy mode strings fold into the practice|live model
    await engine.settings.set("trading.mode", "dry_run")
    assert engine.settings.get("trading.mode") == "practice"
    await engine.settings.set("trading.mode", "sim")
    assert engine.settings.get("trading.mode") == "practice"
    await engine.settings.set("trading.mode", "paper")
    assert engine.settings.get("trading.mode") == "live"
    await engine.settings.set("trading.mode", "practice")
    # dry run is a per-order flag, not a mode: it validates and never routes
    order = await engine.orders.place(OrderIntent(
        portfolio_id=pid, symbol="AAPL", side="BUY", qty=1, order_type="MKT",
        dry_run=True))
    assert order["status"] == "DRY_RUN"
    assert engine.positions.position_qty(pid, "AAPL") == 0


async def test_live_order_blocked_in_practice_mode(engine):
    live = next(p for p in engine.positions.portfolios() if p["kind"] == "live")
    await wait_quote(engine, "AAPL")
    order = await engine.orders.place(OrderIntent(
        portfolio_id=live["id"], symbol="AAPL", side="BUY", qty=1, order_type="MKT"))
    assert order["status"] == "REJECTED_RISK"
    assert "blocks" in order["rejectReason"]


async def test_bracket_spawns_children_and_oca(engine):
    pid = sim_portfolio(engine)["id"]
    await wait_quote(engine, "AAPL")
    order = await engine.orders.place(OrderIntent(
        portfolio_id=pid, symbol="AAPL", side="BUY", qty=2, order_type="MKT",
        bracket=BracketSpec(take_profit_pct=50.0, stop_loss_pct=50.0)))

    async def children_exist():
        rows = await engine.orders.list_orders(pid)
        return len([o for o in rows if o["parentId"] == order["id"]]) == 2
    await wait_for(children_exist)

    rows = await engine.orders.list_orders(pid)
    children = [o for o in rows if o["parentId"] == order["id"]]
    kinds = sorted(c["orderType"] for c in children)
    assert kinds == ["LMT", "STP"]
    assert all(c["ocaGroup"] for c in children)
    parent = next(o for o in rows if o["id"] == order["id"])
    tp = next(c for c in children if c["orderType"] == "LMT")
    sl = next(c for c in children if c["orderType"] == "STP")
    assert tp["limitPrice"] == pytest.approx(parent["avgFillPrice"] * 1.5, rel=0.01)
    assert sl["stopPrice"] == pytest.approx(parent["avgFillPrice"] * 0.5, rel=0.01)


async def test_position_avg_cost_and_realized_pnl(engine):
    keeper = engine.positions
    pid = sim_portfolio(engine)["id"]
    await keeper.apply_fill(pid, "TEST", "STK", "BUY", 10, 100.0, 1.0)
    await keeper.apply_fill(pid, "TEST", "STK", "BUY", 10, 110.0, 1.0)
    assert keeper.position_qty(pid, "TEST") == 20
    pos = next(p for p in keeper.positions_list(pid) if p["symbol"] == "TEST")
    assert pos["avgCost"] == pytest.approx(105.0)
    # sell half at 120 -> realized (120-105)*10 = 150
    result = await keeper.apply_fill(pid, "TEST", "STK", "SELL", 10, 120.0, 1.0)
    assert result["realizedPnl"] == pytest.approx(150.0)
    assert keeper.position_qty(pid, "TEST") == 10


async def test_equity_and_snapshot(engine):
    pid = sim_portfolio(engine)["id"]
    eq = await engine.positions.equity(pid)
    assert eq == pytest.approx(10_000, rel=0.05)
    points = await engine.positions.snapshot_equity()
    assert any(p["portfolioId"] == pid for p in points)
    series = await engine.positions.equity_series(pid)
    assert len(series) >= 1


async def test_chart_history_seeded(engine):
    await engine.ensure_symbol("NVDA")
    bars = engine.bars.bars("NVDA", tf="1m", limit=100)
    assert len(bars) >= 20  # synthesized history present
    bars5 = engine.bars.bars("NVDA", tf="5m", limit=10)
    assert bars5
