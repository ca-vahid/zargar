"""Options chain providers — normalized rows, provider-agnostic consumers.

* **CBOE** (default) — free delayed JSON at
  ``cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json``. No account,
  no token, works from Canada. One ~6 MB request returns the whole chain **with
  greeks and IV** plus the underlying's current price, ~15-min delayed.
  Verified live 2026-08-21. US listings only (no ``.TO``/``.V``).
* **Tradier** — optional (``ZARGAR_TRADIER_TOKEN``; US-address signup).
* IBKR slots in here once the account activates (``reqSecDefOptParams``).

Normalized row shape (every provider):

    {symbol (unpadded OCC), underlying, expiry (ISO), option_type (call|put),
     strike, bid, ask, last, volume, open_interest,
     greeks: {delta, gamma, theta, vega, mid_iv}}
"""
from __future__ import annotations

import logging
import time

import httpx

from . import occ

log = logging.getLogger("zargar.options.chain")

TRADIER_PROD_BASE = "https://api.tradier.com/v1"
TRADIER_SANDBOX_BASE = "https://sandbox.tradier.com/v1"
CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")


class OptionsError(RuntimeError):
    pass


def _f(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


# --- CBOE ----------------------------------------------------------------------

class CboeClient:
    """Free delayed chain with greeks. One fetch covers every expiry, so
    payloads are cached per underlying for a short TTL."""

    name = "cboe"
    delayed = True
    CACHE_TTL = 60.0

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._http = client or httpx.AsyncClient(timeout=30, headers={"User-Agent": UA},
                                                 follow_redirects=True)
        self._cache: dict[str, tuple[float, dict]] = {}

    @property
    def available(self) -> bool:
        return True

    def cached_at(self, symbol: str) -> float | None:
        hit = self._cache.get(symbol.upper().strip())
        return hit[0] if hit else None

    async def _payload(self, symbol: str) -> dict:
        sym = symbol.upper().strip()
        if "." in sym:
            raise OptionsError(f"{sym}: CBOE lists US options only (no .TO/.V symbols)")
        hit = self._cache.get(sym)
        now = time.time()
        if hit and now - hit[0] < self.CACHE_TTL:
            return hit[1]
        r = await self._http.get(CBOE_URL.format(symbol=sym))
        if r.status_code == 404:
            raise OptionsError(f"no US-listed options for {sym} (CBOE 404)")
        if r.status_code >= 400:
            raise OptionsError(f"CBOE HTTP {r.status_code}")
        data = (r.json() or {}).get("data") or {}
        if not data.get("options"):
            raise OptionsError(f"CBOE returned no contracts for {sym}")
        self._cache[sym] = (now, data)
        return data

    @staticmethod
    def _normalize(row: dict, underlying: str) -> dict | None:
        o = occ.parse(row.get("option") or "")
        if o is None:
            return None
        iv = row.get("iv")
        return {
            "symbol": o.symbol,
            "underlying": underlying,
            "expiry": o.expiry.isoformat(),
            "option_type": o.option_type,
            "strike": o.strike,
            "bid": _f(row.get("bid")),
            "ask": _f(row.get("ask")),
            "last": _f(row.get("last_trade_price")),
            "volume": int(_f(row.get("volume"))),
            "open_interest": int(_f(row.get("open_interest"))),
            "greeks": {
                "delta": row.get("delta"),
                "gamma": row.get("gamma"),
                "theta": row.get("theta"),
                "vega": row.get("vega"),
                "mid_iv": iv if iv else None,   # CBOE reports 0.0 for deep ITM
            },
        }

    async def expirations(self, symbol: str) -> list[str]:
        data = await self._payload(symbol)
        out: set[str] = set()
        for row in data.get("options") or []:
            o = occ.parse(row.get("option") or "")
            if o:
                out.add(o.expiry.isoformat())
        return sorted(out)

    async def chain(self, symbol: str, expiry: str) -> list[dict]:
        data = await self._payload(symbol)
        sym = symbol.upper().strip()
        rows = []
        for row in data.get("options") or []:
            n = self._normalize(row, sym)
            if n and n["expiry"] == expiry:
                rows.append(n)
        return rows

    async def all_rows(self, symbol: str) -> list[dict]:
        data = await self._payload(symbol)
        sym = symbol.upper().strip()
        return [n for n in (self._normalize(r, sym) for r in data.get("options") or []) if n]

    async def spot(self, symbol: str) -> float | None:
        data = await self._payload(symbol)
        v = data.get("current_price") or data.get("close")
        return float(v) if v else None

    async def underlying_quote(self, symbol: str) -> dict:
        """Underlying snapshot riding along in the chain payload."""
        data = await self._payload(symbol)
        return {
            "spot": _f(data.get("current_price") or data.get("close")) or None,
            "prevClose": _f(data.get("prev_day_close")) or None,
            "iv30": data.get("iv30"),
            "bid": _f(data.get("bid")) or None,
            "ask": _f(data.get("ask")) or None,
        }

    async def aclose(self) -> None:
        await self._http.aclose()


# --- Tradier -------------------------------------------------------------------

class TradierClient:
    name = "tradier"
    delayed = False

    def __init__(self, token: str, *, sandbox: bool = False,
                 client: httpx.AsyncClient | None = None) -> None:
        self._token = token
        self._base = TRADIER_SANDBOX_BASE if sandbox else TRADIER_PROD_BASE
        self._http = client or httpx.AsyncClient(timeout=15)

    @property
    def available(self) -> bool:
        return bool(self._token)

    async def _get(self, path: str, params: dict) -> dict:
        if not self._token:
            raise OptionsError("Tradier token not configured (ZARGAR_TRADIER_TOKEN)")
        r = await self._http.get(f"{self._base}{path}", params=params, headers={
            "Authorization": f"Bearer {self._token}", "Accept": "application/json"})
        if r.status_code == 401:
            raise OptionsError("Tradier rejected the token (401)")
        if r.status_code >= 400:
            raise OptionsError(f"Tradier HTTP {r.status_code}: {r.text[:200]}")
        return r.json() or {}

    async def expirations(self, symbol: str) -> list[str]:
        data = await self._get("/markets/options/expirations",
                               {"symbol": symbol.upper(), "includeAllRoots": "true"})
        exp = (data.get("expirations") or {}).get("date") or []
        if isinstance(exp, str):
            exp = [exp]
        return sorted(exp)

    async def chain(self, symbol: str, expiry: str) -> list[dict]:
        data = await self._get("/markets/options/chains",
                               {"symbol": symbol.upper(), "expiration": expiry, "greeks": "true"})
        opts = (data.get("options") or {}).get("option") or []
        if isinstance(opts, dict):
            opts = [opts]
        out = []
        for c in opts:
            g = c.get("greeks") or {}
            out.append({
                "symbol": occ.normalize(str(c.get("symbol") or "")),
                "underlying": c.get("underlying") or c.get("root_symbol") or symbol.upper(),
                "expiry": expiry,
                "option_type": (c.get("option_type") or "").lower(),
                "strike": float(c.get("strike") or 0),
                "bid": _f(c.get("bid")),
                "ask": _f(c.get("ask")),
                "last": _f(c.get("last")),
                "volume": int(_f(c.get("volume"))),
                "open_interest": int(_f(c.get("open_interest"))),
                "greeks": {"delta": g.get("delta"), "gamma": g.get("gamma"),
                           "theta": g.get("theta"), "vega": g.get("vega"),
                           "mid_iv": g.get("mid_iv") or g.get("smv_vol")},
            })
        return out

    async def all_rows(self, symbol: str) -> list[dict]:
        rows: list[dict] = []
        for exp in await self.expirations(symbol):
            rows.extend(await self.chain(symbol, exp))
        return rows

    async def spot(self, symbol: str) -> float | None:
        data = await self._get("/markets/quotes", {"symbols": symbol.upper(), "greeks": "false"})
        q = (data.get("quotes") or {}).get("quote") or {}
        if isinstance(q, list):
            q = q[0] if q else {}
        v = q.get("last") or q.get("close")
        return float(v) if v else None

    async def underlying_quote(self, symbol: str) -> dict:
        return {"spot": await self.spot(symbol), "prevClose": None, "iv30": None,
                "bid": None, "ask": None}

    async def aclose(self) -> None:
        await self._http.aclose()


# --- Alpaca OPRA (real-time contract quotes) -------------------------------------

ALPACA_DATA_BASE = "https://data.alpaca.markets"


class AlpacaOptionsData:
    """Real-time OPRA quotes/trades for KNOWN contracts — the Algo Trader Plus
    subscription includes them (probed 2026-09-02: NBBO ~1 s old, sizes +
    exchanges; snapshots carry greeks/IV). This is the QUOTE source for tracked
    contracts; the chain browser still comes from the chain provider. It is not
    a chain provider itself (no expirations()/chain()) — phase 2 adds that from
    ``/v1beta1/options/snapshots/{underlying}`` + ``/v2/options/contracts`` (OI)."""

    name = "alpaca"
    delayed = False
    BATCH = 100

    def __init__(self, key_id: str, secret: str, client: httpx.AsyncClient | None = None,
                 *, feed: str = "opra") -> None:
        self._http = client or httpx.AsyncClient(
            timeout=10, base_url=ALPACA_DATA_BASE,
            headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret})
        self._feed = feed

    @property
    def available(self) -> bool:
        return True

    @staticmethod
    def _ts_ms(t: str | None) -> int:
        if not t:
            return 0
        try:
            import datetime as _dt
            s = t.replace("Z", "+00:00")
            if "." in s:                                 # trim nanoseconds to microseconds
                head, tail = s.split(".", 1)
                frac = tail.split("+", 1)[0][:6]
                s = f"{head}.{frac}+00:00"
            return int(_dt.datetime.fromisoformat(s).timestamp() * 1000)
        except ValueError:
            return 0

    async def latest(self, symbols: list[str]) -> dict[str, dict]:
        """``{occ: {bid, ask, bid_size, ask_size, last, last_size, quote_ts, trade_ts}}``
        for every contract Alpaca knows; a symbol it does not know is simply
        absent (the caller falls back to the chain provider for it)."""
        out: dict[str, dict] = {}
        syms: list[str] = []
        for x in symbols:
            o = occ.parse(x)
            if o is not None:
                syms.append(o.symbol)
        for i in range(0, len(syms), self.BATCH):
            chunk = syms[i:i + self.BATCH]
            params = {"symbols": ",".join(chunk), "feed": self._feed}
            rq = await self._http.get("/v1beta1/options/quotes/latest", params=params)
            if rq.status_code in (401, 403):
                raise OptionsError(f"Alpaca options data refused ({rq.status_code}) — subscription?")
            if rq.status_code >= 400:
                raise OptionsError(f"Alpaca options quotes HTTP {rq.status_code}")
            quotes = (rq.json() or {}).get("quotes") or {}
            trades: dict = {}
            try:
                rt = await self._http.get("/v1beta1/options/trades/latest", params=params)
                if rt.status_code < 400:
                    trades = (rt.json() or {}).get("trades") or {}
            except httpx.HTTPError:                      # last is optional — the NBBO is the point
                trades = {}
            for sym, q in quotes.items():
                t = trades.get(sym) or {}
                out[sym] = {
                    "bid": _f(q.get("bp")), "ask": _f(q.get("ap")),
                    "bid_size": int(_f(q.get("bs"))), "ask_size": int(_f(q.get("as"))),
                    "last": _f(t.get("p")), "last_size": int(_f(t.get("s"))),
                    "quote_ts": self._ts_ms(q.get("t")), "trade_ts": self._ts_ms(t.get("t")),
                }
        return out

    async def aclose(self) -> None:
        await self._http.aclose()
