"""E17-01 (2026-09-17): a locally recentered price never keeps executable venue provenance.

The MRNA Sep-18 165C Practice fill at 0.75 (10:04:54 ET) happened because the OPRA overlay
(1.90/2.00, anchor 1.95) was recentered around a STALE `last` of 0.70 delivered by the
slower chart feed (the contract had printed 0.70 at 09:43 and 09:49 ET) and the result kept
source="opra" with a fresh source time, so the sim executor priced a fill off it. Pure, no
DB, no network."""
from types import SimpleNamespace as NS

from zargar.brokers.sim import SimExecutor
from zargar.bus import Bus
from zargar.domain import Quote
from zargar.marketdata import QuoteCache

NOW = 1789653894793
SYM = "MRNA260918C00165000"


def _cache_with_venue_overlay():
    cache = QuoteCache(Bus())
    cache.set_overlay(SYM, bid=1.90, ask=2.00, bid_size=17, ask_size=1,
                      source="opra", source_ts=NOW - 1000, anchor_last=1.95)
    return cache


def test_venue_overlay_is_never_recentered_by_a_slower_feeds_last():
    cache = _cache_with_venue_overlay()
    cache.on_quote(Quote(symbol=SYM, last=0.70, bid=0, ask=0, ts=NOW))
    q = cache.get(SYM)
    assert (q.bid, q.ask) == (1.90, 2.00) and q.source == "opra" and q.transform == ""
    assert q.last == 0.70                                    # the print is kept as a print, not as a market
    assert SimExecutor().quote_rejection(NS(sec_type="OPT"), q, NOW) is None   # the raw venue quote still prices fills


def test_chain_overlay_recentering_keeps_raw_prices_and_derived_provenance():
    """The 2026-09-02 GOOGL 0DTE lesson stands for the DELAYED chain: a live print past the
    band recentres the estimate - but the estimate is labelled derived, the raw chain prices
    ride along, and no fill can be priced off it."""
    cache = QuoteCache(Bus())
    cache.set_overlay(SYM, bid=0.12, ask=0.13, bid_size=0, ask_size=0,
                      source="chain", source_ts=NOW - 900_000, anchor_last=0.125)
    cache.on_quote(Quote(symbol=SYM, last=0.60, bid=0, ask=0, ts=NOW))
    q = cache.get(SYM)
    assert (q.bid, q.ask) == (0.595, 0.605)                  # display estimate, same width
    assert (q.raw_bid, q.raw_ask, q.raw_source) == (0.12, 0.13, "chain") and q.raw_source_ts == NOW - 900_000
    assert q.source == "derived:chain" and q.transform == "recenter-v1" and q.delayed is True
    reason = SimExecutor().quote_rejection(NS(sec_type="OPT"), q, NOW)
    assert reason and ("derived" in reason.lower() or "delayed" in reason.lower())
    # shares path: a derived estimate is refused too (the raw quote is the only executable one)
    assert SimExecutor(max_spread_pct=0.0).quote_rejection(NS(sec_type="STK"), q, NOW) is not None


def test_updating_an_existing_cached_quote_follows_the_same_rule():
    cache = QuoteCache(Bus())
    cache.on_quote(Quote(symbol=SYM, last=0.70, bid=0.68, ask=0.72, ts=NOW - 5000))
    # a venue overlay arriving AFTER a stale print must not be bent to that print
    cache.set_overlay(SYM, bid=1.90, ask=2.00, bid_size=17, ask_size=1,
                      source="opra", source_ts=NOW - 1000, anchor_last=1.95)
    q = cache.get(SYM)
    assert (q.bid, q.ask, q.source, q.transform) == (1.90, 2.00, "opra", "")


def test_sim_fill_evidence_carries_raw_and_transform_fields_when_derived():
    cache = QuoteCache(Bus())
    cache.set_overlay(SYM, bid=0.12, ask=0.13, source="chain", source_ts=NOW - 900_000, anchor_last=0.125)
    cache.on_quote(Quote(symbol=SYM, last=0.60, bid=0, ask=0, ts=NOW))
    ev = SimExecutor().quote_evidence(cache.get(SYM), NOW)
    assert ev["source"] == "derived:chain" and ev["transform"] == "recenter-v1"
    assert (ev["rawBid"], ev["rawAsk"], ev["rawSource"], ev["rawSourceAt"]) == (0.12, 0.13, "chain", NOW - 900_000)
    raw = SimExecutor().quote_evidence(Quote(symbol=SYM, bid=1.9, ask=2.0, last=1.95, source="opra", source_ts=NOW, ts=NOW), NOW)
    assert raw["transform"] == "" and raw["rawBid"] is None
