"""2026-09-19 profitability study: two RESEARCH knobs on the pure read, both default to the behaviour that was live before
them. `stop_candles` (H1) and `target_collision` (E1) were measured on real option prints and REJECTED; they stay as
default-off research knobs so the measurement can be reproduced. These tests pin (a) the defaults change nothing and
(b) what each knob does when set."""
from __future__ import annotations

from dataclasses import replace

from zargar.marketstructure.aggregate import aggregate
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.rules import Team2Rules
from zargar.techniques.team2.session import simulate_session

from .test_team2_session import DAY, make_rules
from .test_team2_target_collision import _collision_day


def _collision_read(rules):
    prev, today, z, pmh = _collision_day()
    plan = build_skeleton("SPY", DAY.isoformat(), aggregate(prev, 15), rules)
    plan["targetsPlanned"]["above"] = z["pdh"].top + 0.2
    plan["targets"]["above"] = z["pdh"].top + 0.2
    done = complete_plan(plan, today)
    return simulate_session(done, today, rules, sigma=0.20, warmup_1m=prev).to_dict()


def test_defaults_are_the_behaviour_before_the_knobs():
    r = Team2Rules()
    assert r.stop_candles == 1 and r.target_collision == "refuse"
    base = make_rules()
    same = replace(base, stop_candles=1, target_collision="refuse")
    a, b = _collision_read(base), _collision_read(same)
    assert a["events"] == b["events"] and a["trades"] == b["trades"]


def test_collision_replan_either_finds_a_distinct_destination_beyond_the_level_or_still_refuses():
    refuse = _collision_read(make_rules())
    assert any(e["event"] == "skip_target_collision" for e in refuse["events"])
    assert not any(e["event"] == "fire" and str(e.get("setup", "")).startswith("pm_break_up") for e in refuse["events"])
    res = _collision_read(replace(make_rules(), target_collision="replan"))
    setup = [s for s in res["setups"] if s["kind"] == "pm_break_up"][0]
    replans = [e for e in res["events"] if e["event"] == "target_replanned" and e.get("source") == "collision_replan"]
    fires = [e for e in res["events"] if e["event"] == "fire" and e.get("setup") == setup["id"]]
    skips = [e for e in res["events"] if e["event"] == "skip_target_collision" and e.get("setup") == setup["id"]]
    assert replans or skips, "the collision is either re-planned or refused, never ignored"
    for e in replans:
        assert e["target"] > setup["anchor"] and e["target"] > e["spot"], "a re-planned destination is distinct, beyond the level and ahead"
    for t in res["trades"]:
        if t["setup"] == setup["id"] and t.get("target") is not None:
            assert t["target"] > setup["anchor"]
    if not replans:
        assert not fires


def test_two_candle_stop_never_exits_on_the_first_close_through_the_line():
    one = _collision_read(replace(make_rules(), target_collision="replan"))
    two = _collision_read(replace(make_rules(), target_collision="replan", stop_candles=2))
    for t in two["trades"]:
        if "S1" in t["exitReason"]:
            assert "2 consecutive 2m closes" in t["exitReason"] and "stop_candles=2" in t["exitReason"]
    for t in one["trades"]:
        if "S1" in t["exitReason"]:
            assert "one-candle stop" in t["exitReason"]
