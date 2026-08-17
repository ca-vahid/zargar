"""Fill-engine semantics: opposite-touch market fills, limit crossing, stops, OCA."""
import asyncio

from zargar.brokers.base import BrokerOrder, ExecReport
from zargar.brokers.sim import SimExecutor
from zargar.domain import OrderSide, OrderType, Quote, TimeInForce


def quote(symbol="AAPL", bid=99.98, ask=100.02, last=100.0):
    return Quote(symbol=symbol, bid=bid, ask=ask, last=last,
                 bid_size=500, ask_size=500)


def order(**kw):
    base = dict(id="o1", symbol="AAPL", sec_type="STK", side=OrderSide.BUY, qty=10,
                order_type=OrderType.MKT, tif=TimeInForce.DAY)
    base.update(kw)
    return BrokerOrder(**base)


class Collector:
    def __init__(self):
        self.reports: list[ExecReport] = []

    async def __call__(self, report: ExecReport):
        self.reports.append(report)

    def fills(self):
        return [r for r in self.reports if r.kind == "fill"]

    def cancelled(self):
        return [r for r in self.reports if r.kind == "cancelled"]


def make_executor(latency_ms=0, slippage_bps=0.0):
    ex = SimExecutor(latency_ms=latency_ms, slippage_bps=slippage_bps)
    collector = Collector()
    ex.on_report = collector
    return ex, collector


async def test_market_buy_fills_at_ask():
    ex, col = make_executor()
    await ex.submit(order())
    await ex.on_quote(quote())
    assert len(col.fills()) == 1
    assert col.fills()[0].fill_price == 100.02  # opposite touch
    assert col.fills()[0].fill_qty == 10


async def test_market_sell_fills_at_bid():
    ex, col = make_executor()
    await ex.submit(order(side=OrderSide.SELL))
    await ex.on_quote(quote())
    assert col.fills()[0].fill_price == 99.98


async def test_market_slippage_applied():
    ex, col = make_executor(slippage_bps=10.0)  # 0.1%
    await ex.submit(order())
    await ex.on_quote(quote())
    assert col.fills()[0].fill_price > 100.02


async def test_latency_delays_fill():
    ex, col = make_executor(latency_ms=150)
    await ex.submit(order())
    await ex.on_quote(quote())
    assert not col.fills()  # not yet eligible
    await asyncio.sleep(0.2)
    await ex.on_quote(quote())
    assert len(col.fills()) == 1


async def test_limit_buy_waits_for_ask():
    ex, col = make_executor()
    await ex.submit(order(order_type=OrderType.LMT, limit_price=99.50))
    await ex.on_quote(quote(bid=99.98, ask=100.02))
    assert not col.fills()  # ask above limit
    await ex.on_quote(quote(bid=99.40, ask=99.45, last=99.42))
    assert len(col.fills()) == 1
    assert col.fills()[0].fill_price <= 99.50


async def test_limit_sell_waits_for_bid():
    ex, col = make_executor()
    await ex.submit(order(side=OrderSide.SELL, order_type=OrderType.LMT, limit_price=100.50))
    await ex.on_quote(quote())
    assert not col.fills()
    await ex.on_quote(quote(bid=100.60, ask=100.70, last=100.65))
    assert col.fills()[0].fill_price >= 100.50


async def test_stop_sell_triggers_on_last():
    ex, col = make_executor()
    await ex.submit(order(side=OrderSide.SELL, order_type=OrderType.STP, stop_price=99.0))
    await ex.on_quote(quote(last=99.5))
    assert not col.fills()
    await ex.on_quote(quote(bid=98.90, ask=98.95, last=98.92))
    assert len(col.fills()) == 1
    assert col.fills()[0].fill_price == 98.90  # market fill at bid after trigger


async def test_halted_quote_never_fills():
    ex, col = make_executor()
    await ex.submit(order())
    q = quote()
    q.halted = True
    await ex.on_quote(q)
    assert not col.fills()


async def test_oca_sibling_cancelled_on_fill():
    ex, col = make_executor()
    await ex.submit(order(id="tp", side=OrderSide.SELL, order_type=OrderType.LMT,
                          limit_price=105.0, oca_group="g1"))
    await ex.submit(order(id="sl", side=OrderSide.SELL, order_type=OrderType.STP,
                          stop_price=95.0, oca_group="g1"))
    await ex.on_quote(quote(bid=105.2, ask=105.3, last=105.25))  # take-profit crosses
    fills = col.fills()
    assert len(fills) == 1 and fills[0].order_id == "tp"
    cancelled = col.cancelled()
    assert len(cancelled) == 1 and cancelled[0].order_id == "sl"
    assert ex.working_count == 0


async def test_cancel_removes_order():
    ex, col = make_executor()
    await ex.submit(order(order_type=OrderType.LMT, limit_price=90.0))
    await ex.cancel("o1")
    assert col.cancelled()[0].order_id == "o1"
    await ex.on_quote(quote(bid=89.0, ask=89.05, last=89.0))
    assert not col.fills()
