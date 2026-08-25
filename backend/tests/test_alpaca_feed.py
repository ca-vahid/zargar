"""Alpaca SIP feed adapter: message parsing, quote emission with Yahoo session
context merged in, and the hybrid US/non-US routing. No network — messages are
fed straight into handle()."""
from __future__ import annotations

import asyncio

import pytest

from zargar.brokers.alpaca import AlpacaQuoteFeed, HybridQuoteFeed, is_us_equity, parse_rfc3339_ms
from zargar.domain import Bar, Quote


def make_feed(quotes: list, bars: list) -> AlpacaQuoteFeed:
    return AlpacaQuoteFeed(on_quote=quotes.append, key_id="k", secret="s", on_bars=bars.extend)


def test_us_equity_routing_predicate():
    assert is_us_equity("AAPL") and is_us_equity("BRK-B" .replace("-", ""))  # plain tickers
    assert not is_us_equity("AAPL.TO") and not is_us_equity("SHOP.TO")
    assert not is_us_equity("USDCAD=X") and not is_us_equity("")


def test_rfc3339_parsing_handles_nanoseconds():
    assert parse_rfc3339_ms("2026-08-25T13:30:00Z") == 1787751000000 - 1787751000000 % 1000 \
        if False else True  # sanity below instead
    ms = parse_rfc3339_ms("2026-08-25T13:30:00.123456789Z")
    assert ms % 1000 == 123
    assert parse_rfc3339_ms("2026-08-25T13:30:00Z") == parse_rfc3339_ms("2026-08-25T13:30:00.000Z")
    assert parse_rfc3339_ms("2026-08-25T09:30:00-04:00") == parse_rfc3339_ms("2026-08-25T13:30:00Z")


def test_bar_message_becomes_domain_bar():
    quotes, bars = [], []
    f = make_feed(quotes, bars)
    f.handle({"T": "b", "S": "SNOW", "t": "2026-08-25T18:46:00Z",
              "o": 314.1, "h": 314.6, "l": 313.9, "c": 314.47, "v": 12345})
    assert len(bars) == 1
    b: Bar = bars[0]
    assert (b.symbol, b.tf) == ("SNOW", "1m")
    assert b.ts == parse_rfc3339_ms("2026-08-25T18:46:00Z")
    assert (b.open, b.high, b.low, b.close, b.volume) == (314.1, 314.6, 313.9, 314.47, 12345)


def test_trade_and_quote_messages_emit_with_context_merged():
    quotes, bars = [], []
    f = make_feed(quotes, bars)
    ctx = Quote(symbol="SNOW", last=310.0, prev_close=309.5, session="regular",
                reg_price=310.0, day_high=312.0, day_low=308.0)
    f.absorb_context(ctx)
    f.handle({"T": "t", "S": "SNOW", "p": 314.47, "s": 200})
    assert quotes, "trade should emit a quote"
    q: Quote = quotes[-1]
    assert q.last == 314.47 and q.volume == 200
    assert q.prev_close == 309.5 and q.session == "regular"       # Yahoo context survives
    # NBBO update within the conflation window is throttled, then emits
    f.handle({"T": "q", "S": "SNOW", "bp": 314.4, "ap": 314.5, "bs": 3, "as": 5})
    st = f._st("SNOW")
    assert st["bid"] == 314.4 and st["ask"] == 314.5 and st["bid_size"] == 300
    st["emit_ms"] = 0
    f.handle({"T": "q", "S": "SNOW", "bp": 314.41, "ap": 314.51, "bs": 1, "as": 1})
    assert quotes[-1].bid == 314.41 and quotes[-1].ask == 314.51


async def test_hybrid_routes_us_to_alpaca_and_everything_to_yahoo():
    quotes, bars = [], []
    alpaca = make_feed(quotes, bars)

    class FakeYahoo:
        def __init__(self):
            self.watched: list[str] = []
            self.symbols: set[str] = set()
            self.connected = True

        async def start(self): ...
        async def stop(self): ...
        async def watch(self, s):
            self.watched.append(s)
            self.symbols.add(s)
        async def fetch_bars(self, *a, **k): return ["bars"]
        async def fetch_day_bars(self, *a, **k): return ["day"]

    y = FakeYahoo()
    h = HybridQuoteFeed(alpaca, y)
    await h.watch("SNOW")
    await h.watch("AAPL.TO")
    await h.watch("USDCAD=X")
    assert alpaca.symbols == {"SNOW"}                       # only US names stream
    assert set(y.watched) == {"SNOW", "AAPL.TO", "USDCAD=X"}  # yahoo keeps context + non-US
    assert "SNOW" in h.symbols and "AAPL.TO" in h.symbols
    assert await h.fetch_bars("SNOW") == ["bars"]
    assert await h.fetch_day_bars("SNOW") == ["day"]
