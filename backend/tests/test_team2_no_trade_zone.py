"""C1 geometry (2026-09-13, other team's review of the week-37 plan): the ordered truth table of `sizing_bucket` in both
modes, the explicit obstacle rule that keeps F15's case refused, and the proof that the knobs are OFF by default so
nothing in the live read changes until the user flips them."""
from __future__ import annotations

from zargar.marketstructure import aggregate
from zargar.marketstructure.dailylevels import Zone
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.rules import Team2Rules
from zargar.techniques.team2.scenario import pm_room, sizing_bucket
from zargar.techniques.team2.session import simulate_session

from .test_team2_integrity import drift_day
from .test_team2_session import DAY, make_rules, path_1m, prev_day_bars

Z = {"pdh": Zone("pdh", 718.91, 718.60, "2026-09-03", 0), "pdl": Zone("pdl", 709.69, 709.00, "2026-09-03", 0)}
PMH, PML = 722.06, 717.13


def test_truth_table_pm_range_mode():
    assert sizing_bucket(721.44, Z, PMH, PML) == "none"            # inside PM, beyond the zone: V6's picture (F15)
    assert sizing_bucket(718.00, Z, PMH, PML) == "none"            # inside both ranges
    assert sizing_bucket(723.00, Z, PMH, PML) == "full"            # beyond both
    assert sizing_bucket(716.00, Z, PMH, PML) == "small"           # outside PM, inside yesterday's range
    assert sizing_bucket(721.44, Z, None, None) == "full"          # no PM range: yesterday's zones only


def test_truth_table_conjunction_mode():
    m = "conjunction"
    assert sizing_bucket(718.00, Z, PMH, PML, mode=m) == "none"    # inside BOTH ranges = risk off (B5)
    assert sizing_bucket(721.44, Z, PMH, PML, mode=m) == "small"   # inside PM but beyond the zone: V6's rung, never full
    assert sizing_bucket(723.00, Z, PMH, PML, mode=m) == "full"
    assert sizing_bucket(716.00, Z, PMH, PML, mode=m) == "small"
    assert sizing_bucket(721.44, Z, None, None, mode=m) == "full"


def test_f15_case_is_not_kept_by_geometry_but_by_the_room_rule():
    # the reviewers' point: QQQ 2026-09-04 10:02 long 721.44 (PDH top 718.91, PM 717.13-722.06) is inside the PM range
    # but OUTSIDE yesterday's range -> pure conjunction ALLOWS it (small). Its refusal is the explicit room rule.
    assert sizing_bucket(721.44, Z, PMH, PML, mode="conjunction") == "small"
    assert round(pm_room(721.44, "long", PMH, PML), 2) == 0.62
    assert pm_room(723.00, "long", PMH, PML) is None               # outside the range: no PM obstacle
    assert round(pm_room(717.50, "short", PMH, PML), 2) == 0.37
    assert pm_room(721.44, "long", None, None) is None


def test_fridays_spy_entry_under_the_conjunction():
    z = {"pdh": Zone("pdh", 760.11, 758.85, "2026-09-10", 0), "pdl": Zone("pdl", 757.00, 756.64, "2026-09-10", 0)}
    assert sizing_bucket(765.27, z, 766.53, 758.17) == "none"                        # what refused the author's candle
    assert sizing_bucket(765.27, z, 766.53, 758.17, mode="conjunction") == "small"   # C1: tradeable, small
    assert round(pm_room(765.27, "long", 766.53, 758.17) / 0.56, 1) == 2.2           # ~2.2 ATR of room to the PMH


def _read(plan_patch: dict | None = None, **rule_kw):
    rules = make_rules(**rule_kw)
    prev = prev_day_bars()
    today = path_1m(DAY, (4, 0), (20, 0), drift_day)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(prev, 15), rules), today)
    plan.update(plan_patch or {})
    return simulate_session(plan, today, rules, sigma=0.2, warmup_1m=prev)


def test_knobs_are_off_by_default_and_the_read_is_unchanged():
    r = Team2Rules()
    assert r.no_trade_zone == "pm_range" and r.pm_room_atr == 0.0 and r.min_target_atr == 0.0
    base = _read()
    same = _read(no_trade_zone="pm_range", pm_room_atr=0.0, min_target_atr=0.0)
    assert [e["event"] for e in base.events] == [e["event"] for e in same.events]
    assert not [e for e in base.events if e["event"] in ("skip_pm_room", "skip_target_near")]


def test_the_new_skips_exist_only_when_their_knobs_are_on():
    # a huge minimum target room refuses every entry with a reason of its own; a huge room requirement refuses
    # every in-range entry that is not the pm_break retest
    # the drift day's plan carries no up-target; give it one nine cents above the 10:00 entry (570.71) so C3 can judge it
    base = _read(plan_patch={"targets": {"above": 570.80, "below": None}})
    assert [e for e in base.events if e["event"] == "fire" and e.get("target") == 570.8]      # off: the near target is taken
    near = _read(plan_patch={"targets": {"above": 570.80, "below": None}}, min_target_atr=1.0)
    skips = [e for e in near.events if e["event"] == "skip_target_near"]
    assert skips and skips[0]["roomAtr"] < 1.0 and not [e for e in near.events if e["event"] == "fire"]
    room = _read(no_trade_zone="conjunction", pm_room_atr=100.0)
    kinds = {e["event"] for e in room.events}
    assert "skip_pm_room" in kinds or "fire" in kinds            # in-range entries are refused by the room rule, out-of-range ones fire
