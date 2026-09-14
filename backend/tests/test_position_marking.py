"""How a position is valued.

2026-09-14: EM Practice held 2 INTC 0DTE calls bought at $1.00 and one print
marked them near $7. Equity jumped +$1,406 (+14%) for a single 30 s sample and
that spike was persisted into equity_points for good — it set the dashboard
chart's whole vertical range for the day, and the same figure feeds the
daily-loss halt, where a bad print the other way halts a book that never lost
anything. Options mark off the two-sided market now.
"""
import pytest

from zargar.domain import Quote
from zargar.models import Portfolio


async def _book_with(engine, symbol: str, sec_type: str, qty: float, avg: float) -> str:
    pid = f"mark{sec_type}{int(qty)}"
    async with engine.sf() as session:
        session.add(Portfolio(id=pid, name=f"Mark {pid}", kind="sim",
                              cash=10_000.0, starting_cash=10_000.0, base_currency="USD"))
        await session.commit()
    await engine.positions.load()
    engine.positions._positions[(pid, symbol, sec_type)] = {
        "portfolioId": pid, "symbol": symbol, "secType": sec_type,
        "qty": qty, "avgCost": avg, "realizedPnl": 0.0, "currency": "USD",
    }
    return pid


OPT = "INTC260914C00096000"


@pytest.mark.asyncio
async def test_an_option_marks_at_the_mid_not_a_lone_print(engine):
    """The regression: a $7 print against a $1.45/$1.55 book is not a valuation."""
    pid = await _book_with(engine, OPT, "OPT", 2.0, 1.00)
    engine.quotes.on_quote(Quote(symbol=OPT, bid=1.45, ask=1.55, last=7.03))
    pos = engine.positions._positions[(pid, OPT, "OPT")]
    assert engine.positions._mark(pos) == pytest.approx(1.50)
    # 2 contracts x 100 x 1.50 = 300, not the 1,406 the bad print implied
    assert await engine.positions.equity(pid) == pytest.approx(10_300.0)


@pytest.mark.asyncio
async def test_a_zero_bid_marks_at_half_the_ask_not_at_a_stale_print(engine):
    """The contract is going worthless; the ask is the only live information.

    Falling through to `last` here is what let a stale print back in: a 0 bid
    for one tick put a $123 spike in the headline on 2026-09-14.
    """
    pid = await _book_with(engine, OPT, "OPT", 2.0, 1.00)
    engine.quotes.on_quote(Quote(symbol=OPT, bid=0.0, ask=0.05, last=7.03))
    pos = engine.positions._positions[(pid, OPT, "OPT")]
    assert engine.positions._mark(pos) == pytest.approx(0.025)


@pytest.mark.asyncio
async def test_with_no_market_at_all_the_print_is_the_fallback(engine):
    """No bid AND no ask: a print is all there is."""
    pid = await _book_with(engine, OPT, "OPT", 2.0, 1.00)
    engine.quotes.on_quote(Quote(symbol=OPT, bid=0.0, ask=0.0, last=0.03))
    pos = engine.positions._positions[(pid, OPT, "OPT")]
    assert engine.positions._mark(pos) == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_shares_are_unchanged(engine):
    """Only options changed: an equity print IS the valuation."""
    pid = await _book_with(engine, "AAPL", "STK", 10.0, 200.0)
    engine.quotes.on_quote(Quote(symbol="AAPL", bid=249.0, ask=251.0, last=255.0))
    pos = engine.positions._positions[(pid, "AAPL", "STK")]
    assert engine.positions._mark(pos) == pytest.approx(255.0)


@pytest.mark.asyncio
async def test_with_no_quote_at_all_the_brokers_mark_wins_then_avg_cost(engine):
    pid = await _book_with(engine, OPT, "OPT", 2.0, 1.00)
    pos = engine.positions._positions[(pid, OPT, "OPT")]
    assert engine.positions._mark(pos) == pytest.approx(1.00)      # avg cost
    pos["mark"] = 1.20
    assert engine.positions._mark(pos) == pytest.approx(1.20)      # broker's sync mark


@pytest.mark.asyncio
async def test_the_displayed_pnl_and_the_equity_agree(engine):
    """One mark, so the row you read and the number risk reads cannot diverge."""
    pid = await _book_with(engine, OPT, "OPT", 2.0, 1.00)
    engine.quotes.on_quote(Quote(symbol=OPT, bid=1.45, ask=1.55, last=7.03))
    row = engine.positions.positions_list(pid)[0]
    assert row["last"] == pytest.approx(1.50)
    assert row["marketValue"] == pytest.approx(300.0)
    assert row["unrealizedPnl"] == pytest.approx(100.0)
    eq = await engine.positions.equity(pid)
    assert eq - 10_000.0 == pytest.approx(row["marketValue"])
