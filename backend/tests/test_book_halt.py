"""Halt scopes (PLATFORM-RULES 2026-09-04): the daily-loss breaker halts only the losing BOOK by
default, RiskGate refuses entries on that book and lets exits through, other books keep trading,
the release comes at the day roll or by hand, and the old global behaviour is one setting away.
A technique can also pause its own plans on a book after its own bad day."""
from __future__ import annotations

import uuid
from dataclasses import replace

import pytest

from zargar.execution.exits import reduce_only_exit_intent
from zargar.execution.planrunner import Trade
from zargar.marketdata import persist_bars
from zargar.marketstructure import filter_session
from zargar.models import Portfolio
from zargar.orders import OrderIntent
from zargar.risk import HaltState, RiskGate

from .test_riskgate import FakePositions, FakeQuotes, P, check
from .test_team2_runner import rig  # noqa: F401
from .test_team2_session import DAY, prev_day_bars, trend_day


def _intent(pid: str, **kw) -> OrderIntent:
    base = dict(portfolio_id=pid, symbol="AAPL", side="BUY", qty=2, order_type="LMT", limit_price=100.0)
    base.update(kw)
    return OrderIntent(**base)


async def test_riskgate_refuses_entries_on_a_halted_book_only():
    quotes = FakeQuotes()
    quotes.set("AAPL", 100.0)
    halt = HaltState()
    halt.engage_book("p1", "daily loss limit: Practice at -9.13%", day="2026-09-04")
    gate = RiskGate({"risk.daily_loss_halt_pct": 3.0, "risk.halt_allows_exits": True, "risk.stale_quote_seconds": 10,
                     "risk.max_order_notional": 100000, "risk.max_position_notional": 100000},
                    quotes, FakePositions(), halt)
    # the halted book: entry refused, the global switch untouched
    v = await gate.evaluate(_intent("p1"), P)
    assert not check(v, "book_halt").passed and "halted for the day" in check(v, "book_halt").detail
    assert check(v, "kill_switch").passed and not halt.engaged
    # another book trades
    v2 = await gate.evaluate(_intent("p2"), P)
    assert check(v2, "book_halt").passed
    # exits on the halted book still pass (reduce-only, risk.halt_allows_exits)
    x = reduce_only_exit_intent(portfolio_id="p1", symbol="AAPL", sec_type="STK", qty=1, bid=99.0,
                                force_market=True, source="technique", technique_id="team2")
    vx = await gate.evaluate(x, P)
    assert check(vx, "book_halt").passed
    # persisted shape carries the books
    d = halt.to_dict()
    assert d["books"]["p1"]["reason"].startswith("daily loss limit") and d["engaged"] is False


async def test_daily_loss_breaker_halts_the_losing_book_not_the_world(engine, monkeypatch):
    sim = next(p for p in engine.positions.portfolios() if p["kind"] == "sim")
    other = Portfolio(id=uuid.uuid4().hex, name="Team2 Practice", kind="sim", starting_cash=10_000.0, cash=10_000.0)
    async with engine.sf() as session:
        session.add(other)
        await session.commit()
    engine.positions.register_portfolio(other)
    await engine.settings.set("risk.daily_loss_halt_pct", 3.0, journal=False)

    async def loss(pid):
        return -5.0 if pid == sim["id"] else -0.5

    async def traded():
        return {sim["id"], other.id}

    monkeypatch.setattr(engine.positions, "daily_loss_pct", loss)
    monkeypatch.setattr(engine, "_traded_today", traded)
    await engine.check_daily_loss()
    assert engine.halt.book_halted(sim["id"]) and not engine.halt.book_halted(other.id)
    assert not engine.halt.engaged                                    # the global switch stays off
    assert engine.trading_halted(sim["id"]) and engine.trading_halted(other.id) is None
    # a second pass does not re-engage or spam
    await engine.check_daily_loss()
    assert len(engine.halt.books) == 1
    # manual release, then the breaker re-halts on the next pass while the book is still below the limit
    await engine.release_book_halt(sim["id"], source="app")
    assert engine.trading_halted(sim["id"]) is None
    await engine.check_daily_loss()
    assert engine.halt.book_halted(sim["id"])
    # the day roll releases it
    engine.halt.books[sim["id"]]["day"] = "2000-01-01"

    async def flat(pid):
        return 0.0

    monkeypatch.setattr(engine.positions, "daily_loss_pct", flat)
    await engine.check_daily_loss()
    assert not engine.halt.books
    # the old behaviour is one setting away
    await engine.settings.set("risk.daily_loss_halt_scope", "global", journal=False)
    monkeypatch.setattr(engine.positions, "daily_loss_pct", loss)
    await engine.check_daily_loss()
    assert engine.halt.engaged and engine.halt.source == "auto" and not engine.halt.books
    await engine.release_halt(source="app")


async def test_technique_pauses_its_own_plans_on_a_book_after_its_bad_day(rig):
    eng, sim = rig
    prev = prev_day_bars()
    today, _ = trend_day(prev)
    for sym in ("SPY", "QQQ"):                                   # two plans on the same book
        await persist_bars(eng.sf, [replace(b, symbol=sym) for b in prev])
        await persist_bars(eng.sf, [replace(b, symbol=sym) for b in filter_session(today, "pre")])
    await eng.settings.set("techniques.team2.symbols", ["SPY", "QQQ"], journal=False)
    out = await eng.team2.nightly_plans(DAY.isoformat(), arm=True)
    runner = eng.team2_runner
    aps = [runner.get(r) for r in out["armed"]]
    assert len(aps) == 2 and all(ap.status == "armed" for ap in aps)
    await eng.settings.set("techniques.team2.daily_loss_halt_pct", 1.0, journal=False)
    eq = float(await eng.positions.equity(aps[0].config.portfolio_id))
    # one plan's realised loss crosses 1% of the book: EVERY Team2 plan on that book pauses
    tr = Trade(trigger_id="scenario_1@09:30#1", kind="scenario_1", fired_ts=1, window="team2", entry=570.0,
               stop=569.0, targets=[], status="closed", setup_id="scenario_1@09:30", realized_pnl=-(eq * 0.02))
    aps[0].trades[tr.trigger_id] = tr
    assert await runner._maybe_loss_halt(aps[0])
    assert all(ap.status == "paused" for ap in aps)
    assert any(e["event"] == "technique_loss_halt" for e in aps[1].events)
    assert "team2 loss halt" in (aps[1].stop_reason or "")
    # the book itself is NOT halted (other techniques trade on) and the global switch is off
    assert eng.trading_halted(aps[0].config.portfolio_id) is None and not eng.halt.engaged
    # a paused plan is left alone on the next pass
    assert not await runner._maybe_loss_halt(aps[0])
