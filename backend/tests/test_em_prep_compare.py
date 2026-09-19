"""prep-compare-v1 (integrated plan B "Required comparison"): the chronological shared book, identical-sample selections,
coverage counts and the no-leak rule. Acceptance row "Comparison". Pure - no database, no network, no model."""
import inspect
import json
import os

from zargar.tools import em_prep_compare as cmp

FX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "em_overnight_reviews_2026_09_18.json"), encoding="utf-8"))
_SRC = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "em_source_notes_2026_09_18.json"), encoding="utf-8"))
_AMD = next(v for k, v in _SRC["plans"].items() if k.startswith("17df157e"))           # the ingest plan whose k1 breakout failed R2 at 2.97
FX["AMD"] = {"plan": _AMD["plan"], "analysis": None}


def _f(sym, idx, held, r, run=None, trig="k1"):
    return {"symbol": sym, "runId": run or f"run-{sym}", "trigger": trig, "fillIndex": idx, "barsHeld": held, "r": r, "outcome": "x"}


def test_shared_capacity_is_applied_chronologically_not_summed_independently():
    cap = {**cmp.CAPACITY, "maxPositionPct": 50.0}                               # 2 slots
    fills = [_f("A", 5, 100, +2.0), _f("B", 6, 100, +1.0), _f("C", 7, 10, +5.0), _f("D", 120, 10, -1.0)]
    b = cmp.shared_book(fills, cap)
    assert b["capacity"]["slots"] == 2 and b["taken"] == 3 and b["refused"] == 1 and b["refusedWhy"] == {"no_free_slot": 1}
    assert b["sumR"] == 2.0 and b["independentSumR"] == 7.0, "the best trade (C) found no free slot - independent sums overstate"
    assert "PROXY-ONLY" in b["label"]


def test_the_daily_loss_halt_stops_new_entries_and_one_plan_holds_one_position():
    fills = [_f("A", 1, 5, -1.0), _f("B", 2, 5, -1.0), _f("C", 30, 5, +4.0), _f("A", 3, 5, +9.0, trig="k2")]
    b = cmp.shared_book(fills)
    assert b["capacity"]["haltAtR"] == -1.5 and b["haltedAtIndex"] == 7
    assert b["refusedWhy"] == {"plan_already_open": 1, "daily_loss_halt": 1} and b["sumR"] == -2.0 and b["worstDrawdownR"] == -2.0
    assert cmp.shared_book([{**_f("Z", None, 5, 3.0)}])["untimedExcluded"] == 1, "a fill without a time is excluded with a count, never assumed"


def test_selections_use_identical_samples_and_keep_model_rejected_plans():
    rows = [{"symbol": s, "runId": f"run-{s}", "scorable": True, "cohorts": {"C_exceptions": s == "META"}, "preopen": {},
             "replay": {"fills": [{"trigger": "k1", "fillIndex": 10, "barsHeld": 5, "r": 1.0, "outcome": "tp1"},
                                  {"trigger": "r2", "fillIndex": 20, "barsHeld": 5, "r": -1.0, "outcome": "stopped"}]}} for s in ("NVDA", "META", "AMD")]
    runs = {f"run-{s}": {"plan": FX[s]["plan"], "analysis": FX[s]["analysis"]} for s in ("NVDA", "META", "AMD")}
    sel = cmp.selections(rows, runs, {"preparationPolicy": "deterministic", "gradeFloor": "B", "conditionalReviewFix": "report"})
    assert sel["members"]["baseline_model"] == [] and sel["members"]["deterministic"] == ["run-NVDA", "run-META"] and sel["members"]["frozen_exception"] == ["run-META"]
    assert sel["decisions"]["run-AMD"]["deterministic"] == "refused", "AMD's 2.97R breakout stays a named baseline refusal"
    fills, cov = cmp.fills_of(rows, sel["members"]["deterministic"], sel["decisions"], restrict=True)
    assert cov == {"plans": 2, "scorable": 2, "unknown": 0, "replannedNotRejudged": 0}
    assert [f["trigger"] for f in fills] == ["k1", "k1"], "NVDA's grade-C r2 is not an eligible trigger under the floor - its fill is not counted"
    rows[0]["scorable"] = False
    _, cov2 = cmp.fills_of(rows, sel["members"]["deterministic"], sel["decisions"], restrict=True)
    assert cov2["unknown"] == 1 and cov2["scorable"] == 1, "missing paths are excluded WITH a coverage count"


def test_no_outcome_leaks_into_selection_and_costs_are_never_inferred_from_r():
    src = inspect.getsource(cmp.selections)
    assert "replay" not in src and "outcome" not in src and '"r"' not in src, "selection reads the plan and the saved review only - never what happened next"
    body = inspect.getsource(cmp)
    assert "never converted into dollars" in body and "paidModelCalls" in body and "anthropic.Anthropic" not in body and "messages.create" not in body


def test_runtime_rates_envelope_and_provenance_keys():
    """Owner re-check 2026-09-19: the settings envelope is unwrapped like the Tips cost tool; a bare card passes; junk is empty."""
    from zargar.tools.em_prep_compare import unwrap_rates
    card = {"_meta": {"verifiedAt": "2026-09-17"}, "claude-opus-5": {"in": 5.0, "out": 25.0}}
    assert unwrap_rates({"v": card}) == card and unwrap_rates(card) == card
    assert unwrap_rates(None) == {} and unwrap_rates({"v": 3}) == {"v": 3} and unwrap_rates([1]) == {}
    assert sorted(k for k in unwrap_rates({"v": card}) if not k.startswith("_")) == ["claude-opus-5"]
