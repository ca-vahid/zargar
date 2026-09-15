"""Unknown submission -> actual order-update reconciliation, at fca56b7.

External order I/O and housekeeping are mocked; the shared uncertainty handler,
order-update callback, serialization and Team2 overlay reconciliation are real.
No database, provider or actual order calls.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from zargar.orders import SubmitUncertain
from zargar.execution.planrunner import Trade
from .test_codex_team2_data_eod import rig, ms


async def uncertain_trade():
    runner, ap = rig()
    t = Trade(trigger_id="scenario_1@09:45#1", kind="scenario_1", window="team2", direction="long",
              fired_ts=ms(10, 0), entry=100, stop=99, targets=[104], status="submitting",
              instrument="options", filled_qty=0)
    ap.trades[t.trigger_id] = t
    runner._alert = AsyncMock()
    runner.engine.orders = SimpleNamespace(place=AsyncMock(side_effect=SubmitUncertain("known-order-id", TimeoutError("ACK missing"))))
    await runner._place_with_retry(ap, t, SimpleNamespace(), stage="entry")
    assert t.submit_uncertain and t.status == "submitting"
    assert runner.owner_of("known-order-id") == (ap.run_id, t.trigger_id)
    assert t.trigger_id not in runner.state_extras(ap)["executionRefused"]
    return runner, ap, t


@pytest.mark.parametrize("status", ["REJECTED", "CANCELLED"])
async def test_confirmed_zero_fill_clears_uncertainty_and_exempts_proxy(status):
    runner, ap, t = await uncertain_trade()
    await runner.on_order_update({"id": "known-order-id", "status": status, "filledQty": 0,
                                  "rejectReason": "venue confirmed terminal zero-fill outcome"})
    assert t.status in ("failed", "cancelled")
    assert t.trigger_id in runner.state_extras(ap)["executionRefused"], "a confirmed zero-fill is still treated as unresolved"
    assert not t.submit_uncertain, "confirmed terminal venue evidence never clears submit_uncertain"
    assert t.to_dict()["submitUncertain"] is False


async def test_partial_fill_after_uncertainty_stays_managed_and_never_exempt():
    runner, ap, t = await uncertain_trade()
    await runner.on_order_update({"id": "known-order-id", "status": "PARTIALLY_FILLED", "filledQty": 1,
                                  "avgFillPrice": .5})
    assert t.status == "open" and t.filled_qty == 1 and t.remaining == 1
    assert t.trigger_id not in runner.state_extras(ap)["executionRefused"]
