"""Daily-loss semantics: halts require zargar trades; drift only warns."""
import datetime as dt

from sqlalchemy import func, select

from zargar import bus as topics
from zargar.models import Event, Order, Portfolio
from zargar.portfolio import ET

from .conftest import wait_for


async def seed_live_portfolio(eng, pid="real1", cash=10_000.0):
    async with eng.sf() as session:
        row = Portfolio(id=pid, name="Webull CASH", kind="live",
                        starting_cash=cash, cash=cash)
        session.add(row)
        await session.commit()
    eng.positions.register_portfolio(row, venue="snaptrade")
    return pid


async def anchor_with_loss(eng, pid, symbol="AAPL", loss_pct=9.0):
    """Give the portfolio a position, anchor day-start, then inflate the
    anchor so current equity reads ~loss_pct% below it."""
    await eng.ensure_symbol(symbol)
    await wait_for(lambda: eng.quotes.get(symbol) is not None)
    eng.positions._positions[(pid, symbol, "STK")] = {
        "portfolioId": pid, "symbol": symbol, "secType": "STK",
        "qty": 10.0, "avgCost": 100.0, "realizedPnl": 0.0,
    }
    assert await eng.positions.daily_loss_pct(pid) == 0.0  # anchors now
    today = dt.datetime.now(tz=ET).date().isoformat()
    eq = await eng.positions.equity(pid)
    eng.positions._day_start_equity[(pid, today)] = eq / (1 - loss_pct / 100)


async def count_events(eng, type_: str) -> int:
    async with eng.sf() as session:
        return (await session.execute(
            select(func.count(Event.id)).where(Event.type == type_))).scalar_one()


async def test_anchor_waits_for_quotes(engine):
    pid = await seed_live_portfolio(engine, pid="anchorless")
    engine.positions._positions[(pid, "ZZZQ", "STK")] = {
        "portfolioId": pid, "symbol": "ZZZQ", "secType": "STK",
        "qty": 5.0, "avgCost": 50.0, "realizedPnl": 0.0,
    }
    # no quote for ZZZQ -> no anchor, no reading
    assert await engine.positions.daily_loss_pct(pid) is None
    today = dt.datetime.now(tz=ET).date().isoformat()
    assert (pid, today) not in engine.positions._day_start_equity

    await engine.ensure_symbol("ZZZQ")
    await wait_for(lambda: engine.quotes.get("ZZZQ") is not None)
    assert await engine.positions.daily_loss_pct(pid) == 0.0  # anchored on real prices
    assert (pid, today) in engine.positions._day_start_equity


async def test_passive_drift_warns_but_never_halts(engine):
    pid = await seed_live_portfolio(engine)
    await anchor_with_loss(engine, pid, loss_pct=9.0)

    queue, unsub = engine.bus.subscribe(topics.SYSTEM)
    await engine.check_daily_loss()
    await engine.check_daily_loss()  # second pass must not re-warn
    unsub()

    assert engine.halt.engaged is False
    assert await count_events(engine, "DailyDriftWarning") == 1
    assert await count_events(engine, "DailyLossHalt") == 0
    drift_msgs = []
    while not queue.empty():
        msg = queue.get_nowait()
        if msg.get("kind") == "drift":
            drift_msgs.append(msg)
    assert len(drift_msgs) == 1
    assert drift_msgs[0]["portfolioId"] == pid
    assert drift_msgs[0]["lossPct"] < -8


async def test_traded_portfolio_still_halts(engine):
    pid = await seed_live_portfolio(engine, pid="traded1")
    await anchor_with_loss(engine, pid, loss_pct=9.0)
    async with engine.sf() as session:
        session.add(Order(id="o-today", portfolio_id=pid, symbol="AAPL",
                          side="BUY", qty=1.0, order_type="MKT", status="FILLED"))
        await session.commit()

    await engine.check_daily_loss()
    assert engine.halt.engaged is True
    assert "Webull CASH" in engine.halt.reason
    assert await count_events(engine, "DailyLossHalt") == 1
    assert await count_events(engine, "DailyDriftWarning") == 0


async def test_dry_run_orders_do_not_arm_the_halt(engine):
    pid = await seed_live_portfolio(engine, pid="dryonly")
    await anchor_with_loss(engine, pid, loss_pct=9.0)
    async with engine.sf() as session:
        session.add(Order(id="o-dry", portfolio_id=pid, symbol="AAPL",
                          side="BUY", qty=1.0, order_type="MKT", status="DRY_RUN"))
        await session.commit()

    await engine.check_daily_loss()
    assert engine.halt.engaged is False
    assert await count_events(engine, "DailyDriftWarning") == 1
