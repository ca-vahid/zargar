"""Event calendar — earnings and ex-dividend dates as an engine capability
(techniques research A5, 2026-08-27).

Consumers: exit policies (`flatten_before("earnings")`, the short-call ex-div
guard) and scan inputs (the Drift/PEAD technique scans confirmed earnings).
Source v1 is Yahoo's quoteSummary `calendarEvents` (cookie + crumb dance); the
timing class (BMO/AMC) is derived from the ET hour of the timestamp. Yahoo dates
alone are not reliable enough to *fire* on — the record carries `source` and
`fetchedAt` so a second-source cross-check can be layered on without changing
consumers; until then techniques must treat `confirmed=False` as advisory.

    ev = await engine.calendar.get("AAPL")
    # {"symbol", "earnings": ["2026-10-29", ...], "earningsTiming": "AMC|BMO|unknown",
    #  "exDividend": "2026-11-07" | None, "dividendDate": ..., "confirmed": False,
    #  "source": "yahoo", "fetchedAt": ms}
    days = await engine.calendar.days_to_earnings("AAPL")   # None when unknown
"""
from __future__ import annotations

import datetime as dt
import logging
import time
from zoneinfo import ZoneInfo

import httpx

ET = ZoneInfo("America/New_York")
log = logging.getLogger("zargar.calendar")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
QS_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}"
CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
WARM_URL = "https://fc.yahoo.com"
CACHE_SECONDS = 12 * 3600


def _timing(ts: int) -> str:
    t = dt.datetime.fromtimestamp(ts, ET)
    m = t.hour * 60 + t.minute
    if m <= 10 * 60:
        return "BMO"
    if m >= 15 * 60 + 30:
        return "AMC"
    return "unknown"


class EventCalendar:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=10.0, headers={"User-Agent": UA},
                                                   follow_redirects=True)
        self._own_client = client is None
        self._crumb: str | None = None
        self._cache: dict[str, tuple[float, dict]] = {}

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()

    async def _ensure_crumb(self) -> str | None:
        if self._crumb:
            return self._crumb
        try:
            await self._client.get(WARM_URL)               # sets the cookie the crumb needs
            r = await self._client.get(CRUMB_URL)
            if r.status_code == 200 and r.text and "<" not in r.text:
                self._crumb = r.text.strip()
        except httpx.HTTPError as exc:
            log.warning("calendar crumb fetch failed: %s", exc)
        return self._crumb

    async def get(self, symbol: str, *, max_age_seconds: int = CACHE_SECONDS) -> dict:
        """The calendar record for one symbol; cached ~12h; empty fields on failure
        (never raises — a missing calendar must not break a scan)."""
        sym = symbol.upper().strip()
        hit = self._cache.get(sym)
        now = time.time()
        if hit and now - hit[0] < max_age_seconds:
            return hit[1]
        out = {"symbol": sym, "earnings": [], "earningsTiming": "unknown", "exDividend": None,
               "dividendDate": None, "confirmed": False, "source": "yahoo",
               "fetchedAt": int(now * 1000)}
        try:
            crumb = await self._ensure_crumb()
            params = {"modules": "calendarEvents"}
            if crumb:
                params["crumb"] = crumb
            r = await self._client.get(QS_URL.format(sym=sym), params=params)
            if r.status_code in (401, 403):                 # stale crumb: one refresh
                self._crumb = None
                crumb = await self._ensure_crumb()
                if crumb:
                    params["crumb"] = crumb
                    r = await self._client.get(QS_URL.format(sym=sym), params=params)
            r.raise_for_status()
            res = (((r.json() or {}).get("quoteSummary") or {}).get("result") or [])
            cal = (res[0].get("calendarEvents") if res else None) or {}
            earn = (cal.get("earnings") or {}).get("earningsDate") or []
            stamps = [int(e.get("raw")) for e in earn if isinstance(e, dict) and e.get("raw")]
            out["earnings"] = sorted({dt.datetime.fromtimestamp(t, ET).strftime("%Y-%m-%d") for t in stamps})
            if stamps:
                out["earningsTiming"] = _timing(min(stamps))
            exd = cal.get("exDividendDate")
            if isinstance(exd, dict) and exd.get("raw"):
                out["exDividend"] = dt.datetime.fromtimestamp(int(exd["raw"]), ET).strftime("%Y-%m-%d")
            dd = cal.get("dividendDate")
            if isinstance(dd, dict) and dd.get("raw"):
                out["dividendDate"] = dt.datetime.fromtimestamp(int(dd["raw"]), ET).strftime("%Y-%m-%d")
        except Exception as exc:
            log.warning("calendar fetch failed for %s: %s", sym, exc)
        self._cache[sym] = (now, out)
        return out

    async def days_to_earnings(self, symbol: str) -> int | None:
        """Calendar days until the next known earnings date (None = unknown)."""
        rec = await self.get(symbol)
        today = dt.datetime.now(ET).date()
        future = [d for d in rec["earnings"] if dt.date.fromisoformat(d) >= today]
        if not future:
            return None
        return (dt.date.fromisoformat(future[0]) - today).days

    async def days_to_ex_dividend(self, symbol: str) -> int | None:
        rec = await self.get(symbol)
        if not rec["exDividend"]:
            return None
        days = (dt.date.fromisoformat(rec["exDividend"]) - dt.datetime.now(ET).date()).days
        return days if days >= 0 else None
