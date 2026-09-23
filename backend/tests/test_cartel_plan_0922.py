"""2026-09-22 improvement plan: P2 dry-up rule variant, P3 arm-quality gate, P5 gap-open retest,
P6 research panels under a 5m pilot, P7 receipt-time freshness for the lab's underlying quote.
Every price and volume below is SYNTHETIC; the shapes follow the recorded cases named per test."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from zargar.brokers.alpaca import AlpacaQuoteFeed
from zargar.domain import Bar
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy, automatic_review
from zargar.techniques.options_cartel.entry import read_entry
from zargar.techniques.options_cartel.lab_market_quotes import underlying_snapshot
from zargar.techniques.options_cartel.plans import EntryPolicy
from zargar.techniques.options_cartel.setups import SetupParameters

from .test_options_cartel_entry import MIN, OPEN, plan
from .test_options_cartel_prepare import input_data
from .test_options_cartel_setups import histories, read


# ---- P2: dry-up rule --------------------------------------------------------------------------

def dry_up(ratio, rule):
    bars, index = histories()
    prior = [b.model_copy(update={"volume": 3_000_000}) for b in bars[-20:-10]]
    base = [b.model_copy(update={"volume": int(3_000_000*ratio)}) for b in bars[-10:]]
    result = read([*bars[:-20], *prior, *base], index, parameters=SetupParameters(dry_up_rule=rule))
    return next(c for c in result["checks"] if c["name"] == "Volume dries up in consolidation")


def test_ntap_like_0_916_contraction_passes_only_the_non_increasing_rule():
    legacy = dry_up(.916, "ratio_v1")
    assert legacy["status"] == "fail" and legacy["rule"] == "ratio_v1" and legacy["threshold"] == .8
    literal = dry_up(.916, "non_increasing_v1")
    assert literal["status"] == "pass" and literal["rule"] == "non_increasing_v1" and literal["threshold"] == 1.0
    assert dry_up(1.05, "non_increasing_v1")["status"] == "fail"   # rising volume is never a dry-up
    assert SetupParameters().dry_up_rule == "ratio_v1"             # saved policies keep the legacy rule


# ---- P3: arm-quality gate -----------------------------------------------------------------------

def test_arm_gate_refuses_a_plan_whose_first_target_is_too_close_and_is_off_by_default():
    candidate = {"setup": "base", "trigger": 150., "invalidation": 140., "targets": [152.], "contextPassed": True}
    loose = PreparationPolicy(min_target_distance_pct=0)
    reviewed = automatic_review(input_data(), {"candidates": [candidate]}, loose)
    assert reviewed is not None and reviewed.reviewed_targets[0] == 152.     # 0.2R: armed under the legacy default
    gated = PreparationPolicy(min_target_distance_pct=0, min_arm_target_r=.5)
    assert automatic_review(input_data(), {"candidates": [candidate]}, gated) is None
    roomy = {**candidate, "targets": [160.]}
    assert automatic_review(input_data(), {"candidates": [roomy]}, gated).reviewed_targets[0] == 160.   # 1.0R passes
    assert PreparationPolicy().min_arm_target_r == 0


# ---- P5: gap-open retest (BBY 2026-09-22 shape: opened just above the trigger and held) ----------

def gap_tape(volume=400, low=48.82):
    """First 5m bucket opens above the 48.80 trigger, dips back to it and closes at its high."""
    bars = []
    for i in range(5):
        close = 48.95 if i == 4 else 48.86
        bars.append(Bar("HOOD", "1m", OPEN+i*MIN, 48.85, max(close, 48.87), low, close, volume, source="exchange"))
    return bars


def test_breakout_mode_never_enters_a_gap_and_hold_session():
    p = plan(entry=EntryPolicy(timeframe_minutes=5))
    assert read_entry(p, gap_tape(), OPEN+5*MIN)["signal"] is None


def test_gap_retest_variant_confirms_a_completed_retest_candle_with_unchanged_rules():
    p = plan(entry=EntryPolicy(timeframe_minutes=5, gap_policy="retest_v1"))
    result = read_entry(p, gap_tape(), OPEN+5*MIN)
    assert result["signal"] and result["signal"]["at"] == OPEN+5*MIN and result["signal"]["volumeRatio"] == 2.0
    assert any(d["decision"] == "gap_observed" for d in result["trace"])
    thin = read_entry(p, gap_tape(volume=200), OPEN+5*MIN)       # 1.0x volume: still refused
    assert thin["signal"] is None and any(d["decision"] == "watch_only" for d in thin["trace"])
    # Never came back within the 0.25% retest tolerance (48.92): no retest, no entry.
    far = [replace(b, low=48.95, open=48.96, high=49.0, close=48.98) for b in gap_tape()]
    assert read_entry(p, far, OPEN+5*MIN)["signal"] is None


# ---- P7: lab underlying quote judged on receipt time ------------------------------------------------

def lab_feed(state):
    feed = object.__new__(AlpacaQuoteFeed); feed._feed = "sip"; feed._state = {"TEST": state}
    return SimpleNamespace(feed=feed)


def test_a_print_stamped_ahead_of_the_host_clock_is_fresh_when_just_received():
    at = 1_000_000
    engine = lab_feed({"last": 10., "last_ts": at+9_000, "last_received_ts": at-500, "bid": 9.99, "ask": 10.01,
                       "quote_ts": at+9_000, "quote_received_ts": at-500, "bid_size": 2, "ask_size": 3})
    result = underlying_snapshot(engine, "TEST", lambda: at)
    assert result["status"] == "observed" and result["price"] == 10. and result["venueAheadOfReceiptMs"] == 9_500
    stale = lab_feed({"last": 10., "last_ts": at-20_000, "last_received_ts": at-20_000})
    assert underlying_snapshot(stale, "TEST", lambda: at)["status"] == "unavailable"
    implausible = lab_feed({"last": 10., "last_ts": at+60_000, "last_received_ts": at-500})
    assert underlying_snapshot(implausible, "TEST", lambda: at)["status"] == "unavailable"   # a genuinely future print
    legacy = lab_feed({"last": 10., "last_ts": at-5_000})   # no receipt stamp: original rule
    assert underlying_snapshot(legacy, "TEST", lambda: at)["status"] == "observed"


def test_feed_records_receipt_time_beside_venue_time():
    feed = AlpacaQuoteFeed.__new__(AlpacaQuoteFeed)
    feed._feed = "sip"; feed._state = {}; feed._emit = lambda *a: None
    feed.handle({"T": "q", "S": "TEST", "bp": 9.99, "ap": 10.01, "bs": 1, "as": 1, "t": "2026-09-22T14:00:00Z"})
    snap = feed.venue_snapshot("TEST")
    assert snap["quote_ts"] > 0 and snap["quote_received_ts"] > 0
