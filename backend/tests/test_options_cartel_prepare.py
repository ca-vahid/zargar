"""Composition test: screen -> measured setup -> reviewed plan -> causal signal."""
from dataclasses import replace

import pytest

from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.entry import read_entry
from zargar.techniques.options_cartel.plans import CartelPlan, EntryPolicy
from zargar.techniques.options_cartel.prepare import build_volume_baseline, prepare_plan
from zargar.techniques.options_cartel.rules import CartelRules
from zargar.techniques.options_cartel.screen import ListingFacts
from zargar.techniques.options_cartel.setups import SetupParameters

from .test_options_cartel_setups import histories


def input_data():
    bars, benchmark = histories()
    index = [b.model_copy(update={"open": 100+i*.01, "close": 100+i*.01,
                                  "high": 101+i*.01, "low": 99+i*.01}) for i, b in enumerate(benchmark)]
    at = bars[-1].closes_at
    minutes = []
    for day in bars[-5:]:
        opens, _ = session_bounds(day.session.isoformat())
        minutes += [Bar("TEST", "1m", opens+i*60_000, 145, 146, 144, 145, 100) for i in range(5)]
    return {"plan_id": "reviewed-test", "history": bars, "indices": {"SPY": index, "QQQ": [
        b.model_copy(update={"symbol": "QQQ"}) for b in index]},
            "facts": ListingFacts(symbol="TEST", observed_at=at, source="fixture", market_cap=1e9),
            "rules": CartelRules.for_profile("june_2026", min_adr_pct=2), "parameters": SetupParameters(),
            "entry_policy": EntryPolicy(timeframe_minutes=5), "minute_history": minutes, "as_of_ms": at,
            "direction": "long", "setup": "base", "horizon_sessions": 3, "reviewed_targets": (170.,),
            "review_note": "Reviewed synthetic base, not a historical performance claim.", "target_source": "fixture"}


def test_reviewed_plan_can_drive_the_same_entry_kernel_after_json_roundtrip():
    result = prepare_plan(**input_data())
    p = CartelPlan.model_validate(result["plan"]["plan"])
    assert p.trigger == 147 and p.invalidation == 143
    assert p.volume_baseline == {0: 500.}
    assert result["review"]["targetsOverridden"] and not result["warnings"]
    opens, _ = session_bounds(p.first_session.isoformat())
    tape = [Bar("TEST", "1m", opens+i*60_000, 146.5, 147.3, 146.5, 147.2, 200) for i in range(5)]
    signal = read_entry(p, tape, opens+5*60_000)["signal"]
    assert signal and signal["stop"] == 146.5 and signal["targets"] == [170.]


def test_reviewed_ascending_triangle_preserves_geometry_and_entry_policy():
    args = input_data()
    for j in range(10):
        args['history'][70+j] = args['history'][70+j].model_copy(update={'high': 150., 'low': 140+j*.4})
    args['setup'] = 'ascending_triangle'
    result = prepare_plan(**args)
    plan = CartelPlan.model_validate_json(CartelPlan.model_validate(result['plan']['plan']).model_dump_json())
    assert plan.setup == 'ascending_triangle'
    assert (plan.trigger, plan.invalidation, plan.targets) == (150., 140., (170.,))
    assert plan.entry.timeframe_minutes == 5


def test_missing_targets_do_not_get_an_invented_r_multiple():
    args = input_data()
    args.update(reviewed_targets=None, target_source=None)
    with pytest.raises(ValueError, match="no confirmed historical targets"):
        prepare_plan(**args)


def test_target_override_requires_provenance_and_failed_context_cannot_be_overridden():
    args = input_data()
    args["target_source"] = None
    with pytest.raises(ValueError, match="source/rationale"):
        prepare_plan(**args)
    args = input_data()
    args["facts"] = args["facts"].model_copy(update={"market_cap": None})
    with pytest.raises(ValueError, match="context did not pass"):
        prepare_plan(**args)


def test_unrecognized_setup_and_empty_review_are_rejected():
    args = input_data()
    args["setup"] = "nonexistent"
    with pytest.raises(ValueError, match="not present"):
        prepare_plan(**args)
    args = input_data()
    args["review_note"] = "  "
    with pytest.raises(ValueError, match="review note"):
        prepare_plan(**args)


def test_baseline_uses_median_and_ignores_future_unfinished_sessions():
    args = input_data()
    bars = args["minute_history"]
    # A single high-volume day cannot dominate the median.
    bars = [replace(b, volume=10000) if i < 5 else b for i, b in enumerate(bars)]
    baseline = build_volume_baseline(bars, "TEST", 5, args["as_of_ms"])
    assert baseline["baselines"] == {0: 500.}
    earlier = build_volume_baseline(bars, "TEST", 5, args["as_of_ms"]-1)
    assert earlier["baselines"] == {}  # 4 complete days < 5 required samples


def test_missing_bucket_minute_is_not_zero_volume():
    args = input_data()
    baseline = build_volume_baseline(args["minute_history"][1:], "TEST", 5, args["as_of_ms"])
    assert baseline["baselines"] == {} and baseline["sampleCounts"][0] == 4


def test_duplicate_volume_conflict_is_not_silently_overwritten():
    args = input_data()
    bars = args["minute_history"]
    with pytest.raises(ValueError, match="conflicting"):
        build_volume_baseline(bars+[replace(bars[-1], volume=99)], "TEST", 5, args["as_of_ms"])
    assert build_volume_baseline(bars+[bars[-1]], "TEST", 5, args["as_of_ms"])["baselines"] == {0: 500.}


def test_empty_baseline_is_exposed_and_cannot_produce_a_signal():
    args = input_data()
    args["minute_history"] = []
    result = prepare_plan(**args)
    assert result["warnings"] and result["plan"]["plan"]["volume_baseline"] == {}
