"""Lane A pure reviewer, feasibility classifier and evaluator selection (2026-09-18): order-free, no database."""
import datetime as dt

from zargar.marketstructure.market_calendar import trading_days
from zargar.techniques.options_cartel.data import DailyBar
from zargar.techniques.options_cartel.lane_a import (
    FeasibilityPolicy, LaneAParameters, ceiling_tests, effective_cap, feasibility_from_chain, lane_a_review,
)
from zargar.tools.cartel_lane_a_eval import choose_original, classify_analysis, old_planner_outcome

SESSIONS = trading_days(dt.date(2026, 6, 1), dt.date(2026, 9, 11))
AS_OF = int(dt.datetime(2026, 9, 12, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


def _history(closes, highs=None, lows=None):
    bars = []
    for i, (s, c) in enumerate(zip(SESSIONS[-len(closes):], closes)):
        h = highs[i] if highs else c + 1
        l = lows[i] if lows else c - 1
        c = min(c, h)
        l = min(l, c)
        bars.append(DailyBar(symbol="TEST", session=s, open=c, high=h, low=l, close=c, volume=1_000_000))
    return bars


def _analysis(trigger, invalidation, checks_pass=True, family="base"):
    return {"checks": [{"name": "Market/universe screen", "status": "pass" if checks_pass else "fail"},
                       {"name": "Daily base tightness", "status": "pass"}],
            "candidates": [{"setup": family, "trigger": trigger, "invalidation": invalidation, "contextPassed": checks_pass, "targets": []}]}


def test_ceiling_tests_count_sessions_within_tolerance_of_the_base_high():
    base = _history([100] * 10, highs=[100.5, 99.0, 100.4, 99.5, 98.0, 99.9, 100.0, 99.2, 100.3, 99.8])
    tests = ceiling_tests(base, 0.5)
    assert tests["ceiling"] == 100.5 and tests["touches"] == 4       # 100.5, 100.4, 100.0 (0.497%), 100.3


def test_lane_a_qualifies_a_repeatedly_tested_base_with_a_confirmed_pivot_and_records_the_inactive_experiment():
    closes = [110] * 50 + [100] * 10
    highs = [111] * 20 + [120] + [111] * 29 + [100.5, 99.0, 100.4, 99.5, 98.0, 99.9, 100.0, 99.2, 100.3, 99.8]
    lows = [109] * 50 + [96] * 10
    history = _history(closes, highs, lows)
    review = lane_a_review(_analysis(100.5, 96.0), history, as_of_ms=AS_OF, direction="long", market_direction="long",
                           parameters=LaneAParameters(experimental_min_planning_r=1.5))
    assert review["qualified"] and review["stage"] == "qualified"
    assert review["candidate"]["targets"][0] == 120.0 and review["candidate"]["targetSource"].startswith("Confirmed")
    assert abs(review["structuralR"] - (120 - 100.5) / (100.5 - 96)) < 1e-9
    assert review["experimental"] == {"minPlanningR": 1.5, "passes": True, "active": False}


def test_lane_a_names_the_first_failing_stage():
    closes = [110] * 50 + [100] * 10
    lows = [109] * 50 + [96] * 10
    one_touch = [111] * 50 + [100.5, 99.0, 99.4, 99.5, 98.0, 99.9, 99.0, 99.2, 99.3, 99.8]
    history = _history(closes, one_touch, lows)
    assert lane_a_review(_analysis(100.5, 96.0), history, as_of_ms=AS_OF, direction="short", market_direction="short")["stage"] == "direction"
    assert lane_a_review(_analysis(100.5, 96.0), history, as_of_ms=AS_OF, direction="long", market_direction="short")["stage"] == "direction"
    assert lane_a_review(_analysis(100.5, 96.0, checks_pass=False), history, as_of_ms=AS_OF, direction="long", market_direction="long")["stage"] == "context"
    assert lane_a_review(_analysis(100.5, 96.0, family="flag"), history, as_of_ms=AS_OF, direction="long", market_direction="long")["stage"] == "base_family"
    assert lane_a_review(_analysis(100.5, 96.0), history, as_of_ms=AS_OF, direction="long", market_direction="long")["stage"] == "ceiling_tests"
    flat = [100.5] * 50 + [100.5, 99.0, 100.4, 99.5, 98.0, 99.9, 100.0, 99.2, 100.3, 99.8]
    assert lane_a_review(_analysis(100.5, 96.0), _history(closes, flat, lows), as_of_ms=AS_OF, direction="long", market_direction="long")["stage"] == "confirmed_target"


def _row(occ, expiry, right, delta, bid, ask, oi):
    return {"occ": occ, "expiry": expiry, "option_type": right, "delta": delta, "bid": bid, "ask": ask, "open_interest": oi}


def test_feasibility_keeps_every_failure_and_reserves_single_cause_states_for_single_failures():
    policy = FeasibilityPolicy(max_ask=5.0)
    first = dt.date(2026, 9, 17)
    good = _row("X261016C00100000", "2026-10-16", "call", 0.5, 2.0, 2.2, 500)
    pricey = _row("X261016C00090000", "2026-10-16", "call", 0.7, 7.0, 7.4, 500)
    wide = _row("X261016C00105000", "2026-10-16", "call", 0.4, 1.0, 1.5, 500)
    thin = _row("X261016C00110000", "2026-10-16", "call", 0.3, 1.0, 1.1, 10)
    wide_thin_pricey = _row("X261016C00080000", "2026-10-16", "call", 0.8, 8.0, 12.0, 10)   # spread + OI + premium
    short_dte = _row("X260925C00100000", "2026-09-25", "call", 0.5, 2.0, 2.1, 500)
    put = _row("X261016P00100000", "2026-10-16", "put", -0.5, 2.0, 2.1, 500)
    kw = dict(direction="long", first_session=first, policy=policy, observed_at="2026-09-16")
    assert feasibility_from_chain([good, pricey], **kw)["state"] == "affordable"
    over = feasibility_from_chain([pricey], **kw)
    assert over["state"] == "over_budget" and over["lowestOtherwiseEligibleAsk"] == 7.4
    assert feasibility_from_chain([wide], **kw)["state"] == "spread_blocked"
    # the reviewer's case: spread + open interest + premium must NOT read as spread-only
    multi = feasibility_from_chain([wide_thin_pricey], **kw)
    assert multi["state"] == "filtered_other" and multi["failureSets"] == {"spread+open_interest+premium": 1}
    assert multi["spreadOnlyContracts"] == 0 and multi["lowestOtherwiseEligibleAsk"] is None
    other = feasibility_from_chain([thin, wide, pricey], **kw)
    assert other["state"] == "over_budget"      # a premium-only contract exists; the other failure sets are still reported
    assert other["failureSets"] == {"open_interest": 1, "spread": 1, "premium": 1}
    assert feasibility_from_chain([short_dte, put], **kw)["state"] == "no_chain"


def test_effective_cap_mirrors_preparation_and_names_missing_bounds():
    cap = effective_cap(5.0, 500.0, 10_000.0, 10.0)
    assert cap["maxAsk"] == 5.0 and cap["binding"] == "policy" and cap["bounds"]["budget"] == 5.0 and cap["bounds"]["equityRisk"] == 10.0 and cap["missing"] == []
    cap = effective_cap(5.0, 300.0, None, 10.0)
    assert cap["maxAsk"] == 3.0 and cap["binding"] == "budget" and cap["missing"] == ["equityRisk"]
    cap = effective_cap(5.0, 500.0, 2_000.0, 10.0)
    assert cap["maxAsk"] == 2.0 and cap["binding"] == "equityRisk"


def test_choose_original_takes_the_earliest_evaluated_run_with_a_known_market_read():
    runs = [{"id": "a", "market": "unknown", "evaluated": 3000, "rows": [1]},        # benchmark unknown: not original
            {"id": "b", "market": "mixed", "evaluated": 0, "rows": []},              # no evaluation: not original
            {"id": "c", "market": "mixed", "evaluated": 3080, "rows": [1]},          # original
            {"id": "d", "market": "long", "evaluated": 3081, "rows": [1]}]           # later run: lineage only
    assert choose_original(runs)["id"] == "c"
    assert choose_original(runs[:2]) is None


def test_classify_analysis_separates_direction_screen_and_context():
    screen_ok = {"gates": [{"label": "Market agrees with direction", "status": "fail"}, {"label": "Price above minimum", "status": "pass"}]}
    screen_bad = {"gates": [{"label": "Market agrees with direction", "status": "pass"}, {"label": "ADR above minimum", "status": "fail"}]}
    analysis_ok = {"checks": [{"name": "Market/universe screen", "status": "fail"}, {"name": "Daily base tightness", "status": "pass"}]}
    analysis_bad = {"checks": [{"name": "Daily base tightness", "status": "fail"}]}
    assert classify_analysis(analysis_ok, screen_ok, "long", "mixed") == ("direction", ["direction=long, market=mixed"])
    assert classify_analysis(analysis_ok, screen_bad, "long", "long") == ("screen", ["ADR above minimum"])
    assert classify_analysis(analysis_bad, screen_ok, "long", "long") == ("context", ["Daily base tightness"])
    assert classify_analysis(analysis_ok, screen_ok, "long", "long") == ("history", [])   # the market gate alone never blocks here


def test_old_planner_outcome_classes():
    assert old_planner_outcome("filtered", None, context_passed=True) == "old_planner_rejected"
    assert old_planner_outcome("filtered", None, context_passed=False) == "screen_or_context_rejected"
    assert old_planner_outcome("plan_blocked", None, context_passed=True) == "old_planner_blocked"
    assert old_planner_outcome("candidate", "armed", context_passed=True) == "old_planner_candidate:armed"
    assert old_planner_outcome("data_error", None, context_passed=False) == "unavailable_evidence"
    assert old_planner_outcome(None, None, context_passed=True) == "not_in_preparation_rows"
