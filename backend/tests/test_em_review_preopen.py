"""Independent pre-open direction parity cases; no database or live services."""
import asyncio
from types import SimpleNamespace

import pytest

from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.marketstructure.tracker import TriggerTracker
from zargar.technique.arming import PlanArmer
from zargar.technique.rulebook import Thresholds


@pytest.mark.parametrize(
    "kind,direction,entry,stop,premarket,expected",
    [
        ("breakdown", "short", 99.0, 101.0, 100.0, "ok"),
        ("breakdown", "short", 99.0, 101.0, 98.5, "gapped_past"),
        ("breakout", "long", 101.0, 99.0, 100.0, "ok"),
        ("breakout", "long", 101.0, 99.0, 101.5, "gapped_past"),
        ("bounce", "long", 99.0, 97.0, 100.0, "ok"),
        ("reject", "short", 101.0, 103.0, 100.0, "ok"),
    ],
)
def test_preopen_gap_verdict_matches_the_direction_aware_open_tracker(
    kind, direction, entry, stop, premarket, expected
):
    thresholds = Thresholds(long_only=False)
    trigger = {
        "id": "review", "kind": kind, "direction": direction, "valid": True,
        "entry": {"price": entry, "basis": "on_break" if kind in ("breakout", "breakdown") else "at_level"},
        "stop": {"price": stop}, "targets": [{"price": entry + (3 if direction == "long" else -3)}],
    }
    pre_tracker = TriggerTracker(trigger, thresholds, prev_close=100.0)
    ap = SimpleNamespace(plan={"lastClose": 100.0}, trackers={"review": pre_tracker})
    armer = PlanArmer.__new__(PlanArmer)
    armer.engine = SimpleNamespace(settings={"technique.arm.preopen_replan": True})
    armer.technique = SimpleNamespace(thresholds=lambda: thresholds)
    verdict = asyncio.run(armer.preopen_check(ap, premarket))

    # Independent production path: the same level and opening price at the
    # actual session open. Values avoid the stop and magnitude-gap boundaries.
    opened = TriggerTracker(trigger, thresholds, prev_close=100.0)
    open_ms, _ = session_bounds("2026-09-14")
    status = opened.on_bar(Bar(symbol="X", tf="1m", ts=open_ms,
                               open=premarket, high=premarket, low=premarket,
                               close=premarket, volume=100), 0)
    open_verdict = status if status in ("gapped_past", "gapped_through", "gap_void") else "ok"
    assert open_verdict == expected
    assert verdict["rows"][0]["verdict"] == expected
    assert verdict["replan"] is (expected != "ok")
