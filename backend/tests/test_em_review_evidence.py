"""Review-only regressions for fa1f797. No database or paid model access.

These assert required behavior and are expected to fail on the reviewed tree.
Run against the pinned source via PYTHONPATH; this file intentionally lives
outside backend/tests so its database conftest is not collected.
"""

import asyncio
from types import SimpleNamespace

import pytest

from zargar.domain import Bar
from zargar.execution.planrunner import PlanRunner, Trade
from zargar.marketstructure.outcome import (
    plan_from_candidate,
    plan_from_contract,
    same_plan,
    simulate_plan,
)


@pytest.mark.parametrize("adapter", [plan_from_contract, plan_from_candidate])
def test_short_outcome_preserves_profitable_short_path(adapter):
    """A valid profitable put-underlying plan must not become invalid/unfilled."""
    contract = {
        "verdict": "setup",
        "setupType": "resistance_reject",
        "direction": "short",
        "entry": {"price": 100.0, "basis": "at_level"},
        "stop": {"price": 101.0},
        "targets": [{"price": 99.0}, {"price": 98.0}, {"price": 97.0}],
        "riskReward": 3.0,
        "valid": True,
    }
    bars = [
        Bar(symbol="TEST", tf="1m", ts=1_789_396_500_000,
            open=100.0, high=100.2, low=99.8, close=100.0, volume=1000),
        Bar(symbol="TEST", tf="1m", ts=1_789_396_560_000,
            open=100.0, high=100.1, low=99.5, close=99.5, volume=1000),
        Bar(symbol="TEST", tf="1m", ts=1_789_396_620_000,
            open=99.5, high=99.5, low=96.5, close=97.0, volume=1000),
    ]
    outcome = simulate_plan(bars, 0, adapter(contract), entry_window=2, horizon=2)
    assert outcome["filled"], outcome
    assert outcome["rMultiple"] > 0, outcome


def test_same_plan_does_not_collapse_different_profit_targets():
    """The rejected candidate needs a separate score if its targets differ."""
    common = {
        "direction": "long",
        "entry": {"price": 100.0, "basis": "at_level"},
        "stop": {"price": 99.0},
    }
    near = {**common, "targets": [{"price": 101.0}, {"price": 102.0}]}
    far = {**common, "targets": [{"price": 105.0}, {"price": 110.0}]}
    assert not same_plan(near, far)


@pytest.mark.parametrize("field", ["critic", "critic_advisory", "errors", "retries"])
def test_restore_preserves_trade_review_evidence(field):
    """Restart must preserve experiment labels and failure history exactly."""
    original = Trade(
        trigger_id="r2",
        kind="reject",
        direction="short",
        fired_ts=1_789_396_500_000,
        window="prime_open",
        entry=100.0,
        stop=101.0,
        targets=[99.0, 98.0, 97.0],
        status="closed",
        critic={"kill": True, "summary": "tape objection", "violations": ["R3.2"]},
        critic_advisory=True,
        errors=["first submission timed out"],
        retries=1,
    )
    ap = SimpleNamespace(
        run_id="review-only",
        config=SimpleNamespace(single_contract_exit="tp2"),
        trades={},
        trackers={},
    )
    runner = SimpleNamespace(
        _log=lambda *args, **kwargs: None,
        register_order=lambda *args, **kwargs: None,
    )
    asyncio.run(PlanRunner._restore_trades(
        runner, ap, {"trades": [original.to_dict()]}
    ))
    assert getattr(ap.trades["r2"], field) == getattr(original, field)
