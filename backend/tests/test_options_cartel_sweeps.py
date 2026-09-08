import pytest

from tests.test_options_cartel_entry import MIN, OPEN, plan, tape
from tests.test_options_cartel_replay import candle
from zargar.techniques.options_cartel.exits import ExitCampaign
from zargar.techniques.options_cartel.sweeps import SweepRequest, SweepVariant, evaluate_sweep


def snapshot():
    bars = tape() + [candle(10, 48.92, 55.), candle(11, 54., 48.92), candle(12, 48.9, 49.)]
    return {"runId": "case", "asOfMs": OPEN+13*MIN, "config": {
        "planSnapshot": plan().snapshot(), "exitCampaign": ExitCampaign.for_profile("may_2026", [55.]).model_dump(mode="json"),
        "minutes": [b.to_row() for b in bars], "daily": [], "request": {"quantity": 100, "slippage_bps": 0}}}


def test_variant_changes_entry_without_changing_saved_plan():
    saved = snapshot()
    before = saved["config"]["planSnapshot"]["plan"]["entry"].copy()
    result = evaluate_sweep([saved], [SweepVariant(name="tight", max_chase_r=.1)])
    assert result["rows"][0]["result"]["status"] == "closed"
    assert result["rows"][1]["result"]["fills"] == []
    assert result["summaries"][0]["closedScored"] == 1
    assert result["summaries"][1]["meanClosedR"] is None
    assert result["summaries"][1]["pairedClosed"] == 0
    assert result["summaries"][1]["pairedMeanDeltaR"] is None
    assert saved["config"]["planSnapshot"]["plan"]["entry"] == before
    assert result["placesOrders"] is False


def test_missing_data_never_enters_average_as_zero_return():
    saved = snapshot()
    saved["config"]["minutes"] = []
    result = evaluate_sweep([saved], [SweepVariant(name="same")])
    assert all(s["incomplete"] == 1 and s["meanClosedR"] is None for s in result["summaries"])


def test_duplicate_cases_and_reserved_names_rejected():
    with pytest.raises(ValueError):
        SweepRequest(replay_ids=["x", "x"], variants=[SweepVariant(name="test")])
    with pytest.raises(ValueError):
        SweepRequest(replay_ids=["x"], variants=[SweepVariant(name="baseline")])


def test_identical_variant_has_zero_paired_delta():
    result = evaluate_sweep([snapshot()], [SweepVariant(name="same")])
    assert result["summaries"][1]["pairedClosed"] == 1
    assert result["summaries"][1]["pairedMeanDeltaR"] == 0
