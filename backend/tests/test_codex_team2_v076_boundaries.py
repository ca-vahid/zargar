"""Submission-boundary follow-up; synthetic clocks/transport, no DB or real orders.

Runs the shared retry loop and final guard with external order I/O mocked.
Pinned runtime build 0394b14 (v0.7.77 containing Team2 v0.7.76).
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from zargar.execution.planrunner import Trade
from .test_codex_team2_data_eod import rig, ms

# Adopted verbatim (Codex, 2026-09-14) with ONE adaptation: the first case exercises the EM desk's FA-01 `_entry_guard`,
# which lives on their branch (the running build 0394b14) and is not on main; it is skipped where FA-01 is absent and
# run for real in the running checkout before every deploy. `test_team2_eod_0914.py` covers the same boundary on main.
from zargar.techniques.team2.runner import Team2Runner as _T2
_needs_fa01 = pytest.mark.skipif(not hasattr(_T2, "_entry_guard"), reason="FA-01 _entry_guard is on the EM branch, not on this checkout")


def trade_for(ap):
    t = Trade(trigger_id="scenario_1@14:45#1", kind="scenario_1", window="team2", direction="long",
              fired_ts=ms(15, 28), entry=100, stop=99, targets=[104], status="submitting",
              instrument="options", filled_qty=0)
    ap.trades[t.trigger_id] = t
    return t


@_needs_fa01
@pytest.mark.parametrize("cross_cutoff,expected_calls", [(False, 2), (True, 1)])
async def test_transport_retry_rechecks_cutoff_at_submit(monkeypatch, cross_cutoff, expected_calls):
    import zargar.techniques.team2.runner as team2
    import zargar.execution.planrunner as shared
    runner, ap = rig()
    t = trade_for(ap)
    clock = [ms(15, 29) + 59000]
    monkeypatch.setattr(team2.time, "time", lambda: clock[0] / 1000)
    monkeypatch.setattr(shared, "now_ms", lambda: clock[0])
    runner.engine.quotes = SimpleNamespace(get=lambda _: None)
    runner.judge_entry_quote = lambda *args: None  # quote validity is independent of the timing boundary
    guard = runner._entry_guard(ap, t, {"symbol": "SPY260914C00101000", "ask": .5}, 1, .5)
    attempts = []
    async def place(intent, *, before_submit=None):
        if before_submit:
            before_submit()
        attempts.append(clock[0])
        if len(attempts) == 1:
            raise ConnectionError("temporarily unavailable before submission")
        return {"id": "synthetic-order", "status": "SUBMITTED"}
    async def delay(_seconds):
        clock[0] = ms(15, 30) + 1000 if cross_cutoff else ms(15, 29) + 59500
    monkeypatch.setattr(shared.asyncio, "sleep", delay)
    runner.engine.orders = SimpleNamespace(place=place)
    assert await runner.entry_gate(ap, t, "order") is None
    await runner._place_with_retry(ap, t, SimpleNamespace(), stage="entry", before_submit=guard)
    assert len(attempts) == expected_calls, "transport retry bypassed Team2 cutoff although it ran the final guard"


async def test_unknown_ack_timeout_does_not_become_zero_exposure_exemption():
    runner, ap = rig()
    t = trade_for(ap)
    ap.config.max_retries = 0
    # executor.submit can accept remotely, then raise before the runner receives an ACK/order id.
    runner.engine.orders = SimpleNamespace(place=AsyncMock(side_effect=TimeoutError("timeout awaiting broker ACK after send")))
    assert await runner._place_with_retry(ap, t, SimpleNamespace(), stage="entry") is None
    extras = runner.state_extras(ap)
    assert t.trigger_id not in extras["executionRefused"], "uncertain transport outcome was treated as definitively unfilled"


def test_definite_unfilled_rejection_remains_exempt():
    runner, ap = rig()
    t = trade_for(ap)
    t.status = "rejected"
    t.reason = "venue confirmed rejection; no fill"
    assert t.trigger_id in runner.state_extras(ap)["executionRefused"]
