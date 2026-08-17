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
