"""Synthetic follow-up at 7b1dee2. No database, provider, or real order calls.

Uses the original review rig: housekeeping is stubbed, real Team2 routing runs,
and money actions stop at mocked _enter. These are untested boundaries, not
claims of actual Sep14 trades.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from zargar.execution.planrunner import Trade
from .test_codex_team2_data_eod import rig, bar, ms


def result(events):
    setups = [{"id": "scenario_1@09:45", "kind": "scenario_1", "direction": "long", "target": 104.0}]
    return SimpleNamespace(events=events, setups=setups,
                           to_dict=lambda: {"events": events, "setups": setups, "summary": {}})


async def test_correction_cannot_mint_a_backdated_entry_within_age_limit(monkeypatch):
    import zargar.techniques.team2.runner as module
    import zargar.execution.planrunner as shared
    runner, ap = rig()
    clock = [ms(10, 2)]
    monkeypatch.setattr(module.time, "time", lambda: clock[0] / 1000)
    monkeypatch.setattr(shared, "now_ms", lambda: clock[0])
    event = {"event": "fire", "ts": ms(10, 2), "setup": "scenario_1@09:45", "touch": 1,
             "spot": 101.0, "target": 104.0, "targetKind": "plan", "regime": {"stack": "bull", "atr": 1},
             "entryKind": "ema", "why": "signal introduced by corrected close", "sizeMult": 1}
    def corrected_read(plan, bars, *args, **kwargs):
        changed = any(b.ts == ms(10, 1) and b.close == 101 for b in bars)
        return result([event] if changed else [])
    monkeypatch.setattr(module, "simulate_session", corrected_read)
    runner.pick_contract = AsyncMock(return_value={"symbol": "SPY260914C00102000", "ask": .5})
    runner._enter = AsyncMock()
    await runner.on_minute_bar("SPY", bar(10, 1, 100))
    assert runner._enter.await_count == 0
    clock[0] = ms(10, 3)
    await runner.on_minute_bar("SPY", bar(10, 1, 101))
    assert runner._bars[ap.run_id][0].close == 101
    clock[0] = ms(10, 4)
    await runner.on_minute_bar("SPY", bar(10, 3, 101))
    await runner.wait_fires(ap.run_id)
    assert runner._enter.await_count == 0, "historical correction minted a new 10:02 entry at 10:04"


@pytest.mark.parametrize("minute,allowed", [(28, 1), (32, 0)])
async def test_add_path_obeys_actual_cutoff(monkeypatch, minute, allowed):
    import zargar.techniques.team2.runner as module
    import zargar.execution.planrunner as shared
    runner, ap = rig()
    monkeypatch.setattr(module.time, "time", lambda: ms(15, minute) / 1000)
    monkeypatch.setattr(shared, "now_ms", lambda: ms(15, minute))
    ap.bar_index = 3
    base = Trade(trigger_id="scenario_1@09:45#1", setup_id="scenario_1@09:45", kind="scenario_1",
                 direction="long", window="team2", fired_ts=ms(10, 0), status="open", entry=100, stop=99, targets=[104],
                 filled_qty=3, remaining=2, instrument="options", order_symbol="SPY260914C00102000",
                 contract={"symbol": "SPY260914C00102000", "ask": .5})
    ap.trades[base.trigger_id] = base
    runner.engine.quotes = SimpleNamespace(get=lambda _: SimpleNamespace(ask=.5, bid=.49))
    runner._enter = AsyncMock()
    event = {"event": "add", "setup": base.setup_id, "ts": ms(15, 28), "spot": 101,
             "adds": 1, "fraction": .33, "why": "synthetic retest add"}
    await runner._add_from_event(ap, event, bar(15, 27, 101), halted=False, journal=True)
    await runner.wait_fires(ap.run_id)
    assert runner._enter.await_count == allowed, "add bypassed actual-time entry check and cached-contract picker check"


async def test_durable_refusal_reload_restores_execution_overlay():
    runner, ap = rig()
    tid = "scenario_1@09:45#1"
    payload = {"trigger": tid, "event": "contract_refused", "verdict": "refused", "reason": "live ask below band"}
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [SimpleNamespace(payload=payload)]))))
    class Context:
        async def __aenter__(self): return session
        async def __aexit__(self, *args): return False
    runner.engine.sf = Context
    ap.plan["contractAuthority"] = "quotes"
    assert await runner.load_contract_verdicts() == 1
    assert runner._contract_verdicts[ap.run_id][0]["trigger"] == tid
    assert tid in ap.plan.get("executionRefused", []), "restore loads reporting but leaves the read's proxy exemption empty"


def test_journaled_attempt_survives_crash_before_trade_projection():
    runner, ap = rig()
    runner._last_sim[ap.run_id] = {"trades": [], "bias": {}}
    runner._contract_verdicts[ap.run_id] = [{"trigger": "scenario_1@09:45#1", "event": "contract_refused",
        "verdict": "refused", "reason": "live ask below band", "examined": [{"ask": .13, "strike": 290}]}]
    assert not ap.trades
    card = runner._score_execution(ap)
    assert card["funnel"]["policyRefused"] == 1
    assert card["funnel"]["attempts"] == 1, "durable refusal vanished from attempt count because projection was absent"
    assert len(card["rows"]) == 1
