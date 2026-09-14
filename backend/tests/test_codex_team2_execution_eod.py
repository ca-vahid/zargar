"""F125: a refused/deferred option proxy must not become a Practice-book loss.

Reviewed at 5188956 and rechecked against runtime commit b1da621 (v0.7.72).
These tests use the actual Team2Runner loss calculation,
desk tally and pre-entry gate, with only I/O replaced. They do not load market
history, read sealed C2 validation outputs, start an engine or access a database.

The 2026-09-14 report had ONE IWM model loser after a zero-order refusal. The
two-loser cases below are synthetic boundary tests, not claims that the real
desk reached its daily cap that day.
"""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from zargar.execution.planrunner import Trade
from zargar.marketstructure.sessions import ET
from zargar.techniques.team2.runner import Team2Runner


def _attempt(tid: str, *, verdict: str = "refused", filled_loss: bool = False,
             routed_unfilled: bool = False) -> Trade:
    return Trade(
        trigger_id=tid, kind="scenario_1", fired_ts=1, window="team2",
        entry=290.0, stop=289.0, targets=[], instrument="options",
        status="closed" if filled_loss else "failed",
        reason=f"contract_{verdict}: nothing sent",
        entry_order_id=f"order-{tid}" if filled_loss or routed_unfilled else None,
        filled_qty=2.0 if filled_loss else 0.0,
        remaining=0.0, realized_pnl=-40.0 if filled_loss else 0.0,
    )


def _model_losses(n: int) -> dict:
    return {"trades": [{"setup": f"proxy-{i}", "win": False, "pnlPct": -126.71}
                       for i in range(n)]}


def _plan(run_id: str, symbol: str, trades: list[Trade], *, mode: str = "auto"):
    return SimpleNamespace(
        run_id=run_id, symbol=symbol, plan_for=dt.datetime.now(ET).date().isoformat(),
        status="armed", bar_index=1,
        config=SimpleNamespace(mode=mode, max_open_trades=1, instrument="options"),
        trades={t.trigger_id: t for t in trades}, fire_tasks={},
    )


def _runner(plans: list, simulations: dict) -> Team2Runner:
    runner = Team2Runner.__new__(Team2Runner)
    runner._armed = {ap.run_id: ap for ap in plans}
    runner._last_sim = simulations
    runner._loss_tally = {}
    runner.rules = lambda: SimpleNamespace(
        losses_desk_wide=True, max_losses_per_day=2, max_concurrent_positions=1,
    )
    runner.probe_events = []
    runner._log = lambda ap, event, why, **detail: runner.probe_events.append(event)
    runner._fire_rest = AsyncMock()
    return runner


@pytest.mark.parametrize("verdict", ["refused", "deferred"])
def test_no_order_no_fill_is_zero_book_losses_even_if_the_proxy_lost(verdict):
    attempt = _attempt("candidate-1", verdict=verdict)
    assert attempt.entry_order_id is None and attempt.filled_qty == 0
    count, _basis = Team2Runner._plan_losses("auto", [attempt], _model_losses(1))
    assert count == 0, "an unfilled option proxy spent one of the Practice book's two losses"


def test_a_real_filled_closed_loser_still_counts_as_one_book_loss():
    filled = _attempt("filled-1", filled_loss=True)
    count, basis = Team2Runner._plan_losses("auto", [filled], _model_losses(4))
    assert (count, basis) == (1, "book")


def test_alert_only_analysis_keeps_its_separate_model_loss_count():
    count, basis = Team2Runner._plan_losses("alert", [], _model_losses(2))
    assert (count, basis) == (2, "model")


def test_routed_but_unfilled_order_is_not_a_book_loss():
    cancelled = _attempt("cancelled-1", routed_unfilled=True)
    cancelled.status = "cancelled"
    count, _basis = Team2Runner._plan_losses("auto", [cancelled], _model_losses(2))
    assert count == 0


def test_deferred_symbol_cannot_add_model_losses_to_another_symbols_book_loss():
    refused = _plan("iwm", "IWM", [_attempt("refused-1")])
    actual = _plan("spy", "SPY", [_attempt("filled-1", filled_loss=True)])
    runner = _runner([refused, actual], {"iwm": _model_losses(1), "spy": _model_losses(1)})
    assert runner.losses_across_plans() == 1, "desk tally mixed an unfilled proxy with an actual loss"


async def _try_next_symbol_fire(runner: Team2Runner, ap) -> None:
    setup_id = "scenario_1@13:45"
    event = {
        "event": "fire", "setup": setup_id, "touch": 1, "ts": 2,
        "spot": 100.0, "target": 102.0, "targetKind": "plan", "entryKind": "ema",
        "regime": {"stack": "bull", "atr": 1.0, "ema13": 99.0},
        "bucket": "small", "sizeMult": 0.5,
    }
    result = SimpleNamespace(setups=[{
        "id": setup_id, "kind": "scenario_1", "direction": "long", "anchor": 99.0,
        "target": 102.0,
    }])
    await runner._fire_from_event(ap, event, SimpleNamespace(close=100.0), result,
                                  halted=False, journal=False)


@pytest.mark.asyncio
async def test_two_unfilled_proxy_losses_cannot_block_another_symbols_valid_fire():
    refused = _plan("iwm", "IWM", [_attempt("candidate-1"), _attempt("candidate-2", verdict="deferred")])
    next_symbol = _plan("spy", "SPY", [])
    runner = _runner([refused, next_symbol], {"iwm": _model_losses(2), "spy": _model_losses(0)})
    assert all(t.filled_qty == 0 and t.entry_order_id is None for t in refused.trades.values())
    await _try_next_symbol_fire(runner, next_symbol)
    assert runner._fire_rest.await_count == 1, "a flat book was blocked by two hypothetical losses on another symbol"
    assert "skip_loss_cap_desk" not in runner.probe_events


@pytest.mark.asyncio
async def test_flat_book_without_model_losses_reaches_entry_path():
    next_symbol = _plan("spy", "SPY", [])
    runner = _runner([next_symbol], {"spy": _model_losses(0)})
    await _try_next_symbol_fire(runner, next_symbol)
    assert runner._fire_rest.await_count == 1


@pytest.mark.asyncio
async def test_two_actual_filled_losses_still_block_the_next_symbols_fire():
    actual = _plan("iwm", "IWM", [_attempt("filled-1", filled_loss=True), _attempt("filled-2", filled_loss=True)])
    next_symbol = _plan("spy", "SPY", [])
    runner = _runner([actual, next_symbol], {"iwm": _model_losses(0), "spy": _model_losses(0)})
    await _try_next_symbol_fire(runner, next_symbol)
    runner._fire_rest.assert_not_awaited()
    assert "skip_loss_cap_desk" in runner.probe_events
