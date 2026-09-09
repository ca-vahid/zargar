"""T-12 on history: score a replay's FIRED triggers by whether a sweep confirmed them
(FLOW-CONFIRMATION-PLAN phase 1).

    python -m zargar.tools.flow_variant --sweep 4a4a8fb7 --sweep f5781133 [--before 15 --after 10] [--include-invalid] [--json]

For every fired trigger in the given walk-forward sweeps this tool
  1. rebuilds the contract our runner would have bought (T5.1/T5.2 from the day's chain
     snapshot: nearest expiry, first strike just OTM in the trade direction) plus one
     strike either side (decision D2),
  2. backfills sweeps for those contracts on that session from Alpaca prints (cached in
     `flow_sweeps`; tick-test classification, see research/optiontrades.py),
  3. marks the fire CONFIRMED when a sweep printed inside [touch - before, touch + after],
  4. reports R with and without the gate, per kind and per session, against the adopt bar
     (D7: +0.3R/fire and no more than half the fires lost... the gate can only remove fires).

The gate is evaluated on the replay's own fills and exits: a confirmed fire keeps the
replay's R, an unconfirmed one is dropped. Nothing here changes a rule; the verdict is
recorded by hand in TRADING-RULES T-12.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
import json
import sys

from sqlalchemy import select

from ..config import AppConfig
from ..db import create_all
from ..engine import Engine
from ..marketstructure.sessions import session_bounds
from ..models import FlowSweep, OptionChainSnapshot, TechniqueSweep
from ..research.optiontrades import (SweepRules, classify_tick, detect_sweeps, et_minute,
                                     fetch_option_trades)
from ..technique.options import choose_expiry, select_contract

MIN = 60_000
ET = dt.timezone(dt.timedelta(hours=-4))


def _chain_rows(rows) -> list[dict]:
    out = []
    for r in rows:
        out.append({"symbol": r.occ, "underlying": r.underlying, "expiry": r.expiry, "option_type": r.option_type,
                    "strike": float(r.strike), "bid": float(r.bid or 0), "ask": float(r.ask or 0),
                    "volume": int(r.volume or 0), "open_interest": int(r.open_interest or 0),
                    "greeks": {"delta": r.delta, "theta": None, "mid_iv": r.iv}})
    return out


def _neighbours(chain: list[dict], occ: str) -> list[str]:
    me = next((c for c in chain if c["symbol"] == occ), None)
    if not me:
        return [occ]
    same = sorted((c for c in chain if c["expiry"] == me["expiry"] and c["option_type"] == me["option_type"]),
                  key=lambda c: c["strike"])
    i = next((k for k, c in enumerate(same) if c["symbol"] == occ), None)
    if i is None:
        return [occ]
    picks = [same[i]] + ([same[i - 1]] if i > 0 else []) + ([same[i + 1]] if i + 1 < len(same) else [])
    return [c["symbol"] for c in picks]


async def _sweeps_for(eng, occ: str, day: str, oi: int, cfg, sem: asyncio.Semaphore, cache: dict) -> list[int]:
    """Sweep minutes for a contract on a day: from flow_sweeps if present, else backfilled now."""
    key = (occ, day)
    if key in cache:
        return cache[key]
    async with eng.sf() as s:
        rows = (await s.execute(select(FlowSweep).where(FlowSweep.occ == occ, FlowSweep.day == day))).scalars().all()
        done = (await s.execute(select(FlowSweep.id).where(FlowSweep.occ == occ, FlowSweep.day == day).limit(1))).first()
    if rows:
        cache[key] = [r.minute_ts for r in rows]
        return cache[key]
    o, c = session_bounds(day)
    async with sem:
        try:
            trades = await fetch_option_trades(occ, o, c, key=cfg.alpaca_key_id, secret=cfg.alpaca_secret)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {occ} {day}: {exc}", file=sys.stderr)
            cache[key] = []
            return []
    minutes = classify_tick(trades)
    sweeps = detect_sweeps(occ, minutes, oi, SweepRules())
    underlying = "".join(ch for ch in occ[:6] if not ch.isdigit()).rstrip() or occ[:4]
    if sweeps:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        async with eng.sf() as s:
            for sw in sweeps:
                await s.execute(pg_insert(FlowSweep).values(
                    underlying=underlying, occ=occ, day=day, minute_ts=sw.ts, window_contracts=sw.window_contracts,
                    window_buys=sw.window_buys, cumulative=sw.cumulative, oi=sw.oi, vol_oi=sw.vol_oi,
                    big_prints=sw.big_prints, notional=sw.notional, method=sw.method, source="alpaca",
                ).on_conflict_do_nothing(constraint="uq_flow_sweep_occ_minute"))
            await s.commit()
    cache[key] = [sw.ts for sw in sweeps]
    return cache[key]


async def run(args) -> int:
    cfg = AppConfig()
    if not (cfg.alpaca_key_id and cfg.alpaca_secret):
        print("Alpaca keys are not configured", file=sys.stderr)
        return 2
    eng = Engine(cfg)
    await create_all(eng.db)
    # --- collect fired triggers from the replay sweeps
    fires: list[dict] = []
    async with eng.sf() as s:
        for pre in args.sweep:
            sw = (await s.execute(select(TechniqueSweep).where(TechniqueSweep.id.like(pre + "%")))).scalar_one_or_none()
            if sw is None:
                print(f"sweep {pre} not found", file=sys.stderr)
                continue
            from ..models import TechniqueWalkforward
            rows = (await s.execute(select(TechniqueWalkforward).where(TechniqueWalkforward.sweep_id == sw.id))).scalars().all()
            for row in rows:
                res = row.result if isinstance(row.result, dict) else json.loads(row.result or "{}")
                for t in res.get("triggers") or []:
                    if t.get("status") != "fired" or not t.get("firedTs"):
                        continue
                    if not t.get("valid") and not args.include_invalid:
                        continue
                    fires.append({"symbol": row.symbol, "session": row.plan_for, "trigger": t["id"], "kind": t.get("kind"),
                                  "direction": "short" if t.get("kind") in ("reject", "breakdown") else "long",
                                  "firedTs": int(t["firedTs"]), "entry": float(t.get("fillPrice") or t.get("entry") or 0),
                                  "valid": bool(t.get("valid")), "r": float((t.get("sim") or {}).get("rMultiple") or 0),
                                  "outcome": (t.get("sim") or {}).get("outcome"), "window": t.get("firedWindow")})
    print(f"{len(fires)} fired trigger(s) from {len(args.sweep)} sweep(s)")
    # --- contracts + sweeps per fire
    sem = asyncio.Semaphore(4)
    cache: dict = {}
    chains: dict = {}
    scored = []
    for f in fires:
        key = (f["symbol"], f["session"])
        if key not in chains:
            async with eng.sf() as s:
                rows = (await s.execute(select(OptionChainSnapshot).where(
                    OptionChainSnapshot.underlying == f["symbol"], OptionChainSnapshot.date == f["session"]))).scalars().all()
            chains[key] = _chain_rows(rows)
        chain = chains[key]
        if not chain:
            f["contract"] = None
            f["reason"] = "no chain snapshot"
            scored.append(f)
            continue
        today = dt.date.fromisoformat(f["session"])
        expiry, is_0dte = choose_expiry(sorted({c["expiry"] for c in chain}), today)
        pick = select_contract(chain, f["entry"], f["direction"], expiry=expiry, today=today, is_0dte=is_0dte) if expiry else None
        if pick is None:
            f["contract"] = None
            f["reason"] = "no contract just OTM"
            scored.append(f)
            continue
        occs = _neighbours(chain, pick.symbol)
        oi_by = {c["symbol"]: c["open_interest"] for c in chain}
        hits = []
        for occ in occs:
            minutes = await _sweeps_for(eng, occ, f["session"], oi_by.get(occ, 0), cfg, sem, cache)
            for m in minutes:
                if f["firedTs"] - args.before * MIN <= m <= f["firedTs"] + args.after * MIN:
                    hits.append((occ, m))
        f["contract"] = pick.symbol
        f["contracts"] = occs
        f["confirmed"] = bool(hits)
        f["sweeps"] = [(o, et_minute(m)) for o, m in hits]
        scored.append(f)
    await eng.db.dispose()
    # --- report
    with_c = [f for f in scored if f.get("contract")]
    conf = [f for f in with_c if f.get("confirmed")]
    unconf = [f for f in with_c if not f.get("confirmed")]
    def stat(xs):
        n = len(xs); r = sum(x["r"] for x in xs); w = sum(1 for x in xs if x["r"] > 0)
        return {"fires": n, "sumR": round(r, 2), "avgR": round(r / n, 3) if n else None, "wins": w}
    report = {"fires": len(fires), "withContract": len(with_c), "noChain": len([f for f in scored if not f.get("contract")]),
              "all": stat(with_c), "confirmed": stat(conf), "unconfirmed": stat(unconf),
              "byKind": {k: {"all": stat([f for f in with_c if f["kind"] == k]), "confirmed": stat([f for f in conf if f["kind"] == k])}
                         for k in sorted({f["kind"] for f in with_c})},
              "bySession": {d: {"all": stat([f for f in with_c if f["session"] == d]), "confirmed": stat([f for f in conf if f["session"] == d])}
                            for d in sorted({f["session"] for f in with_c})},
              "confirmedFires": [{k: f[k] for k in ("session", "symbol", "trigger", "kind", "r", "outcome", "contract", "sweeps")} for f in conf],
              "params": {"before": args.before, "after": args.after, "includeInvalid": args.include_invalid, "sweeps": args.sweep}}
    if args.json:
        print(json.dumps(report, indent=1, default=str))
        return 0
    print(f"fires with a contract: {len(with_c)} (no chain: {report['noChain']})")
    print(f"  ALL         {report['all']}")
    print(f"  CONFIRMED   {report['confirmed']}")
    print(f"  UNCONFIRMED {report['unconfirmed']}")
    for k, v in report["byKind"].items():
        print(f"  {k:10} all {v['all']} | confirmed {v['confirmed']}")
    for d, v in report["bySession"].items():
        print(f"  {d} all {v['all']} | confirmed {v['confirmed']}")
    for f in conf:
        print(f"   + {f['session']} {f['symbol']} {f['trigger']} {f['kind']} R {f['r']:+.2f} {f['outcome']} via {f['sweeps']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="T-12 on history: confirmed vs unconfirmed replay fires")
    p.add_argument("--sweep", action="append", required=True, help="walk-forward sweep id (prefix ok), repeatable")
    p.add_argument("--before", type=int, default=15, help="minutes before the touch a sweep may sit")
    p.add_argument("--after", type=int, default=10, help="minutes after the touch to wait (D3)")
    p.add_argument("--include-invalid", action="store_true")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    return asyncio.run(run(a))


if __name__ == "__main__":
    sys.exit(main())
