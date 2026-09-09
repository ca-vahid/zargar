"""Backfill option sweeps from Alpaca prints (FLOW-CONFIRMATION-PLAN phase 0/1).

    python -m zargar.tools.optiontrades_backfill --occ TSLA260831C00360000 --day 2026-08-31
    python -m zargar.tools.optiontrades_backfill --occ GPRO260918C00001000 --day 2026-08-31 --oi 2733 --dry
    python -m zargar.tools.optiontrades_backfill --underlying NVDA --day 2026-09-04 --near 3   # contracts near the money

Open interest comes from the nightly chain snapshot of that day (`option_chain_snapshots`),
`--oi` overrides it (the author quotes the morning figure, which can differ). `--dry`
prints the per-minute flow and the sweeps without writing. Reads the same Alpaca keys
the engine uses (ZARGAR_ALPACA_KEY_ID / ZARGAR_ALPACA_SECRET in backend/.env).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..config import AppConfig
from ..db import create_all
from ..engine import Engine
from ..marketstructure.sessions import session_bounds
from ..models import FlowSweep, OptionChainSnapshot
from ..research.optiontrades import (SweepRules, classify_tick, detect_sweeps, et_minute,
                                     fetch_option_trades)


async def snapshot_oi(db, occ: str, day: str) -> int | None:
    async with db.sf() as s:
        row = (await s.execute(select(OptionChainSnapshot).where(OptionChainSnapshot.occ == occ,
                                                                 OptionChainSnapshot.date <= day)
                               .order_by(OptionChainSnapshot.date.desc()).limit(1))).scalar_one_or_none()
    return int(row.open_interest) if row is not None else None


async def near_money_contracts(db, underlying: str, day: str, near: int) -> list[str]:
    """The `near` strikes either side of the spot in the day's snapshot, nearest expiry."""
    async with db.sf() as s:
        rows = (await s.execute(select(OptionChainSnapshot).where(OptionChainSnapshot.underlying == underlying.upper(),
                                                                  OptionChainSnapshot.date == day))).scalars().all()
    if not rows:
        return []
    exp = min(r.expiry for r in rows if r.expiry >= day) if any(r.expiry >= day for r in rows) else min(r.expiry for r in rows)
    same = [r for r in rows if r.expiry == exp]
    mids = [r for r in same if r.mid]
    spot = None
    calls = sorted((r for r in same if r.option_type == "call"), key=lambda r: r.strike)
    puts = sorted((r for r in same if r.option_type == "put"), key=lambda r: r.strike)
    # spot ~ the strike where call and put mids cross
    best = None
    for c in calls:
        p = next((x for x in puts if x.strike == c.strike), None)
        if p and c.mid and p.mid:
            d = abs(c.mid - p.mid)
            if best is None or d < best[0]:
                best = (d, c.strike)
    spot = best[1] if best else (calls[len(calls) // 2].strike if calls else None)
    if spot is None:
        return []
    out = []
    for side in (calls, puts):
        ranked = sorted(side, key=lambda r: abs(r.strike - spot))[: max(1, near)]
        out.extend(r.occ for r in ranked)
    return sorted(set(out))


async def run(args) -> int:
    cfg = AppConfig()
    if not (cfg.alpaca_key_id and cfg.alpaca_secret):
        print("Alpaca keys are not configured (ZARGAR_ALPACA_KEY_ID / ZARGAR_ALPACA_SECRET)", file=sys.stderr)
        return 2
    eng = Engine(cfg)                      # no brokers/feeds started: just the session factory
    await create_all(eng.db)
    db = eng
    day = args.day
    o, c = session_bounds(day)
    occs = list(args.occ or [])
    if args.underlying:
        occs += await near_money_contracts(db, args.underlying, day, args.near)
    if not occs:
        print("no contracts to scan (pass --occ or --underlying with a snapshot for that day)", file=sys.stderr)
        return 1
    rules = SweepRules()
    written = 0
    for occ in occs:
        trades = await fetch_option_trades(occ, o, c, key=cfg.alpaca_key_id, secret=cfg.alpaca_secret)
        minutes = classify_tick(trades)
        oi = args.oi if args.oi is not None else (await snapshot_oi(db, occ, day) or 0)
        sweeps = detect_sweeps(occ, minutes, oi, rules)
        total = sum(m.contracts for m in minutes)
        print(f"{occ} {day}: {len(trades)} prints, {total} contracts, OI {oi} ({total / max(oi, 1):.1f}x) -> {len(sweeps)} sweep(s)")
        for sw in sweeps:
            print(f"   {et_minute(sw.ts)} ET  window {sw.window_buys} buys / {sw.window_contracts} contracts, "
                  f"cumulative {sw.cumulative} = {sw.vol_oi:.1f}x OI, big prints {sw.big_prints}")
        if args.dry or not sweeps:
            if args.dry and args.verbose:
                for m in minutes:
                    print(f"      {et_minute(m.ts)} {m.contracts:6d} buys {m.buys:6d} prints {m.prints:4d} big {m.big_prints}")
            continue
        underlying = "".join(ch for ch in occ[:6] if not ch.isdigit()).rstrip() or occ[:4]
        async with db.sf() as s:
            for sw in sweeps:
                stmt = pg_insert(FlowSweep).values(
                    underlying=underlying, occ=occ, day=day, minute_ts=sw.ts,
                    window_contracts=sw.window_contracts, window_buys=sw.window_buys, cumulative=sw.cumulative,
                    oi=sw.oi, vol_oi=sw.vol_oi, big_prints=sw.big_prints, notional=sw.notional,
                    method=sw.method, source="alpaca",
                ).on_conflict_do_nothing(constraint="uq_flow_sweep_occ_minute")
                await s.execute(stmt)
            await s.commit()
        written += len(sweeps)
    print(f"wrote {written} sweep row(s)" if not args.dry else "dry run, nothing written")
    await eng.db.dispose()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="backfill option sweeps from Alpaca prints")
    p.add_argument("--occ", action="append", help="unpadded OCC contract (repeatable)")
    p.add_argument("--underlying", help="scan the near-the-money contracts of this symbol (needs a chain snapshot for the day)")
    p.add_argument("--near", type=int, default=3, help="strikes either side of the money to scan")
    p.add_argument("--day", required=True, help="ET session date YYYY-MM-DD")
    p.add_argument("--oi", type=int, help="override open interest")
    p.add_argument("--dry", action="store_true")
    p.add_argument("--verbose", action="store_true")
    a = p.parse_args(argv)
    return asyncio.run(run(a))


if __name__ == "__main__":
    sys.exit(main())
