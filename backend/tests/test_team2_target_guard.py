"""Team2 F72 — the profit-target guard on NEW entries.

A gap that opens THROUGH the PDH/PDL zone leaves the planned level behind price before the 15m
confirmation arrives (SPY 2026-09-09 09:46: `scenario_4 break PDL` armed with target 764.75 while
SPY traded 763.7; IWM 293.56 at 293.2). Both target tests are "touched" tests — `b2.low <= target`
on the 2m close in the read, `last <= target` on the ~2s quote watch in the runner — so a target at
or behind the entry closes the position on its first bar or its first print, and for a SHORT a
target ABOVE the entry is a LOSS booked under a "target reached" label.

Every case is mirrored long/short. The guard is ENTRY-side only: an open position keeps its own
target, premium stop, candle stop, trims and flatten, which the last section pins down.
"""
from __future__ import annotations

import math

import pytest

from zargar.execution.planrunner import Trade
from zargar.marketstructure import aggregate, prior_day_zones
from zargar.techniques.team2.levels import level_ladder, next_structural_level
from zargar.techniques.team2.plan import build_skeleton, complete_plan
from zargar.techniques.team2.runner import Team2Runner
from zargar.techniques.team2.scenario import target_is_ahead
from zargar.techniques.team2.session import simulate_session

from .test_team2_session import DAY, make_rules, path_1m, prev_day_bars, trend_day, zones_of

PREV_BARS = prev_day_bars()
Z = zones_of(PREV_BARS)


# ----------------------------------------------------------------- the predicate itself
@pytest.mark.parametrize("direction,target,spot,ok", [
    # ahead — the only shape that may trade
    ("long", 570.0, 568.0, True),
    ("short", 566.0, 568.0, True),
    # wrong side: behind the entry in the trade's own direction
    ("long", 566.0, 568.0, False),
    ("short", 570.0, 568.0, False),
    # equal price is not a target: the "touched" test is already true on the entry bar
    ("long", 568.0, 568.0, False),
    ("short", 568.0, 568.0, False),
    # a hair ahead still counts — the guard judges the side, it invents no minimum room
    ("long", 568.01, 568.0, True),
    ("short", 567.99, 568.0, True),
    # no target at all is allowed: stops, trims and the flatten still manage the trade
    ("long", None, 568.0, True),
    ("short", None, 568.0, True),
    # an unjudgeable spot is left to the caller's other gates
    ("long", 570.0, None, True),
    ("short", 566.0, None, True),
])
def test_target_is_ahead_is_mirrored_and_rejects_equal_prices(direction, target, spot, ok):
    assert target_is_ahead(target, spot, direction) is ok


# ----------------------------------------------------------------- days
def down_day(prev):
    """The mirror of `trend_day`: pre-market drifts 566 -> 564, the open pushes DOWN through the PDL
    zone and the 15m bar closes below it (scenario 4, short); 09:46-10:00 pops back up into the
    EMA13 and closes below it (the short's pullback); then it sells off."""
    z = zones_of(prev)
    bot = z["pdl"].bottom

    def f(i):
        m = 4 * 60 + i
        if m < 9 * 60 + 30:
            return 566.0 - 2.0 * (i / 330)
        x = m - 9 * 60 - 30
        if x < 15:
            return 564.0 + (bot - 1.2 - 564.0) * (x / 14)      # break the zone, 15m closes below
        if x < 30:
            return bot - 1.2 + 1.0 * ((x - 15) / 15)           # pop back toward the EMA13
        if x < 120:
            return bot - 0.2 - 5.5 * ((x - 30) / 90)           # sell off
        if x < 300:
            return bot - 5.7 + 5.0 * ((x - 120) / 180)
        return bot - 0.7 + 0.05 * math.sin(i / 3)
    return path_1m(DAY, (4, 0), (20, 0), f), z


def read(day_fn, *, retarget=None, ladder=None, **rule_kw):
    """Run one synthetic session. `retarget` rewrites the plan's own target the way a gap that has
    already run through the level leaves it — the one input the guard is about. `ladder` injects the
    structural levels: this harness has a SINGLE prior session and `level_ladder` excludes the zone's
    own date, so a real plan built here has no pivots at all (its `targets` are None for the same
    reason, which is why every test sets them). Ladder CONSTRUCTION is covered separately, against a
    multi-session history."""
    rules = make_rules(**rule_kw)
    today, _z = day_fn(PREV_BARS)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(PREV_BARS, 15), rules), today)
    if retarget:
        plan["targets"] = {**(plan.get("targets") or {}), **retarget}
    if ladder is not None:
        plan["levelLadder"] = ladder
    return simulate_session(plan, today, rules, sigma=0.2, warmup_1m=PREV_BARS)


def _events(res, kind):
    return [e for e in res.events if e["event"] == kind]


def _entry_spot(res):
    assert res.trades, "control day did not trade"
    t = res.trades[0]
    return float(t.get("entrySpot") if t.get("entrySpot") is not None else t["entry"])


# ----------------------------------------------------------------- the guard refuses new entries
def test_short_entry_is_refused_when_the_target_sits_above_it():
    """SPY 2026-09-09 exactly: the break is real, the target is already behind price."""
    entry = _entry_spot(read(down_day))

    res = read(down_day, retarget={"below": entry + 3.0})       # target ABOVE the short's entry
    assert not res.trades
    assert not _events(res, "fire")
    skips = _events(res, "skip_target_behind")
    assert skips, [e["event"] for e in res.events]
    assert "above" in skips[0]["why"] and "(F72)" in skips[0]["why"]


def test_long_entry_is_refused_when_the_target_sits_below_it():
    """The mirror: a long whose planned level is already under the pullback entry."""
    entry = _entry_spot(read(trend_day))

    res = read(trend_day, retarget={"above": entry - 3.0})      # target BELOW the long's entry
    assert not res.trades
    assert not _events(res, "fire")
    skips = _events(res, "skip_target_behind")
    assert skips, [e["event"] for e in res.events]
    assert "below" in skips[0]["why"] and "(F72)" in skips[0]["why"]


@pytest.mark.parametrize("day_fn,key,sign", [(down_day, "below", 1.0), (trend_day, "above", -1.0)])
def test_a_target_a_hair_on_the_wrong_side_is_refused_on_both_sides(day_fn, key, sign):
    """The boundary end-to-end. An EXACT tie cannot be reached from the plan — the entry spot is the
    raw EMA13 and the trade dict rounds it to 4 dp, so a target copied back from it always lands a
    fraction ahead. Equality itself is pinned on both sides by the predicate test above; here we
    prove the boundary is judged at all, one ten-thousandth on the wrong side."""
    entry = _entry_spot(read(day_fn))
    res = read(day_fn, retarget={key: entry + sign * 0.0001})
    assert not res.trades
    assert _events(res, "skip_target_behind")


@pytest.mark.parametrize("day_fn,key,sign", [(down_day, "below", -1.0), (trend_day, "above", 1.0)])
def test_a_target_that_is_ahead_still_fires_on_both_sides(day_fn, key, sign):
    """The guard must not over-fire: move the target further AHEAD and the day still trades."""
    entry = _entry_spot(read(day_fn))
    res = read(day_fn, retarget={key: entry + sign * 4.0})
    fires = _events(res, "fire")
    assert res.trades and fires
    # a later RE-entry may still be refused once price has run past the moved target — that is the
    # guard working, not over-firing. What matters is that the first entry was allowed through.
    skips = _events(res, "skip_target_behind")
    assert not skips or skips[0]["ts"] > fires[0]["ts"], (fires[0], skips[0])


@pytest.mark.parametrize("day_fn,key,sign", [(down_day, "below", 3.0), (trend_day, "above", -3.0)])
def test_the_refusal_does_not_spend_the_d9_pullback_allowance(day_fn, key, sign):
    """F18/F61: this is a refusal about the PLAN, not about the quality of the pullback, so the
    setup's D9 touch allowance is untouched — only a PRICED fire spends it."""
    entry = _entry_spot(read(day_fn))
    res = read(day_fn, retarget={key: entry + sign})
    live = [s for s in res.setups if not s["dead"]]
    assert live, res.setups
    assert all(s["touches"] == 0 for s in live), live
    assert any(s["skipped"] == "skip_target_behind" for s in res.setups), res.setups


def test_the_refusal_is_not_restated_on_every_2m_close():
    """F23: `note_once` says a structural refusal once and again only after a real touch clears it
    (`s._skipped`), so it is one row per pullback episode — never one per 2m close, which would bury
    the read and the journal under identical rows."""
    entry = _entry_spot(read(down_day))
    res = read(down_day, retarget={"below": entry + 3.0})
    skips = _events(res, "skip_target_behind")
    assert skips, "the refusal must be stated at least once"
    assert len(skips) <= res.summary["setups"] * 3, (len(skips), res.summary)
    assert len(skips) < res.summary["bars2m"] / 10, (len(skips), res.summary["bars2m"])
    assert len({e["ts"] for e in skips}) == len(skips), "one row per 2m close at most"


# ----------------------------------------------------------------- the quote watch (runner side)
def _trade(direction: str, entry: float, targets: list[float]) -> Trade:
    """A trade shaped the way the Team2 runner builds one, open with a fill."""
    t = Trade(trigger_id="scenario_4@09:30#1", kind="scenario_4", fired_ts=0, window="team2",
              entry=entry, stop=entry + 1.0 if direction == "short" else entry - 1.0,
              targets=list(targets), direction=direction, instrument="options", multiplier=100.0)
    t.status, t.qty, t.filled_qty, t.remaining, t.avg_fill = "open", 2.0, 2.0, 2.0, 0.60
    t.order_symbol = "SPY260909P00565000"
    return t


@pytest.fixture
def watch():
    """`target_breach` reads only the trade — the quote watch calls it with a live print."""
    return Team2Runner.__new__(Team2Runner).target_breach


@pytest.mark.parametrize("direction,entry,target,print_at", [
    ("short", 565.0, 568.0, 565.0),     # target ABOVE a short: the entry print already "touches" it
    ("long", 568.0, 565.0, 568.0),      # target BELOW a long: same, mirrored
])
def test_a_wrong_side_target_would_fire_on_the_first_live_print(watch, direction, entry, target, print_at):
    """The exposure F72 closes: `target_breach` runs on the ~2s quote watch, so a wrong-side target
    sells the whole position on the FIRST print — before a single 2m bar closes."""
    assert watch(_trade(direction, entry, [target]), print_at) is not None


@pytest.mark.parametrize("direction,entry,print_at", [("short", 565.0, 565.0), ("long", 568.0, 568.0)])
def test_dropping_the_target_disarms_that_quote_watch_exit(watch, direction, entry, print_at):
    """What the runner now does instead: no target at all. The trade is still managed by its candle
    stop, its premium stop and the 15:45 flatten — none of which run through `target_breach`."""
    assert watch(_trade(direction, entry, []), print_at) is None


# --------------------------------------------- existing-position protection is NOT weakened
@pytest.mark.parametrize("direction,entry,target,miss,hit", [
    ("short", 568.0, 565.0, 566.0, 564.9),
    ("long", 565.0, 568.0, 567.0, 568.1),
])
def test_a_valid_target_on_an_open_position_still_exits_on_the_print(watch, direction, entry, target, miss, hit):
    tr = _trade(direction, entry, [target])
    assert watch(tr, miss) is None
    reason = watch(tr, hit)
    assert reason is not None and f"{target:.2f}" in reason


def test_an_open_position_keeps_every_exit_the_read_owns():
    """The guard is entry-side: once a position is open the read still runs its target, premium
    stop, candle stop, trims and flatten. The control day opens a position and closes it."""
    res = read(down_day)
    assert res.trades
    assert res.trades[0].get("exits"), res.trades[0]
    assert res.open_position is None, "the synthetic day must close its position"


# =============================================================== the runner's fallback (F72, revised)
# An invalid target must never become permission for a TARGETLESS entry: that is a weaker outcome
# than the refusal the read applies to the same condition, and a silent one. Invalid means refused
# at BOTH layers; only a genuinely ABSENT target is allowed through.
@pytest.fixture
def resolve():
    return Team2Runner.__new__(Team2Runner).resolve_fire_target


@pytest.mark.parametrize("direction,spot,bad", [("short", 763.7, 764.75), ("long", 764.75, 763.7)])
def test_an_invalid_target_on_the_fire_refuses_the_entry(resolve, direction, spot, bad):
    target, refusal = resolve({"target": bad}, {"target": bad}, spot, direction)
    assert target is None
    assert refusal is not None and "F72" in refusal


@pytest.mark.parametrize("direction,spot,bad", [("short", 763.7, 764.75), ("long", 764.75, 763.7)])
def test_an_invalid_setup_fallback_refuses_instead_of_entering_targetless(resolve, direction, spot, bad):
    """The exact hole: the fire carried NO target, so the setup's stale one is picked up. Dropping it
    would enter with no target at all - permission the read never gave. It must refuse."""
    target, refusal = resolve({"target": None}, {"target": bad}, spot, direction)
    assert target is None
    assert refusal is not None
    assert "setup" in refusal, refusal
    assert "no target at all" in refusal, refusal


@pytest.mark.parametrize("direction,spot", [("short", 763.7), ("long", 764.75)])
def test_a_genuinely_absent_target_is_still_allowed_through(resolve, direction, spot):
    """The one shape that may enter targetless - and it is the shape the read already validated."""
    target, refusal = resolve({"target": None}, {"target": None}, spot, direction)
    assert target is None and refusal is None


@pytest.mark.parametrize("direction,spot,good", [("short", 763.7, 760.0), ("long", 764.75, 768.0)])
def test_a_valid_target_is_carried_onto_the_trade(resolve, direction, spot, good):
    target, refusal = resolve({"target": good}, {}, spot, direction)
    assert refusal is None and target == pytest.approx(good)


@pytest.mark.parametrize("direction,spot,good,bad",
                         [("short", 763.7, 760.0, 764.75), ("long", 764.75, 768.0, 763.7)])
def test_the_fires_own_valid_target_wins_over_a_stale_setup_one(resolve, direction, spot, good, bad):
    target, refusal = resolve({"target": good}, {"target": bad}, spot, direction)
    assert refusal is None and target == pytest.approx(good)


def test_an_unparseable_target_refuses_rather_than_falling_through(resolve):
    target, refusal = resolve({"target": "not-a-number"}, {}, 763.7, "short")
    assert target is None and refusal is not None


# =============================================================== hod_target=always cannot recover this
def test_hod_target_always_does_not_recover_a_target_price_has_run_through():
    """X3b's `nearer` test only ever pulls the target CLOSER: for a short it requires the running LOD
    to be ABOVE the planned target. When price has already run THROUGH that target the LOD is below
    it, so X3b declines and the case is unrecovered - `hod_target="always"` is not a fix for F72.
    Mirrored on the long side."""
    for day_fn, key, sign in [(down_day, "below", 3.0), (trend_day, "above", -3.0)]:
        entry = _entry_spot(read(day_fn))
        res = read(day_fn, retarget={key: entry + sign}, hod_target="always")
        assert not res.trades, (day_fn.__name__, res.trades)
        assert _events(res, "skip_target_behind"), day_fn.__name__
        assert not _events(res, "target_replanned"), "the variant is off by default"


# =============================================================== the structural re-planning VARIANT
def test_the_ladder_is_ordered_outward_and_selection_is_price_relative():
    ladder = {"highs": [570.0, 575.0, 580.0], "lows": [560.0, 555.0, 550.0]}
    assert next_structural_level(ladder, 566.0, "long") == 570.0
    assert next_structural_level(ladder, 571.0, "long") == 575.0       # price moved: a different level
    assert next_structural_level(ladder, 566.0, "short") == 560.0
    assert next_structural_level(ladder, 559.0, "short") == 555.0      # ditto, mirrored
    assert next_structural_level(ladder, 590.0, "long") is None        # nothing left above
    assert next_structural_level(ladder, 540.0, "short") is None
    assert next_structural_level(None, 566.0, "short") is None


def test_the_plan_carries_a_ladder_built_from_the_same_pivots():
    """Construction, against a real multi-session history (the one-day harness above has no pivots
    to find — `level_ladder` excludes the zone's own session, exactly like `targets_beyond`)."""
    import datetime as dt
    hist = []
    for back in (4, 3, 2):
        hist += prev_day_bars(DAY - dt.timedelta(days=back))
    hist += prev_day_bars(DAY - dt.timedelta(days=1))
    rules = make_rules()
    bars15 = aggregate(hist, 15)
    plan = build_skeleton("SPY", DAY.isoformat(), bars15, rules)
    ladder = plan.get("levelLadder")
    assert ladder and (ladder["highs"] or ladder["lows"]), ladder
    assert ladder["highs"] == sorted(ladder["highs"])                 # outward: ascending
    assert ladder["lows"] == sorted(ladder["lows"], reverse=True)     # outward: descending
    assert ladder == level_ladder(bars15, prior_day_zones([b for b in bars15 if b.ts]),
                                  lookback_sessions=rules.target_lookback_sessions)
    # and it is a SUPERSET of the zone-anchored answer: same pivots, just not filtered by the zone
    tg = plan["targets"]
    if tg.get("above") is not None:
        assert tg["above"] in ladder["highs"]
    if tg.get("below") is not None:
        assert tg["below"] in ladder["lows"]


def _ladder_for(entry: float, direction: str) -> dict:
    """Structural levels either side of the entry, the far one being the recoverable target."""
    if direction == "short":
        return {"highs": [entry + 8.0], "lows": [entry - 2.5, entry - 6.0]}
    return {"highs": [entry + 2.5, entry + 6.0], "lows": [entry - 8.0]}


@pytest.mark.parametrize("day_fn,key,sign,direction",
                         [(down_day, "below", 3.0, "short"), (trend_day, "above", -3.0, "long")])
def test_the_variant_recovers_the_trade_the_baseline_refuses(day_fn, key, sign, direction):
    """Same day, same stale target, same ladder: off = refused, entry = re-planned and traded."""
    entry = _entry_spot(read(day_fn))
    lad = _ladder_for(entry, direction)
    base = read(day_fn, retarget={key: entry + sign}, ladder=lad)
    assert not base.trades and _events(base, "skip_target_behind")

    var = read(day_fn, retarget={key: entry + sign}, ladder=lad, target_replan="entry")
    assert _events(var, "target_replanned"), [e["event"] for e in var.events]
    assert var.trades, "the variant must recover a trade the baseline refuses"
    assert var.trades[0]["targetKind"] == "replan", var.trades[0]


@pytest.mark.parametrize("day_fn,key,sign,direction",
                         [(down_day, "below", 3.0, "short"), (trend_day, "above", -3.0, "long")])
def test_the_replanned_target_is_validated_at_the_entry_that_used_it(day_fn, key, sign, direction):
    """Validation at ENTRY, not only at arming: every re-planned target must be strictly ahead of the
    entry spot of the very fire that carried it - not of the price when the scenario armed."""
    entry = _entry_spot(read(day_fn))
    var = read(day_fn, retarget={key: entry + sign}, ladder=_ladder_for(entry, direction),
               target_replan="entry")
    fires = _events(var, "fire")
    assert fires
    checked = 0
    for f in fires:
        if f.get("targetKind") != "replan":
            continue
        assert target_is_ahead(f["target"], f["spot"], direction), f
        checked += 1
    assert checked, "no re-planned fire to validate"


def test_a_replan_is_re_validated_and_cannot_become_an_exemption():
    """With no ladder to draw on, the variant finds no candidate and the BASELINE still refuses -
    the re-plan is a candidate, never a licence to trade a target that is not ahead."""
    entry = _entry_spot(read(down_day))
    rules = make_rules(target_replan="entry")
    today, _z = down_day(PREV_BARS)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(PREV_BARS, 15), rules), today)
    plan["targets"] = {**plan["targets"], "below": entry + 3.0}
    plan["levelLadder"] = {"highs": [], "lows": []}                    # nothing structural to fall back to
    res = simulate_session(plan, today, rules, sigma=0.2, warmup_1m=PREV_BARS)
    assert not res.trades
    assert _events(res, "skip_target_behind")
    assert not _events(res, "target_replanned")


def test_the_variant_is_off_by_default_and_changes_nothing_when_targets_are_sound():
    """A variant must be measurable against the baseline: with a sound target both agree exactly."""
    base = read(down_day)
    var = read(down_day, target_replan="entry", ladder=_ladder_for(_entry_spot(base), "short"))
    assert [e["event"] for e in base.events] == [e["event"] for e in var.events]
    assert base.summary["trades"] == var.summary["trades"]
    assert not _events(var, "target_replanned")
    assert make_rules().target_replan == "off"
