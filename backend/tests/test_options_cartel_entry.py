"""Causal entry signals, source geometry and restart-stable replay identity."""
import datetime as dt
from dataclasses import replace

import pytest
from pydantic import ValidationError

from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.entry import read_entry
from zargar.techniques.options_cartel.plans import CartelPlan, EntryPolicy

DAY = dt.date(2026, 5, 5)
OPEN, CLOSE = session_bounds(DAY.isoformat())
MIN = 60_000


def plan(**changes):
    defaults = {"id": "source-geometry", "symbol": "HOOD", "direction": "long", "setup": "flag",
                "created_at": OPEN - MIN, "first_session": DAY, "last_session": DAY,
                "trigger": 48.80, "invalidation": 48.32, "targets": (55., 63.),
                "source_refs": ("S06",), "rationale": "Synthetic timing using S06 HOOD price geometry.",
                "entry": EntryPolicy(timeframe_minutes=5), "baseline_as_of": OPEN-MIN,
                "volume_baseline": {0: 1000., 1: 1000., 2: 1000., 3: 1000.}}
    defaults.update(changes)
    return CartelPlan(**defaults)


def tape():
    return [Bar("HOOD", "1m", OPEN + i * MIN, 48.65, 48.75, 48.4, 48.70, 500) for i in range(5)] + [
        Bar("HOOD", "1m", OPEN + i * MIN, 48.70, 48.94, 48.6, 48.92, 500) for i in range(5, 10)]


def test_source_prices_are_not_changed_by_entry_interpretation():
    p = plan(entry=EntryPolicy(timeframe_minutes=5, stop_mode="preplanned"))
    signal = read_entry(p, tape(), OPEN + 10 * MIN)["signal"]
    assert signal["referencePrice"] == 48.92 and signal["stop"] == 48.32
    assert signal["targets"] == [55., 63.]
    assert signal["risk"] == pytest.approx(.60)
    assert "fillPrice" not in signal


def test_only_completed_confirmation_buckets_can_trigger():
    assert read_entry(plan(), tape(), OPEN + 10 * MIN - 1)["signal"] is None
    assert read_entry(plan(), tape(), OPEN + 10 * MIN)["status"] == "triggered"


def test_stop_uses_only_session_extreme_available_at_trigger():
    p = plan()
    bars = tape()
    first = read_entry(p, bars, OPEN + 10 * MIN)
    assert first["signal"]["stop"] == 48.4
    future = Bar("HOOD", "1m", OPEN + 15 * MIN, 49., 50., 20., 25., 2000)
    assert read_entry(p, bars + [future], OPEN + 10 * MIN) == first
    # Even replaying the entire day must freeze the original entry-time stop.
    assert read_entry(p, bars + [future], CLOSE) == first


def test_breakout_candle_stop_is_a_distinct_snapshotted_choice():
    p = plan(entry=EntryPolicy(timeframe_minutes=5, stop_mode="breakout_bar"))
    result = read_entry(p, tape(), OPEN + 10 * MIN)
    assert result["signal"]["stop"] == 48.6
    assert p.snapshot()["plan"]["entry"]["stop_mode"] == "breakout_bar"


def test_entry_event_survives_serialization_and_duplicate_minute_delivery():
    p, bars = plan(), tape()
    expected = read_entry(p, bars, OPEN + 10 * MIN)
    restored = CartelPlan.model_validate(p.snapshot()["plan"])
    assert read_entry(restored, bars + [bars[-1]], OPEN + 10 * MIN) == expected


def test_missing_minutes_cannot_fabricate_session_low_or_confirmation():
    bars = tape()
    result = read_entry(plan(), bars[1:], OPEN + 10 * MIN)
    assert result["signal"] is None
    assert "missing" in " ".join(t["reason"].lower() for t in result["trace"])
    result = read_entry(plan(), bars[:-1], OPEN + 10 * MIN)
    assert result["status"] == "missing_data"


def test_arming_after_a_break_cannot_replay_an_old_entry():
    p = plan(created_at=OPEN + 7 * MIN)
    assert read_entry(p, tape(), OPEN + 10 * MIN)["signal"] is None
    assert read_entry(p, tape(), OPEN + MIN)["status"] == "not_created"


def test_observation_cutoff_keeps_invalidation_but_suppresses_missed_entry():
    cutoff = OPEN + 10 * MIN
    assert read_entry(plan(), tape(), cutoff, entry_after=cutoff)["signal"] is None
    invalidated = [replace(b, low=48.1, close=48.2) for b in tape()[:5]] + tape()[5:]
    result = read_entry(plan(), invalidated, cutoff, entry_after=cutoff)
    assert result["status"] == "invalidated"
    assert result["trace"][-1]["at"] == OPEN + 5 * MIN


def test_never_chase_and_already_reached_target_are_rejected():
    p = plan(entry=EntryPolicy(timeframe_minutes=5, max_chase_r=0.1))
    assert read_entry(p, tape(), OPEN + 10 * MIN)["signal"] is None
    p = plan(targets=(48.9,))
    assert read_entry(p, tape(), OPEN + 10 * MIN)["signal"] is None


def test_absent_or_low_volume_cannot_confirm_an_entry():
    for baseline in ({}, {0: 10000, 1: 10000}):
        result = read_entry(plan(volume_baseline=baseline), tape(), OPEN + 10 * MIN)
        assert result["signal"] is None
        assert result["trace"][-1]["decision"] == "watch_only"


def test_invalidated_plan_does_not_later_resurrect():
    bars = tape()
    bars[:5] = [replace(b, low=48.1, close=48.2) for b in bars[:5]]
    assert read_entry(plan(), bars, OPEN + 10 * MIN)["status"] == "invalidated"


def test_retest_waits_for_a_subsequent_candle_and_a_confirmed_break():
    p = plan(entry=EntryPolicy(timeframe_minutes=5, mode="retest"))
    bars = tape()
    assert read_entry(p, bars, OPEN + 10 * MIN)["signal"] is None
    bars += [Bar("HOOD", "1m", OPEN+i*MIN, 48.92, 48.94, 48.79, 48.92, 500) for i in range(10, 15)]
    result = read_entry(p, bars, OPEN + 15 * MIN)
    assert result["status"] == "triggered" and result["signal"]["at"] == OPEN + 15 * MIN
    no_break_volume = p.model_copy(update={"volume_baseline": {0: 1000, 1: 10000, 2: 1000}})
    assert read_entry(no_break_volume, bars, OPEN + 15 * MIN)["signal"] is None


def test_bearish_put_reference_is_directional_mirror():
    p = plan(direction="short", trigger=51.2, invalidation=51.68, targets=(45., 37.))
    bars = [replace(b, open=100-b.open, close=100-b.close, high=100-b.low, low=100-b.high) for b in tape()]
    signal = read_entry(p, bars, OPEN+10*MIN)["signal"]
    assert signal["direction"] == "short"
    assert signal["stop"] == 51.6
    assert signal["referencePrice"] == pytest.approx(51.08)


def test_invalid_geometry_and_future_baselines_fail_at_plan_boundary():
    for changes in ({"invalidation": 49}, {"targets": (55, 54)}, {"targets": ()},
                    {"baseline_as_of": OPEN}, {"volume_baseline": {100: 500}},
                    {"volume_baseline": {0: float("nan")}}):
        with pytest.raises(ValidationError):
            plan(**changes)


def test_conflicting_history_rejected_and_untriggered_horizon_expires():
    bars = tape()
    with pytest.raises(ValueError, match="conflicting"):
        read_entry(plan(), bars + [replace(bars[-1], volume=1)], OPEN+10*MIN)
    assert read_entry(plan(), bars[:5], CLOSE)["status"] == "expired"


def test_first_candle_gap_above_trigger_is_not_an_observed_cross():
    bars = [replace(b, open=49., high=49.1, low=48.9, close=49.) for b in tape()]
    assert read_entry(plan(), bars, OPEN + 10*MIN)["signal"] is None


def test_source_gap_retest_requires_explicit_policy_and_actual_level_retest():
    p = plan(entry=EntryPolicy(timeframe_minutes=5, mode="retest", allow_gap_retest=True))
    bars = [Bar("HOOD", "1m", OPEN+i*MIN, 49., 49., 48.7, 48.95, 500) for i in range(5)]
    result = read_entry(p, bars, OPEN+5*MIN)
    assert result["status"] == "triggered"
    assert result["trace"][0]["decision"] == "gap_observed"
    no_touch = [replace(b, low=48.99, high=49.2, close=49.2) for b in bars]
    assert read_entry(p, no_touch, OPEN+5*MIN)["signal"] is None
    legacy = p.model_copy(update={"entry": EntryPolicy(timeframe_minutes=5, mode="retest")})
    assert read_entry(legacy, bars, OPEN+5*MIN)["signal"] is None
    assert read_entry(p, bars, OPEN+5*MIN-1)["signal"] is None


def test_gap_retest_has_a_bearish_mirror_and_keeps_volume_confirmation():
    p = plan(direction="short", trigger=51.2, invalidation=51.68, targets=(45.,),
             entry=EntryPolicy(timeframe_minutes=5, mode="retest", allow_gap_retest=True))
    bars = [Bar("HOOD", "1m", OPEN+i*MIN, 51., 51.3, 51., 51.05, 500) for i in range(5)]
    assert read_entry(p, bars, OPEN+5*MIN)["status"] == "triggered"
    assert read_entry(p, [replace(b, volume=1) for b in bars], OPEN+5*MIN)["signal"] is None
