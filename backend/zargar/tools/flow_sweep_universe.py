"""T-12 phase 1b: sweeps as the TRIGGER, scored on the author's tempo.

    python -m zargar.tools.flow_sweep_universe --backfill --start 2026-08-27 --end 2026-09-08 [--near 1] [--symbols A,B]
    python -m zargar.tools.flow_sweep_universe --score --start 2026-08-27 --end 2026-09-08 [--json]

--backfill: for every chain-snapshot day in the range and every universe symbol with a
snapshot that day, take the nearest expiry's call and put just OTM of the snapshot's spot
plus `--near` strikes either side, and backfill their sweeps from Alpaca prints (cached in
`flow_sweeps`, tick-test classification).

--score: every sweep in the range is a trade: buy the contract at the close of the sweep
minute (a proxy for the ask), exit at +100% premium, at -50% premium, or at 15:45 ET,
whichever first, on the contract's own 1-minute bars from Alpaca. Reports the
distribution in premium percent, net of the $1.04 round trip on one contract and a 5%
slippage haircut, overall / by underlying / by hour / first sweep of the day only.

Nothing here trades or changes a rule. The verdict goes to TRADING-RULES T-12.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
import json
import statistics
import sys

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..config import AppConfig
from ..db import create_all
from ..engine import Engine
from ..marketstructure.sessions import session_bounds
from ..models import FlowSweep, OptionChainSnapshot
from ..research.optiontrades import (SweepRules, classify_tick, detect_sweeps, et_minute,
                                     fetch_option_trades)
from ..technique.universe import CORE_UNIVERSE

MIN = 60_000
ET = dt.timezone(dt.timedelta(hours=-4))
BARS_URL = "https://data.alpaca.markets/v1beta1/options/bars"


def _spot_from_chain(rows) -> float | None:
    """Spot ~ the strike where the nearest expiry's call and put mids cross."""
    best = None
    by = collections.defaultdict(dict)
    for r in rows:
        by[(r.expiry, float(r.strike))][r.option_type] = r
    for (exp, k), d in by.items():
        c, p = d.get("call"), d.get("put")
        if c and p and c.mid and p.mid:
            diff = abs(float(c.mid) - float(p.mid))
            if best is None or diff < best[0]:
                best = (diff, k)
    return best[1] if best else None


def near_money(rows, near: int) -> list:
    """Nearest expiry on/after the day; the call and put just OTM of spot and `near` strikes beyond."""
    if not rows:
        return []
    day = rows[0].date
    exps = sorted({r.expiry for r in rows if r.expiry >= day})
    if not exps:
        return []
    exp = exps[0]
    same = [r for r in rows if r.expiry == exp]
    spot = _spot_from_chain(same)
    if spot is None:
        return []
    calls = sorted((r for r in same if r.option_type == "call" and float(r.strike) >= spot), key=lambda r: float(r.strike))
    puts = sorted((r for r in same if r.option_type == "put" and float(r.strike) <= spot), key=lambda r: -float(r.strike))
    return calls[: near + 1] + puts[: near + 1]


async def backfill(eng, cfg, args) -> int:
    async with eng.sf() as s:
        days = [r[0] for r in (await s.execute(
            select(OptionChainSnapshot.date).where(OptionChainSnapshot.date >= args.start, OptionChainSnapshot.date <= args.end)
            .distinct().order_by(OptionChainSnapshot.date))).all()]
    symbols = [x.strip().upper() for x in args.symbols.split(",")] if args.symbols else list(CORE_UNIVERSE)
    print(f"backfill: {len(days)} day(s) x {len(symbols)} symbol(s), near={args.near}")
    sem = asyncio.Semaphore(args.concurrency)
    http = httpx.AsyncClient(timeout=60)
    written = skipped = fetched = 0

    async def one(occ: str, day: str, oi: int) -> int:
        nonlocal fetched
        async with eng.sf() as s:
            if (await s.execute(select(FlowSweep.id).where(FlowSweep.occ == occ, FlowSweep.day == day).limit(1))).first():
                return -1
        o, c = session_bounds(day)
        async with sem:
            try:
                trades = await fetch_option_trades(occ, o, c, key=cfg.alpaca_key_id, secret=cfg.alpaca_secret, http=http)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {occ} {day}: {str(exc)[:80]}", file=sys.stderr)
                return 0
        fetched += 1
        sweeps = detect_sweeps(occ, classify_tick(trades), oi, SweepRules())
        if not sweeps:
            return 0
        underlying = "".join(ch for ch in occ[:6] if not ch.isdigit()).rstrip()
        async with eng.sf() as s:
            for sw in sweeps:
                await s.execute(pg_insert(FlowSweep).values(
                    underlying=underlying, occ=occ, day=day, minute_ts=sw.ts, window_contracts=sw.window_contracts,
                    window_buys=sw.window_buys, cumulative=sw.cumulative, oi=sw.oi, vol_oi=sw.vol_oi,
                    big_prints=sw.big_prints, notional=sw.notional, method=sw.method, source="alpaca",
                ).on_conflict_do_nothing(constraint="uq_flow_sweep_occ_minute"))
            await s.commit()
        return len(sweeps)

    for day in days:
        tasks = []
        async with eng.sf() as s:
            rows = (await s.execute(select(OptionChainSnapshot).where(OptionChainSnapshot.date == day,
                                                                      OptionChainSnapshot.underlying.in_(symbols)))).scalars().all()
        by_sym = collections.defaultdict(list)
        for r in rows:
            by_sym[r.underlying].append(r)
        for sym, srows in by_sym.items():
            for r in near_money(srows, args.near):
                tasks.append(one(r.occ, day, int(r.open_interest or 0)))
        res = await asyncio.gather(*tasks)
        w = sum(x for x in res if x > 0)
        sk = sum(1 for x in res if x < 0)
        written += w
        skipped += sk
        print(f"  {day}: {len(by_sym)} symbols, {len(tasks)} contracts, {w} sweep(s) written, {sk} already cached")
    await http.aclose()
    print(f"done: {written} sweep row(s) written, {fetched} contract-days fetched, {skipped} cached")
    return 0


async def _bars(occ: str, day: str, cfg, http) -> list[dict]:
    o, c = session_bounds(day)
    iso = lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = await http.get(BARS_URL, params={"symbols": occ, "timeframe": "1Min", "start": iso(o), "end": iso(c), "limit": 1000},
                       headers={"APCA-API-KEY-ID": cfg.alpaca_key_id, "APCA-API-SECRET-KEY": cfg.alpaca_secret})
    if r.status_code >= 400:
        return []
    return (r.json().get("bars") or {}).get(occ) or []


def score_trade(bars: list[dict], entry_ts: int, *, take: float = 1.0, stop: float = 0.5, flat_hm: tuple[int, int] = (15, 45)) -> dict | None:
    """Buy at the close of the sweep minute; exit on premium +take / -stop / the flat time."""
    from ..brokers.alpaca import parse_rfc3339_ms
    seq = [(parse_rfc3339_ms(str(b["t"])), float(b["o"]), float(b["h"]), float(b["l"]), float(b["c"])) for b in bars]
    seq.sort()
    entry = next((b for b in seq if b[0] >= entry_ts), None)
    if entry is None or entry[4] <= 0:
        return None
    px = entry[4]
    tp, sl = px * (1 + take), px * (1 - stop)
    exit_px, exit_ts, how = None, None, None
    for ts, o, h, l, c in seq:
        if ts <= entry[0]:
            continue
        t = dt.datetime.fromtimestamp(ts / 1000, ET)
        if (t.hour, t.minute) >= flat_hm:
            exit_px, exit_ts, how = c, ts, "flat"
            break
        if l <= sl:                                 # stop first when a bar straddles both (pessimistic)
            exit_px, exit_ts, how = sl, ts, "stop"
            break
        if h >= tp:
            exit_px, exit_ts, how = tp, ts, "take"
            break
    if exit_px is None:
        last = seq[-1]
        exit_px, exit_ts, how = last[4], last[0], "close"
    gross = (exit_px - px) / px
    net_dollars = (exit_px - px) * 100 - 1.04 - 0.05 * px * 100 * 2 * 0.5   # fees + a 5% slippage haircut across the round trip
    return {"entry": round(px, 2), "exit": round(exit_px, 2), "how": how, "pct": round(gross * 100, 1),
            "netPct": round(net_dollars / (px * 100) * 100, 1), "entryTs": entry[0], "exitTs": exit_ts,
            "minutes": int((exit_ts - entry[0]) / MIN)}


async def score(eng, cfg, args) -> int:
    async with eng.sf() as s:
        sweeps = (await s.execute(select(FlowSweep).where(FlowSweep.day >= args.start, FlowSweep.day <= args.end)
                                  .order_by(FlowSweep.day, FlowSweep.occ, FlowSweep.minute_ts))).scalars().all()
    print(f"score: {len(sweeps)} sweep(s) in {args.start}..{args.end}")
    http = httpx.AsyncClient(timeout=60)
    bars_cache: dict = {}
    sem = asyncio.Semaphore(args.concurrency)
    rows = []

    async def one(sw):
        key = (sw.occ, sw.day)
        if key not in bars_cache:
            async with sem:
                bars_cache[key] = await _bars(sw.occ, sw.day, cfg, http)
        tr = score_trade(bars_cache[key], sw.minute_ts)
        if tr is None:
            return None
        return {"day": sw.day, "underlying": sw.underlying, "occ": sw.occ, "minute": et_minute(sw.minute_ts), "volOi": round(sw.vol_oi, 1),
                "windowBuys": sw.window_buys, **tr}
    for r in await asyncio.gather(*(one(sw) for sw in sweeps)):
        if r:
            rows.append(r)
    await http.aclose()
    # first sweep of the day per contract, and per underlying
    first_contract = {}
    for r in sorted(rows, key=lambda x: (x["day"], x["occ"], x["entryTs"])):
        first_contract.setdefault((r["day"], r["occ"]), r)
    first_und = {}
    for r in sorted(rows, key=lambda x: (x["day"], x["underlying"], x["entryTs"])):
        first_und.setdefault((r["day"], r["underlying"]), r)

    def agg(xs):
        if not xs:
            return {"n": 0}
        pct = [x["netPct"] for x in xs]
        return {"n": len(xs), "winRate": round(sum(1 for p in pct if p > 0) / len(xs), 2), "meanNetPct": round(statistics.mean(pct), 1),
                "medianNetPct": round(statistics.median(pct), 1), "sumNetPct": round(sum(pct), 0),
                "how": dict(collections.Counter(x["how"] for x in xs))}
    report = {"sweeps": len(sweeps), "scored": len(rows), "all": agg(rows),
              "firstPerContract": agg(list(first_contract.values())), "firstPerUnderlying": agg(list(first_und.values())),
              "byHour": {h: agg([x for x in rows if x["minute"][:2] == h]) for h in sorted({x["minute"][:2] for x in rows})},
              "byUnderlying": {u: agg([x for x in rows if x["underlying"] == u]) for u in sorted({x["underlying"] for x in rows})},
              "best": sorted(rows, key=lambda x: -x["netPct"])[:8], "worst": sorted(rows, key=lambda x: x["netPct"])[:5]}
    if args.json:
        print(json.dumps(report, indent=1, default=str))
        return 0
    print("ALL               ", report["all"])
    print("first per contract", report["firstPerContract"])
    print("first per name    ", report["firstPerUnderlying"])
    for h, v in report["byHour"].items():
        print(f"  {h}:xx {v}")
    top = sorted(report["byUnderlying"].items(), key=lambda kv: -kv[1].get("n", 0))[:12]
    for u, v in top:
        print(f"  {u:6} {v}")
    print("best:", [(x["day"], x["occ"], x["minute"], x["netPct"], x["how"]) for x in report["best"]])
    print("worst:", [(x["day"], x["occ"], x["minute"], x["netPct"], x["how"]) for x in report["worst"]])
    return 0


async def run(args) -> int:
    cfg = AppConfig()
    if not (cfg.alpaca_key_id and cfg.alpaca_secret):
        print("Alpaca keys are not configured", file=sys.stderr)
        return 2
    eng = Engine(cfg)
    await create_all(eng.db)
    try:
        if args.backfill:
            return await backfill(eng, cfg, args)
        if args.score:
            return await score(eng, cfg, args)
        print("pass --backfill or --score", file=sys.stderr)
        return 1
    finally:
        await eng.db.dispose()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="T-12 phase 1b: sweeps as the trigger")
    p.add_argument("--backfill", action="store_true")
    p.add_argument("--score", action="store_true")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--near", type=int, default=1, help="strikes beyond the just-OTM one, each side")
    p.add_argument("--symbols", help="comma list; default = the core universe")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    return asyncio.run(run(a))


if __name__ == "__main__":
    sys.exit(main())
