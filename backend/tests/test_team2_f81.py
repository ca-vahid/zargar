"""F81 (2026-09-10): a target the gap has already run through is re-derived at the pre-open / open from
the morning's structure (PML/PMH, then the level ladder); a target still ahead is left alone."""
from __future__ import annotations

from zargar.techniques.team2.plan import rederive_targets


def plan(below=293.56, above=296.18, ladder=None):
    return {"targets": {"below": below, "above": above}, "targetsPlanned": {"below": below, "above": above},
            "levelLadder": ladder or {"highs": [296.18, 298.51, 299.61], "lows": [292.33, 290.97, 290.88]}}


def test_a_target_the_gap_ran_through_moves_to_the_pml_first():
    # the author's 2026-09-09 IWM: open 292.6 through the 293.56 down-target; PML 291.19 is ahead -> target
    tg, red = rederive_targets(plan(), reference=292.60, pmh=294.10, pml=291.19)
    assert tg["below"] == 291.19 and red["below"]["source"] == "pml" and red["below"]["was"] == 293.56
    assert tg["above"] == 296.18 and "above" not in red                       # still ahead: untouched


def test_then_the_ladder_when_the_pm_extreme_is_behind_too():
    tg, red = rederive_targets(plan(), reference=291.00, pmh=294.10, pml=291.19)
    assert tg["below"] == 290.97 and red["below"]["source"] == "ladder"      # first ladder low strictly below 291.00


def test_nothing_ahead_means_no_target_not_a_stale_one():
    tg, red = rederive_targets(plan(ladder={"highs": [], "lows": []}), reference=291.00, pmh=None, pml=None)
    assert tg["below"] is None and red["below"]["source"] == "none"


def test_a_normal_day_changes_nothing():
    tg, red = rederive_targets(plan(), reference=294.90, pmh=295.40, pml=294.30)
    assert tg == {"below": 293.56, "above": 296.18} and red == {}


def test_complete_plan_records_the_rederivation_and_can_be_switched_off():
    from zargar.marketstructure import aggregate
    from zargar.techniques.team2.plan import build_skeleton, complete_plan
    from zargar.techniques.team2.rules import Team2Rules
    from .test_team2_session import DAY, path_1m, prev_day_bars, zones_of
    prev = prev_day_bars()
    z = zones_of(prev)
    low = z["pdl"].bottom
    # a gap-down morning: pre-market drifts 2.5 below the PDL zone, i.e. through any target just under it
    today = path_1m(DAY, (4, 0), (9, 25), lambda i: low - 2.5 + 0.02 * (i % 5))
    sk = build_skeleton("SPY", DAY.isoformat(), aggregate(prev, 15), Team2Rules())
    if sk["targets"]["below"] is None or sk["targets"]["below"] < low - 2.5:
        sk["targets"]["below"] = sk["targetsPlanned"]["below"] = low - 0.5      # make the planned target sit inside the gap
    done = complete_plan({**sk, "planFor": DAY.isoformat()}, today)
    assert done["dayType"] == "gap_down" and "below" in (done.get("targetsRederived") or {})
    assert done["targets"]["below"] is None or done["targets"]["below"] < done["openPrice"]
    assert done["targetsPlanned"]["below"] == low - 0.5                          # what 17:00 said is kept
    off = complete_plan({**sk, "planFor": DAY.isoformat(), "preopenTargetRederive": False}, today)
    assert off["targets"]["below"] == low - 0.5 and "targetsRederived" not in off


def test_f88_a_legacy_plan_without_targetsplanned_does_not_ratchet_off_its_own_output():
    """F88 (2026-09-10): plans minted before v0.7.34 have no `targetsPlanned`. The 09:25 estimate can
    re-derive a side to None; the 09:30 open must still be able to restore it from what 17:00 said,
    not read the None back as "the plan's target"."""
    legacy = {"targets": {"below": 290.165, "above": 296.04},
              "levelLadder": {"highs": [296.04], "lows": []}}          # nothing on the ladder below
    # 09:25: the pre-market last IS the pre-market low -> nothing ahead -> no target
    tg, red = rederive_targets(legacy, reference=288.09, pmh=291.74, pml=288.09)
    assert tg["below"] is None and red["below"]["was"] == 290.165 and red["below"]["source"] == "none"
    assert legacy["targetsPlanned"]["below"] == 290.165               # pinned on the way through
    legacy["targets"], legacy["targetsRederived"] = tg, red
    # 09:30: the real open is 288.48, the finalized PML 287.83 is ahead again -> the target comes back
    tg2, red2 = rederive_targets(legacy, reference=288.48, pmh=291.74, pml=287.83)
    assert tg2["below"] == 287.83 and red2["below"]["was"] == 290.165 and red2["below"]["source"] == "pml"


def test_f88_recovery_works_from_the_rederived_record_alone():
    """Same, for a plan already persisted mid-degradation: `targets` holds the re-derived value and
    only `targetsRederived[side]["was"]` still remembers the original."""
    mid = {"targets": {"below": 757.90, "above": 767.89},
           "targetsRederived": {"below": {"was": 760.58, "now": 757.90, "source": "pml", "reference": 758.01}},
           "levelLadder": {"highs": [], "lows": []}}
    tg, red = rederive_targets(mid, reference=758.02, pmh=764.60, pml=757.69)
    assert mid["targetsPlanned"]["below"] == 760.58                   # the original, not the 757.90 it had drifted to
    assert tg["below"] == 757.69 and red["below"]["was"] == 760.58    # re-derived off the FINAL pml
