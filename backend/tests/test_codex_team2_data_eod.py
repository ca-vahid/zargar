"""Sep14 EOD read-only review probes: no engine, DB, providers, or real orders.

Reproduced against origin/main 5188956 and runtime b1da621 (v0.7.72).
Fixtures use synthetic bars only.
"""
import datetime as dt
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from zargar.bus import Bus
from zargar.domain import Bar
from zargar.execution.planrunner import ArmConfig, ArmedPlan
from zargar.marketdata import BarAggregator
from zargar.marketstructure.sessions import ET
from zargar.techniques.team2.rules import Team2Rules
from zargar.techniques.team2.runner import Team2Runner


def ms(h, m):
    return int(dt.datetime(2026, 9, 14, h, m, tzinfo=ET).timestamp() * 1000)


def bar(h, m, close=100.0):
    return Bar(symbol="SPY", tf="1m", ts=ms(h, m), open=close, high=close + .1,
               low=close - .1, close=close, volume=100, source="exchange")


def rig():
    eng = SimpleNamespace(settings={}, journal=SimpleNamespace(append=AsyncMock()),
                          trading_halted=lambda _: False, quiesce_until_ms=0)
    runner = Team2Runner(eng)
    runner.rules = lambda: replace(Team2Rules(), losses_desk_wide=False)
    for name in ("_load_warmup", "_ensure_listing", "_persist", "_clock_flatten",
                 "_reprice_stuck_exits", "_manage_live_trims"):
        setattr(runner, name, AsyncMock())
    runner._maybe_loss_halt = AsyncMock(return_value=False)
    runner._session_sigma = AsyncMock(return_value=.2)
    runner._log = Mock()
    runner._publish = Mock()
    ap = ArmedPlan(run_id="review-data", symbol="SPY", plan_for="2026-09-14",
                   plan={"zones": {"present": True}, "openSource": "rth_open"},
                   config=ArmConfig(portfolio_id="review-practice", mode="auto",
                                    instrument="options", use_critic=False),
                   trackers={}, armed_at=0)
    runner._armed[ap.run_id] = ap
    return runner, ap


@pytest.mark.parametrize("correction", [False, True])
async def test_runner_consumes_recovered_or_corrected_exchange_minute(correction):
    runner, ap = rig()
    first, latest = bar(10, 0), bar(10, 2, 102)
    runner._bars[ap.run_id] = [first, latest]
    ap.last_bar_ts, ap.bar_index = latest.ts, 2
    bus = Bus()
    queue, unsubscribe = bus.subscribe("bars")
    agg = BarAggregator(bus)
    agg.seed("SPY", [first, latest])
    revised = bar(10, 0, 101) if correction else bar(10, 1, 101)
    agg.ingest_exchange_bar(revised)
    published = queue.get_nowait()
    assert next(b for b in agg.bars("SPY", include_forming=False) if b.ts == revised.ts).close == 101
    await runner.on_minute_bar(published["symbol"], published["bar"])
    unsubscribe()
    consumed = {b.ts: b.close for b in runner._bars[ap.run_id]}
    assert consumed.get(revised.ts) == 101, {"incoming": revised.ts, "consumed": consumed}


@pytest.mark.parametrize("wall_minute, expected_entries", [(28, 1), (32, 0)])
async def test_delayed_bar_cannot_enter_after_wall_clock_cutoff(monkeypatch, wall_minute, expected_entries):
    import zargar.execution.planrunner as shared
    import zargar.techniques.team2.runner as module

    runner, ap = rig()
    # A 15:28 closed signal arrives during the documented family of multi-minute stalls,
    # after the already configured 15:30 cutoff. The scenario is synthetic, not Sep14 tape.
    monkeypatch.setattr(shared, "now_ms", lambda: ms(15, wall_minute))
    monkeypatch.setattr(module.time, "time", lambda: ms(15, wall_minute) / 1000)
    ap.last_bar_ts, ap.stale = ms(15, 26), True
    runner._bars[ap.run_id] = [bar(15, 26)]
    event = {"event": "fire", "ts": ms(15, 28), "setup": "scenario_1@15:15", "touch": 1,
             "spot": 100.0, "target": 102.0, "targetKind": "plan", "regime": {"stack": "bull", "atr": 1},
             "entryKind": "ema", "why": "synthetic valid pre-cutoff signal", "sizeMult": 1}
    result = SimpleNamespace(events=[event], setups=[{"id": event["setup"], "kind": "scenario_1",
                                                   "direction": "long", "target": 102.0}],
                             to_dict=lambda: {"events": [event], "setups": [], "summary": {}})
    monkeypatch.setattr(module, "simulate_session", lambda *a, **k: result)
    runner.pick_contract = AsyncMock(return_value={"symbol": "SPY260914C00101000", "ask": .5})
    runner._enter = AsyncMock()  # Real _on_bar -> _act -> _fire_from_event -> _fire_rest; stop at order boundary.
    await runner.on_minute_bar("SPY", bar(15, 27))
    await runner.wait_fires(ap.run_id)
    assert runner._enter.await_count == expected_entries, {
        "source_close": "15:28", "wall_clock": f"15:{wall_minute}",
        "cutoff": "15:30", "entry_calls": runner._enter.await_count,
    }
