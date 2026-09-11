"""Ledger reason attribution is book-exact (Codex v0.7.44 review, 2026-09-10):
symbol/time matching without portfolio identity attached the shadow share
plan's 'TP1 11.3617 reached' to the Practice option loss on the same name."""
import datetime as dt

import pytest

from zargar.desk import attach_desk
from zargar.domain import new_id
from zargar.engine import Engine
from zargar.models import Execution, Order
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    attach_desk(eng)
    yield eng
    await eng.stop()


async def _round_trip(rig, pid: str, sym: str) -> str:
    """One FIFO round trip in `pid`; returns the SELL order id."""
    now = dt.datetime.now(dt.timezone.utc)
    oid_in, oid_out = new_id(), new_id()
    async with rig.sf() as session:
        session.add(Order(id=oid_in, portfolio_id=pid, symbol=sym, sec_type="OPT",
                          side="BUY", qty=3, filled_qty=3, order_type="LMT",
                          limit_price=2.11, status="FILLED", source="signal"))
        session.add(Order(id=oid_out, portfolio_id=pid, symbol=sym, sec_type="OPT",
                          side="SELL", qty=3, filled_qty=3, order_type="MKT",
                          status="FILLED", source="signal"))
        await session.flush()
        session.add(Execution(id=new_id(), order_id=oid_in, portfolio_id=pid,
                              symbol=sym, side="BUY", qty=3, price=2.11,
                              ts=now - dt.timedelta(minutes=9)))
        # the SELL prints shortly AFTER the exit decisions the tests journal
        session.add(Execution(id=new_id(), order_id=oid_out, portfolio_id=pid,
                              symbol=sym, side="SELL", qty=3, price=2.02,
                              ts=now + dt.timedelta(seconds=30)))
        await session.commit()
    return oid_out


async def test_cross_book_exit_reason_is_never_borrowed(rig):
    sym = "SPCX260911C00155000"
    practice = next(p["id"] for p in rig.positions.portfolios() if p["kind"] == "sim")
    await _round_trip(rig, practice, sym)
    # a same-symbol exit decision in ANOTHER book, seconds before the SELL
    await rig.journal.append(
        "ManagedPositionExit",
        {"leg": "SPCX", "symbol": "SPCX", "kind": "trim",
         "reason": "TP1 11.3617 reached", "portfolioId": "some-shadow-book",
         "positionId": "shadow-pos", "qty": 50, "reduceOnly": True},
        aggregate_type="position", aggregate_id="shadow-pos",
        portfolio_id="some-shadow-book")
    out = await rig.desk.ledger(days=2)
    trips = [t for d in out["days"] for t in d.get("trips", [])]
    trip = next(t for t in trips if t["symbol"] == sym)
    assert "11.3617" not in str(trip["outReason"] or "")
    assert "unmatched" in str(trip["outReason"] or ""), trip["outReason"]


async def test_same_book_exit_reason_attaches(rig):
    sym = "PURR270115C00015000"
    practice = next(p["id"] for p in rig.positions.portfolios() if p["kind"] == "sim")
    await _round_trip(rig, practice, sym)
    await rig.journal.append(
        "ManagedPositionExit",
        {"leg": sym, "symbol": "PURR", "kind": "stop",
         "reason": "bar closed through the stop 11.2500",
         "portfolioId": practice,
         "positionId": "practice-pos", "qty": 3, "reduceOnly": True},
        aggregate_type="position", aggregate_id="practice-pos",
        portfolio_id=practice)
    out = await rig.desk.ledger(days=2)
    trips = [t for d in out["days"] for t in d.get("trips", [])]
    trip = next(t for t in trips if t["symbol"] == sym)
    assert "11.2500" in str(trip["outReason"] or "")
