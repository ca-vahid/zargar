"""Historical OHLCV bars for technique analysis.

Yahoo's v8 chart endpoint is the free source (see `brokers/yahoo.py` for why v7
is unusable). Depth per interval, verified empirically 2026-08-21:

    1m   ~20 days back, max 8 days per request
    5m   ~60 days
    15m  ~60 days
    30m  ~60 days
    1h   ~730 days
    1d   many years

`as_of` lets the pipeline analyse a past moment — the window ends there and
later bars are never fetched, so a backtest cannot peek at the future.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from zoneinfo import ZoneInfo

import httpx

from ..domain import Bar

log = logging.getLogger("zargar.technique.history")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# Seconds per bar, and the widest single request Yahoo will honour.
INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "1d": 86400}
MAX_REQUEST_SPAN = {"1m": 7 * 86400, "5m": 59 * 86400, "15m": 59 * 86400, "30m": 59 * 86400,
                    "1h": 729 * 86400, "1d": 3650 * 86400}
# How far back each interval is available at all.
MAX_LOOKBACK = {"1m": 20 * 86400, "5m": 59 * 86400, "15m": 59 * 86400, "30m": 59 * 86400,
                "1h": 729 * 86400, "1d": 36500 * 86400}

# Small in-process cache: scheduled scans and chat tools would otherwise
# re-fetch identical windows. Keyed by (symbol, tf, start, end) with a short TTL
# for windows ending "now" and a long one for fully historical windows.
_cache: dict[tuple, tuple[float, list[Bar]]] = {}
_CACHE_MAX = 240            # a 250-symbol sweep must not pin every bar list in RAM forever
_LIVE_TTL = 20.0
_HIST_TTL = 3600.0
_shared_client: httpx.AsyncClient | None = None


def _client_shared() -> httpx.AsyncClient:
    """One keep-alive client for all Yahoo history traffic — a 250-symbol sweep
    was opening (and TLS-handshaking) ~750 throwaway clients."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=20, headers={"User-Agent": UA}, follow_redirects=True,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8))
    return _shared_client


def _cache_put(key: tuple, now: float, bars: list[Bar]) -> None:
    """Insert with eviction: expired entries first, then oldest — the cache was
    unbounded and grew to hundreds of MB across a big sweep (the 708 MB leak)."""
    if len(_cache) >= _CACHE_MAX:
        for k in [k for k, (ts, _) in _cache.items() if now - ts > _HIST_TTL]:
            _cache.pop(k, None)
    while len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)), None)     # insertion order == oldest first
    _cache[key] = (now, bars)
_sem = asyncio.Semaphore(6)


def set_concurrency(n: int) -> None:
    """Global cap on concurrent Yahoo requests (`technique.history.concurrency`).
    The 429 retry with back-off is the safety net; going past ~10 mostly just
    earns throttling."""
    global _sem
    _sem = asyncio.Semaphore(max(1, min(int(n), 12)))


# Back-off between retries of a 429 (sweeps over ~50 symbols fire a few hundred
# requests; Yahoo throttles in bursts, a short pause is usually enough).
_RETRY_PAUSES = (2.0, 5.0, 12.0)


class HistoryError(RuntimeError):
    pass


def clip_request_window(tf: str, start_s: int, end_s: int, now: float | None = None) -> tuple[int, int]:
    """Clamp a request to what Yahoo will actually serve: no older than the
    interval's lookback, and **no later than now** — a chunk that lies wholly in
    the future (e.g. the week after the last planned session) comes back as
    HTTP 400 "Data doesn't exist", which used to fail the whole symbol."""
    now = time.time() if now is None else now
    start_s = max(int(start_s), int(now - MAX_LOOKBACK[tf]))
    end_s = min(int(end_s), int(now) + 60)
    return start_s, end_s


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


# --- Alpaca SIP history (preferred for US symbols when keys are set) ----------
# Minute-aligned timeframes only: Alpaca's 1Hour bars are clock-aligned (09:00,
# 10:00) while Yahoo's are session-aligned (09:30) — swapping those would
# silently reshape 1h structure detection. 1h/1d stay on Yahoo.
_ALPACA = {"key": "", "secret": ""}
ALPACA_TF = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min"}
ALPACA_BARS_URL = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"
_ET = ZoneInfo("America/New_York")


def set_alpaca_credentials(key_id: str, secret: str) -> None:
    """Wired at engine start when ZARGAR_ALPACA_* is configured."""
    _ALPACA["key"] = key_id or ""
    _ALPACA["secret"] = secret or ""


def _rth_only(bars: list[Bar]) -> list[Bar]:
    """Yahoo history was fetched with includePrePost=false; Alpaca returns the
    full tape, so clip to the regular session to keep detector parity."""
    out = []
    for b in bars:
        t = dt.datetime.fromtimestamp(b.ts / 1000, _ET)
        m = t.hour * 60 + t.minute
        if 9 * 60 + 30 <= m < 16 * 60:
            out.append(b)
    return out


async def _alpaca_window(symbol: str, tf: str, start_s: int, end_s: int,
                         http: httpx.AsyncClient) -> list[Bar]:
    headers = {"APCA-API-KEY-ID": _ALPACA["key"], "APCA-API-SECRET-KEY": _ALPACA["secret"]}
    iso = lambda s: dt.datetime.fromtimestamp(s, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {"timeframe": ALPACA_TF[tf], "start": iso(start_s), "end": iso(end_s),
              "limit": 10_000, "feed": "sip", "adjustment": "raw"}
    bars: list[Bar] = []
    token = None
    for _ in range(20):                        # paginate; 20 pages = 200k bars, ample
        if token:
            params["page_token"] = token
        r = await http.get(ALPACA_BARS_URL.format(symbol=symbol.upper()), params=params,
                           headers=headers, timeout=20)
        if r.status_code >= 400:
            raise HistoryError(f"Alpaca HTTP {r.status_code}: {r.text[:120]}")
        data = r.json()
        for row in data.get("bars") or []:
            from ..brokers.alpaca import parse_rfc3339_ms
            bars.append(Bar(symbol=symbol.upper(), tf=tf, ts=parse_rfc3339_ms(str(row["t"])),
                            open=float(row["o"]), high=float(row["h"]), low=float(row["l"]),
                            close=float(row["c"]), volume=int(row.get("v") or 0)))
        token = data.get("next_page_token")
        if not token:
            break
    return _rth_only(bars)


async def fetch_window(
    symbol: str,
    tf: str,
    start_ms: int,
    end_ms: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[Bar]:
    """Bars in [start_ms, end_ms] at `tf` — Alpaca SIP first for US symbols
    when keys are configured (no 429s, true volume), Yahoo as the fallback."""
    if tf not in INTERVAL_SECONDS:
        raise HistoryError(f"unsupported interval {tf!r}")
    now = time.time()
    key = (symbol.upper(), tf, start_ms // 60000, end_ms // 60000)
    hit = _cache.get(key)
    if hit and now - hit[0] < (_LIVE_TTL if end_ms / 1000 > now - 120 else _HIST_TTL):
        return list(hit[1])

    start_s, end_s = clip_request_window(tf, start_ms // 1000, end_ms // 1000, now)
    if end_s <= start_s:
        return []

    own = False                                  # the shared client is never closed here
    http = client or _client_shared()
    bars: list[Bar] = []
    if _ALPACA["key"] and tf in ALPACA_TF and "." not in symbol and "=" not in symbol:
        try:
            bars = await _alpaca_window(symbol, tf, start_s, end_s, http)
        except Exception as exc:
            log.warning("alpaca history failed for %s %s (%s) — falling back to Yahoo", symbol, tf, exc)
            bars = []
    try:
      if not bars:
        span = MAX_REQUEST_SPAN[tf]
        chunks: list[tuple[int, int]] = []
        cursor = start_s
        while cursor < end_s:
            chunks.append((cursor, min(cursor + span, end_s)))
            cursor = chunks[-1][1]

        async def one(c0: int, c1: int) -> list[Bar]:
            params = {"period1": c0, "period2": c1, "interval": tf, "includePrePost": "false"}
            resp = None
            for attempt, pause in enumerate(_RETRY_PAUSES + (None,)):
                async with _sem:
                    from ..brokers.yahoo import yahoo_symbol
                    resp = await http.get(CHART_URL.format(symbol=yahoo_symbol(symbol)), params=params)
                if resp.status_code != 429 or pause is None:
                    break
                log.info("yahoo 429 for %s %s — retry %d in %.0fs", symbol, tf, attempt + 1, pause)
                await asyncio.sleep(pause)
            if resp.status_code == 429:
                raise HistoryError("rate limited by Yahoo (429) — try again shortly")
            if resp.status_code >= 400:
                raise HistoryError(f"Yahoo HTTP {resp.status_code}")
            return _parse(symbol, tf, resp.json())

        # chunks of one window fetch concurrently — the global semaphore still
        # bounds total Yahoo traffic across every symbol in a sweep
        for part in await asyncio.gather(*(one(c0, c1) for c0, c1 in chunks)):
            bars.extend(part)
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
    _cache_put(key, now, clean)
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


async def fetch_session(symbol: str, tf: str, date: str, *,
                        client: httpx.AsyncClient | None = None) -> list[Bar]:
    """All regular-session bars of one ET date (09:30-16:00). Empty on a holiday
    or when Yahoo no longer serves the interval that far back."""
    from .rulebook import session_bounds, session_date
    o, c = session_bounds(date)
    bars = await fetch_window(symbol, tf, o - INTERVAL_SECONDS.get(tf, 60) * 1000, c, client=client)
    return [b for b in bars if session_date(b.ts) == date and o <= b.ts < c]


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
