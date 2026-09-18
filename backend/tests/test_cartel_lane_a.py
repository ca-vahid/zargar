"""Lane A pure reviewer and feasibility classifier (2026-09-18): order-free, no database."""
import datetime as dt

from zargar.techniques.options_cartel.data import DailyBar
from zargar.techniques.options_cartel.lane_a import (
    FeasibilityPolicy, LaneAParameters, ceiling_tests, feasibility_from_chain, lane_a_review,
)
from zargar.marketstructure.market_calendar import trading_days

SESSIONS = trading_days(dt.date(2026, 6, 1), dt.date(2026, 9, 11))
AS_OF = int(dt.datetime(2026, 9, 12, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


def _history(closes, highs=None, lows=None):
    bars = []
    for i, (s, c) in enumerate(zip(SESSIONS[-len(closes):], closes)):
        h = highs[i] if highs else c + 1
        l = lows[i] if lows else c - 1
        c = min(c, h)          # keep the candle geometry valid when a test lowers the high below the nominal close
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
    # 60 sessions: a pivot high at 120 well above the base, then a 10-session base under 100.5
    closes = [110] * 50 + [100] * 10
    highs = [111] * 20 + [120] + [111] * 29 + [100.5, 99.0, 100.4, 99.5, 98.0, 99.9, 100.0, 99.2, 100.3, 99.8]
    lows = [109] * 50 + [96] * 10
    history = _history(closes, highs, lows)
    review = lane_a_review(_analysis(100.5, 96.0), history, as_of_ms=AS_OF, direction="long", market_direction="long",
                           parameters=LaneAParameters(experimental_min_planning_r=1.5))
    assert review["qualified"] and review["stage"] == "qualified"
    # the 111 plateau has no strict pivot (equal neighbours); the lone 120 high is the confirmed pivot
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
    # ceiling tested but no pivot above it: the Fibonacci fallback is off in Lane A
    flat = [100.5] * 50 + [100.5, 99.0, 100.4, 99.5, 98.0, 99.9, 100.0, 99.2, 100.3, 99.8]
    assert lane_a_review(_analysis(100.5, 96.0), _history(closes, flat, lows), as_of_ms=AS_OF, direction="long", market_direction="long")["stage"] == "confirmed_target"


def _row(occ, expiry, right, delta, bid, ask, oi):
    return {"occ": occ, "expiry": expiry, "option_type": right, "delta": delta, "bid": bid, "ask": ask, "open_interest": oi}


def test_feasibility_states_name_why_nothing_passed():
    policy = FeasibilityPolicy(max_ask=5.0)
    first = dt.date(2026, 9, 17)
    good = _row("X261016C00100000", "2026-10-16", "call", 0.5, 2.0, 2.2, 500)
    pricey = _row("X261016C00090000", "2026-10-16", "call", 0.7, 7.0, 7.4, 500)
    wide = _row("X261016C00105000", "2026-10-16", "call", 0.4, 1.0, 1.5, 500)
    thin = _row("X261016C00110000", "2026-10-16", "call", 0.3, 1.0, 1.1, 10)
    short_dte = _row("X260925C00100000", "2026-09-25", "call", 0.5, 2.0, 2.1, 500)
    put = _row("X261016P00100000", "2026-10-16", "put", -0.5, 2.0, 2.1, 500)
    assert feasibility_from_chain([good, pricey], direction="long", first_session=first, policy=policy, observed_at="2026-09-16")["state"] == "affordable"
    over = feasibility_from_chain([pricey], direction="long", first_session=first, policy=policy, observed_at="2026-09-16")
    assert over["state"] == "over_budget" and over["lowestOtherwiseEligibleAsk"] == 7.4
    assert feasibility_from_chain([wide], direction="long", first_session=first, policy=policy, observed_at="2026-09-16")["state"] == "spread_blocked"
    other = feasibility_from_chain([thin, wide, pricey], direction="long", first_session=first, policy=policy, observed_at="2026-09-16")
    assert other["state"] == "filtered_other" and other["firstFailingFilter"] == {"open_interest": 1, "spread": 1, "premium": 1}
    assert feasibility_from_chain([short_dte, put], direction="long", first_session=first, policy=policy, observed_at="2026-09-16")["state"] == "no_chain"
