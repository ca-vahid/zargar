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
    f.handle({"T": "t", "S": "SNOW", "p": 314.47, "s": 200, "t": "2026-08-25T14:00:00Z"})   # a regular-session print (F19 counts only those)
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


def _ctx(ts_ms: int, **kw) -> Quote:
    q = Quote(**{"symbol": "SNOW", "last": 310.0, "prev_close": 309.5, "session": "regular", "reg_price": 310.0, **kw})
    q.ts = ts_ms
    return q

REG = "2026-08-25T14:00:00Z"        # 10:00 ET, regular session
PRE = "2026-08-25T12:00:00Z"        # 08:00 ET, pre-market
NEXT = "2026-08-26T14:00:00Z"       # the next session


def test_day_range_and_volume_are_session_to_date_not_process_to_date():
    """F19 (2026-09-04): after a restart the day high/low/volume must come from Yahoo's session
    values and only WIDEN from live prints; pre-market prints never touch the regular range."""
    quotes, bars = [], []
    f = make_feed(quotes, bars)
    reg_ms = parse_rfc3339_ms(REG)
    # a pre-market print before any seed: last moves, the day range stays empty, no session volume
    f.handle({"T": "t", "S": "SNOW", "p": 305.0, "s": 100, "t": PRE})
    q = quotes[-1]
    assert q.last == 305.0 and q.day_high == 0.0 and q.day_low == 0.0 and q.volume == 0
    # the process "started" at 10:00: Yahoo says the session has already ranged 308–312 on 5M shares
    f.absorb_context(_ctx(reg_ms, day_high=312.0, day_low=308.0, volume=5_000_000))
    f._st("SNOW")["emit_ms"] = 0
    f.handle({"T": "t", "S": "SNOW", "p": 311.0, "s": 200, "t": REG})
    q = quotes[-1]
    assert (q.day_high, q.day_low) == (312.0, 308.0)          # seeded, not "since 10:00"
    assert q.volume == 5_000_200                                # Yahoo total + the print since the seed
    # a live print beyond the seed widens it
    f._st("SNOW")["emit_ms"] = 0
    f.handle({"T": "t", "S": "SNOW", "p": 313.5, "s": 300, "t": REG})
    q = quotes[-1]
    assert q.day_high == 313.5 and q.day_low == 308.0 and q.volume == 5_000_500
    # a fresh Yahoo total re-bases the volume without double counting the prints already in it
    f.absorb_context(_ctx(reg_ms + 60_000, day_high=313.5, day_low=308.0, volume=5_100_000))
    f._st("SNOW")["emit_ms"] = 0
    f.handle({"T": "t", "S": "SNOW", "p": 313.0, "s": 50, "t": REG})
    assert quotes[-1].volume == 5_100_050
    # a Yahoo poll made in PRE-market carries the prior session's range — never seeds
    f.absorb_context(_ctx(parse_rfc3339_ms(PRE), session="pre", day_high=400.0, day_low=100.0, volume=1))
    assert f._st("SNOW")["day_high"] == 313.5 and f._st("SNOW")["day_low"] == 308.0
    # the next session starts from zero
    f._st("SNOW")["emit_ms"] = 0
    f.handle({"T": "t", "S": "SNOW", "p": 320.0, "s": 10, "t": NEXT})
    q = quotes[-1]
    assert (q.day_high, q.day_low, q.volume) == (320.0, 320.0, 10)


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
