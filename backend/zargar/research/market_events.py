"""Market event calendar v2 (W4.1-W4.3, 2026-10-03) - a shared, provenance-first, APPEND-ONLY store of scheduled
macro events and company earnings dates.

Why (docs/techniques/tip/research/2026-10-02-tips-review/D-events.md): the Tips desk's verified-event list was edited
by hand, overwritten on every edit (history lost, the 09-16 FOMC later read as "no event"), never held CPI, ranked a
T-bill auction like an FOMC (221/236 appraisals said "event-day"), and only ever looked at today.

Rules:
- every row is immutable; a change is a NEW row with the same `key` (a later `valid_from`); a removal is a tombstone
  row (`deleted=True`). `as_of(t)` = for each key the row with the greatest `valid_from <= t` - a date first learned
  later never reaches an earlier decision, and a moved date never back-dates;
- each source records the window it actually covered (`market_event_coverage`); a date outside every macro coverage
  window is UNKNOWN, never "no event";
- tiers: 1 = FOMC statement/presser, CPI, Employment Situation, GDP, PCE (Personal Income and Outlays);
  2 = PPI, JOLTS, FOMC minutes; earnings are symbol-scoped (tier 1 for that symbol).

Sources: Federal Reserve FOMC calendar page (parsed), BEA release iCal (fetched), BLS release schedules (bls.gov blocks
scripted downloads, so the schedule published on its official pages is shipped below with its URLs and the date it was
read - re-read on each new year), earnings from Yahoo (`engine.calendar`) cross-checked with Nasdaq's earnings calendar.
Nothing here places, blocks, sizes or times an order by itself - consumers decide (the Tips earnings exit/entry rule and
the observe-first event policies).
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

ET = ZoneInfo("America/New_York")
log = logging.getLogger("zargar.market_events")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BEA_ICS = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
NASDAQ_EARN = "https://api.nasdaq.com/api/calendar/earnings?date={d}"

# BLS 2026 schedules as published on bls.gov (read 2026-10-03 via the official pages below).
BLS_READ_AT = "2026-10-03T03:30:00+00:00"
BLS_2026 = {
    "cpi": ("Consumer Price Index", 1, "08:30", "https://www.bls.gov/schedule/news_release/cpi.htm",
            ["2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10", "2026-05-12", "2026-06-10", "2026-07-14",
             "2026-08-12", "2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10"]),
    "nfp": ("Employment Situation", 1, "08:30", "https://www.bls.gov/schedule/news_release/empsit.htm",
            ["2026-01-09", "2026-02-11", "2026-03-06", "2026-04-03", "2026-05-08", "2026-06-05", "2026-07-02",
             "2026-08-07", "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04"]),
    "ppi": ("Producer Price Index", 2, "08:30", "https://www.bls.gov/schedule/news_release/ppi.htm",
            ["2026-01-14", "2026-01-30", "2026-02-27", "2026-03-18", "2026-04-14", "2026-05-13", "2026-06-11",
             "2026-07-15", "2026-08-13", "2026-09-10", "2026-10-15", "2026-11-13", "2026-12-15"]),
    "jolts": ("JOLTS job openings", 2, "10:00", "https://www.bls.gov/schedule/news_release/jolts.htm",
              ["2026-03-13", "2026-03-31", "2026-05-05", "2026-06-02", "2026-06-30", "2026-08-04", "2026-09-01",
               "2026-09-29", "2026-11-03", "2026-12-01"]),
}
BLS_COVERAGE = ("2026-01-01", "2026-12-31")
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                      "September", "October", "November", "December"], 1)}


# ------------------------------------------------------------------ pure parsers
def ev(kind: str, tier: int, name: str, date: str, time: str | None, source: str, url: str, *,
       symbol: str | None = None, extra: dict | None = None) -> dict:
    key = f"{source}:{kind}:{symbol or '-'}:{date}" + (f":{time}" if kind.startswith("fomc") else "")
    return {"key": key, "kind": kind, "tier": int(tier), "name": name, "date": date, "time": time,
            "scope": "symbol" if symbol else "macro", "symbol": symbol, "source": source, "url": url,
            "extra": extra or {}}


def bls_events() -> list[dict]:
    out = []
    for kind, (name, tier, tm, url, dates) in BLS_2026.items():
        out += [ev(kind, tier, name, d, tm, "bls", url) for d in dates]
    return out


def parse_fomc(html: str) -> tuple[list[dict], tuple[str, str] | None]:
    """FOMC statement (14:00) + press conference (14:30) on each meeting's last day; '*' = SEP meeting."""
    out, years = [], []
    for y in re.findall(r"(\d{4}) FOMC Meetings", html):
        i = html.find(f"{y} FOMC Meetings")
        j = html.find("FOMC Meetings", i + 20)
        seg = html[i:(j if j > 0 else i + 15000)]
        found = False
        for m in re.finditer(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)<',
                             seg, re.S):
            mon, days = m.group(1).strip(), m.group(2).strip()
            mon = mon.split("/")[-1].strip()
            if mon not in MONTHS:
                continue
            sep = "*" in days
            nums = [int(x) for x in re.findall(r"\d+", days)]
            if not nums:
                continue
            last = nums[-1]
            month = MONTHS[mon]
            if len(nums) == 2 and nums[1] < nums[0]:        # a meeting spanning a month end ("Apr/May 30-1")
                month = month
            try:
                d = dt.date(int(y), month, last).isoformat()
            except ValueError:
                continue
            found = True
            x = {"sep": sep, "meeting": days}
            out.append(ev("fomc_statement", 1, "FOMC statement" + (" + projections" if sep else ""), d, "14:00",
                          "fed", FOMC_URL, extra=x))
            out.append(ev("fomc_presser", 1, "FOMC press conference", d, "14:30", "fed", FOMC_URL, extra=x))
        if found:
            years.append(int(y))
    cov = (f"{min(years)}-01-01", f"{max(years)}-12-31") if years else None
    return out, cov


def parse_bea_ics(text: str) -> tuple[list[dict], tuple[str, str] | None]:
    t = re.sub(r"\r?\n[ \t]", "", text.replace("\r\n", "\n"))
    out, dates = [], []
    for e in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", t, re.S):
        ms, md = re.search(r"SUMMARY:(.*)", e), re.search(r"DTSTART[^:]*:(\d{8})(T(\d{6})Z?)?", e)
        if not ms or not md:
            continue
        title = ms.group(1).replace("\\,", ",").replace("\\;", ";").strip()
        if md.group(3):
            inst = dt.datetime.strptime(md.group(1) + md.group(3), "%Y%m%d%H%M%S").replace(
                tzinfo=dt.timezone.utc).astimezone(ET)
        else:
            inst = dt.datetime.strptime(md.group(1), "%Y%m%d").replace(hour=8, minute=30, tzinfo=ET)
        d, tm = inst.date().isoformat(), inst.strftime("%H:%M")
        dates.append(d)
        low = title.lower()
        if low.startswith("personal income and outlays"):
            out.append(ev("pce", 1, "PCE / Personal Income and Outlays", d, tm, "bea", BEA_ICS, extra={"title": title}))
        elif low.startswith("gdp (") or low.startswith("gross domestic product,") or \
                (low.startswith("gross domestic product") and "county" not in low and "state" not in low[:40]):
            if "county" in low or "by state" in low:
                continue
            out.append(ev("gdp", 1, "GDP", d, tm, "bea", BEA_ICS, extra={"title": title}))
    cov = (min(dates), max(dates)) if dates else None
    return out, cov


def parse_nasdaq_earnings(payload: dict, date: str, symbols: set[str]) -> list[dict]:
    rows = (((payload or {}).get("data") or {}).get("rows")) or []
    out = []
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        if symbols and sym not in symbols:
            continue
        tm = str(r.get("time") or "").lower()
        timing = "BMO" if "pre" in tm else "AMC" if "after" in tm else "unknown"
        out.append(ev("earnings", 1, f"{sym} earnings", date, None, "nasdaq",
                      NASDAQ_EARN.format(d=date), symbol=sym, extra={"timing": timing}))
    return out


# ------------------------------------------------------------------ store
def _row_dict(r) -> dict:
    return {"key": r.key, "kind": r.kind, "tier": r.tier, "name": r.name, "date": r.date, "time": r.time,
            "scope": r.scope, "symbol": r.symbol, "source": r.source, "url": r.url, "extra": r.extra or {},
            "validFrom": r.valid_from.isoformat() if r.valid_from else None, "deleted": bool(r.deleted),
            "revision": r.revision}


def _same(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in ("kind", "tier", "name", "date", "time", "symbol")) and \
        (a.get("extra") or {}).get("timing") == (b.get("extra") or {}).get("timing")


class MarketEventStore:
    """The engine's handle (`engine.market_events`). Rows live in Postgres; the current view is cached in memory
    so synchronous readers (the analyst header) can use it."""

    def __init__(self, engine):
        self.engine = engine
        self._current: list[dict] = []
        self._coverage: dict[str, tuple[str, str]] = {}
        self.loaded = False

    async def load(self) -> None:
        from ..models import MarketEventCoverage, MarketEventRow
        async with self.engine.sf() as session:
            rows = (await session.execute(select(MarketEventRow).order_by(
                MarketEventRow.key, MarketEventRow.valid_from))).scalars().all()
            cov = (await session.execute(select(MarketEventCoverage).order_by(
                MarketEventCoverage.fetched_at))).scalars().all()
        latest: dict[str, dict] = {}
        for r in rows:
            latest[r.key] = _row_dict(r)
        self._current = [v for v in latest.values() if not v["deleted"]]
        self._coverage = {}
        for c in cov:
            self._coverage[c.source] = (c.coverage_from, c.coverage_through)
        self.loaded = True

    async def write(self, events: list[dict], *, source: str, coverage: tuple[str, str] | None,
                    now: dt.datetime | None = None, tombstone_missing: bool = True) -> dict:
        """Append a revision for every new/changed event of `source`; with a coverage window, an event of that source
        inside the window that is no longer reported gets a tombstone row."""
        from ..models import MarketEventCoverage, MarketEventRow
        now = now or dt.datetime.now(dt.timezone.utc)
        added = changed = removed = 0
        async with self.engine.sf() as session:
            rows = (await session.execute(select(MarketEventRow).where(MarketEventRow.source == source)
                                          .order_by(MarketEventRow.valid_from))).scalars().all()
            latest: dict[str, MarketEventRow] = {}
            for r in rows:
                latest[r.key] = r
            seen = set()
            for e in events:
                seen.add(e["key"])
                cur = latest.get(e["key"])
                if cur is not None and not cur.deleted and _same(_row_dict(cur), e):
                    continue
                rev = (cur.revision + 1) if cur is not None else 1
                session.add(MarketEventRow(key=e["key"], kind=e["kind"], tier=e["tier"], name=e["name"],
                                           date=e["date"], time=e.get("time"), scope=e["scope"], symbol=e.get("symbol"),
                                           source=source, url=e.get("url"), extra=e.get("extra") or {},
                                           valid_from=now, revision=rev, deleted=False))
                if cur is None or cur.deleted:
                    added += 1
                else:
                    changed += 1
            if tombstone_missing and coverage:
                for k, r in latest.items():
                    if k in seen or r.deleted or not (coverage[0] <= r.date <= coverage[1]):
                        continue
                    session.add(MarketEventRow(key=k, kind=r.kind, tier=r.tier, name=r.name, date=r.date,
                                               time=r.time, scope=r.scope, symbol=r.symbol, source=source, url=r.url,
                                               extra=r.extra or {}, valid_from=now, revision=r.revision + 1,
                                               deleted=True))
                    removed += 1
            if coverage:
                session.add(MarketEventCoverage(source=source, coverage_from=coverage[0],
                                                coverage_through=coverage[1], fetched_at=now))
            await session.commit()
        await self.load()
        return {"source": source, "added": added, "changed": changed, "removed": removed,
                "coverage": list(coverage) if coverage else None}

    async def as_of(self, when: dt.datetime) -> list[dict]:
        """The calendar as it was KNOWN at `when` (a replay never sees a later revision)."""
        from ..models import MarketEventRow
        async with self.engine.sf() as session:
            rows = (await session.execute(select(MarketEventRow).where(MarketEventRow.valid_from <= when)
                                          .order_by(MarketEventRow.key, MarketEventRow.valid_from))).scalars().all()
        latest: dict[str, dict] = {}
        for r in rows:
            latest[r.key] = _row_dict(r)
        return [v for v in latest.values() if not v["deleted"]]

    # ---- reads (current view, synchronous)
    def macro_coverage_through(self) -> str | None:
        """The last date EVERY tier-1 macro source covers (fed, bls, bea present); None = unknown."""
        need = ("fed", "bls", "bea")
        if not all(s in self._coverage for s in need):
            return None
        return min(self._coverage[s][1] for s in need)

    def macro_coverage_from(self) -> str | None:
        need = ("fed", "bls", "bea")
        if not all(s in self._coverage for s in need):
            return None
        return max(self._coverage[s][0] for s in need)

    def between(self, start: str, end: str, *, max_tier: int = 2, symbol: str | None = None,
                macro: bool = True) -> list[dict]:
        out = []
        for e in self._current:
            if not (start <= e["date"] <= end) or e["tier"] > max_tier:
                continue
            if e["scope"] == "macro" and not macro:
                continue
            if e["scope"] == "symbol" and (symbol is None or e["symbol"] != symbol.upper()):
                continue
            out.append(e)
        return sorted(out, key=lambda e: (e["date"], e.get("time") or "99:99"))

    def as_verified(self) -> dict | None:
        """The Tips verified-events shape (`techniques/tip/events.py`) from the store: tier 1-2 macro events only."""
        through = self.macro_coverage_through()
        if not self.loaded or through is None:
            return None
        evs = [{"date": e["date"], "time": e.get("time"), "kind": e["kind"], "name": e["name"], "url": e.get("url"),
                "tier": e["tier"], "verifiedAt": e.get("validFrom"), "verifiedBy": f"market_events:{e['source']}",
                "source": f"market-events:{e['source']}"}
               for e in self._current if e["scope"] == "macro" and e["tier"] <= 2]
        return {"coverageThrough": through, "coverageFrom": self.macro_coverage_from(), "events": evs,
                "store": "market_events"}

    # ---- fetchers
    async def refresh(self, *, symbols: list[str] | None = None) -> dict:
        out: dict = {}
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": UA, "Accept": "*/*"},
                                     follow_redirects=True) as client:
            try:
                out["bls"] = await self.write(bls_events(), source="bls", coverage=BLS_COVERAGE,
                                              now=dt.datetime.fromisoformat(BLS_READ_AT)
                                              if "bls" not in self._coverage else None)
            except Exception as exc:                         # noqa: BLE001
                out["bls"] = {"error": f"{type(exc).__name__}: {exc}"}
            try:
                r = await client.get(FOMC_URL)
                r.raise_for_status()
                evs, cov = parse_fomc(r.text)
                out["fed"] = await self.write(evs, source="fed", coverage=cov) if evs else {"error": "no meetings parsed"}
            except Exception as exc:                         # noqa: BLE001
                out["fed"] = {"error": f"{type(exc).__name__}: {exc}"}
            try:
                r = await client.get(BEA_ICS)
                r.raise_for_status()
                evs, cov = parse_bea_ics(r.text)
                out["bea"] = await self.write(evs, source="bea", coverage=cov) if evs else {"error": "no releases parsed"}
            except Exception as exc:                         # noqa: BLE001
                out["bea"] = {"error": f"{type(exc).__name__}: {exc}"}
            if symbols:
                out["earnings"] = await self.refresh_earnings(client, symbols)
        try:
            await self.engine.journal.append("MarketEventsFetched", out)
        except Exception:                                    # noqa: BLE001
            log.debug("journal MarketEventsFetched failed", exc_info=True)
        return out

    async def refresh_earnings(self, client, symbols: list[str], *, days: int = 21) -> dict:
        """Two sources: Yahoo (engine.calendar) and Nasdaq's daily earnings calendar for the next `days`; a date both
        agree on (within a day) is `confirmed`."""
        syms = {s.upper() for s in symbols if s and "." not in s}
        today = dt.datetime.now(ET).date()
        nas: list[dict] = []
        for i in range(days):
            d = today + dt.timedelta(days=i)
            if d.weekday() >= 5:
                continue
            try:
                r = await client.get(NASDAQ_EARN.format(d=d.isoformat()),
                                     headers={"User-Agent": UA, "Accept": "application/json"})
                if r.status_code == 200:
                    nas += parse_nasdaq_earnings(r.json(), d.isoformat(), syms)
            except Exception:                                # noqa: BLE001
                continue
        res = await self.write(nas, source="nasdaq", coverage=None, tombstone_missing=False)
        yev = []
        cal = getattr(self.engine, "calendar", None)
        if cal is not None:
            for s in sorted(syms):
                try:
                    nxt = await cal.next_earnings(s)
                except Exception:                            # noqa: BLE001
                    nxt = None
                if nxt:
                    yev.append(ev("earnings", 1, f"{s} earnings", nxt[0], None, "yahoo",
                                  "https://finance.yahoo.com/quote/" + s, symbol=s, extra={"timing": nxt[1]}))
        res2 = await self.write(yev, source="yahoo", coverage=None, tombstone_missing=False)
        return {"nasdaq": res, "yahoo": res2}

    def earnings_for(self, symbol: str) -> dict | None:
        """The next report for `symbol` from both sources: {date, timing, confirmed, sources}."""
        today = dt.datetime.now(ET).date().isoformat()
        rows = [e for e in self._current if e["scope"] == "symbol" and e["symbol"] == symbol.upper()
                and e["kind"] == "earnings" and e["date"] >= today]
        if not rows:
            return None
        rows.sort(key=lambda e: e["date"])
        first = rows[0]
        others = [e for e in rows if e["source"] != first["source"]]
        conf = any(abs((dt.date.fromisoformat(e["date"]) - dt.date.fromisoformat(first["date"])).days) <= 1
                   for e in others)
        timing = next((e["extra"].get("timing") for e in rows if (e.get("extra") or {}).get("timing") not in
                       (None, "unknown")), "unknown")
        return {"date": first["date"], "timing": timing, "confirmed": conf,
                "sources": sorted({e["source"] for e in rows})}


def exposure(store: MarketEventStore | None, *, now: dt.datetime, hold_until: dt.date, symbol: str | None) -> dict:
    """W4.3: which events fall inside a position's planned life (now .. hold_until), tier 1-2 macro + the symbol's
    earnings, and the coverage status of that window."""
    if store is None or not store.loaded:
        return {"coverage": "unknown", "events": []}
    start = now.astimezone(ET).date().isoformat()
    end = hold_until.isoformat()
    evs = store.between(start, end, max_tier=2, symbol=symbol)
    through = store.macro_coverage_through()
    cov = "covered" if through and end <= through else "partial" if through and start <= through else "unknown"
    t1 = [e for e in evs if e["tier"] == 1]
    nxt = None
    for e in t1:
        if e.get("time"):
            hh, mm = (int(x) for x in e["time"].split(":"))
            inst = dt.datetime.combine(dt.date.fromisoformat(e["date"]), dt.time(hh, mm), tzinfo=ET)
            if inst > now:
                nxt = {"name": e["name"], "date": e["date"], "time": e["time"],
                       "minutesUntil": int((inst - now).total_seconds() // 60)}
                break
    return {"coverage": cov, "coverageThrough": through, "window": [start, end],
            "events": [{k: e.get(k) for k in ("name", "kind", "tier", "date", "time", "symbol", "source")} for e in evs],
            "tier1": len(t1), "nextTier1": nxt,
            "earnings": next(({"date": e["date"], "timing": (e.get("extra") or {}).get("timing")} for e in evs
                              if e["kind"] == "earnings"), None)}


def policy_shadow(expo: dict, *, now: dt.datetime, sec_type: str, dte: int | None) -> list[dict]:
    """W4.5 (observe only, never an order change): what event rules E1-E3 WOULD do to this entry. Promotion to
    enforce is a preregistered decision (>= 25 affected trades and >= 6 tier-1 events; D-events.md §4.4)."""
    out = []
    t1 = [e for e in (expo or {}).get("events") or [] if e.get("tier") == 1 and e.get("kind") != "earnings"]
    opt = str(sec_type).upper() in ("OPT", "SPREAD")
    before, after = (60, 30) if opt else (15, 15)
    for e in t1:
        if not e.get("time"):
            continue
        hh, mm = (int(x) for x in e["time"].split(":"))
        inst = dt.datetime.combine(dt.date.fromisoformat(e["date"]), dt.time(hh, mm), tzinfo=ET)
        mins = (inst - now).total_seconds() / 60.0
        if -after <= mins <= before:
            out.append({"rule": "E1", "would": "hold the entry", "event": e["name"], "minutesToEvent": round(mins)})
            break
    if t1:
        out.append({"rule": "E2", "would": "halve the risk budget", "events": [e["name"] for e in t1][:3]})
    if opt and dte is not None and dte <= 5 and (t1 or (expo or {}).get("earnings")):
        out.append({"rule": "E3", "would": "flatten the short-dated option before the event",
                    "dte": dte, "events": ([e["name"] for e in t1] + (["earnings"] if expo.get("earnings") else []))[:3]})
    return out
