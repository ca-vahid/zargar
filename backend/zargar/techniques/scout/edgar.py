"""EDGAR transport - polite by construction (SEC fair access: <= 10 req/s, declared
User-Agent with a contact). Every request goes through one throttle (default 5 req/s),
retries 429/5xx with backoff, and never runs requests in parallel.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from pathlib import Path

import httpx

log = logging.getLogger("zargar.scout.edgar")

DEFAULT_UA = "Zargar research vhaeri@bgcengineering.ca"
ARCHIVES = "https://www.sec.gov/Archives/"
DAILY_INDEX = "https://www.sec.gov/Archives/edgar/daily-index/{y}/QTR{q}/form.{ymd}.idx"
DATASET_URLS = (
    # the SEC moved newer quarters to a new folder (seen 2026-10-07: 2026q2+ under datastandardsinnovation)
    "https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/{name}_form345.zip",
    "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{name}_form345.zip",
)
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik10}.json"
SHARES_CONCEPT = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik10}/dei/EntityCommonStockSharesOutstanding.json"
TICKERS = "https://www.sec.gov/files/company_tickers.json"


class EdgarError(RuntimeError):
    pass


class EdgarClient:
    def __init__(self, *, user_agent: str = DEFAULT_UA, max_rps: float = 5.0,
                 client: httpx.AsyncClient | None = None, retries: int = 4) -> None:
        if "@" not in user_agent:
            raise EdgarError("EDGAR requires a User-Agent with a contact email")
        self.max_rps = max(0.1, min(float(max_rps), 9.0))     # hard ceiling under the SEC's 10/s
        self._gap = 1.0 / self.max_rps
        self._last = 0.0
        self._lock = asyncio.Lock()
        self._own = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self.retries = retries
        self.requests = 0

    async def aclose(self) -> None:
        if self._own:
            await self._client.aclose()

    async def _wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._last + self._gap - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()

    async def get(self, url: str, *, allow_404: bool = False) -> httpx.Response | None:
        backoff = 2.0
        for attempt in range(self.retries + 1):
            await self._wait()
            self.requests += 1
            try:
                r = await self._client.get(url)
            except httpx.HTTPError as exc:
                if attempt >= self.retries:
                    raise EdgarError(f"{url}: {exc}") from exc
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            if r.status_code == 404 and allow_404:
                return None
            if r.status_code in (429, 500, 502, 503, 504) or (r.status_code == 403 and attempt < 1):
                if attempt >= self.retries:
                    raise EdgarError(f"{url}: HTTP {r.status_code}")
                log.info("edgar %s -> %s, backing off %.0fs", url, r.status_code, backoff)
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            if r.status_code >= 400:
                raise EdgarError(f"{url}: HTTP {r.status_code}")
            return r
        raise EdgarError(f"{url}: retries exhausted")

    # ------------------------------------------------------------------ endpoints
    async def daily_index(self, day: dt.date) -> str | None:
        """`form.YYYYMMDD.idx`, or None when EDGAR published none (weekend/holiday/not yet)."""
        q = (day.month - 1) // 3 + 1
        r = await self.get(DAILY_INDEX.format(y=day.year, q=q, ymd=day.strftime("%Y%m%d")), allow_404=True)
        return None if r is None else r.content.decode("latin-1")

    async def submission_text(self, path: str) -> str:
        r = await self.get(ARCHIVES + path.lstrip("/"))
        return r.content.decode("utf-8", errors="replace")

    async def header(self, cik: str, accession: str) -> str | None:
        acc = accession.replace("-", "")
        r = await self.get(f"{ARCHIVES}edgar/data/{int(cik)}/{acc}/{accession}.hdr.sgml", allow_404=True)
        return None if r is None else r.content.decode("utf-8", errors="replace")

    async def dataset_zip(self, name: str, dest: Path) -> Path | None:
        """Stream one quarterly insider data set to `dest` (None when not published yet)."""
        for tmpl in DATASET_URLS:
            url = tmpl.format(name=name)
            await self._wait()
            self.requests += 1
            async with self._client.stream("GET", url) as r:
                if r.status_code == 404:
                    continue
                if r.status_code >= 400:
                    raise EdgarError(f"{url}: HTTP {r.status_code}")
                tmp = dest.with_suffix(".part")
                with tmp.open("wb") as fh:
                    async for chunk in r.aiter_bytes(1 << 16):
                        fh.write(chunk)
                tmp.replace(dest)
                return dest
        return None

    async def submissions(self, cik: str) -> dict | None:
        r = await self.get(SUBMISSIONS.format(cik10=f"{int(cik):010d}"), allow_404=True)
        return None if r is None else r.json()

    async def shares_outstanding(self, cik: str) -> dict | None:
        r = await self.get(SHARES_CONCEPT.format(cik10=f"{int(cik):010d}"), allow_404=True)
        return None if r is None else r.json()
