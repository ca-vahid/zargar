"""`exit-latency-v1`: measuring an exit's execution without inventing recoverable money.

The 2026-09-21 case: the IREN TP2 exit was decided while the contract's bid was 2.42 and filled 1.58 s
later at 2.37. Two contracts, ten dollars. Everything here exists to stop that ten dollars being
called a loss the desk could have avoided.
"""
import pytest

from zargar.technique.exit_latency import REACHABLE_AFTER_MS, VERSION, cost, realizable, stages

T0 = 1_790_015_522_000          # the real IREN decision, 18:32:02 UTC


def test_the_stages_measure_only_what_was_recorded():
    st = stages(signal_ts=T0, decided_ts=T0, pending_ts=T0 + 21, dispatch_ts=T0 + 21, fill_ts=T0 + 1584)
    assert st["gapsMs"]["decided->pending"] == 21, "the decision reached an order in 21 ms - not where the time went"
    assert st["gapsMs"]["dispatch->fill"] == 1563, "gaps are between consecutive stamps, so this is order to fill"
    assert st["totalMs"] == 1584 and st["version"] == VERSION


def test_a_stage_that_was_never_recorded_stays_none_rather_than_zero():
    st = stages(signal_ts=T0, fill_ts=T0 + 500)
    assert st["stamps"]["pending"] is None and st["stamps"]["dispatch"] is None
    assert st["gapsMs"] == {"signal->fill": 500}, "no stamp, no gap - never a fabricated zero"


def test_with_no_captured_quotes_the_answer_is_unknown_not_the_fill_price():
    rr = realizable([], side="SELL", qty=2, after_ms=T0)
    assert rr["status"] == "unknown" and rr["bestReachable"] is None
    assert "never journalled" in rr["why"]
    c = cost(2.37, rr, qty=2, multiplier=100)
    assert c["status"] == "unknown" and c["grossDifference"] is None


def test_a_price_seen_before_an_order_could_arrive_is_not_reachable():
    """2.42 at the instant of the signal is exactly the price that must NOT count."""
    obs = [{"ts": T0, "bid": 2.42, "bidSize": 50}, {"ts": T0 + 300, "bid": 2.41, "bidSize": 50}]
    rr = realizable(obs, side="SELL", qty=2, after_ms=T0)
    assert rr["status"] == "unknown", f"nothing stood {REACHABLE_AFTER_MS} ms after the signal"
    assert rr["eligibleObservations"] == 0


def test_a_price_that_still_stood_after_the_dispatch_delay_does_count():
    obs = [{"ts": T0, "bid": 2.42, "bidSize": 50},
           {"ts": T0 + 900, "bid": 2.40, "bidSize": 50},
           {"ts": T0 + 1200, "bid": 2.38, "bidSize": 50}]
    rr = realizable(obs, side="SELL", qty=2, after_ms=T0)
    assert rr["status"] == "measured" and rr["bestReachable"]["price"] == 2.40
    assert rr["depth"] == "covered"
    c = cost(2.37, rr, qty=2, multiplier=100)
    assert c["perUnit"] == 0.03 and c["grossDifference"] == 6.0
    assert "not recoverable money" in c["note"]


def test_the_best_price_in_the_window_is_never_the_answer():
    """A spike that existed for one observation before the delay must not set the reference."""
    obs = [{"ts": T0 + 100, "bid": 9.99, "bidSize": 999}, {"ts": T0 + 1000, "bid": 2.39, "bidSize": 999}]
    rr = realizable(obs, side="SELL", qty=2, after_ms=T0)
    assert rr["bestReachable"]["price"] == 2.39, "the spike was gone before an order could arrive"


def test_depth_that_cannot_cover_the_quantity_is_reported_not_assumed():
    obs = [{"ts": T0 + 1000, "bid": 2.40, "bidSize": 1}]
    rr = realizable(obs, side="SELL", qty=2, after_ms=T0)
    assert rr["status"] == "measured" and rr["bestReachableWithSize"] is None
    assert rr["depth"] == "insufficient"


def test_a_quote_without_a_size_leaves_depth_unknown_rather_than_covered():
    obs = [{"ts": T0 + 1000, "bid": 2.40}]
    rr = realizable(obs, side="SELL", qty=2, after_ms=T0)
    assert rr["depth"] == "unknown" and rr["observationsWithoutSize"] == 1
    assert "depth unknown" in rr["why"]


def test_a_buy_is_judged_at_the_ask_and_wants_the_lowest():
    obs = [{"ts": T0 + 1000, "ask": 2.50, "askSize": 10}, {"ts": T0 + 1200, "ask": 2.45, "askSize": 10}]
    rr = realizable(obs, side="BUY", qty=2, after_ms=T0)
    assert rr["bestReachable"]["price"] == 2.45


@pytest.mark.parametrize("bad", [None, 0, -1])
def test_an_unpriced_observation_is_skipped(bad):
    obs = [{"ts": T0 + 1000, "bid": bad, "bidSize": 10}]
    rr = realizable(obs, side="SELL", qty=2, after_ms=T0)
    assert rr["status"] == "unknown" and rr["pricedObservations"] == 0
