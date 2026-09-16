"""The day anchor every "today" figure measures from.

Regression cover for 2026-09-14: the dashboard's total showed red on a green
morning because the move was derived client-side from a thinned chart array.
The anchor now comes from the persisted equity points, which also means it
survives a restart — the old in-memory one re-based the day at restart price
and the daily-loss halt forgot how far down a book already was.
"""
import datetime as dt

import pytest
from zoneinfo import ZoneInfo

from sqlalchemy import select

from zargar.domain import Quote
from zargar.models import EquityPoint, Event, Portfolio

ET = ZoneInfo("America/New_York")


def _day0_ms() -> int:
    """Today's 04:00 ET, in epoch ms — the boundary the anchor is read against."""
    return int(dt.datetime.now(tz=ET).replace(
        hour=4, minute=0, second=0, microsecond=0).timestamp() * 1000)


async def _book(engine, *, cash: float = 10_000.0) -> str:
    """A sim book with one share of a quoted symbol, so equity is quote-backed."""
    pid = "day" + dt.datetime.now().strftime("%H%M%S%f")[:10]
    async with engine.sf() as session:
        session.add(Portfolio(id=pid, name=f"Day {pid}", kind="sim",
                              cash=cash, starting_cash=cash, base_currency="USD"))
        await session.commit()
    await engine.positions.load()
    return pid


async def _points(engine, pid: str, samples: list[tuple[int, float]]) -> None:
    async with engine.sf() as session:
        for ts, eq in samples:
            session.add(EquityPoint(portfolio_id=pid, ts=ts, equity=eq, cash=eq))
        await session.commit()


@pytest.mark.asyncio
async def test_anchor_is_the_previous_sessions_close(engine):
    """Yesterday's last sample, not today's first — the house day-change rule."""
    pid = await _book(engine)
    day0 = _day0_ms()
    await _points(engine, pid, [
        (day0 - 20 * 3600_000, 9_500.0),   # yesterday morning
        (day0 - 9 * 3600_000, 9_900.0),    # yesterday's close  <- the anchor
        (day0 + 2 * 3600_000, 9_700.0),    # today, already down
        (day0 + 5 * 3600_000, 9_800.0),
    ])
    assert await engine.positions.day_start_equity(pid) == pytest.approx(9_900.0)


@pytest.mark.asyncio
async def test_a_book_with_no_history_anchors_on_its_first_sample_today(engine):
    pid = await _book(engine)
    day0 = _day0_ms()
    await _points(engine, pid, [(day0 + 3600_000, 10_000.0), (day0 + 2 * 3600_000, 10_250.0)])
    assert await engine.positions.day_start_equity(pid) == pytest.approx(10_000.0)


@pytest.mark.asyncio
async def test_the_anchor_survives_a_restart(engine):
    """The regression that mattered: a fresh process must not re-base the day.

    A book that closed at 10,000 and is down to 9,600 reads -4% whether or not
    the engine was restarted at 9,600 in between.
    """
    pid = await _book(engine)
    day0 = _day0_ms()
    await _points(engine, pid, [
        (day0 - 6 * 3600_000, 10_000.0),                 # yesterday's close
        (day0 + 3600_000, 9_600.0),                      # today, down 4%
    ])
    engine.positions._day_start_equity.clear()           # what a restart looks like
    assert await engine.positions.day_start_equity(pid) == pytest.approx(10_000.0)

    pct = await engine.positions.daily_loss_pct(pid)
    assert pct == pytest.approx(0.0)                     # equity is still 10k cash
    # and once the book actually loses, the loss is measured from the close
    engine.positions._portfolios[pid]["cash"] = 9_600.0
    assert await engine.positions.daily_loss_pct(pid) == pytest.approx(-4.0, abs=0.01)


@pytest.mark.asyncio
async def test_the_anchor_is_published_with_every_equity_push(engine):
    """The UI colours the move from this, so it has to ride along with equity."""
    pid = await _book(engine)
    await _points(engine, pid, [(_day0_ms() - 3600_000, 9_800.0)])
    points = await engine.positions.snapshot_equity()
    mine = next(p for p in points if p["portfolioId"] == pid)
    assert mine["dayStart"] == pytest.approx(9_800.0)
    assert mine["equity"] - mine["dayStart"] == pytest.approx(200.0, abs=0.01)


@pytest.mark.asyncio
async def test_a_broker_level_set_moves_the_anchor_not_todays_pnl(engine):
    """A sync is not trading P&L: +$500 of newly-visible cash must not read as a gain."""
    pid = await _book(engine)
    await _points(engine, pid, [(_day0_ms() - 3600_000, 10_000.0)])
    assert await engine.positions.day_start_equity(pid) == pytest.approx(10_000.0)

    await engine.positions.sync_portfolio_state(
        pid, cash=10_500.0, positions=[], source="test")
    assert await engine.positions.day_start_equity(pid) == pytest.approx(10_500.0)
    assert await engine.positions.daily_loss_pct(pid) == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_a_level_set_on_a_book_with_no_anchor_yet_is_not_a_loss(engine):
    """The anchor must be resolved against the PRE-sync book.

    Resolving it afterwards anchors on the new equity and the shift then counts
    the same delta twice: a book going 0 -> 10,000 read as -50% and tripped the
    daily-loss halt on the next order (four test_engine_snaptrade failures).
    """
    pid = await _book(engine, cash=0.0)
    assert not engine.positions._day_start_equity          # nothing anchored yet

    await engine.positions.sync_portfolio_state(
        pid, cash=10_000.0, positions=[], source="test")

    assert await engine.positions.day_start_equity(pid) == pytest.approx(10_000.0)
    assert await engine.positions.daily_loss_pct(pid) == pytest.approx(0.0)


def _hold(engine, pid: str, symbol: str, qty: float, avg: float, currency: str, sec_type: str = "STK"):
    engine.positions._positions[(pid, symbol, sec_type)] = {
        "portfolioId": pid, "symbol": symbol, "secType": sec_type,
        "qty": qty, "avgCost": avg, "realizedPnl": 0.0, "currency": currency,
    }


@pytest.mark.asyncio
async def test_a_sync_that_changes_nothing_never_moves_the_anchor(engine):
    """The 2026-09-15 leak: a broker sync that only CORRECTS a position's
    currency (in-memory CAD, broker says USD) used to shift the anchor by the
    whole FX difference of the holding - nothing moved, nothing should shift."""
    pid = await _book(engine)
    engine.quotes.on_quote(Quote(symbol="USDCAD=X", bid=1.39, ask=1.39, last=1.39))
    engine.quotes.on_quote(Quote(symbol="TQQQ", bid=67.8, ask=68.0, last=67.9))
    engine.positions._portfolios[pid]["baseCurrency"] = "CAD"
    _hold(engine, pid, "TQQQ", 42.0, 32.17, currency="CAD")       # mislabelled, as loaded
    await _points(engine, pid, [(_day0_ms() - 3600_000, 4_096.92)])
    assert await engine.positions.day_start_equity(pid) == pytest.approx(4_096.92)

    await engine.positions.sync_portfolio_state(
        pid, cash=10_000.0,
        positions=[{"symbol": "TQQQ", "secType": "STK", "qty": 42.0, "avgCost": 32.17,
                    "currency": "USD", "price": 67.9}],
        source="test")
    assert await engine.positions.day_start_equity(pid) == pytest.approx(4_096.92)
    async with engine.sf() as session:
        n = len((await session.execute(select(Event).where(
            Event.type == "DayAnchorShifted", Event.portfolio_id == pid))).scalars().all())
    assert n == 0


@pytest.mark.asyncio
async def test_holdings_that_appear_at_a_sync_are_a_level_set(engine):
    """Ten shares the broker reports for the first time are money that was
    already there, valued at the book's mark - not a gain made today."""
    pid = await _book(engine)
    engine.quotes.on_quote(Quote(symbol="XYZ", bid=4.9, ask=5.1, last=5.0))
    await _points(engine, pid, [(_day0_ms() - 3600_000, 10_000.0)])
    assert await engine.positions.day_start_equity(pid) == pytest.approx(10_000.0)

    await engine.positions.sync_portfolio_state(
        pid, cash=10_000.0,
        positions=[{"symbol": "XYZ", "secType": "STK", "qty": 10.0, "avgCost": 4.0, "currency": "USD"}],
        source="test")
    assert await engine.positions.day_start_equity(pid) == pytest.approx(10_050.0)
    assert await engine.positions.daily_loss_pct(pid) == pytest.approx(0.0, abs=0.01)


@pytest.mark.asyncio
async def test_level_sets_are_replayed_after_a_restart(engine):
    """A transfer at 10:00 must still be a transfer, not a loss, after the
    engine restarts at 14:00 - the shift is journaled and folded back in."""
    pid = await _book(engine)
    await _points(engine, pid, [(_day0_ms() - 3600_000, 10_000.0)])
    assert await engine.positions.day_start_equity(pid) == pytest.approx(10_000.0)
    await engine.positions.sync_portfolio_state(pid, cash=8_400.0, positions=[], source="test")
    assert await engine.positions.day_start_equity(pid) == pytest.approx(8_400.0)

    engine.positions._day_start_equity.clear()                    # the restart
    assert await engine.positions.day_start_equity(pid) == pytest.approx(8_400.0)
    assert await engine.positions.daily_loss_pct(pid) == pytest.approx(0.0, abs=0.01)
    async with engine.sf() as session:
        ev = (await session.execute(select(Event).where(
            Event.type == "DayAnchorShifted", Event.portfolio_id == pid))).scalars().one()
    assert ev.payload["delta"] == pytest.approx(-1_600.0)
    assert ev.payload["cashDelta"] == pytest.approx(-1_600.0)
