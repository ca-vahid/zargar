"""W1.4 (2026-10-03): a simulated option limit fills at the venue NBBO observed after latency - never at a band a
slower feed's print bent, never below what the live NBBO allowed. In-memory only (no DB, network or engine).

The three Practice fills flagged by the 2026-10-02 Tips review (MRNA 165C 0.75 vs ask 2.01, AAOI 2.90 vs limit 3.30,
DAL 1.56 vs limit 1.76) all predate E17-01 (v0.8.11, 2026-09-17): the OPRA band was recentred on a stale chart
`last` while keeping `source="opra"`. These cases replay that pattern through QuoteCache -> SimExecutor. MRNA's band
is from its fill receipts; the DAL ask 1.76 is the other book's MKT fill one minute earlier (1.7604 = 1.76 + 2 bps);
the AAOI band is illustrative (no fill receipt existed on 2026-09-08)."""
from zargar.brokers.base import BrokerOrder
from zargar.brokers.sim import SimExecutor
from zargar.bus import Bus
from zargar.domain import OrderSide, OrderType, Quote
from zargar.marketdata import QuoteCache

NOW = 1789653894793


class _Clock:
    def __init__(self, t): self.t = t
    def __call__(self): return self.t


def _rig():
    clock = _Clock(NOW)
    ex = SimExecutor(latency_ms=120, option_sessions=False, clock=clock)
    reports = []

    async def capture(r): reports.append(r)
    ex.on_report = capture
    return ex, clock, reports


def _bent_quote(sym, bid, ask, stale_last, at):
    """The production path: OPRA overlay (fresh), then a chart-feed quote carrying only an old `last`."""
    cache = QuoteCache(Bus())
    cache.set_overlay(sym, bid=bid, ask=ask, bid_size=10, ask_size=10, source="opra", source_ts=at,
                      anchor_last=round((bid + ask) / 2, 2))
    cache.on_quote(Quote(symbol=sym, last=stale_last, bid=0, ask=0, ts=at))
    return cache.get(sym)


async def _limit(ex, clock, sym, side, limit):
    o = BrokerOrder(id=f"{sym}-{side.value}", symbol=sym, sec_type="OPT", side=side, qty=1,
                    order_type=OrderType.LMT, limit_price=limit)
    await ex.submit(o)
    clock.t += 500                                    # past the 120 ms latency
    return o


async def _fill_on(case, side=OrderSide.BUY):
    sym, bid, ask, stale_last, limit = case
    ex, clock, reports = _rig()
    await _limit(ex, clock, sym, side, limit)
    await ex.on_quote(_bent_quote(sym, bid, ask, stale_last, clock.t))
    fills = [r for r in reports if r.kind == "fill"]
    return (fills[0].fill_price if fills else None), ex.working_count


async def test_mrna_non_marketable_limit_rests_instead_of_buying_a_bent_band():
    # 1.90/2.00 OPRA band, 0.70 stale print, limit 1.95: the real market never offered 1.95 -> no fill (was 0.75)
    price, working = await _fill_on(("MRNA260918C00165000", 1.90, 2.00, 0.70, 1.95))
    assert price is None and working == 1


async def test_dal_marketable_limit_fills_at_the_live_ask_not_the_stale_print():
    price, _ = await _fill_on(("DAL261120C00090000", 1.75, 1.76, 1.555, 1.76))
    assert price == 1.76                              # was 1.56


async def test_aaoi_marketable_limit_fills_at_the_live_ask_capped_at_the_limit():
    price, _ = await _fill_on(("AAOI260911C00120000", 3.20, 3.30, 2.85, 3.30))
    assert price == 3.30                              # was 2.90


async def test_sell_mirror_fills_at_the_live_bid_never_a_print_bent_upward():
    price, _ = await _fill_on(("DAL261120C00090000", 1.75, 1.76, 2.40, 1.70), side=OrderSide.SELL)
    assert price == 1.75


async def test_a_quote_observed_before_latency_never_prices_an_option_fill():
    sym = "DAL261120C00090000"
    ex, clock, reports = _rig()
    decision = Quote(symbol=sym, bid=1.55, ask=1.56, last=1.56, bid_size=10, ask_size=10,
                     ts=clock.t, source="opra", source_ts=clock.t)          # the quote seen AT submission
    await _limit(ex, clock, sym, OrderSide.BUY, 1.76)
    await ex.on_quote(decision)                       # dequeued late: must not price the fill
    assert not [r for r in reports if r.kind == "fill"] and ex.working_count == 1
    after = Quote(symbol=sym, bid=1.75, ask=1.76, last=1.76, bid_size=10, ask_size=10,
                  ts=clock.t, source="opra", source_ts=clock.t)
    await ex.on_quote(after)
    fills = [r for r in reports if r.kind == "fill"]
    assert len(fills) == 1 and fills[0].fill_price == 1.76
    assert fills[0].evidence["receivedAt"] >= fills[0].evidence["eligibleAt"]
