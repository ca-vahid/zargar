"""setup-target-v1: a destination belongs to a setup, not to the day.

The two fixtures at the top are Monday 2026-09-21 as it actually happened, taken from the runtime's
journal, not invented. Both breakouts carried as their destination the level that was their own
source, so every entry was refused before contract selection.
"""
from __future__ import annotations

import pytest

from zargar.techniques.team2 import setup_target as st

# --- the incident, from the journal and the stored plans ----------------------------------------
# Every number below is read from the runtime: the 2026-09-21 plans for SPY and QQQ, and the
# journal's targets_rederived / premarket_extrema / pm_break rows. Nothing is invented, and nothing
# is taken from the author's chart.


class Zone:
    def __init__(self, bottom, top):
        self.bottom, self.top = bottom, top


# SPY: evening target 762.95; the pre-open reference 766.20 had run through it, so F81b re-derived
# the day's `above` to the pre-market high 767.26 - which the 10:00 15m close then broke. The
# stored plan's prior-day high zone is 761.50-762.00, entirely BELOW the break; its ladder carries
# highs above it starting at 767.89.
SPY = dict(source=767.26, direction="long", kind="pm_break_up", planned=762.95, pm_high=767.26,
           tick=0.01, zones={"pdh": Zone(761.50, 762.00), "pdl": Zone(757.971, 758.76)},
           ladder=[767.89, 768.12, 768.37, 770.38, 770.48, 771.32])
# QQQ: the same shape, 721.886 re-derived to the pre-market high 729.14, broken at 09:46. Its
# prior-day high zone is 721.285-721.71, also below, and its ladder holds NOTHING above the break.
QQQ = dict(source=729.14, direction="long", kind="pm_break_up", planned=721.886, pm_high=729.14,
           tick=0.01, zones={"pdh": Zone(721.285, 721.71), "pdl": Zone(715.08, 716.07)},
           ladder=[])


# ---------------------------------------------------------------- the collisions
def test_spy_breakout_does_not_take_its_own_source_as_its_destination():
    """Monday's SPY, replayed from the stored plan. The break level is rejected as its own source,
    the overrun evening target and the below-market prior-day zone are rejected as behind, and the
    destination is the NEAREST ladder level above the break: 767.89."""
    r = st.resolve(**SPY)
    assert r["source"] == 767.26 and r["sourceRole"] == "pm_extreme"
    pm = next(c for c in r["ladder"] if c["origin"] == "pm_extreme")
    assert pm["accepted"] is False and pm["rejectedFor"] == "not_distinct"
    planned = next(c for c in r["ladder"] if c["origin"] == "planned")
    assert planned["accepted"] is False and planned["rejectedFor"] == "wrong_side"   # 762.95 is behind
    assert all(c["rejectedFor"] == "wrong_side" for c in r["ladder"] if c["origin"] == "pd_zone")
    assert r["refused"] is False and r["target"] == 767.89 and r["targetOrigin"] == "ladder"
    assert r["target"] != 769.70            # and it is NOT the author's number, two levels farther


def test_qqq_breakout_is_refused_when_nothing_distinct_lies_ahead():
    """Monday's QQQ, replayed from the stored plan: its prior-day zone is below the break and its
    ladder holds nothing above it. The answer is an explicit refusal, not a dropped or widened
    target - so correcting the defect does NOT make this trade happen."""
    r = st.resolve(**QQQ)
    assert r["refused"] is True and r["target"] is None
    assert r["refusedFor"] == "no candidate is distinct and beyond the source"
    assert all(c["accepted"] is False for c in r["ladder"])


def test_the_short_mirror_behaves_identically():
    r = st.resolve(source=729.14, direction="short", kind="pm_break_down", pm_low=729.14,
                   zones={"pdl": Zone(720.00, 726.50)}, tick=0.01)
    pm = next(c for c in r["ladder"] if c["origin"] == "pm_extreme")
    assert pm["rejectedFor"] == "not_distinct"
    assert r["target"] == 726.50 and r["targetOrigin"] == "pd_zone"      # the NEARER edge, below
    assert r["sourceRole"] == "pm_extreme"


# ---------------------------------------------------------------- the selection rule
def test_it_takes_the_nearest_valid_destination_and_never_skips_a_level():
    """2.6. The whole safety of the policy is that nearest cannot skip an intervening obstacle."""
    r = st.resolve(source=100.0, direction="long", kind="pm_break_up",
                   ladder=[101.0, 103.0, 107.0], planned=112.0,
                   zones={"pdh": Zone(105.0, 110.0)}, tick=0.01)
    assert r["target"] == 101.0 and r["targetOrigin"] == "ladder"
    ok = [c["price"] for c in r["ladder"] if c["accepted"]]
    assert 103.0 in ok and 107.0 in ok, "farther levels stay valid; they are simply not chosen"


# --- Case A: a VALID inherited target (spec 3a) -------------------------------------------------
def test_case_a_a_valid_inherited_target_is_preserved_not_moved():
    """The case that answers the target-shopping concern. The evening target is distinct, beyond the
    source and ahead of price, and nothing valid lies between. It survives untouched."""
    r = st.resolve(source=100.0, direction="long", kind="pm_break_up", planned=110.0, tick=0.01)
    assert r["target"] == 110.0 and r["targetOrigin"] == "planned"
    assert r["refused"] is False


def test_case_a_a_valid_inherited_target_is_never_pushed_farther_out():
    """Whatever else the ladder offers, a valid inherited target cannot be replaced by a more
    distant one. This is the property the rejected re-planning variants violate."""
    for extra in ([], [130.0], [130.0, 140.0], [115.0]):
        r = st.resolve(source=100.0, direction="long", kind="pm_break_up", planned=110.0,
                       ladder=extra, tick=0.01)
        assert r["target"] <= 110.0, "a valid inherited target must never be moved farther out"


def test_case_a_a_nearer_obstacle_between_source_and_target_wins():
    """Spec 2.6: a nearer valid level is an obstacle. Skipping it would manufacture room the
    structure does not offer, so it becomes the destination even though the inherited target is
    itself valid."""
    r = st.resolve(source=100.0, direction="long", kind="pm_break_up", planned=110.0,
                   ladder=[104.0], tick=0.01)
    assert r["target"] == 104.0 and r["targetOrigin"] == "ladder"


# --- Case B: an INVALID inherited target (spec 3a) ----------------------------------------------
def test_case_b_an_invalid_inherited_target_is_rejected_and_one_is_resolved():
    """Monday's shape. The inherited target IS the source, so there is no valid target to be
    'closer than' - this resolves one where the day's global value supplied none."""
    r = st.resolve(source=100.0, direction="long", kind="pm_break_up", planned=100.0,
                   ladder=[104.0, 108.0], tick=0.01)
    inherited = next(c for c in r["ladder"] if c["origin"] == "planned")
    assert inherited["accepted"] is False and inherited["rejectedFor"] == "not_distinct"
    assert r["target"] == 104.0, "the nearest VALID candidate, not a comparison against an invalid one"


def test_case_b_is_reported_as_a_different_case_from_case_a():
    """The two cases must be distinguishable in the record, because only Case B changes which
    trades become possible and only Case A speaks to target shopping."""
    a = st.resolve(source=100.0, direction="long", kind="pm_break_up", planned=110.0, tick=0.01)
    b = st.resolve(source=100.0, direction="long", kind="pm_break_up", planned=100.0,
                   ladder=[104.0], tick=0.01)
    assert a["targetOrigin"] == "planned"        # inherited target survived
    assert b["targetOrigin"] == "ladder"         # inherited target was rejected, one was resolved
    assert next(c for c in b["ladder"] if c["origin"] == "planned")["rejectedFor"] == "not_distinct"


def test_ties_break_deterministically_and_repeatably():
    a = st.resolve(source=100.0, direction="long", kind="pm_break_up", ladder=[105.0],
                   zones={"pdh": Zone(105.0, 108.0)}, tick=0.01)
    b = st.resolve(source=100.0, direction="long", kind="pm_break_up", ladder=[105.0],
                   zones={"pdh": Zone(105.0, 108.0)}, tick=0.01)
    assert a["target"] == b["target"] == 105.0
    assert a["targetOrigin"] == b["targetOrigin"] == "pd_zone"    # ORIGIN_ORDER puts the zone first
    assert a["ladder"] == b["ladder"]


# ---------------------------------------------------------------- distinctness and equality
@pytest.mark.parametrize("price,why", [(100.0, "not_distinct"), (100.005, "not_distinct"),
                                       (99.0, "wrong_side"), (100.02, None)])
def test_equality_and_wrong_side_are_named_separately(price, why):
    r = st.resolve(source=100.0, direction="long", kind="pm_break_up", ladder=[price], tick=0.01)
    c = next(c for c in r["ladder"] if c["origin"] == "ladder")
    assert c["rejectedFor"] == why


def test_a_destination_behind_the_live_price_is_refused_not_moved():
    """2.5. Price ran past the destination while contract work was awaited."""
    r = st.resolve(source=100.0, direction="long", kind="pm_break_up", ladder=[105.0],
                   actionable=106.0, tick=0.01)
    c = next(c for c in r["ladder"] if c["origin"] == "ladder")
    assert c["rejectedFor"] == "behind_price"
    assert r["refused"] is True and r["target"] is None


# ---------------------------------------------------------------- causality and the record
def test_no_later_level_can_change_an_earlier_decision():
    """2.2/2.8. The resolver is pure, so the decision is a function of what was known then. A level
    that appears later produces a NEW record; it cannot reach back into the old one."""
    before = st.resolve(source=100.0, direction="long", kind="pm_break_up", ladder=[110.0], tick=0.01)
    after = st.resolve(source=100.0, direction="long", kind="pm_break_up", ladder=[110.0, 102.0], tick=0.01)
    assert before["target"] == 110.0                       # unchanged by anything discovered later
    assert after["target"] == 102.0 and before != after


def test_the_record_carries_the_ladder_the_reasons_and_the_input_times():
    r = st.resolve(source=100.0, direction="long", kind="pm_break_up", ladder=[105.0], pm_high=100.0,
                   planned=99.0, tick=0.01,
                   input_ts={"ladder": 1790000000000, "pm_extreme": 1789999000000})
    assert r["version"] == "setup-target-v1"
    assert {c["origin"] for c in r["ladder"]} == {"ladder", "pm_extreme", "planned"}
    assert all("rejectedFor" in c and "distance" in c for c in r["ladder"])
    assert r["targetInputTs"] == 1790000000000
    assert next(c for c in r["ladder"] if c["origin"] == "pm_extreme")["inputTs"] == 1789999000000


def test_duplicate_candidates_are_recorded_once_not_counted_twice():
    r = st.resolve(source=100.0, direction="long", kind="pm_break_up", ladder=[105.0, 105.0], tick=0.01)
    dupes = [c for c in r["ladder"] if c["rejectedFor"] == "duplicate"]
    assert len(dupes) == 1 and r["target"] == 105.0


def test_no_candidates_at_all_is_its_own_refusal_reason():
    r = st.resolve(source=100.0, direction="long", kind="pm_break_up", tick=0.01)
    assert r["refused"] is True and r["refusedFor"] == "no destination candidates were known"


# ---------------------------------------------------------------- roles
@pytest.mark.parametrize("kind,role", [("pm_break_up", "pm_extreme"), ("pm_break_down", "pm_extreme"),
                                       ("key_break_up", "key_level"), ("scenario_1", "zone_edge"),
                                       ("scenario_4", "zone_edge")])
def test_every_setup_kind_has_a_source_role(kind, role):
    assert st.role_for(kind) == role
    assert st.resolve(source=100.0, direction="long", kind=kind, ladder=[105.0])["sourceRole"] == role


def test_the_resolver_holds_no_symbol_or_price_constants_at_all():
    """Hygiene, NOT a defence against overfitting - excluding one number proves nothing about
    behaviour. The behavioural guarantees are the tests above and below: causal inputs only,
    nearest-obstacle selection, long/short symmetry, independence from future data, valid targets
    preserved, and identical behaviour when disabled. This only checks the module carries no baked
    price or ticker of any kind, which a tuned resolver would need."""
    import pathlib
    import re
    src = pathlib.Path(st.__file__).read_text(encoding="utf-8")
    code = "\n".join(l.split("#")[0] for l in src.splitlines() if not l.strip().startswith("#"))
    code = re.sub(chr(34) * 3 + ".*?" + chr(34) * 3, "", code, flags=re.S)
    assert not re.search(r"\b\d{2,}\.\d+\b", code), "no baked price constants"
    assert not re.search(r"\b(SPY|QQQ|IWM)\b", code), "no baked tickers"


def test_long_and_short_are_exact_mirrors():
    """Symmetry as behaviour: the same structure reflected must produce the same decision."""
    up = st.resolve(source=100.0, direction="long", kind="pm_break_up", planned=100.0,
                    ladder=[104.0, 108.0], pm_high=100.0, tick=0.01)
    dn = st.resolve(source=100.0, direction="short", kind="pm_break_down", planned=100.0,
                    ladder=[96.0, 92.0], pm_low=100.0, tick=0.01)
    assert up["target"] == 104.0 and dn["target"] == 96.0
    assert up["sourceRole"] == dn["sourceRole"] == "pm_extreme"
    assert [c["rejectedFor"] for c in up["ladder"]] == [c["rejectedFor"] for c in dn["ladder"]]


def test_only_inputs_known_at_confirmation_can_reach_the_decision():
    """Causality as behaviour: the resolver is a pure function of its arguments, so there is no
    channel by which a later bar, level or price could enter. Passing the same inputs in any order
    returns the same record."""
    kw = dict(source=100.0, direction="long", kind="pm_break_up", tick=0.01)
    a = st.resolve(**kw, ladder=[104.0, 108.0], planned=110.0)
    b = st.resolve(**kw, planned=110.0, ladder=[104.0, 108.0])
    assert a == b
    # and the record carries the input times, so a reader can check them against the confirmation
    c = st.resolve(**kw, ladder=[104.0], input_ts={"ladder": 1790000000000})
    assert c["targetInputTs"] == 1790000000000
