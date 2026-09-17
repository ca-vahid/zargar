"""A venue label must not authenticate locally recentered prices. No DB/network."""
from types import SimpleNamespace as NS
from zargar.bus import Bus
from zargar.domain import Quote
from zargar.marketdata import QuoteCache
from zargar.brokers.sim import SimExecutor

NOW = 1789653894793
SYM = "MRNA260918C00165000"


def adjusted_quote():
    cache = QuoteCache(Bus())
    cache.set_overlay(SYM, bid=1.90, ask=2.00, bid_size=17, ask_size=1,
                      source="opra", source_ts=NOW-1000, anchor_last=1.95)
    cache.on_quote(Quote(symbol=SYM,last=0.70,bid=0,ask=0,ts=NOW))
    return cache.get(SYM)


def test_opra_bid_ask_are_not_recentered_on_another_last_trade():
    q = adjusted_quote()
    assert (q.bid,q.ask) == (1.90,2.00), "raw OPRA prices were changed to a synthetic 0.65/0.75 market"


def test_locally_adjusted_price_cannot_pass_as_opra_fill_evidence():
    q = adjusted_quote()
    if (q.bid,q.ask) != (1.90,2.00):
        assert SimExecutor().quote_rejection(NS(sec_type="OPT"),q,NOW) is not None, \
            "synthetic adjusted prices retained venue provenance and passed the fill qualifier"


def test_unchanged_qualified_opra_quote_remains_eligible():
    q=Quote(symbol=SYM,last=1.95,bid=1.90,ask=2.00,bid_size=17,ask_size=1,
            ts=NOW,source="opra",source_ts=NOW-1000)
    assert SimExecutor().quote_rejection(NS(sec_type="OPT"),q,NOW) is None
