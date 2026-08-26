"""Bar aggregation from quotes and timeframe resampling."""
from zargar.bus import Bus
from zargar.domain import Quote
from zargar.marketdata import MINUTE_MS, BarAggregator


def q(symbol, last, ts, volume=0):
    return Quote(symbol=symbol, last=last, bid=last - 0.01, ask=last + 0.01,
                 volume=volume, ts=ts)


def test_forming_bar_tracks_ohlc():
    agg = BarAggregator(Bus())
    t0 = 1_700_000_040_000 - (1_700_000_040_000 % MINUTE_MS)
    agg.on_quote(q("AAPL", 100.0, t0 + 1000, volume=10))
    agg.on_quote(q("AAPL", 101.5, t0 + 5000, volume=25))
    agg.on_quote(q("AAPL", 99.5, t0 + 9000, volume=40))
    bars = agg.bars("AAPL")
    assert len(bars) == 1
    bar = bars[0]
    assert bar.open == 100.0 and bar.high == 101.5 and bar.low == 99.5 and bar.close == 99.5
    assert bar.volume == 30  # deltas: 15 + 15 (first quote seeds the counter)


def test_minute_rollover_closes_bar():
    bus = Bus()
    closed = []
    queue, unsub = bus.subscribe("bars")
    agg = BarAggregator(bus)
    t0 = 1_700_000_040_000 - (1_700_000_040_000 % MINUTE_MS)
    agg.on_quote(q("AAPL", 100.0, t0 + 1000))
    agg.on_quote(q("AAPL", 101.0, t0 + MINUTE_MS + 1000))  # next minute
    while not queue.empty():
        closed.append(queue.get_nowait())
    unsub()
    assert len(closed) == 1
    assert closed[0]["bar"].close == 100.0
    bars = agg.bars("AAPL")
    assert len(bars) == 2  # closed + forming


def test_resample_5m():
    agg = BarAggregator(Bus())
    t0 = 1_700_000_000_000 - (1_700_000_000_000 % (5 * MINUTE_MS))
    prices = [100.0, 102.0, 98.0, 99.0, 101.0]
    for i, price in enumerate(prices):
        agg.on_quote(q("AAPL", price, t0 + i * MINUTE_MS + 500))
    bars5 = agg.bars("AAPL", tf="5m")
    assert len(bars5) == 1
    bar = bars5[0]
    assert bar.open == 100.0
    assert bar.high == 102.0
    assert bar.low == 98.0
    assert bar.close == 101.0


def test_exchange_bar_replaces_the_held_sampled_bar():
    """A7 (2026-08-26) — for a symbol that delivers exchange bars, a closed quote-sampled
    bar is HELD briefly so the exchange bar for that minute is what consumers see;
    without one the sampled bar is flushed after the hold; an exchange bar that arrives
    while the minute is still forming is used on the roll. One bar per minute, always."""
    import asyncio
    from zargar.domain import Bar

    def drain(queue):
        out = []
        while not queue.empty():
            out.append(queue.get_nowait())
        return out

    async def run():
        bus = Bus()
        queue, unsub = bus.subscribe("bars")
        agg = BarAggregator(bus)
        agg.configure(hold_seconds=lambda: 0.15, expects_exchange=lambda s: True)
        t0 = 1_700_000_040_000 - (1_700_000_040_000 % MINUTE_MS)
        agg.on_quote(q("AAPL", 100.0, t0 + 1000, volume=10))
        agg.on_quote(q("AAPL", 101.0, t0 + MINUTE_MS + 1000, volume=20))       # minute 0 closes -> held
        assert queue.empty()
        agg.ingest_exchange_bar(Bar(symbol="AAPL", tf="1m", ts=t0, open=100.0, high=100.4, low=99.8,
                                    close=100.2, volume=5000))
        msgs = drain(queue)
        assert len(msgs) == 1 and msgs[0].get("source") == "exchange" and msgs[0]["bar"].volume == 5000
        await asyncio.sleep(0.25)
        assert queue.empty()                                                  # the timer did not double-publish
        assert agg.bars("AAPL")[0].volume == 5000
        # no exchange bar for minute 1 -> the sampled bar is flushed after the hold
        agg.on_quote(q("AAPL", 102.0, t0 + 2 * MINUTE_MS + 1000, volume=30))
        assert queue.empty()
        await asyncio.sleep(0.25)
        msgs = drain(queue)
        assert len(msgs) == 1 and "source" not in msgs[0] and msgs[0]["bar"].close == 101.0
        # exchange bar for the FORMING minute 2 arrives early -> used on the roll, published at once
        agg.ingest_exchange_bar(Bar(symbol="AAPL", tf="1m", ts=t0 + 2 * MINUTE_MS, open=102.0, high=102.5,
                                    low=101.9, close=102.3, volume=7000))
        assert queue.empty()
        agg.on_quote(q("AAPL", 103.0, t0 + 3 * MINUTE_MS + 1000, volume=40))
        msgs = drain(queue)
        assert len(msgs) == 1 and msgs[0].get("source") == "exchange" and msgs[0]["bar"].close == 102.3
        unsub()

    asyncio.run(run())
