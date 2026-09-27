"""Team2 P0 fixes of 2026-09-27 (plan of record 2026-09-24 §5 P0.1 / P0.2 / P0.4)."""
from __future__ import annotations

from types import SimpleNamespace

from zargar.execution.planrunner import Trade
from zargar.techniques.team2.rules import Team2Rules
from zargar.techniques.team2.runner import Team2Runner
from zargar.techniques.team2.service import method_version, rules_hash

from .test_team2_close import _armed_plan
from .test_team2_runner import rig  # noqa: F401

DECISION = 1_790_172_000_000          # a 2m bar boundary (2026-09-23 10:18:00 ET)


def _runner():
    return object.__new__(Team2Runner)


def _fire(ts, direction="short"):
    return SimpleNamespace(fired_ts=ts, direction=direction)


def test_two_books_on_one_decision_price_the_same_spot():
    """09-23: Control read 284.000 and Sizing 0.5 read 284.005 two seconds apart; `strike < spot` then picked the
    283P for one book and the 284P for the other. The second book now reuses the first book's spot."""
    r, rules = _runner(), Team2Rules()
    s1, src1 = r._shared_fire_spot("IWM", _fire(DECISION + 2_000), rules, 284.005)
    s2, src2 = r._shared_fire_spot("IWM", _fire(DECISION + 4_000), rules, 284.000)
    assert (s1, src1) == (284.005, "live") and (s2, src2) == (284.005, "shared_fire_snapshot")


def test_a_different_decision_symbol_or_direction_reads_its_own_spot():
    r, rules = _runner(), Team2Rules()
    r._shared_fire_spot("IWM", _fire(DECISION + 2_000), rules, 284.005)
    assert r._shared_fire_spot("IWM", _fire(DECISION + 120_000), rules, 283.50) == (283.50, "live")      # next bar
    assert r._shared_fire_spot("QQQ", _fire(DECISION + 3_000), rules, 736.10) == (736.10, "live")        # other symbol
    assert r._shared_fire_spot("IWM", _fire(DECISION + 3_000, "long"), rules, 284.20) == (284.20, "live")  # other side


def test_a_fire_without_a_real_time_is_never_shared():
    r, rules = _runner(), Team2Rules()
    assert r._shared_fire_spot("IWM", _fire(1), rules, 284.0) == (284.0, "live")
    assert r._shared_fire_spot("IWM", _fire(1), rules, 285.0) == (285.0, "live")


def test_old_decisions_are_forgotten():
    r, rules = _runner(), Team2Rules()
    r._shared_fire_spot("IWM", _fire(DECISION), rules, 284.0)
    r._shared_fire_spot("IWM", _fire(DECISION + 60 * 60_000), rules, 290.0)
    assert all(k[2] >= DECISION + 30 * 60_000 for k in r._fire_spots)


async def test_live_trims_name_their_authority(rig, monkeypatch):
    eng, _ = rig
    runner, ap = await _armed_plan(eng)
    await runner.set_mode(ap.run_id, "auto")
    seen: list[tuple] = []

    async def fake_exit(ap_, t, kind, qty, *, journal, force_market=False, reason="", authority=None):
        seen.append((kind, authority or {}))

    monkeypatch.setattr(runner, "_exit", fake_exit)
    monkeypatch.setattr(runner, "_live_pct", lambda tr: 62.0)
    tr = Trade(trigger_id="pm_break_down@10:00#1", kind="pm_break_down", fired_ts=DECISION, window="team2", entry=283.4,
               stop=283.9, targets=[], status="open", setup_id="pm_break_down@10:00", entry_order_id="e", filled_qty=20,
               remaining=20, avg_fill=0.62, instrument="options", order_symbol="IWM260923P00284000", multiplier=100.0)
    ap.trades[tr.trigger_id] = tr
    await runner._manage_live_trims(ap, runner.rules(), journal=True)
    assert seen and seen[0][0] == "tp1"
    auth = seen[0][1]
    assert auth["authority"] == "trim" and auth["decidedBy"] == "live_trim" and auth["livePct"] == 62.0


def test_the_team2_vocabulary_extends_the_shared_one():
    from zargar.execution.planrunner import PlanRunner
    assert Team2Runner.AUTHORITY["model_trail"] == "structural stop" and Team2Runner.AUTHORITY["model_trim"] == "trim"
    assert all(Team2Runner.AUTHORITY[k] == v for k, v in PlanRunner.AUTHORITY.items())
    assert "live_trim" not in PlanRunner.AUTHORITY, "Team2's labels stay Team2's"


def test_plans_carry_a_method_version_and_a_rules_hash():
    v = method_version()
    assert len(v) == 16 and v != "unavailable"
    a, b = rules_hash(Team2Rules().to_dict()), rules_hash({**Team2Rules().to_dict(), "premium_stop_pct": 40.0})
    assert len(a) == 16 and a != b and a == rules_hash(dict(reversed(list(Team2Rules().to_dict().items()))))
