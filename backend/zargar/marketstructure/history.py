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

log = logging.getLogger("zargar.marketstructure.history")

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


def clip_request_window(tf: str, start_s: int, end_s: int, now: float | None = None, *,
                        provider: str = "yahoo") -> tuple[int, int]:
    """Clamp a request to what the provider will actually serve: **no later than now** for
    everyone — a chunk that lies wholly in the future (e.g. the week after the last planned
    session) comes back as HTTP 400 "Data doesn't exist", which used to fail the whole symbol —
    and, for Yahoo only, no older than the interval's lookback. F75 repair (2026-09-09): the
    Yahoo depth used to clamp Alpaca requests too, so a backfill of 2026-08-14..19 silently
    started at 08-20 and the quarantined block had no replacement."""
    now = time.time() if now is None else now
    start_s = int(start_s)
    if provider == "yahoo":
        start_s = max(start_s, int(now - MAX_LOOKBACK[tf]))
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
        if i >= len(vols) or vols[i] is None:
            continue                                 # R5/F79: a minute without volume is provisional, not a bar
        out.append(Bar(symbol=symbol.upper(), tf=tf, ts=int(ts) * 1000, source="exchange",
                       open=float(o), high=float(h), low=float(lo), close=float(c),
                       volume=int(vols[i])))
    return out


# --- Alpaca SIP history (preferred for US symbols when keys are set) ----------
# Minute-aligned timeframes only: Alpaca's 1Hour bars are clock-aligned (09:00,
# 10:00) while Yahoo's are session-aligned (09:30) — swapping those would
# silently reshape 1h structure detection. 1h/1d stay on Yahoo.
_ALPACA = {"key": "", "secret": ""}
ALPACA_TF = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min"}
_cache_provider: dict = {}        # which provider filled each cache key (review R5)
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
                         http: httpx.AsyncClient, *, session: str = "rth") -> list[Bar]:
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
            bars.append(Bar(symbol=symbol.upper(), tf=tf, ts=parse_rfc3339_ms(str(row["t"])), source="exchange",
                            open=float(row["o"]), high=float(row["h"]), low=float(row["l"]),
                            close=float(row["c"]), volume=int(row.get("v") or 0)))
        token = data.get("next_page_token")
        if not token:
            break
    return bars if session == "ext" else _rth_only(bars)


async def fetch_window(
    symbol: str,
    tf: str,
    start_ms: int,
    end_ms: int,
    *,
    client: httpx.AsyncClient | None = None,
    session: str = "rth",
    refresh: bool = False,
) -> list[Bar]:
    bars, _provider = await fetch_window_ex(symbol, tf, start_ms, end_ms, client=client, session=session, refresh=refresh)
    return bars


async def fetch_window_ex(
    symbol: str,
    tf: str,
    start_ms: int,
    end_ms: int,
    *,
    client: httpx.AsyncClient | None = None,
    session: str = "rth",
    refresh: bool = False,
) -> tuple[list[Bar], str | None]:
    """`fetch_window` plus WHICH provider answered ("alpaca" | "yahoo" | None when nothing did) —
    a repair that zeroes history may only do so on a venue response it can name (review R5)."""
    """Bars in [start_ms, end_ms] at `tf` — Alpaca SIP first for US symbols
    when keys are configured (no 429s, true volume), Yahoo as the fallback.

    `session="rth"` (default) is the regular session only — every existing detector
    keeps seeing exactly what it saw. `session="ext"` (2026-09-03, Team2 desk) returns
    the full 04:00–20:00 ET tape (Yahoo `includePrePost`, Alpaca unfiltered) for
    pre-market levels and extended-hours indicators; consumers clip with
    `aggregate.filter_session`."""
    if tf not in INTERVAL_SECONDS:
        raise HistoryError(f"unsupported interval {tf!r}")
    if session not in ("rth", "ext"):
        raise HistoryError(f"unsupported session {session!r} (rth|ext)")
    now = time.time()
    key = (symbol.upper(), tf, start_ms // 60000, end_ms // 60000, session)
    hit = _cache.get(key)
    if not refresh and hit and now - hit[0] < (_LIVE_TTL if end_ms / 1000 > now - 120 else _HIST_TTL):
        return list(hit[1]), _cache_provider.get(key)

    start_s, end_s = clip_request_window(tf, start_ms // 1000, end_ms // 1000, now, provider="alpaca")
    if end_s <= start_s:
        return [], None
    provider: str | None = None

    own = False                                  # the shared client is never closed here
    http = client or _client_shared()
    bars: list[Bar] = []
    if _ALPACA["key"] and tf in ALPACA_TF and "." not in symbol and "=" not in symbol:
        try:
            bars = await _alpaca_window(symbol, tf, start_s, end_s, http, session=session)
            provider = "alpaca" if bars else None
        except Exception as exc:
            log.warning("alpaca history failed for %s %s (%s) — falling back to Yahoo", symbol, tf, exc)
            bars = []
    try:
      if not bars:
        start_s, end_s = clip_request_window(tf, start_s, end_s, now, provider="yahoo")
        if end_s <= start_s:
            return [], None
        provider = "yahoo"
        span = MAX_REQUEST_SPAN[tf]
        chunks: list[tuple[int, int]] = []
        cursor = start_s
        while cursor < end_s:
            chunks.append((cursor, min(cursor + span, end_s)))
            cursor = chunks[-1][1]

        async def one(c0: int, c1: int) -> list[Bar]:
            params = {"period1": c0, "period2": c1, "interval": tf,
                      "includePrePost": "true" if session == "ext" else "false"}
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
    if session == "rth":
        clean = clip_to_rth(clean, tf)
    _cache_put(key, now, clean)
    _cache_provider[key] = provider if clean else None
    return list(clean), (provider if clean else None)


def clip_to_rth(bars: list[Bar], tf: str) -> list[Bar]:
    """Regular session only (09:30 <= t < 16:00 ET) for intraday bars. Yahoo's
    `includePrePost=false` still returns a trailing bucket stamped at the CLOSE
    on the same evening (the 16:00:00 print), and a 1h bar stamped 16:00 with a
    one-print range shrank DELL's ATR-based stop on 2026-09-03 20:54 so the
    reject trigger failed the chop rule that a next-day replay passed (+2.55R
    missed). Daily/weekly bars are untouched."""
    if tf in ("1d", "1wk", "1mo") or not bars:
        return bars
    from .sessions import session_bounds, session_date
    out: list[Bar] = []
    bounds: dict[str, tuple[int, int]] = {}
    for b in bars:
        day = session_date(b.ts)
        o, c = bounds.get(day) or bounds.setdefault(day, session_bounds(day))
        if o <= b.ts < c:
            out.append(b)
    return out


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
    from .sessions import session_bounds, session_date
    o, c = session_bounds(date)
    bars = await fetch_window(symbol, tf, o - INTERVAL_SECONDS.get(tf, 60) * 1000, c, client=client)
    return [b for b in bars if session_date(b.ts) == date and o <= b.ts < c]


async def fetch_extended_session(symbol: str, tf: str, date: str, *,
                                 client: httpx.AsyncClient | None = None) -> list[Bar]:
    """All 04:00–20:00 ET bars of one date (pre + regular + post). Team2's pre-market
    range and extended-hours EMAs read this; RTH-only callers keep `fetch_session`."""
    from .sessions import ET, session_date
    y, m, d = (int(x) for x in date.split("-"))
    lo = int(dt.datetime(y, m, d, 4, 0, tzinfo=ET).timestamp() * 1000)
    hi = int(dt.datetime(y, m, d, 20, 0, tzinfo=ET).timestamp() * 1000)
    bars = await fetch_window(symbol, tf, lo - INTERVAL_SECONDS.get(tf, 60) * 1000, hi,
                              client=client, session="ext")
    return [b for b in bars if session_date(b.ts) == date and lo <= b.ts < hi]


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
