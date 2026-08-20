"""Yahoo Finance polling quote feed.

Stopgap real-market data source until the IBKR feed is available. The classic
v7 quote endpoint now serves unauthenticated callers HOURLY snapshots (prices
pinned to the top of the hour), so this feed polls the v8 chart endpoint per
symbol instead: its 1-minute bars are genuinely live (seconds old).

Unofficial endpoints — the feed fails closed: on persistent errors or a 429
cooldown, `connected` goes false, quotes age out, and the RiskGate's
quote_fresh check blocks orders.

Yahoo's `.TO` / `.V` suffix convention matches zargar's natively.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Callable

import httpx

from ..domain import Quote, now_ms
from .base import QuoteFeed

log = logging.getLogger("zargar.yahoo")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
COOKIE_URL = "https://fc.yahoo.com"

# Chart bars carry no bid/ask — synthesize a small spread around last so the
# SimExecutor (which needs bid/ask > 0) keeps filling practice orders against
# real prices.
SYNTH_SPREAD = 0.00025  # 2.5 bps each side

MAX_CONCURRENCY = 5
COOLDOWN_SECONDS = 90  # after a 429, stand down before hammering again


class YahooQuoteFeed(QuoteFeed):
    def __init__(
        self,
        on_quote: Callable[[Quote], None],
        poll_seconds: float = 3.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._on_quote = on_quote
        self._poll_seconds = poll_seconds
        self._http = client or httpx.AsyncClient(
            timeout=10, headers={"User-Agent": UA}, follow_redirects=True)
        self._symbols: set[str] = set()
        self._cookie_warm = False
        self._task: asyncio.Task | None = None
        self._last_ok = 0
        self._cooldown_until = 0.0

    @property
    def symbols(self) -> set[str]:
        return set(self._symbols)

    @property
    def connected(self) -> bool:
        return bool(self._last_ok) and now_ms() - self._last_ok < 60_000

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="yahoo-quote-poll")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._http.aclose()

    async def watch(self, symbol: str) -> None:
        self._symbols.add(symbol.upper())

    # ------------------------------------------------------------------ polling
    async def _loop(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception:  # pragma: no cover - defensive
                log.exception("yahoo poll failed")
            await asyncio.sleep(self._poll_seconds)

    async def _ensure_cookie(self) -> None:
        if self._cookie_warm:
            return
        with contextlib.suppress(httpx.HTTPError):
            await self._http.get(COOKIE_URL)
        self._cookie_warm = True

    async def poll_once(self) -> None:
        """One sweep: every watched symbol fetched from the chart endpoint."""
        if not self._symbols or time.monotonic() < self._cooldown_until:
            return
        await self._ensure_cookie()
        now_s = int(time.time())
        sem = asyncio.Semaphore(MAX_CONCURRENCY)
        rate_limited = False
        any_ok = False

        async def fetch(symbol: str) -> None:
            nonlocal rate_limited, any_ok
            async with sem:
                try:
                    resp = await self._http.get(
                        CHART_URL.format(symbol=symbol),
                        params={
                            "interval": "1m",
                            "period1": now_s - 30 * 60,
                            "period2": now_s,
                            "includePrePost": "true",
                        })
                except httpx.HTTPError:
                    return
            if resp.status_code == 429:
                rate_limited = True
                return
            if resp.status_code != 200:
                return
            try:
                quote = self._parse_chart(symbol, resp.json())
            except (ValueError, KeyError):
                return
            if quote is not None:
                any_ok = True
                self._on_quote(quote)

        await asyncio.gather(*(fetch(s) for s in sorted(self._symbols)))
        if rate_limited:
            self._cooldown_until = time.monotonic() + COOLDOWN_SECONDS
            log.warning("yahoo rate-limited (429) — cooling down %ss", COOLDOWN_SECONDS)
        if any_ok:
            self._last_ok = now_ms()

    def _parse_chart(self, symbol: str, data: dict) -> Quote | None:
        result = (((data or {}).get("chart") or {}).get("result") or [None])[0]
        if not result:
            return None
        stamps = result.get("timestamp") or []
        block = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        closes = block.get("close") or []
        volumes = block.get("volume") or []
        last = 0.0
        volume = 0
        for i in range(len(closes) - 1, -1, -1):
            if closes[i] is not None:
                last = float(closes[i])
                if i < len(volumes) and volumes[i] is not None:
                    volume = int(volumes[i])
                break
        if last <= 0:  # off-session fallback: meta close (may be stale)
            meta = result.get("meta") or {}
            last = float(meta.get("regularMarketPrice") or 0.0)
        if last <= 0:
            return None
        _ = stamps  # bar time informs freshness only via connected-age today
        return Quote(
            symbol=symbol.upper(),
            bid=round(last * (1 - SYNTH_SPREAD), 4),
            ask=round(last * (1 + SYNTH_SPREAD), 4),
            last=last,
            bid_size=0,
            ask_size=0,
            volume=volume,
            halted=False,
            ts=now_ms(),
        )
