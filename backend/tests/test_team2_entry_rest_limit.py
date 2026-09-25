"""F131 (2026-09-24): an unfilled Team2 entry or add is cancelled after two 2m decisions (240 s).

09-24: SPY pm_break_up@12:15#1+add1 sent 12:46:02 LMT 0.60, filled 13:19:38 at 0.56 into a falling market and was
stopped at 13:25 (-$444 after fees across Control and Sizing 0.5). The setup was still open, so F130 did not apply.
"""
from __future__ import annotations

from types import SimpleNamespace

from zargar.execution.planrunner import Trade

from .test_team2_close import _armed_plan
from .test_team2_runner import rig  # noqa: F401

SENT = 1_790_268_362_000          # 2026-09-24 12:46:02 ET


def _add(status="working", filled=0.0, fired=SENT):
    return Trade(trigger_id="pm_break_up@12:15#1+add1", kind="pm_break_up", fired_ts=fired, window="team2", entry=768.5,
                 stop=767.9, targets=[], status=status, setup_id="pm_break_up@12:15", entry_order_id="863c92f4",
                 filled_qty=filled, remaining=filled, instrument="options", order_symbol="SPY260924C00769000",
                 multiplier=100.0)


async def _rig(eng, monkeypatch):
    runner, ap = await _armed_plan(eng)
    await runner.set_mode(ap.run_id, "auto")
    calls: list[str] = []

    async def fake_cancel(oid):
        calls.append(oid)

    monkeypatch.setattr(eng.orders, "cancel", fake_cancel)
    return runner, ap, calls


def _bar(close_ms):
    return SimpleNamespace(ts=close_ms - 60_000)


async def test_an_add_resting_past_the_limit_is_cancelled(rig, monkeypatch):
    eng, _ = rig
    runner, ap, calls = await _rig(eng, monkeypatch)
    tr = _add()
    ap.trades[tr.trigger_id] = tr
    await runner._expire_resting_entries(ap, _bar(SENT + 5 * 60_000))
    assert calls == ["863c92f4"] and tr.status == "cancelled" and "F131" in tr.reason
    ev = [e for e in ap.events if e["event"] == "entry_expired_unfilled"]
    assert ev and "add limit rested" in ev[0]["text"]


async def test_inside_the_limit_nothing_is_cancelled(rig, monkeypatch):
    eng, _ = rig
    runner, ap, calls = await _rig(eng, monkeypatch)
    tr = _add()
    ap.trades[tr.trigger_id] = tr
    await runner._expire_resting_entries(ap, _bar(SENT + 4 * 60_000))          # exactly 240 s: still allowed
    assert calls == [] and tr.status == "working"


async def test_a_partial_fill_keeps_what_filled(rig, monkeypatch):
    eng, _ = rig
    runner, ap, calls = await _rig(eng, monkeypatch)
    tr = _add(filled=4.0)
    ap.trades[tr.trigger_id] = tr
    await runner._expire_resting_entries(ap, _bar(SENT + 10 * 60_000))
    assert calls == ["863c92f4"] and tr.status == "open" and tr.filled_qty == 4.0


async def test_open_trades_uncertain_submissions_and_missing_fire_times_are_left_alone(rig, monkeypatch):
    eng, _ = rig
    runner, ap, calls = await _rig(eng, monkeypatch)
    held = _add(status="open", filled=12.0)
    held.trigger_id = "held"
    unsure = _add()
    unsure.trigger_id = "unsure"
    unsure.submit_uncertain = True
    no_time = _add(fired=1)
    no_time.trigger_id = "no_time"
    for t in (held, unsure, no_time):
        ap.trades[t.trigger_id] = t
    await runner._expire_resting_entries(ap, _bar(SENT + 60 * 60_000))
    assert calls == [] and held.status == "open" and unsure.status == "working" and no_time.status == "working"


async def test_the_limit_can_be_switched_off(rig, monkeypatch):
    eng, _ = rig
    runner, ap, calls = await _rig(eng, monkeypatch)
    monkeypatch.setattr(runner, "rt", lambda k, d=None: 0 if k == "entry_rest_max_seconds" else d)
    tr = _add()
    ap.trades[tr.trigger_id] = tr
    await runner._expire_resting_entries(ap, _bar(SENT + 60 * 60_000))
    assert calls == [] and tr.status == "working"


async def test_a_fill_racing_the_cancel_is_still_booked(rig, monkeypatch):
    eng, _ = rig
    runner, ap, calls = await _rig(eng, monkeypatch)
    tr = _add()
    ap.trades[tr.trigger_id] = tr
    runner.register_order("863c92f4", (ap.run_id, tr.trigger_id))
    await runner._expire_resting_entries(ap, _bar(SENT + 5 * 60_000))
    await runner.on_order_update({"id": "863c92f4", "status": "FILLED", "filledQty": 12.0, "avgFillPrice": 0.56})
    assert tr.status == "open" and tr.filled_qty == 12.0


def test_the_setting_exists_with_the_registered_value():
    from zargar.settings_service import DEFAULTS
    assert DEFAULTS["techniques.team2.entry_rest_max_seconds"] == 240
