"""YahooQuoteFeed: chart-based polling, quote mapping, 429 cooldown."""
import httpx

from zargar.brokers.yahoo import YahooQuoteFeed


def chart_payload(closes, volumes=None):
    return {"chart": {"result": [{
        "timestamp": list(range(1_700_000_000, 1_700_000_000 + len(closes) * 60, 60)),
        "meta": {"regularMarketPrice": closes[-1] or 0},
        "indicators": {"quote": [{
            "close": closes,
            "volume": volumes or [100] * len(closes),
        }]},
    }]}}


class StubYahoo:
    def __init__(self):
        self.charts: dict[str, dict] = {}
        self.status = 200
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "fc.yahoo.com":
            return httpx.Response(200, text="")
        if "/v8/finance/chart/" in request.url.path:
            if self.status != 200:
                return httpx.Response(self.status, text="slow down")
            symbol = request.url.path.rsplit("/", 1)[-1]
            payload = self.charts.get(symbol)
            if payload is None:
                return httpx.Response(404)
            return httpx.Response(200, json=payload)
        return httpx.Response(404)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def chart_requests(self):
        return [r for r in self.requests if "/v8/finance/chart/" in r.url.path]


async def test_polls_every_symbol_and_publishes_live_bar_close():
    stub = StubYahoo()
    stub.charts["AAPL"] = chart_payload([310.0, 311.5, None])  # trailing null bar
    stub.charts["SHOP.TO"] = chart_payload([98.0, 98.5, 98.75])
    quotes = []
    feed = YahooQuoteFeed(on_quote=quotes.append, client=stub.client())
    await feed.watch("aapl")
    await feed.watch("SHOP.TO")
    await feed.poll_once()

    assert {r.url.path.rsplit("/", 1)[-1] for r in stub.chart_requests()} == {"AAPL", "SHOP.TO"}
    by_sym = {q.symbol: q for q in quotes}
    assert by_sym["AAPL"].last == 311.5          # newest non-null close
    assert by_sym["SHOP.TO"].last == 98.75
    assert 0 < by_sym["AAPL"].bid < 311.5 < by_sym["AAPL"].ask  # synthetic spread
    assert feed.connected
    await feed.stop()


async def test_rate_limit_triggers_cooldown():
    stub = StubYahoo()
    stub.charts["AAPL"] = chart_payload([100.0])
    stub.status = 429
    quotes = []
    feed = YahooQuoteFeed(on_quote=quotes.append, client=stub.client())
    await feed.watch("AAPL")
    await feed.poll_once()
    assert quotes == [] and not feed.connected
    n = len(stub.chart_requests())
    await feed.poll_once()  # inside the cooldown window: no new requests
    assert len(stub.chart_requests()) == n
    await feed.stop()


async def test_recovers_after_error_status():
    stub = StubYahoo()
    stub.charts["AAPL"] = chart_payload([100.0])
    stub.status = 500
    quotes = []
    feed = YahooQuoteFeed(on_quote=quotes.append, client=stub.client())
    await feed.watch("AAPL")
    await feed.poll_once()          # 500 -> no quotes, no cooldown
    assert quotes == []
    stub.status = 200
    await feed.poll_once()
    assert [q.symbol for q in quotes] == ["AAPL"]
    assert feed.connected
    await feed.stop()


# ---------------------------------------------------------------- symbol search

SEARCH_FIXTURE = {
    "quotes": [
        {"symbol": "SHOP.TO", "shortname": "Shopify Inc.", "exchDisp": "Toronto",
         "quoteType": "EQUITY"},
        {"symbol": "SHOP", "shortname": "Shopify Inc.", "exchDisp": "NYSE",
         "quoteType": "EQUITY"},
        {"symbol": "SHOP-FUT", "shortname": "some future", "quoteType": "FUTURE"},
        {"shortname": "no symbol row", "quoteType": "EQUITY"},
        {"symbol": "tqqq", "longname": "ProShares UltraPro QQQ",
         "exchange": "NGM", "quoteType": "ETF"},
    ],
    "news": [],
}


async def test_search_symbols_filters_and_normalizes():
    from zargar.brokers.yahoo import search_symbols

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert "/v1/finance/search" in request.url.path
        return httpx.Response(200, json=SEARCH_FIXTURE)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    results = await search_symbols("shop", client=client)
    await client.aclose()

    assert seen[0].url.params["q"] == "shop"
    # futures and symbol-less rows dropped; symbols upper-cased
    assert [r["symbol"] for r in results] == ["SHOP.TO", "SHOP", "TQQQ"]
    assert results[0] == {"symbol": "SHOP.TO", "name": "Shopify Inc.",
                          "exchange": "Toronto", "type": "EQUITY"}
    # longname/exchange fallbacks apply
    assert results[2]["name"] == "ProShares UltraPro QQQ"
    assert results[2]["exchange"] == "NGM"


# ------------------------------------------------------ day-change basis + day bars

async def test_quote_carries_previous_close_and_session():
    """The day-change basis must be the PRIOR session close (what brokers show),
    with regular-session price and session phase carried alongside."""
    from zargar.brokers.yahoo import _session

    stub = StubYahoo()
    payload = chart_payload([136.5, 136.9, 136.97])
    payload["chart"]["result"][0]["meta"].update({
        "regularMarketPrice": 136.97, "chartPreviousClose": 134.0,
        "regularMarketDayHigh": 137.35, "regularMarketDayLow": 131.22,
    })
    stub.charts["SPCX"] = payload
    got: list = []
    feed = YahooQuoteFeed(got.append, poll_seconds=1.0, client=stub.client())
    await feed.watch("SPCX")
    await feed.poll_once()
    q = got[0]
    assert q.prev_close == 134.0 and q.reg_price == 136.97
    assert q.day_high == 137.35 and q.day_low == 131.22
    assert round((q.last / q.prev_close - 1) * 100, 2) == 2.22  # Webull's number
    d = q.to_dict()
    assert d["prevClose"] == 134.0 and d["regPrice"] == 136.97

    periods = {"pre": {"start": 100, "end": 200}, "regular": {"start": 200, "end": 300},
               "post": {"start": 300, "end": 400}}
    assert _session(periods, now_s=150) == "pre"
    assert _session(periods, now_s=250) == "regular"
    assert _session(periods, now_s=350) == "post"
    assert _session(periods, now_s=450) == "closed"
    assert _session(None) == ""


async def test_fetch_day_bars_returns_real_session_bars():
    from zargar.brokers.yahoo import parse_day_bars

    payload = {"chart": {"result": [{
        "timestamp": [1_700_000_000, 1_700_000_060, 1_700_000_120],
        "meta": {},
        "indicators": {"quote": [{
            "open": [10.0, 10.2, None], "high": [10.3, 10.4, None],
            "low": [9.9, 10.1, None], "close": [10.2, 10.3, None],
            "volume": [100, 200, None],
        }]},
    }]}}
    bars = parse_day_bars("spcx", payload)
    assert [b.ts for b in bars] == [1_700_000_000_000, 1_700_000_060_000]  # null close skipped
    assert bars[0].symbol == "SPCX" and bars[0].tf == "1m"
    assert (bars[1].open, bars[1].high, bars[1].low, bars[1].close, bars[1].volume) == (
        10.2, 10.4, 10.1, 10.3, 200)

    stub = StubYahoo()
    stub.charts["SPCX"] = payload
    feed = YahooQuoteFeed(lambda q: None, client=stub.client())
    got = await feed.fetch_day_bars("SPCX")
    assert len(got) == 2
    req = stub.chart_requests()[-1]
    assert req.url.params["range"] == "1d" and req.url.params["includePrePost"] == "false"


async def test_fetch_bars_maps_range_and_interval():
    from zargar.brokers.yahoo import RANGE_TFS
    import pytest as _pytest

    stub = StubYahoo()
    stub.charts["AAPL"] = chart_payload([1.0, 2.0])
    feed = YahooQuoteFeed(lambda q: None, client=stub.client())
    bars = await feed.fetch_bars("AAPL", tf="1h", range_="3mo")
    assert len(bars) == 2 and bars[0].tf == "1h"
    req = stub.chart_requests()[-1]
    assert req.url.params["interval"] == "60m"   # Yahoo spells 1h as 60m
    assert req.url.params["range"] == "3mo"
    assert req.url.params["includePrePost"] == "false"
    with _pytest.raises(ValueError):
        await feed.fetch_bars("AAPL", tf="1m", range_="1y")  # Yahoo has no 1m that far back
    assert "1m" not in RANGE_TFS["1y"]
