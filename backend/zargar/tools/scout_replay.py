"""Scout P2 - historical replay of the SCREENS (no LLM - PLAN F5), after costs. Research only, read-only.

    python -m zargar.tools.scout_replay s1 --start 2018-01-01 --end 2026-09-30
    python -m zargar.tools.scout_replay s2 --start 2023-01-01 --end 2026-09-30
    python -m zargar.tools.scout_replay s1 --start 2018-01-01 --end 2026-09-30 --set min_insider_value_usd=0 --label v1

What it does (the same pure code the live desk runs: `screens.screen_s1` / `measure_reaction` / `screen_s2`,
`classify.classify_one`, `service.shares_market_cap`):

* **S1** - every officer/director open-market purchase in `scout_insider_trades` is replayed point in time
  (signal = filing acceptance; CMP labels from past trades only) into clusters, for the opportunistic kind
  AND the unclassified variant.
* **S2** - every 8-K item 2.02 of the companies listed today on NYSE / Nasdaq (SEC `company_tickers_exchange`,
  per-issuer submissions JSON) is measured (day 0..+1 abnormal return vs SPY, volume ratio), de-duplicated per
  company and day 0, ranked per day 0; the top decile on volume is the signal, every OTHER gate-passing
  reporter of the same days is the baseline (the historical analog of the peer-matched random book).
* **Gates** applied: price, 20-day dollar volume (raw prices), market cap (SEC shares fact filed before the
  signal x raw close). NOT applied (no point-in-time source): the live entry spread, earnings-in-hold,
  corporate actions, Tips mentions. The spread is charged as an assumed half spread per side instead.
* **Trade**: buy at the entry session's OPEN (the live rule buys at 10:00 ET - the open is the daily-bar
  proxy), stop = entry - 2 x 14-day ATR (a touch exits at the stop, a gap below exits at the open), time exit
  at the close of the last hold session; split/dividend-adjusted prices. Costs: $1 per order on the position
  size + the assumed half spread each side.

Known biases, stated in every report: S2's universe is TODAY's listings (survivorship - delisted losers are
missing, results flatter the screen); a ticker with no price history is counted and dropped; daily bars cannot
see the 10:00 quote. Every run appends its parameters and headline to `VARIANTS.jsonl` (PLAN F9: a backtest
means nothing without the number of variants tried).

Places no orders, writes nothing to the database. Bars / SEC answers are cached under `--cache`.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import gzip
import json
import math
import os
import statistics
import tempfile
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import httpx
from sqlalchemy import text

from ..db import make_engine, make_session_factory
from ..domain import Bar
from ..marketstructure import market_calendar as mcal
from ..techniques.scout.classify import Classification, classify_one
from ..techniques.scout.edgar import DEFAULT_UA, EdgarClient, EdgarError
from ..techniques.scout.form4 import ET, submissions_json_acceptance
from ..techniques.scout.screens import (S1Params, S2Params, add_sessions, dedupe_reactions, measure_reaction,
                                        s1_purchases, screen_s1, screen_s2)
from ..techniques.scout.service import shares_market_cap

ALPACA_BARS = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"
EXCHANGES = {"NYSE", "Nasdaq"}


# =========================================================================== pure: trade + statistics
def simulate_trade(rows: list[list], entry_date: str, hold: int, *, atr_days: int = 14, stop_mult: float = 2.0) -> dict | None:
    """`rows` = adjusted daily [date, o, h, l, c, v], oldest first. None when the trade cannot be priced
    (no bar within 3 sessions of the entry date, or fewer than `atr_days` + 1 prior sessions)."""
    idx = next((i for i, r in enumerate(rows) if r[0] >= entry_date), None)
    if idx is None or idx < atr_days + 1:
        return None
    if rows[idx][0] != entry_date and rows[idx][0] > add_sessions(entry_date, 3):
        return None
    prior = rows[idx - atr_days - 1:idx]
    trs = [max(c[2] - c[3], abs(c[2] - p[4]), abs(c[3] - p[4])) for p, c in zip(prior, prior[1:])]
    atr = sum(trs) / len(trs) if trs else 0.0
    entry = float(rows[idx][1])
    stop = entry - stop_mult * atr
    if entry <= 0 or atr <= 0 or stop <= 0:
        return None
    exit_px, exit_date, reason = None, None, None
    for k in range(hold):
        j = idx + k
        if j >= len(rows):
            exit_px, exit_date, reason = float(rows[-1][4]), rows[-1][0], "data_end"
            break
        d, o, h, lo, c = rows[j][0], float(rows[j][1]), float(rows[j][2]), float(rows[j][3]), float(rows[j][4])
        if k > 0 and o <= stop:
            exit_px, exit_date, reason = o, d, "gap"
            break
        if lo <= stop:
            exit_px, exit_date, reason = stop, d, "stop"
            break
        if k == hold - 1:
            exit_px, exit_date, reason = c, d, "time"
    return {"entryDate": rows[idx][0], "entry": entry, "atr": atr, "stop": stop, "exitDate": exit_date,
            "exit": exit_px, "reason": reason, "gross": exit_px / entry - 1.0}


def gate_facts(raw: list[list], entry_date: str, *, adv_days: int = 20) -> dict:
    """Point-in-time price / dollar-volume facts from RAW daily bars (sessions before the entry)."""
    prior = [r for r in raw if r[0] < entry_date][-adv_days:]
    if not prior:
        return {"close": None, "adv": None}
    adv = sum(float(r[4]) * float(r[5]) for r in prior) / len(prior) if len(prior) >= adv_days else None
    return {"close": float(prior[-1][4]), "adv": adv}


def stats(xs: list[float]) -> dict:
    n = len(xs)
    if not n:
        return {"n": 0}
    mean = sum(xs) / n
    sd = statistics.stdev(xs) if n > 1 else 0.0
    return {"n": n, "mean": mean, "median": statistics.median(xs), "hit": sum(1 for x in xs if x > 0) / n,
            "t": (mean / (sd / math.sqrt(n))) if sd > 0 else None}


def clustered(trades: list[dict], field: str) -> dict:
    """Month-clustered mean and t: overlapping holds inside a month are one observation."""
    by: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        by[t["entryDate"][:7]].append(t[field])
    means = [sum(v) / len(v) for v in by.values()]
    s = stats(means)
    return {"months": s.get("n", 0), "mean": s.get("mean"), "t": s.get("t")}


def summarize(trades: list[dict]) -> dict:
    by_year: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_year[t["entryDate"][:4]].append(t)

    def block(ts):
        return {"net": stats([t["net"] for t in ts]), "gross": stats([t["gross"] for t in ts]),
                "abnormalNet": stats([t["net"] - t["bench"] for t in ts]),
                "exits": {r: sum(1 for t in ts if t["reason"] == r) for r in ("time", "stop", "gap", "data_end")}}
    return {"all": {**block(trades), "netByMonth": clustered(trades, "net"),
                    "abnormalByMonth": clustered([{**t, "ab": t["net"] - t["bench"]} for t in trades], "ab")},
            "byYear": {y: block(ts) for y, ts in sorted(by_year.items())}}


# =========================================================================== data (cached)
class Data:
    def __init__(self, cache: Path, key: str, secret: str, ua: str):
        self.cache = cache
        (cache / "bars").mkdir(parents=True, exist_ok=True)
        (cache / "sec").mkdir(parents=True, exist_ok=True)
        self.headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        self.http = httpx.AsyncClient(timeout=30)
        self.edgar = EdgarClient(user_agent=ua, max_rps=8.0)
        self.sem = asyncio.Semaphore(8)
        self.start = "2014-06-01"
        self.end = dt.date.today().isoformat()

    async def aclose(self):
        await self.http.aclose()
        await self.edgar.aclose()

    @staticmethod
    def _read(p: Path):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def _write(p: Path, obj) -> None:
        tmp = p.with_suffix(p.suffix + ".part")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(obj, fh)
        tmp.replace(p)

    async def _alpaca(self, sym: str, adjustment: str) -> list[list]:
        params = {"timeframe": "1Day", "start": self.start + "T00:00:00Z", "end": self.end + "T00:00:00Z",
                  "limit": 10000, "feed": "sip", "adjustment": adjustment}
        out, token = [], None
        for _ in range(10):
            if token:
                params["page_token"] = token
            for attempt in range(5):
                r = await self.http.get(ALPACA_BARS.format(symbol=sym), params=params, headers=self.headers)
                if r.status_code != 429:
                    break
                await asyncio.sleep(2.0 * (attempt + 1))
            if r.status_code >= 400:
                return out
            data = r.json()
            out += [[str(b["t"])[:10], b["o"], b["h"], b["l"], b["c"], b.get("v") or 0] for b in data.get("bars") or []]
            token = data.get("next_page_token")
            if not token:
                break
        return out

    async def bars(self, sym: str) -> dict:
        """{'raw': rows, 'adj': rows} for one symbol, whole window, cached on disk."""
        p = self.cache / "bars" / f"{sym.replace('/', '_')}.json.gz"
        if p.exists():
            return self._read(p)
        async with self.sem:
            try:
                raw, adj = await asyncio.gather(self._alpaca(sym, "raw"), self._alpaca(sym, "all"))
            except httpx.HTTPError:
                return {"raw": [], "adj": []}
        obj = {"raw": raw, "adj": adj}
        self._write(p, obj)
        return obj

    async def shares(self, cik: str) -> dict:
        p = self.cache / "sec" / f"shares-{int(cik)}.json.gz"
        if p.exists():
            return self._read(p)
        try:
            data = await self.edgar.shares_outstanding(cik) or {}
        except EdgarError:
            return {}
        slim = {"units": {"shares": [{k: f.get(k) for k in ("end", "val", "accn", "filed", "frame")}
                                      for f in ((data.get("units") or {}).get("shares") or [])]}}
        self._write(p, slim)
        return slim

    async def earnings_events(self, cik: str, start: str) -> list[dict]:
        """8-K item 2.02 filings of one issuer since `start`: [{accession, acceptance (ISO, true instant)}]."""
        p = self.cache / "sec" / f"e202-{int(cik)}-{start}.json.gz"
        if p.exists():
            return self._read(p)
        try:
            data = await self.edgar.submissions(cik)
        except EdgarError:
            return []
        out: list[dict] = []
        if data:
            blocks = [(data.get("filings") or {}).get("recent") or {}]
            recent_dates = blocks[0].get("filingDate") or []
            if recent_dates and min(recent_dates) > start:
                for f in (data.get("filings") or {}).get("files") or []:
                    if str(f.get("filingTo") or "9999") >= start:
                        try:
                            r = await self.edgar.get(f"https://data.sec.gov/submissions/{f['name']}", allow_404=True)
                            if r is not None:
                                blocks.append(r.json())
                        except (EdgarError, ValueError):
                            pass
            for b in blocks:
                for form, items, acc, at, fd in zip(b.get("form", []), b.get("items", []), b.get("accessionNumber", []),
                                                    b.get("acceptanceDateTime", []), b.get("filingDate", [])):
                    if form == "8-K" and "2.02" in (items or "") and fd >= start:
                        ts = submissions_json_acceptance(at)
                        if ts is not None:
                            out.append({"accession": acc, "acceptance": ts.isoformat()})
        self._write(p, out)
        return out


def _bar_objs(sym: str, rows: list[list]) -> list[Bar]:
    out = []
    for d, o, h, lo, c, v in rows:
        ts = int(dt.datetime.combine(dt.date.fromisoformat(d), dt.time(9, 30), ET).timestamp() * 1000)
        out.append(Bar(sym, "1d", ts, float(o), float(h), float(lo), float(c), int(v or 0)))
    return out


def _window(rows: list[list], lo: str, hi: str) -> list[list]:
    return [r for r in rows if lo <= r[0] <= hi]


class Bench:
    def __init__(self, rows: list[list]):
        self.rows = rows
        self.open = {r[0]: float(r[1]) for r in rows}
        self.close = {r[0]: float(r[4]) for r in rows}

    def ret(self, entry: str, exit_: str) -> float:
        a, b = self.open.get(entry), self.close.get(exit_)
        return (b / a - 1.0) if a and b else 0.0


def _price_trade(tr: dict, bench: Bench, cost: float) -> dict:
    return {**tr, "net": tr["gross"] - cost, "bench": bench.ret(tr["entryDate"], tr["exitDate"])}


# =========================================================================== S1
async def replay_s1(args, data: Data, sf) -> dict:
    p = S1Params(**{**dict(window_days=10, min_insiders=2, min_value_usd=100_000.0, min_insider_value_usd=10_000.0,
                           max_row_value_usd=500_000_000.0), **args.overrides.get("s1", {})})
    lo = (dt.date.fromisoformat(args.start) - dt.timedelta(days=30)).isoformat()
    print(f"S1: loading purchases {lo}..{args.end} and the CMP history", flush=True)
    async with sf() as s:
        ym = (await s.execute(text(
            "select insider_cik, substr(trans_date,1,4)::int y, substr(trans_date,6,2)::int m, "
            "min(coalesce(filed_date, trans_date)) known from scout_insider_trades "
            "where trans_code in ('P','S') and trans_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' "
            "and trans_date >= '2014-01-01' and trans_date < '2030-01-01' "
            "and (filed_date is null or trans_date <= filed_date) group by 1,2,3"))).all()
        rows = (await s.execute(text(
            "select accession, row_key, form_type, issuer_cik, ticker, insider_cik, insider_name, is_director, "
            "is_officer, officer_title, trans_date, trans_code, acq_disp, shares, price, value, filed_date, "
            "acceptance_ts, source from scout_insider_trades where trans_code = 'P' and trans_date >= :lo "
            "and trans_date <= :hi and (is_officer or is_director)"), {"lo": lo, "hi": args.end})).mappings().all()
    hist: dict[str, list[tuple]] = defaultdict(list)
    for cik, y, m, known in ym:
        hist[str(cik)].append((y, m, str(known)[:10]))
    cache: dict[tuple, Classification] = {}

    def classify(cik: str, year: int) -> Classification:
        k = (cik, year)
        if k not in cache:
            cutoff = f"{year - 1}-12-31"
            months: dict[int, set[int]] = defaultdict(set)
            for y, m, known in hist.get(cik, ()):
                if year - 3 <= y <= year - 1 and known <= cutoff:
                    months[y].add(m)
            cache[k] = classify_one(months, year, years=3, coverage_start="2015-01-01")
        return cache[k]

    purchases = s1_purchases([dict(r) for r in rows], p)
    print(f"S1: {len(rows)} purchase rows -> {len(purchases)} qualifying; screening", flush=True)
    hits = {"s1_insider": screen_s1(purchases, classify, p),
            "s1_unclassified": screen_s1(purchases, classify, p, include_unclassified=True)}
    funnel: dict[str, dict] = {}
    todo: dict[str, list] = defaultdict(list)
    for kind, hs in hits.items():
        hs = [h for h in hs if args.start <= h.signal_ts.date().isoformat() <= args.end]
        f = funnel[kind] = {"clusters": len(hs), "noTicker": 0, "noBars": 0, "price": 0, "adv": 0, "marketCap": 0,
                            "marketCapUnknown": 0, "unpriced": 0, "traded": 0}
        for h in hs:
            t = (h.ticker or "").upper()
            if not t.isalpha() or len(t) > 5:
                f["noTicker"] += 1
                continue
            todo[t].append((kind, h))
    print(f"S1: clusters {json.dumps({k: v['clusters'] for k, v in funnel.items()})}; "
          f"{len(todo)} tickers to price", flush=True)
    bench = Bench((await data.bars("SPY"))["adj"])
    cost = 2 * args.fee / args.position + 2 * args.half_spread_pct / 100.0
    trades: dict[str, list[dict]] = defaultdict(list)
    done = 0

    async def one(ticker: str, items: list):
        nonlocal done
        b = await data.bars(ticker)
        for kind, h in items:
            f = funnel[kind]
            if not b["adj"] or not b["raw"]:
                f["noBars"] += 1
                continue
            g = gate_facts(b["raw"], h.entry_date)
            if g["close"] is None or g["close"] < args.min_price:
                f["price"] += 1
                continue
            if g["adv"] is None or g["adv"] < args.min_adv:
                f["adv"] += 1
                continue
            if args.min_cap > 0:
                mcap, _ = shares_market_cap(await data.shares(h.issuer_cik), g["close"], h.signal_ts.date().isoformat())
                if mcap is None:
                    f["marketCapUnknown"] += 1
                    continue
                if mcap < args.min_cap:
                    f["marketCap"] += 1
                    continue
            tr = simulate_trade(b["adj"], h.entry_date, args.s1_hold)
            if tr is None:
                f["unpriced"] += 1
                continue
            f["traded"] += 1
            trades[kind].append({**_price_trade(tr, bench, cost), "ticker": ticker, "value": h.total_value,
                                 "insiders": len(h.insiders)})
        done += 1
        if done % 250 == 0:
            print(f"S1: priced {done}/{len(todo)} tickers", flush=True)

    work = list(todo.items())
    for i in range(0, len(work), 100):                        # bounded fan-out: memory stays flat
        await asyncio.gather(*[one(t, items) for t, items in work[i:i + 100]])
    return {"signal": "s1", "params": asdict(p), "funnel": funnel,
            "lanes": {k: summarize(v) for k, v in trades.items()}, "trades": trades}


# =========================================================================== S2
async def replay_s2(args, data: Data, sf) -> dict:
    p = S2Params(**{**dict(top_pct=10.0, volume_mult=2.0, volume_avg_days=20, entry_offset_sessions=2),
                    **args.overrides.get("s2", {})})
    r = await data.edgar.get("https://www.sec.gov/files/company_tickers_exchange.json")
    j = r.json()
    fi = {n: i for i, n in enumerate(j["fields"])}
    universe: dict[str, str] = {}
    for row in j["data"]:
        t = str(row[fi["ticker"]] or "").upper()
        if row[fi["exchange"]] in EXCHANGES and t.isalpha() and len(t) <= 5:
            universe.setdefault(str(row[fi["cik"]]), t)
    if args.limit:
        universe = dict(sorted(universe.items())[:args.limit])
    print(f"S2: {len(universe)} listed issuers; reading 8-K item 2.02 history since {args.start}", flush=True)
    spy = (await data.bars("SPY"))["adj"]
    bench = Bench(spy)
    cost = 2 * args.fee / args.position + 2 * args.half_spread_pct / 100.0
    events: list[dict] = []
    funnel = {"issuers": len(universe), "events": 0, "noBars": 0, "unmeasured": 0, "duplicates": 0}
    done = 0

    async def one(cik: str, ticker: str):
        nonlocal done
        evs = [e for e in await data.earnings_events(cik, args.start)
               if args.start <= e["acceptance"][:10] <= args.end]
        if evs:
            b = await data.bars(ticker)
            for e in evs:
                funnel["events"] += 1
                if not b["adj"]:
                    funnel["noBars"] += 1
                    continue
                ts = dt.datetime.fromisoformat(e["acceptance"])
                d = ts.astimezone(ET).date()
                lo, hi = (d - dt.timedelta(days=50)).isoformat(), (d + dt.timedelta(days=8)).isoformat()
                rx = measure_reaction({"ticker": ticker, "accession": e["accession"], "acceptance_ts": ts},
                                      _bar_objs(ticker, _window(b["adj"], lo, hi)),
                                      _bar_objs("SPY", _window(spy, lo, hi)), p)
                if rx.abnormal_return is None or rx.volume_ratio is None:
                    funnel["unmeasured"] += 1
                    continue
                entry = add_sessions(rx.day0, p.entry_offset_sessions)
                events.append({"rx": rx, "cik": cik, "entry": entry, "gate": gate_facts(b["raw"], entry),
                               "trade": simulate_trade(b["adj"], entry, args.s2_hold)})
        done += 1
        if done % 500 == 0:
            print(f"S2: read {done}/{len(universe)} issuers, {len(events)} measured events", flush=True)

    items = list(universe.items())
    for i in range(0, len(items), 200):                      # bounded fan-out: memory stays flat
        await asyncio.gather(*[one(c, t) for c, t in items[i:i + 200]])
    kept, dups = dedupe_reactions([e["rx"] for e in events])
    funnel["duplicates"] = len(dups)
    keep_ids = {id(x) for x in kept}
    events = [e for e in events if id(e["rx"]) in keep_ids]
    hits, _ = screen_s2(kept, p)
    hit_ids = {id(h.reaction) for h in hits}
    lanes: dict[str, list[dict]] = {"s2_selected": [], "s2_baseline_other_reporters": []}
    gf = {k: {"n": 0, "price": 0, "adv": 0, "marketCap": 0, "marketCapUnknown": 0, "unpriced": 0, "traded": 0}
          for k in lanes}
    print(f"S2: {len(events)} events after dedupe, {len(hits)} top-decile-on-volume hits; applying gates", flush=True)
    for e in events:
        lane = "s2_selected" if id(e["rx"]) in hit_ids else "s2_baseline_other_reporters"
        f, g = gf[lane], e["gate"]
        f["n"] += 1
        if g["close"] is None or g["close"] < args.min_price:
            f["price"] += 1
            continue
        if g["adv"] is None or g["adv"] < args.min_adv:
            f["adv"] += 1
            continue
        if args.min_cap > 0:
            mcap, _ = shares_market_cap(await data.shares(e["cik"]), g["close"], e["rx"].day1)
            if mcap is None:
                f["marketCapUnknown"] += 1
                continue
            if mcap < args.min_cap:
                f["marketCap"] += 1
                continue
        if e["trade"] is None:
            f["unpriced"] += 1
            continue
        f["traded"] += 1
        lanes[lane].append({**_price_trade(e["trade"], bench, cost), "ticker": e["rx"].ticker,
                            "abnormalReturn": e["rx"].abnormal_return, "volumeRatio": e["rx"].volume_ratio})
    return {"signal": "s2", "params": asdict(p), "funnel": {**funnel, "lanes": gf},
            "lanes": {k: summarize(v) for k, v in lanes.items()}, "trades": lanes}


# =========================================================================== report
def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:+.2f}%"


def _t(x) -> str:
    return "n/a" if x is None else f"{x:+.2f}"


def render(res: dict, args) -> str:
    cost = 2 * args.fee / args.position + 2 * args.half_spread_pct / 100.0
    L = [f"# Scout replay - {res['signal'].upper()} screen, {args.start} to {args.end}", "",
         f"Run {dt.datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}, label `{args.label}`. Screens only, no LLM. "
         f"Costs charged per trade: {cost * 100:.2f}% round trip (${args.fee:g} per order on ${args.position:g} + "
         f"{args.half_spread_pct:g}% assumed half spread per side).", "",
         f"Parameters: `{json.dumps(res['params'])}`; gates: price >= ${args.min_price:g}, 20-day dollar volume >= "
         f"${args.min_adv / 1e6:g}M, market cap >= ${args.min_cap / 1e6:g}M. Hold: "
         f"{args.s1_hold if res['signal'] == 's1' else args.s2_hold} sessions, stop 2 x ATR(14).", "",
         "**Not applied / known biases:** the live entry-spread gate, earnings-in-hold, corporate-action and Tips gates "
         "(no point-in-time source); entry is the session OPEN, the live rule buys at 10:00 ET; "
         + ("the universe is today's NYSE/Nasdaq listings, so delisted companies are missing (survivorship - results "
            "flatter the screen)." if res["signal"] == "s2" else
            "a ticker with no price history today (renamed, delisted) is dropped and counted under `noBars`."), "",
         "## Funnel", "", "```json", json.dumps(res["funnel"], indent=1), "```", ""]
    for lane, sm in res["lanes"].items():
        a = sm["all"]
        if not a["net"].get("n"):
            L += [f"## {lane}", "", "No priced trades.", ""]
            continue
        L += [f"## {lane}", "",
              f"All years: **{a['net']['n']} trades, mean net {_pct(a['net']['mean'])}** (median {_pct(a['net']['median'])}, "
              f"{a['net']['hit'] * 100:.0f}% winners, t {_t(a['net']['t'])}); gross {_pct(a['gross']['mean'])}; "
              f"net minus SPY over the same days {_pct(a['abnormalNet']['mean'])} (t {_t(a['abnormalNet']['t'])}). "
              f"Month-clustered: net {_pct(a['netByMonth']['mean'])} (t {_t(a['netByMonth']['t'])}, "
              f"{a['netByMonth']['months']} months), net minus SPY {_pct(a['abnormalByMonth']['mean'])} "
              f"(t {_t(a['abnormalByMonth']['t'])}). Exits: {a['exits']}.", "",
              "| Year | Trades | Mean net | Median net | Winners | Mean net - SPY | t (net - SPY) | Stops+gaps |",
              "|---|---|---|---|---|---|---|---|"]
        for y, b in sm["byYear"].items():
            n = b["net"]["n"]
            L.append(f"| {y} | {n} | {_pct(b['net']['mean'])} | {_pct(b['net']['median'])} | {b['net']['hit'] * 100:.0f}% | "
                     f"{_pct(b['abnormalNet']['mean'])} | {_t(b['abnormalNet']['t'])} | "
                     f"{(b['exits']['stop'] + b['exits']['gap']) / n * 100:.0f}% |")
        L.append("")
    return "\n".join(L)


def _parse_set(pairs: list[str]) -> dict:
    out: dict[str, dict] = {"s1": {}, "s2": {}}
    s1 = set(S1Params.__dataclass_fields__)
    for kv in pairs or []:
        k, v = kv.split("=", 1)
        out["s1" if k in s1 else "s2"][k] = int(v) if v.lstrip("-").isdigit() else float(v)
    return out


async def main_async(args) -> None:
    from ..config import AppConfig
    cfg = AppConfig()
    if not (cfg.alpaca_key_id and cfg.alpaca_secret):
        raise SystemExit("Alpaca data keys are required (ZARGAR_ALPACA_KEY_ID / ZARGAR_ALPACA_SECRET)")
    cache = Path(args.cache or Path(tempfile.gettempdir()) / "zargar-scout-replay")
    data = Data(cache, cfg.alpaca_key_id, cfg.alpaca_secret, DEFAULT_UA)
    engine = make_engine(os.environ.get("ZARGAR_DATABASE_URL") or cfg.database_url)
    sf = make_session_factory(engine)
    try:
        res = await (replay_s1 if args.signal == "s1" else replay_s2)(args, data, sf)
    finally:
        await data.aclose()
        await engine.dispose()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{dt.date.today().isoformat()}-{args.signal}-{args.label}"
    (out / f"{stem}.md").write_text(render(res, args), encoding="utf-8")
    with gzip.open(cache / f"{stem}-trades.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(res["trades"], fh)
    head = {lane: {"n": sm["all"]["net"].get("n", 0), "meanNet": sm["all"]["net"].get("mean"),
                   "meanNetMinusSpy": sm["all"].get("abnormalNet", {}).get("mean"),
                   "tClustered": sm["all"].get("abnormalByMonth", {}).get("t")} for lane, sm in res["lanes"].items()}
    with (out / "VARIANTS.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": dt.datetime.now(ET).isoformat(), "signal": args.signal, "label": args.label,
                             "start": args.start, "end": args.end, "params": res["params"],
                             "gates": {"minPrice": args.min_price, "minAdv": args.min_adv, "minCap": args.min_cap},
                             "costs": {"fee": args.fee, "position": args.position, "halfSpreadPct": args.half_spread_pct},
                             "headline": head}) + "\n")
    print(json.dumps(head, indent=1))
    print(f"report: {out / (stem + '.md')}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Scout P2 historical replay of the screens (no LLM, read-only)")
    ap.add_argument("signal", choices=["s1", "s2"])
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--label", default="v2")
    ap.add_argument("--set", action="append", default=[], help="screen parameter override, e.g. min_insider_value_usd=0")
    ap.add_argument("--min-price", type=float, default=5.0)
    ap.add_argument("--min-adv", type=float, default=5_000_000.0)
    ap.add_argument("--min-cap", type=float, default=300_000_000.0)
    ap.add_argument("--position", type=float, default=600.0)
    ap.add_argument("--fee", type=float, default=1.0)
    ap.add_argument("--half-spread-pct", type=float, default=0.15)
    ap.add_argument("--s1-hold", type=int, default=20)
    ap.add_argument("--s2-hold", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0, help="S2: only the first N issuers (smoke test)")
    ap.add_argument("--cache", default="")
    ap.add_argument("--out", default="docs/techniques/scout/replay")
    args = ap.parse_args()
    args.overrides = _parse_set(args.set)
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
