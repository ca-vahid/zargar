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

from zargar.models import EquityPoint, Portfolio

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
