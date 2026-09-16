"""Scoped book PAUSE (2026-09-15, the Team2 sizing experiment's breach action): refuses entries and adds on ONE book,
keeps protective exits, leaves other books alone, survives restart AND the ET day roll, is released only explicitly,
and its release never clears the independent risk halts (nor do they clear it)."""
from __future__ import annotations

import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from zargar.engine import Engine
from zargar.execution.exits import reduce_only_exit_intent
from zargar.execution.planrunner import Trade
from zargar.orders import OrderIntent
from zargar.risk import HaltState, RiskGate

from .test_codex_team2_data_eod import bar, ms, rig
from .test_riskgate import FakePositions, FakeQuotes, P, check

SETTINGS = {"risk.daily_loss_halt_pct": 3.0, "risk.halt_allows_exits": True, "risk.stale_quote_seconds": 10,
            "risk.max_order_notional": 100000, "risk.max_position_notional": 100000}


def _intent(pid: str, **kw) -> OrderIntent:
    base = dict(portfolio_id=pid, symbol="AAPL", side="BUY", qty=2, order_type="LMT", limit_price=100.0)
    base.update(kw)
    return OrderIntent(**base)


async def test_riskgate_refuses_entries_on_the_paused_book_only_and_lets_exits_through():
    quotes = FakeQuotes(); quotes.set("AAPL", 100.0)
    halt = HaltState()
    halt.pause_book("team2-practice", "experiment loss stop: -$812 since activation", source="app", label="team2-sizing-cap-2026-09")
    gate = RiskGate(SETTINGS, quotes, FakePositions(), halt)
    v = await gate.evaluate(_intent("team2-practice"), P)
    assert not check(v, "book_pause").passed and "team2-sizing-cap-2026-09" in check(v, "book_pause").detail
    assert check(v, "kill_switch").passed and check(v, "book_halt").passed and not halt.engaged
    v2 = await gate.evaluate(_intent("em-practice"), P)                      # another book trades
    assert check(v2, "book_pause").passed
    x = reduce_only_exit_intent(portfolio_id="team2-practice", symbol="AAPL", sec_type="STK", qty=1, bid=99.0,
                                force_market=True, source="technique", technique_id="team2")
    vx = await gate.evaluate(x, P)                                            # a protective exit passes
    assert check(vx, "book_pause").passed


def _engine_halt(halt: HaltState):
    """An engine-shaped object whose trading_halted is the REAL Engine method over a real HaltState."""
    eng = SimpleNamespace(halt=halt)
    eng.trading_halted = types.MethodType(Engine.trading_halted, eng)
    return eng


def _fire(h, m):
    return {"event": "fire", "ts": ms(h, m), "setup": "scenario_1@09:45", "touch": 1, "spot": 101.0, "target": 104.0,
            "targetKind": "plan", "regime": {"stack": "bull", "atr": 1}, "entryKind": "ema", "why": "fixture", "sizeMult": 1}


async def test_team2_entries_and_adds_are_refused_on_the_paused_book_and_another_book_is_not(monkeypatch):
    import zargar.techniques.team2.runner as module
    halt = HaltState()
    halt.pause_book("review-practice", "experiment loss stop", label="team2-sizing-cap-2026-09")
    runner, ap = rig()
    runner.engine.halt = halt
    runner.engine.trading_halted = _engine_halt(halt).trading_halted
    monkeypatch.setattr(module.time, "time", lambda: ms(10, 2) / 1000)
    runner.pick_contract = AsyncMock(return_value={"symbol": "SPY260914C00102000", "ask": .5})
    runner._enter = AsyncMock()
    # an entry: refused before any order chain, recorded as halt_skip with the pause's reason
    halted = bool(runner.engine.trading_halted(ap.config.portfolio_id))
    await runner._fire_from_event(ap, _fire(10, 2), bar(10, 1), SimpleNamespace(setups=[]), halted=halted, journal=True)
    await runner.wait_fires(ap.run_id)
    assert runner._enter.await_count == 0 and not ap.trades
    kinds = [c.args[1] for c in runner._log.call_args_list]
    assert "halt_skip" in kinds and "team2-sizing-cap-2026-09" in str([c.args[2] for c in runner._log.call_args_list if c.args[1] == "halt_skip"])
    # an add on an open position: refused too, the position itself stays managed
    base = Trade(trigger_id="scenario_1@09:45#1", setup_id="scenario_1@09:45", kind="scenario_1", direction="long", window="team2",
                 fired_ts=ms(9, 46), status="open", entry=100, stop=99, targets=[104], filled_qty=3, remaining=2, instrument="options",
                 order_symbol="SPY260914C00102000", contract={"symbol": "SPY260914C00102000", "ask": .5})
    ap.trades[base.trigger_id] = base
    runner.engine.quotes = SimpleNamespace(get=lambda _: SimpleNamespace(ask=.5, bid=.49))
    add = {"event": "add", "setup": base.setup_id, "ts": ms(10, 2), "spot": 101, "adds": 1, "fraction": .33, "why": "retest add"}
    await runner._add_from_event(ap, add, bar(10, 1), halted=halted, journal=True)
    await runner.wait_fires(ap.run_id)
    assert runner._enter.await_count == 0 and len(ap.trades) == 1 and base.status == "open"
    assert "add_skip" in [c.args[1] for c in runner._log.call_args_list]
    # another book is untouched
    assert runner.engine.trading_halted("em-practice") is None


def test_the_pause_survives_restart_and_the_day_roll_while_a_book_halt_does_not():
    h = HaltState()
    h.engage_book("team2-practice", "daily loss limit", day="2026-09-15")
    h.pause_book("team2-practice", "experiment loss stop", label="team2-sizing-cap-2026-09")
    saved = h.to_dict()
    assert "pauses" in saved and "day" not in saved["pauses"]["team2-practice"]
    # restart the same day: both come back
    same = HaltState.restore(saved, today="2026-09-15")
    assert same.book_halted("team2-practice") and same.book_paused("team2-practice")
    # restart after the ET day roll: the daily halt is gone, the pause is not
    later = HaltState.restore(saved, today="2026-09-16")
    assert later.book_halted("team2-practice") is None
    assert later.book_paused("team2-practice")["label"] == "team2-sizing-cap-2026-09"
    assert HaltState.restore(None, today="2026-09-16").pauses == {}


async def test_releasing_the_pause_never_clears_the_independent_halts_and_vice_versa():
    calls = []
    eng = SimpleNamespace(halt=HaltState(), settings=SimpleNamespace(set=AsyncMock(), get=lambda k, d=None: {"techniques.team2.size_full": 0.5}.get(k, d)),
                          journal=SimpleNamespace(append=AsyncMock()), bus=SimpleNamespace(publish=lambda *a, **k: calls.append(a)),
                          positions=SimpleNamespace(portfolio=lambda pid: {"name": "Team2 Practice"}))
    for name in ("pause_book", "release_book_pause", "release_book_halt", "engage_book_halt", "release_halt", "engage_halt", "trading_halted", "_portfolio_name"):
        setattr(eng, name, types.MethodType(getattr(Engine, name), eng))
    await eng.engage_halt("manual halt", source="app")
    await eng.engage_book_halt("team2-practice", "daily loss limit", source="auto")
    p = await eng.pause_book("team2-practice", "experiment loss stop", label="team2-sizing-cap-2026-09")
    assert p["snapshot"]["techniques.team2.size_full"] == 0.5, "the record shows what the book was running; the pause changes no setting"
    assert eng.settings.set.await_count == 3 and all(c.args[0] == "system.halt" for c in eng.settings.set.await_args_list)
    # release the pause: the global switch and the daily-loss halt are untouched
    await eng.release_book_pause("team2-practice")
    assert eng.halt.book_paused("team2-practice") is None and eng.halt.engaged and eng.halt.book_halted("team2-practice")
    # the other way round: releasing the halts never releases a pause
    await eng.pause_book("team2-practice", "experiment loss stop", label="team2-sizing-cap-2026-09")
    await eng.release_book_halt("team2-practice")
    await eng.release_halt()
    assert eng.halt.book_paused("team2-practice") and not eng.halt.engaged and eng.halt.book_halted("team2-practice") is None
    assert eng.trading_halted("team2-practice").startswith("book paused (team2-sizing-cap-2026-09)")
    assert eng.trading_halted("em-practice") is None
    kinds = [c.args[0] for c in eng.journal.append.await_args_list]
    assert kinds.count("BookPaused") == 2 and kinds.count("BookPauseReleased") == 1
