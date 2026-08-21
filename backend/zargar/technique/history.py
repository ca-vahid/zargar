"""Historical OHLCV bars for technique analysis.

Yahoo's v8 chart endpoint is the free source (see `brokers/yahoo.py` for why v7
is unusable). Depth per interval, verified empirically 2026-08-21:

    1m   ~20 days back, max 8 days per request
    5m   ~60 days
    15m  ~60 days
    1h   ~730 days
    1d   many years

`as_of` lets the pipeline analyse a past moment — the window ends there and
later bars are never fetched, so a backtest cannot peek at the future.
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from ..domain import Bar

log = logging.getLogger("zargar.technique.history")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# Seconds per bar, and the widest single request Yahoo will honour.
INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
MAX_REQUEST_SPAN = {"1m": 7 * 86400, "5m": 59 * 86400, "15m": 59 * 86400,
                    "1h": 729 * 86400, "1d": 3650 * 86400}
# How far back each interval is available at all.
MAX_LOOKBACK = {"1m": 20 * 86400, "5m": 59 * 86400, "15m": 59 * 86400,
                "1h": 729 * 86400, "1d": 36500 * 86400}

# Small in-process cache: scheduled scans and chat tools would otherwise
# re-fetch identical windows. Keyed by (symbol, tf, start, end) with a short TTL
# for windows ending "now" and a long one for fully historical windows.
_cache: dict[tuple, tuple[float, list[Bar]]] = {}
_LIVE_TTL = 20.0
_HIST_TTL = 3600.0
_sem = asyncio.Semaphore(4)


class HistoryError(RuntimeError):
    pass


def _parse(symbol: str, tf: str, data: dict) -> list[Bar]:
    result = (((data or {}).get("chart") or {}).get("result") or [None])[0]
    if not result:
        err = ((data or {}).get("chart") or {}).get("error") or {}
        raise HistoryError(err.get("description") or "empty chart result")
    stamps = result.get("timestamp") or []
    q = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens, highs = q.get("open") or [], q.get("high") or []
    lows, closes = q.get("low") or [], q.get("close") or []
    vols = q.get("volume") or []
    out: list[Bar] = []
    for i, ts in enumerate(stamps):
        o = opens[i] if i < len(opens) else None
        h = highs[i] if i < len(highs) else None
        lo = lows[i] if i < len(lows) else None
        c = closes[i] if i < len(closes) else None
        if o is None or h is None or lo is None or c is None:
            continue
        v = vols[i] if i < len(vols) and vols[i] is not None else 0
        out.append(Bar(symbol=symbol.upper(), tf=tf, ts=int(ts) * 1000,
                       open=float(o), high=float(h), low=float(lo), close=float(c),
                       volume=int(v)))
    return out


async def fetch_window(
    symbol: str,
    tf: str,
    start_ms: int,
    end_ms: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[Bar]:
    """Bars in [start_ms, end_ms] at `tf`, chunking requests to Yahoo's limits."""
    if tf not in INTERVAL_SECONDS:
        raise HistoryError(f"unsupported interval {tf!r}")
    now = time.time()
    key = (symbol.upper(), tf, start_ms // 60000, end_ms // 60000)
    hit = _cache.get(key)
    if hit and now - hit[0] < (_LIVE_TTL if end_ms / 1000 > now - 120 else _HIST_TTL):
        return list(hit[1])

    oldest_allowed = now - MAX_LOOKBACK[tf]
    start_s = max(start_ms // 1000, int(oldest_allowed))
    end_s = end_ms // 1000
    if end_s <= start_s:
        return []

    own = client is None
    http = client or httpx.AsyncClient(timeout=20, headers={"User-Agent": UA},
                                       follow_redirects=True)
    bars: list[Bar] = []
    try:
        span = MAX_REQUEST_SPAN[tf]
        cursor = start_s
        while cursor < end_s:
            chunk_end = min(cursor + span, end_s)
            params = {"period1": cursor, "period2": chunk_end, "interval": tf,
                      "includePrePost": "false"}
            async with _sem:
                resp = await http.get(CHART_URL.format(symbol=symbol.upper()), params=params)
            if resp.status_code == 429:
                raise HistoryError("rate limited by Yahoo (429) — try again shortly")
            if resp.status_code >= 400:
                raise HistoryError(f"Yahoo HTTP {resp.status_code}")
            bars.extend(_parse(symbol, tf, resp.json()))
            cursor = chunk_end
    finally:
        if own:
            await http.aclose()

    # Dedupe on ts (chunk edges can overlap) and clip to the requested window.
    seen: set[int] = set()
    clean: list[Bar] = []
    for b in sorted(bars, key=lambda x: x.ts):
        if b.ts in seen or b.ts < start_ms or b.ts > end_ms:
            continue
        seen.add(b.ts)
        clean.append(b)
    _cache[key] = (now, clean)
    return list(clean)


async def fetch_recent(symbol: str, tf: str, *, sessions: int = 5,
                       as_of_ms: int | None = None,
                       client: httpx.AsyncClient | None = None) -> list[Bar]:
    """Roughly `sessions` trading days of bars ending at `as_of_ms` (default now).

    Calendar days are over-requested (weekends, holidays) and the result is
    trimmed to the last `sessions` distinct session dates.
    """
    end_ms = as_of_ms or int(time.time() * 1000)
    cal_days = max(2, int(sessions * 1.6) + 2)
    start_ms = end_ms - cal_days * 86400 * 1000
    bars = await fetch_window(symbol, tf, start_ms, end_ms, client=client)
    if not bars:
        return bars
    from .levels import session_key
    keys: list[str] = []
    for b in bars:
        k = session_key(b.ts)
        if not keys or keys[-1] != k:
            keys.append(k)
    keep = set(keys[-sessions:])
    return [b for b in bars if session_key(b.ts) in keep]


def interval_available(tf: str, as_of_ms: int | None) -> bool:
    """Whether Yahoo still serves `tf` bars at `as_of_ms`."""
    if tf not in MAX_LOOKBACK:
        return False
    if as_of_ms is None:
        return True
    return (time.time() - as_of_ms / 1000) < MAX_LOOKBACK[tf] - 86400


def split_sessions(bars: list[Bar]) -> dict[str, list[Bar]]:
    from .levels import session_key
    out: dict[str, list[Bar]] = {}
    for b in bars:
        out.setdefault(session_key(b.ts), []).append(b)
    return out
