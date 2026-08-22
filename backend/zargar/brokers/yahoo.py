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

from ..domain import Bar, Quote, now_ms
from .base import QuoteFeed

log = logging.getLogger("zargar.yahoo")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
COOKIE_URL = "https://fc.yahoo.com"
SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"

# instrument kinds worth surfacing in the lookup UI
SEARCH_TYPES = {"EQUITY", "ETF", "INDEX", "CRYPTOCURRENCY"}


async def search_symbols(
    query: str, client: httpx.AsyncClient | None = None
) -> list[dict]:
    """Ticker/name lookup via Yahoo's search endpoint (no auth needed).

    Returns [{symbol, name, exchange, type}] filtered to tradable/watchable
    instrument kinds. Symbols come back in Yahoo's convention, which matches
    zargar's natively (`.TO`, `.V`, ...).
    """
    owns = client is None
    http = client or httpx.AsyncClient(
        timeout=8, headers={"User-Agent": UA}, follow_redirects=True)
    try:
        resp = await http.get(SEARCH_URL, params={
            "q": query, "quotesCount": 12, "newsCount": 0, "listsCount": 0})
        resp.raise_for_status()
        data = resp.json()
    finally:
        if owns:
            await http.aclose()
    out: list[dict] = []
    for row in data.get("quotes") or []:
        sym = row.get("symbol")
        kind = (row.get("quoteType") or "").upper()
        if not sym or kind not in SEARCH_TYPES:
            continue
        out.append({
            "symbol": str(sym).upper(),
            "name": row.get("shortname") or row.get("longname") or "",
            "exchange": row.get("exchDisp") or row.get("exchange") or "",
            "type": kind,
        })
    return out

# Chart bars carry no bid/ask — synthesize a small spread around last so the
# SimExecutor (which needs bid/ask > 0) keeps filling practice orders against
# real prices.
SYNTH_SPREAD = 0.00025  # 2.5 bps each side

MAX_CONCURRENCY = 5
COOLDOWN_SECONDS = 90  # after a 429, stand down before hammering again

# chart history: zargar timeframe -> Yahoo interval, and which timeframes Yahoo
# serves for each range (1m history only reaches ~7 days, 5m/15m ~60 days,
# 1h ~2 years, 1d forever)
YAHOO_INTERVAL = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "60m", "1d": "1d"}
RANGE_TFS: dict[str, tuple[str, ...]] = {
    "1d": ("1m", "5m", "15m", "1h"),
    "5d": ("1m", "5m", "15m", "1h", "1d"),
    "1mo": ("5m", "15m", "1h", "1d"),
    "3mo": ("1h", "1d"),
    "6mo": ("1h", "1d"),
    "1y": ("1h", "1d"),
    "5y": ("1d",),
}


class YahooQuoteFeed(QuoteFeed):
    def __init__(
        self,
        on_quote: Callable[[Quote], None],
        poll_seconds: float | Callable[[], float] = 3.0,
        client: httpx.AsyncClient | None = None,
        on_bars: Callable[[list], None] | None = None,
    ) -> None:
        self._on_quote = on_quote
        # optional: hand completed 1-minute exchange bars to a consumer (the bar
        # aggregator's ingest_exchange_bar) so live decisions use real OHLC/volume
        self._on_bars = on_bars
        # a callable re-reads the live setting every cycle — speed changes
        # apply without a restart
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
    def _interval(self) -> float:
        raw = self._poll_seconds() if callable(self._poll_seconds) else self._poll_seconds
        try:
            return max(1.0, float(raw))  # floor: don't hammer Yahoo below 1s
        except (TypeError, ValueError):
            return 3.0

    async def _loop(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception:  # pragma: no cover - defensive
                log.exception("yahoo poll failed")
            await asyncio.sleep(self._interval())

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
                payload = resp.json()
                quote = self._parse_chart(symbol, payload)
            except (ValueError, KeyError):
                return
            if quote is not None:
                any_ok = True
                self._on_quote(quote)
                if self._on_bars is not None:
                    try:
                        bars = self._parse_completed_bars(symbol, payload)
                        if bars:
                            self._on_bars(bars)
                    except (ValueError, KeyError, TypeError):
                        pass

        await asyncio.gather(*(fetch(s) for s in sorted(self._symbols)))
        if rate_limited:
            self._cooldown_until = time.monotonic() + COOLDOWN_SECONDS
            log.warning("yahoo rate-limited (429) — cooling down %ss", COOLDOWN_SECONDS)
        if any_ok:
            self._last_ok = now_ms()

    def _parse_completed_bars(self, symbol: str, data: dict) -> list:
        """Completed regular-session 1-minute bars from the chart response (the
        last, still-forming minute is excluded). Returns Bar objects."""
        from ..domain import Bar
        result = (((data or {}).get("chart") or {}).get("result") or [None])[0]
        if not result:
            return []
        ts = result.get("timestamp") or []
        block = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        o, h, l, c, v = (block.get(k) or [] for k in ("open", "high", "low", "close", "volume"))
        now_bucket = (now_ms() // 60_000) * 60_000
        out = []
        for i, t in enumerate(ts):
            if t is None or i >= len(c) or c[i] is None:
                continue
            bar_ms = int(t) * 1000
            if bar_ms >= now_bucket:                 # still-forming minute — skip
                continue
            op = o[i] if i < len(o) and o[i] is not None else c[i]
            hi = h[i] if i < len(h) and h[i] is not None else c[i]
            lo = l[i] if i < len(l) and l[i] is not None else c[i]
            vol = int(v[i]) if i < len(v) and v[i] is not None else 0
            out.append(Bar(symbol=symbol.upper(), tf="1m", ts=bar_ms,
                           open=float(op), high=float(hi), low=float(lo), close=float(c[i]), volume=vol))
        return out[-30:]

    def _parse_chart(self, symbol: str, data: dict) -> Quote | None:
        result = (((data or {}).get("chart") or {}).get("result") or [None])[0]
        if not result:
            return None
        meta = result.get("meta") or {}
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
        reg_price = _num(meta.get("regularMarketPrice"))
        if last <= 0:  # off-session fallback: meta close (may be stale)
            last = reg_price
        if last <= 0:
            return None
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
            # day-change basis is the PRIOR session close (what every broker
            # shows), never today's first bar
            prev_close=_num(meta.get("chartPreviousClose")) or _num(meta.get("previousClose")),
            reg_price=reg_price,
            day_high=_num(meta.get("regularMarketDayHigh")),
            day_low=_num(meta.get("regularMarketDayLow")),
            session=_session(meta.get("currentTradingPeriod")),
        )

    async def fetch_bars(self, symbol: str, tf: str = "1m", range_: str = "1d",
                         include_pre_post: bool = False) -> list[Bar]:
        """Chart history straight from Yahoo for a (timeframe, range) pair —
        real exchange bars for the Trade chart's range selector."""
        interval = YAHOO_INTERVAL.get(tf)
        if interval is None or tf not in RANGE_TFS.get(range_, ()):
            raise ValueError(f"unsupported range/timeframe: {range_}/{tf}")
        await self._ensure_cookie()
        try:
            resp = await self._http.get(
                CHART_URL.format(symbol=symbol),
                params={"interval": interval, "range": range_,
                        "includePrePost": "true" if include_pre_post else "false"})
        except httpx.HTTPError:
            return []
        if resp.status_code != 200:
            return []
        try:
            return parse_bars(symbol, tf, resp.json())
        except (ValueError, KeyError, TypeError):
            return []

    async def fetch_day_bars(self, symbol: str) -> list[Bar]:
        """Today's regular-session 1m bars — real exchange history for the day
        sparkline instead of ticks-since-boot."""
        return await self.fetch_bars(symbol, "1m", "1d", include_pre_post=False)


def _num(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _session(periods: dict | None, now_s: float | None = None) -> str:
    """Classify the current moment against Yahoo's currentTradingPeriod."""
    if not periods:
        return ""
    now_s = time.time() if now_s is None else now_s
    try:
        pre, reg, post = periods["pre"], periods["regular"], periods["post"]
        if reg["start"] <= now_s < reg["end"]:
            return "regular"
        if pre["start"] <= now_s < pre["end"]:
            return "pre"
        if post["start"] <= now_s < post["end"]:
            return "post"
    except (KeyError, TypeError):
        return ""
    return "closed"


def parse_day_bars(symbol: str, data: dict) -> list[Bar]:
    return parse_bars(symbol, "1m", data)


def parse_bars(symbol: str, tf: str, data: dict) -> list[Bar]:
    """Yahoo chart payload -> Bars of timeframe `tf` (null-close rows skipped)."""
    result = (((data or {}).get("chart") or {}).get("result") or [None])[0]
    if not result:
        return []
    stamps = result.get("timestamp") or []
    block = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens, highs, lows = block.get("open") or [], block.get("high") or [], block.get("low") or []
    closes, volumes = block.get("close") or [], block.get("volume") or []
    out: list[Bar] = []
    for i, ts in enumerate(stamps):
        c = closes[i] if i < len(closes) else None
        if c is None:
            continue
        o = opens[i] if i < len(opens) and opens[i] is not None else c
        h = highs[i] if i < len(highs) and highs[i] is not None else max(o, c)
        lo = lows[i] if i < len(lows) and lows[i] is not None else min(o, c)
        v = volumes[i] if i < len(volumes) and volumes[i] is not None else 0
        out.append(Bar(symbol=symbol.upper(), tf=tf, ts=int(ts) * 1000,
                       open=float(o), high=float(h), low=float(lo), close=float(c),
                       volume=int(v)))
    return out
