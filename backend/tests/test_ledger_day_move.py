"""The ledger and the Dashboard agree on today (2026-09-14).

The user compared the two screens: Dashboard "+429.97 today", Ledger "TODAY
+145.07", plus a "+4.00 unexplained" pill. Two findings:

* the pill was a marking mismatch — the ledger valued open lots at the last
  print while the book (since v0.7.70) marks options at the mid, and the gap
  was exactly (mid − last) × qty × 100 over three open lots;
* the headline gap was two definitions — the ledger's day row books a trip's
  whole gain on the day it closes, the Dashboard counts today's move. The
  ledger now carries the day move too, so the top tile can say one thing.
"""
import datetime as dt

import pytest
from zoneinfo import ZoneInfo

from zargar.desk import attach_desk
from zargar.domain import Quote, new_id
from zargar.engine import Engine
from zargar.models import EquityPoint, Execution, Order
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config

ET = ZoneInfo("America/New_York")
OPT = "SPCX260911C00155000"


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    attach_desk(eng)
    yield eng
    await eng.stop()


def _practice(rig) -> str:
    return next(p["id"] for p in rig.positions.portfolios() if p["kind"] == "sim")


async def _open_lot(rig, pid: str, sym: str, qty: int = 3, px: float = 2.11) -> None:
    """A BUY that is still riding — no SELL, so the ledger lists it under `open`."""
    oid = new_id()
    async with rig.sf() as session:
        session.add(Order(id=oid, portfolio_id=pid, symbol=sym, sec_type="OPT",
                          side="BUY", qty=qty, filled_qty=qty, order_type="LMT",
                          limit_price=px, status="FILLED", source="signal"))
        await session.flush()
        session.add(Execution(id=new_id(), order_id=oid, portfolio_id=pid,
                              symbol=sym, side="BUY", qty=qty, price=px,
                              ts=dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=9)))
        await session.commit()


def test_mark_price_is_the_books_own_rule(engine):
    """One unit, valued exactly as equity() would value it."""
    engine.quotes.on_quote(Quote(symbol=OPT, bid=2.00, ask=2.10, last=2.50))
    assert engine.positions.mark_price(OPT, "OPT") == pytest.approx(2.05)   # mid, not the print
    engine.quotes.on_quote(Quote(symbol="AAPL", bid=249.0, ask=251.0, last=255.0))
    assert engine.positions.mark_price("AAPL", "STK") == pytest.approx(255.0)  # a share print IS the mark
    assert engine.positions.mark_price("NOPE", "STK") is None              # nothing to mark against


async def test_the_ledger_marks_an_open_lot_like_the_book(rig):
    pid = _practice(rig)
    await _open_lot(rig, pid, OPT)
    rig.quotes.on_quote(Quote(symbol=OPT, bid=2.00, ask=2.10, last=2.50))
    led = await rig.desk.ledger(days=30)
    lot = next(o for o in led["open"] if o["symbol"] == OPT)
    assert lot["mark"] == pytest.approx(2.05)
    # riding = (mark − in) × qty × 100 − entry fees, at the SAME mark
    assert lot["unrealized"] == pytest.approx((2.05 - 2.11) * 3 * 100 - lot["fees"], abs=0.01)


async def test_the_ledger_carries_the_dashboards_day_move(rig):
    """dayMove is equity − the previous session's close, summed over the books —
    the number the Dashboard headline shows, so the two screens cannot differ."""
    pid = _practice(rig)
    day0 = int(dt.datetime.now(tz=ET).replace(hour=4, minute=0, second=0, microsecond=0)
               .timestamp() * 1000)
    async with rig.sf() as session:
        session.add(EquityPoint(portfolio_id=pid, ts=day0 - 3600_000,
                                equity=9_800.0, cash=9_800.0))
        await session.commit()
    led = await rig.desk.ledger(days=30)
    books = [p for p in rig.positions.portfolios() if p["kind"] == "sim"]
    expect_start = sum([9_800.0 if p["id"] == pid else
                        (await rig.positions.day_start_equity(p["id"]) or 0) for p in books])
    assert led["dayStart"] == pytest.approx(expect_start, abs=0.01)
    assert led["dayMove"] == pytest.approx(led["total"] - expect_start, abs=0.01)
