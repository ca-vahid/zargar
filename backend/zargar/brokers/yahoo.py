"""Yahoo Finance polling quote feed.

Stopgap real-market data source until the IBKR feed is available: near-realtime
(~1-2s delayed) quotes for the watched symbols, batched into one request per
poll. Unofficial endpoints — the feed fails closed: on persistent errors
`connected` goes false, quotes age out, and the RiskGate's quote_fresh check
blocks orders.

Yahoo's `.TO` / `.V` suffix convention matches zargar's natively.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Callable

import httpx

from ..domain import Quote, now_ms
from .base import QuoteFeed

log = logging.getLogger("zargar.yahoo")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")
QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
COOKIE_URL = "https://fc.yahoo.com"

# When Yahoo reports no bid/ask (off-hours), synthesize a spread around last so
# the SimExecutor (which needs bid/ask > 0) keeps filling sim portfolios
# against real prices.
SYNTH_SPREAD = 0.00025  # 2.5 bps each side


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
        self._crumb: str | None = None
        self._task: asyncio.Task | None = None
        self._last_ok = 0

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

    async def _ensure_crumb(self) -> None:
        if self._crumb is not None:
            return
        with contextlib.suppress(httpx.HTTPError):
            await self._http.get(COOKIE_URL)  # warms the session cookie jar
        resp = await self._http.get(CRUMB_URL)
        if resp.status_code == 200 and resp.text and "<" not in resp.text:
            self._crumb = resp.text.strip()
        else:
            self._crumb = ""  # some sessions work without one

    async def poll_once(self) -> None:
        """One batched fetch of all watched symbols."""
        if not self._symbols:
            return
        await self._ensure_crumb()
        params = {"symbols": ",".join(sorted(self._symbols))}
        if self._crumb:
            params["crumb"] = self._crumb
        resp = await self._http.get(QUOTE_URL, params=params)
        if resp.status_code in (401, 403):
            # crumb/cookie expired: refresh once, next poll retries
            self._crumb = None
            log.info("yahoo session expired (%s); refreshing crumb", resp.status_code)
            return
        resp.raise_for_status()
        payload = resp.json()
        rows = ((payload.get("quoteResponse") or {}).get("result")) or []
        for row in rows:
            quote = self._to_quote(row)
            if quote is not None:
                self._on_quote(quote)
        self._last_ok = now_ms()

    def _to_quote(self, row: dict) -> Quote | None:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            return None
        last = float(row.get("regularMarketPrice") or 0.0)
        bid = float(row.get("bid") or 0.0)
        ask = float(row.get("ask") or 0.0)
        if last <= 0 and bid <= 0 and ask <= 0:
            return None
        if (bid <= 0 or ask <= 0) and last > 0:
            bid = round(last * (1 - SYNTH_SPREAD), 4)
            ask = round(last * (1 + SYNTH_SPREAD), 4)
        return Quote(
            symbol=symbol,
            bid=bid,
            ask=ask,
            last=last if last > 0 else (bid + ask) / 2,
            bid_size=int(row.get("bidSize") or 0),
            ask_size=int(row.get("askSize") or 0),
            volume=int(row.get("regularMarketVolume") or 0),
            halted=False,
            ts=now_ms(),
        )
