"""Real-tracker regressions for 758ccfb8; no database, engine startup or model calls."""
import asyncio
from dataclasses import asdict, replace
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from zargar.domain import Bar
from zargar.marketstructure.tracker import TriggerTracker
from zargar.technique.arming import PlanArmer
from zargar.technique.entry_decision import evaluate_entry, policy_from_thresholds, snapshot_from_tracker
from zargar.technique.rulebook import Thresholds


def _ts(hour, minute):
    return int(datetime(2026, 9, 15, hour, minute, tzinfo=ZoneInfo("America/New_York")).timestamp() * 1000)


def _snapshot(tracker, bar):
    return snapshot_from_tracker(
        attempt_id="attempt", run_id="run", plan={"planFor": "2026-09-15", "builtFromSession": "2026-09-14"},
        plan_status="armed", trigger_id="trigger", tracker=tracker, signal_bar=asdict(bar),
        received_ts=bar.ts + 60_001, decided_ts=bar.ts + 60_001,
    )


def _breakout(candidate_hour, candidate_minute, targets, confirming_closes):
    trigger = {
        "id": "trigger", "kind": "breakout", "direction": "long",
        "entry": {"price": 100.0}, "stop": {"price": 99.0},
        "targets": [{"price": p} for p in targets],
    }
    tracker = TriggerTracker(trigger=trigger, thresholds=Thresholds(), gap_rules=False)
    candidate_ts = _ts(candidate_hour, candidate_minute)
    bars = [
        Bar(symbol="X", tf="1m", ts=candidate_ts - (6 - i) * 60_000,
            open=99.8, high=99.9, low=99.7, close=99.8, volume=1_000)
        for i in range(6)
    ]
    bars.append(Bar(symbol="X", tf="1m", ts=candidate_ts,
                    open=99.8, high=100.25, low=99.78, close=100.2, volume=2_000))
    bars.extend(
        Bar(symbol="X", tf="1m", ts=candidate_ts + (i + 1) * 60_000,
            open=c - .1, high=c + .1, low=c - .2, close=c, volume=1_000)
        for i, c in enumerate(confirming_closes)
    )
    for i, bar in enumerate(bars):
        tracker.on_bar(bar, i)
    assert tracker.status == "fired"
    assert tracker.events[-1]["confirmedAfter"] == tracker.thresholds.followthrough_bars
    return tracker, bars[-1]


def test_confirmed_break_keeps_tracker_candidate_window_semantics():
    tracker, bar = _breakout(10, 29, (102.0, 104.0, 108.0), (100.3, 100.4, 100.5))
    assert tracker.events[-2]["window"] == "prime_open"
    assert tracker.fired_window == "midday"
    decision = evaluate_entry(_snapshot(tracker, bar), policy_from_thresholds(tracker.thresholds))
    # The shared tracker checked eligibility at the candidate; the latency change
    # must not add a second confirmation-bar window gate.
    assert decision.verdict == "allow", decision.to_dict()


def test_saved_geometry_does_not_become_invalid_when_break_close_passes_tp1():
    tracker, bar = _breakout(9, 40, (101.0, 108.0, 112.0), (100.3, 100.4, 101.2))
    assert tracker.entry == 100.0 and tracker.fill_price == 101.2
    # Current-price R2 remains a downstream check; the existing small-position
    # TP2 policy still has more than 3R at this close.
    assert (108.0 - tracker.fill_price) / (tracker.fill_price - tracker.stop) > 3
    decision = evaluate_entry(_snapshot(tracker, bar), policy_from_thresholds(tracker.thresholds))
    assert decision.verdict == "allow", decision.to_dict()


def test_fire_snapshot_uses_the_rules_that_actually_fired_the_tracker():
    thresholds = Thresholds()
    tracker = TriggerTracker(
        trigger={"id": "trigger", "kind": "bounce", "direction": "long", "entry": {"price": 100.0},
                 "stop": {"price": 99.0}, "targets": [{"price": 101.0}, {"price": 102.0}]},
        thresholds=thresholds, gap_rules=False,
    )
    for i in range(7):
        price = 101.0 if i < 6 else 100.0
        bar = Bar(symbol="X", tf="1m", ts=_ts(9, 30) + i * 60_000,
                  open=price, high=price + .1, low=price - .1, close=price,
                  volume=1_000 if i < 6 else 700)
        tracker.on_bar(bar, i)
    assert tracker.status == "fired" and tracker.events[-1]["rel"] == .7
    runner = PlanArmer(SimpleNamespace(settings={}),
                       SimpleNamespace(thresholds=lambda: replace(thresholds, volume_floor_mult=.8)))
    ap = SimpleNamespace(run_id="run", plan={"planFor": "2026-09-15"}, status="armed")
    trade = SimpleNamespace(signal_bar=asdict(bar), timing={"receivedTs": bar.ts + 60_001})
    decision = asyncio.run(runner.fire_decision(ap, "trigger", tracker, trade, attempt_id="attempt"))
    volume = next(check for check in decision["checks"] if check["name"] == "volume")
    assert volume["facts"]["floor"] == tracker.thresholds.volume_floor_mult, decision
    assert decision["verdict"] == "allow", decision
