"""YahooQuoteFeed: batching, quote mapping, spread synthesis, crumb refresh."""
import httpx

from zargar.brokers.yahoo import YahooQuoteFeed


class StubYahoo:
    def __init__(self, rows=None, quote_status=200):
        self.rows = rows or []
        self.quote_status = quote_status
        self.requests: list[httpx.Request] = []
        self.crumb_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if "getcrumb" in request.url.path:
            self.crumb_calls += 1
            return httpx.Response(200, text="crumb123")
        if request.url.host == "fc.yahoo.com":
            return httpx.Response(200, text="")
        if "/v7/finance/quote" in request.url.path:
            if self.quote_status != 200:
                return httpx.Response(self.quote_status, text="denied")
            return httpx.Response(200, json={"quoteResponse": {"result": self.rows}})
        return httpx.Response(404)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def row(symbol="AAPL", price=230.0, bid=229.9, ask=230.1, volume=1000):
    return {"symbol": symbol, "regularMarketPrice": price, "bid": bid, "ask": ask,
            "bidSize": 5, "askSize": 7, "regularMarketVolume": volume}


async def test_batched_poll_publishes_quotes():
    stub = StubYahoo(rows=[row("AAPL"), row("SHOP.TO", price=98.5, bid=98.4, ask=98.6)])
    quotes = []
    feed = YahooQuoteFeed(on_quote=quotes.append, client=stub.client())
    await feed.watch("aapl")
    await feed.watch("SHOP.TO")
    await feed.poll_once()

    quote_reqs = [r for r in stub.requests if "/v7/finance/quote" in r.url.path]
    assert len(quote_reqs) == 1  # one batched request
    assert set(quote_reqs[0].url.params["symbols"].split(",")) == {"AAPL", "SHOP.TO"}
    assert quote_reqs[0].url.params["crumb"] == "crumb123"
    assert {q.symbol for q in quotes} == {"AAPL", "SHOP.TO"}
    aapl = next(q for q in quotes if q.symbol == "AAPL")
    assert aapl.bid == 229.9 and aapl.ask == 230.1 and aapl.last == 230.0
    assert feed.connected
    await feed.stop()


async def test_synthesizes_spread_when_no_bid_ask():
    stub = StubYahoo(rows=[row("AAPL", price=200.0, bid=0, ask=0)])
    quotes = []
    feed = YahooQuoteFeed(on_quote=quotes.append, client=stub.client())
    await feed.watch("AAPL")
    await feed.poll_once()
    q = quotes[0]
    assert 0 < q.bid < 200.0 < q.ask  # synthetic spread around last
    assert abs(q.ask - q.bid) / 200.0 < 0.001
    await feed.stop()


async def test_crumb_refresh_on_401():
    stub = StubYahoo(rows=[row("AAPL")], quote_status=401)
    quotes = []
    feed = YahooQuoteFeed(on_quote=quotes.append, client=stub.client())
    await feed.watch("AAPL")
    await feed.poll_once()          # 401 -> crumb invalidated, no quotes, no raise
    assert quotes == [] and not feed.connected
    stub.quote_status = 200
    await feed.poll_once()          # refetches crumb, then succeeds
    assert stub.crumb_calls == 2
    assert [q.symbol for q in quotes] == ["AAPL"]
    assert feed.connected
    await feed.stop()
