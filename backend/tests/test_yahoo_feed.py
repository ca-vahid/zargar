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
