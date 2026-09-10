"""T-13 (2026-09-09): a bounce/reject level the open gapped through is a CONTINUATION
setup in the gap direction when `gap_through_continuation` is on (SPY 09-09: opened
below the prior-day low, drifted -0.4% - the author's +126% puts). Off by default so
the walk-forward can sweep it (`sweep --set gap_through_continuation=true`)."""
import datetime as dt

from zargar.marketstructure.tracker import TriggerTracker
from zargar.technique.rulebook import Thresholds

from .test_technique_walkforward import _bar

DAY = dt.date(2026, 9, 9)          # a Wednesday


def _trigger():
    return {"id": "b1", "kind": "bounce", "direction": "long", "setupType": "support_bounce",
            "entry": {"price": 100.0, "basis": "at_level"}, "stop": {"price": 99.5},
            "targets": [{"price": 101.0}, {"price": 102.0}, {"price": 103.0}], "valid": True}


def _session():
    # opens through the stop: 99.0 < 99.5; opening bar low 98.8 is the continuation edge
    bars = [_bar(DAY, 9, 30, 99.0, 99.3, 98.8, 99.1, 1000)]
    for i in range(6):                                  # quiet bars above the edge, volume baseline
        bars.append(_bar(DAY, 9, 31 + i, 99.1, 99.2, 98.95, 99.05, 1000))
    # the break: big-bodied bearish bar, 5x volume, closing well under the edge
    bars.append(_bar(DAY, 9, 37, 99.0, 99.02, 98.45, 98.5, 5000))
    for i in range(3):                                  # follow-through: closes stay below the break close
        bars.append(_bar(DAY, 9, 38 + i, 98.5, 98.55, 98.2, 98.4 - 0.05 * i, 1500))
    return bars


def test_gapped_through_level_is_terminal_by_default():
    tr = TriggerTracker(_trigger(), thresholds=Thresholds(), prev_close=100.4)
    for i, b in enumerate(_session()):
        tr.on_bar(b, i)
    assert tr.status == "gapped_through"


def test_gapped_through_level_becomes_a_continuation_break_when_asked():
    tr = TriggerTracker(_trigger(), thresholds=Thresholds(gap_through_continuation=True), prev_close=100.4)
    bars = _session()
    tr.on_bar(bars[0], 0)
    assert tr.status == "waiting"
    assert tr.direction == "short" and tr.kind == "breakdown"
    assert tr.stop == 100.0 and tr.entry == 98.8              # stop at the gapped level, entry on the opening low
    assert [t["price"] for t in tr.trigger["targets"]] == [97.6, 96.4, 95.2]   # 1R/2R/3R off a 1.2 risk
    assert tr.trigger["continuation"]["from"] == "gapped_through"
    for i, b in enumerate(bars[1:], start=1):
        tr.on_bar(b, i)
    assert tr.status == "fired", (tr.status, tr.events[-3:], tr.skipped)
    assert tr.fill_price is not None and tr.fill_price <= 98.8
    assert any(e["event"] == "gap_continuation_armed" for e in tr.events)


def test_reclaim_of_the_gapped_level_invalidates_the_continuation():
    tr = TriggerTracker(_trigger(), thresholds=Thresholds(gap_through_continuation=True), prev_close=100.4)
    bars = _session()[:3] + [_bar(DAY, 9, 33, 99.5, 100.3, 99.4, 100.2, 3000)]   # closes back above the level
    for i, b in enumerate(bars):
        tr.on_bar(b, i)
    assert tr.status == "invalidated"


def test_loose_continuation_fires_on_the_first_close_through_the_opening_extreme():
    t = Thresholds(gap_through_continuation=True, gap_continuation_confirm=False)
    tr = TriggerTracker(_trigger(), thresholds=t, prev_close=100.4)
    bars = _session()
    for i, b in enumerate(bars):
        tr.on_bar(b, i)
        if tr.status == "fired":
            break
    assert tr.status == "fired" and tr.fired_ts == bars[7].ts     # the 09:37 break bar itself, no follow-through wait
    assert tr.fill_price == 98.5 and tr.entry == 98.5
