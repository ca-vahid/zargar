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
from zargar.marketstructure import aggregate
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


def read(day_fn, *, retarget=None, **rule_kw):
    """Run one synthetic session. `retarget` rewrites the plan's own target the way a gap that has
    already run through the level leaves it — the one input the guard is about."""
    rules = make_rules(**rule_kw)
    today, _z = day_fn(PREV_BARS)
    plan = complete_plan(build_skeleton("SPY", DAY.isoformat(), aggregate(PREV_BARS, 15), rules), today)
    if retarget:
        plan["targets"] = {**(plan.get("targets") or {}), **retarget}
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
