"""F130 (2026-09-23): a working entry does not outlive the setup it was sent for.

Control's IWM pm_break_down@09:30#1: BUY 40 IWM260923P00283000 LMT 0.25 submitted 10:18, the read's target
printed 10:27 and the read closed the setup, the resting order filled 11:08 into a move against it and was
orphan-stopped at 11:10 for -$243.20. Only the 15:45 flatten used to cancel a working entry.
"""
from __future__ import annotations

from zargar.execution.planrunner import Trade

from .test_team2_close import _armed_plan
from .test_team2_runner import rig  # noqa: F401

SETUP = "pm_break_down@09:30"


def _working(trigger="pm_break_down@09:30#1", order="078c5d2f"):
    return Trade(trigger_id=trigger, kind="pm_break_down", fired_ts=1, window="team2", entry=283.4, stop=283.9,
                 targets=[282.1], status="working", setup_id=SETUP, entry_order_id=order, instrument="options",
                 order_symbol="IWM260923P00283000", multiplier=100.0)


async def _wire(eng, runner, ap, monkeypatch):
    await runner.set_mode(ap.run_id, "auto")
    runner._last_sim[ap.run_id] = {"trades": [{"setup": SETUP}]}
    calls: list[tuple] = []

    async def fake_cancel(oid):
        calls.append(("cancel", oid))

    async def fake_exit(ap_, t, kind, qty, *, journal, force_market=False, reason="", authority=None):
        calls.append(("exit", t.trigger_id, kind, qty))

    monkeypatch.setattr(eng.orders, "cancel", fake_cancel)
    monkeypatch.setattr(runner, "_exit", fake_exit)
    return calls


async def test_the_reads_exit_cancels_an_unfilled_entry_of_that_setup(rig, monkeypatch):
    eng, _ = rig
    runner, ap = await _armed_plan(eng)
    calls = await _wire(eng, runner, ap, monkeypatch)
    tr = _working()
    ap.trades[tr.trigger_id] = tr
    await runner._exit_from_event(ap, {"event": "exit", "setup": SETUP, "why": "target 282.10 reached", "pnlPct": 60.0},
                                  journal=True)
    assert ("cancel", "078c5d2f") in calls and tr.status == "cancelled"
    assert not any(c[0] == "exit" for c in calls), "nothing was held, so nothing is sold"
    assert "F130" in tr.reason
    assert any(e["event"] == "entry_cancelled_setup_closed" for e in ap.events)


async def test_a_trim_does_not_cancel_the_working_entry(rig, monkeypatch):
    """A partial take-profit leaves the setup alive; only the read's full exit ends the order's premise."""
    eng, _ = rig
    runner, ap = await _armed_plan(eng)
    calls = await _wire(eng, runner, ap, monkeypatch)
    tr = _working()
    ap.trades[tr.trigger_id] = tr
    await runner._exit_from_event(ap, {"event": "trim", "setup": SETUP, "why": "+50% trim", "fraction": 0.5, "pnlPct": 50.0},
                                  journal=True)
    assert calls == [] and tr.status == "working"


async def test_another_setups_exit_leaves_the_working_entry_alone(rig, monkeypatch):
    eng, _ = rig
    runner, ap = await _armed_plan(eng)
    calls = await _wire(eng, runner, ap, monkeypatch)
    tr = _working()
    ap.trades[tr.trigger_id] = tr
    await runner._exit_from_event(ap, {"event": "exit", "setup": "scenario_1@10:00", "why": "stop"}, journal=True)
    assert calls == [] and tr.status == "working"


async def test_an_open_position_of_the_same_setup_is_still_exited(rig, monkeypatch):
    """The fix touches only the resting order; a filled trade of that setup keeps its exit path."""
    eng, _ = rig
    runner, ap = await _armed_plan(eng)
    calls = await _wire(eng, runner, ap, monkeypatch)
    held = Trade(trigger_id="pm_break_down@09:30#2", kind="pm_break_down", fired_ts=2, window="team2", entry=283.4,
                 stop=283.9, targets=[282.1], status="open", setup_id=SETUP, entry_order_id="e2", filled_qty=20,
                 remaining=20, avg_fill=0.62, instrument="options", order_symbol="IWM260923P00284000", multiplier=100.0)
    tr = _working()
    ap.trades[tr.trigger_id] = tr
    ap.trades[held.trigger_id] = held
    await runner._exit_from_event(ap, {"event": "exit", "setup": SETUP, "why": "target 282.10 reached", "pnlPct": 60.0},
                                  journal=True)
    assert ("cancel", "078c5d2f") in calls and tr.status == "cancelled"
    assert any(c[0] == "exit" and c[1] == held.trigger_id for c in calls)


async def test_a_replay_without_journal_cancels_nothing(rig, monkeypatch):
    eng, _ = rig
    runner, ap = await _armed_plan(eng)
    calls = await _wire(eng, runner, ap, monkeypatch)
    tr = _working()
    ap.trades[tr.trigger_id] = tr
    await runner._exit_from_event(ap, {"event": "exit", "setup": SETUP, "why": "target"}, journal=False)
    assert ("cancel", "078c5d2f") not in calls and tr.status == "working"


async def test_the_clock_flatten_names_its_authority(rig, monkeypatch):
    """F130: every exit carries the authority that decided it — the clock flatten said so only in prose."""
    eng, _ = rig
    runner, ap = await _armed_plan(eng)
    await runner.set_mode(ap.run_id, "auto")
    seen: list[dict] = []

    async def fake_exit(ap_, t, kind, qty, *, journal, force_market=False, reason="", authority=None):
        seen.append(authority or {})

    monkeypatch.setattr(runner, "_exit", fake_exit)
    ap.trades["h"] = Trade(trigger_id="h", kind="pm_break_down", fired_ts=1, window="team2", entry=283.4, stop=283.9,
                           targets=[], status="open", setup_id=SETUP, entry_order_id="e", filled_qty=10, remaining=10,
                           avg_fill=0.5, instrument="options", order_symbol="IWM260923P00283000", multiplier=100.0)
    await runner._clock_flatten(ap, runner.rules())
    assert seen and seen[0]["authority"] == "clock exit" and seen[0]["decidedBy"] == "clock_flatten"


def test_the_authority_vocabulary_names_the_live_target_and_the_quote_stop():
    from zargar.execution.planrunner import PlanRunner
    assert PlanRunner.AUTHORITY["live_target"] == "target"
    assert PlanRunner.AUTHORITY["quote_stop_watch"] == "structural stop"


async def test_a_fill_that_races_the_cancel_is_still_booked_and_managed(rig, monkeypatch):
    """The cancel is a request; if the venue filled first, the fill is booked and the trade is open again, so
    the orphan guard, the premium stop and the flatten manage it — nothing the desk holds goes unwatched."""
    eng, _ = rig
    runner, ap = await _armed_plan(eng)
    await _wire(eng, runner, ap, monkeypatch)
    tr = _working()
    ap.trades[tr.trigger_id] = tr
    runner.register_order("078c5d2f", (ap.run_id, tr.trigger_id))
    await runner._exit_from_event(ap, {"event": "exit", "setup": SETUP, "why": "target"}, journal=True)
    assert tr.status == "cancelled"
    await runner.on_order_update({"id": "078c5d2f", "status": "FILLED", "filledQty": 40.0, "avgFillPrice": 0.25})
    assert tr.status == "open" and tr.filled_qty == 40
