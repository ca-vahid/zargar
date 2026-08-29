"""Flow threshold calibration sweep (NEXT-GAPS FL1) — offline, read-only.

Replays `flag_contracts` over the accumulated `option_chain_snapshots` for a
GRID of candidate thresholds and reports, per combo:

- symbols flagged per day (the noise budget — we want <= ~10),
- contracts flagged per day, and the share that are 0-2 DTE (the noise),
- the overnight OI-confirmation rate on consecutive day pairs (flagged volume
  that became real open interest — the signal), vs the ALL-contracts baseline
  rate (how often any active contract's OI grows that much anyway).

Talks to Postgres directly (no running server needed); spot comes from the
chain itself (put-call parity) so quotes are not required.

    python -m zargar.tools.flow_calibrate [--days N] [--json]
    ZARGAR_REVIEW_DATABASE_URL=... overrides the DB.
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import os
import sys
from collections import defaultdict

from sqlalchemy import select

from ..config import AppConfig
from ..engine import Engine
from ..models import OptionChainSnapshot
from ..techniques.flow.scan import FlowThresholds, confirm_oi, flag_contracts, spot_from_chain

# the candidate grid — small on purpose: every axis is a hypothesis, not a fit
GRID = {
    "dte_min": [0, 2, 3, 5],
    "premium_min": [100_000.0, 250_000.0, 500_000.0],
    "vol_oi_min": [1.25, 2.0, 3.0],
    "min_contract_volume": [500, 1000],
}


def _row(s: OptionChainSnapshot) -> dict:
    return {"symbol": s.occ, "expiry": s.expiry, "strike": s.strike,
            "option_type": s.option_type, "volume": s.volume,
            "open_interest": s.open_interest, "bid": s.bid, "ask": s.ask,
            "last": s.last, "greeks": {"mid_iv": s.iv}}


async def _load(eng, days_limit: int) -> dict[str, dict[str, list[dict]]]:
    """day -> underlying -> rows."""
    async with eng.sf() as session:
        day_rows = (await session.execute(
            select(OptionChainSnapshot.date).distinct()
            .order_by(OptionChainSnapshot.date.desc()).limit(days_limit))).scalars().all()
        days = sorted(day_rows)
        out: dict[str, dict[str, list[dict]]] = {}
        for day in days:
            snaps = (await session.execute(
                select(OptionChainSnapshot).where(OptionChainSnapshot.date == day)
            )).scalars().all()
            by: dict[str, list[dict]] = defaultdict(list)
            for s in snaps:
                by[s.underlying].append(_row(s))
            out[day] = dict(by)
    return out


def _baseline_confirmation(data: dict[str, dict[str, list[dict]]],
                           pairs: list[tuple[str, str]]) -> tuple[int, int]:
    """How often ANY active contract (vol >= 100) grows OI overnight by
    >= 0.5 x its volume — what confirmation rates must beat to mean anything."""
    hits = total = 0
    for d0, d1 in pairs:
        for sym, rows in data[d0].items():
            nxt = {r["symbol"]: int(r["open_interest"] or 0)
                   for r in data[d1].get(sym, [])}
            for r in rows:
                vol = int(r["volume"] or 0)
                if vol < 100 or r["symbol"] not in nxt:
                    continue
                total += 1
                if nxt[r["symbol"]] - int(r["open_interest"] or 0) >= 0.5 * vol:
                    hits += 1
    return hits, total


def _sweep(data: dict[str, dict[str, list[dict]]]) -> list[dict]:
    days = sorted(data)
    pairs = [(days[i], days[i + 1]) for i in range(len(days) - 1)]
    spots: dict[tuple[str, str], float] = {}
    for day, by in data.items():
        for sym, rows in by.items():
            spots[(day, sym)] = spot_from_chain(rows)

    base_hits, base_total = _baseline_confirmation(data, pairs)
    results = []
    for combo in itertools.product(*GRID.values()):
        kw = dict(zip(GRID.keys(), combo))
        t = FlowThresholds(**kw)
        syms_per_day: list[int] = []
        contracts = low_dte = conf_hits = conf_total = 0
        flags_by_day_sym: dict[tuple[str, str], list[dict]] = {}
        for day, by in data.items():
            n_syms = 0
            for sym, rows in by.items():
                spot = spots[(day, sym)]
                if spot <= 0:
                    continue
                fl = flag_contracts(rows, spot=spot, day=day, t=t)
                if fl:
                    n_syms += 1
                    contracts += len(fl)
                    low_dte += sum(1 for f in fl if (f.get("dte") or 0) <= 2)
                    flags_by_day_sym[(day, sym)] = fl
            syms_per_day.append(n_syms)
        for d0, d1 in pairs:
            for sym in data[d0]:
                fl = flags_by_day_sym.get((d0, sym))
                if not fl:
                    continue
                nxt = {r["symbol"]: int(r["open_interest"] or 0)
                       for r in data[d1].get(sym, [])}
                confirmed = confirm_oi(fl, nxt)
                conf_total += len(fl)
                conf_hits += len(confirmed)
        results.append({
            **kw,
            "symsPerDay": round(sum(syms_per_day) / max(len(syms_per_day), 1), 1),
            "contractsPerDay": round(contracts / max(len(days), 1), 1),
            "lowDtePct": round(100 * low_dte / contracts, 1) if contracts else None,
            "oiConfirmPct": round(100 * conf_hits / conf_total, 1) if conf_total else None,
            "confirmN": conf_total,
        })
    results.sort(key=lambda r: (r["symsPerDay"], -(r["oiConfirmPct"] or 0)))
    return [{"_baselineOiConfirmPct": round(100 * base_hits / base_total, 1) if base_total else None,
             "_baselineN": base_total, "_days": days, "_pairs": len(pairs)}] + results


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    cfg = AppConfig()
    if os.environ.get("ZARGAR_REVIEW_DATABASE_URL"):
        cfg = AppConfig(database_url=os.environ["ZARGAR_REVIEW_DATABASE_URL"])
    eng = Engine(cfg)
    try:
        from ..db import create_all
        await create_all(eng.db)
        data = await _load(eng, args.days)
        if len(data) < 2:
            print(f"only {len(data)} snapshot day(s) — need >= 2 for OI confirmation",
                  file=sys.stderr)
        out = _sweep(data)
        if args.json:
            print(json.dumps(out, indent=1))
        else:
            meta = out[0]
            print(f"days: {', '.join(meta['_days'])} · pairs: {meta['_pairs']} · "
                  f"baseline OI-confirm: {meta['_baselineOiConfirmPct']}% "
                  f"(n={meta['_baselineN']})")
            hdr = f"{'dteMin':>6} {'prem$k':>7} {'volOI':>5} {'minVol':>6} | " \
                  f"{'sym/d':>6} {'ctr/d':>6} {'0-2d%':>6} {'conf%':>6} {'n':>5}"
            print(hdr)
            print("-" * len(hdr))
            for r in out[1:]:
                print(f"{r['dte_min']:>6} {r['premium_min'] / 1000:>7.0f} "
                      f"{r['vol_oi_min']:>5.2f} {r['min_contract_volume']:>6} | "
                      f"{r['symsPerDay']:>6} {r['contractsPerDay']:>6} "
                      f"{(r['lowDtePct'] if r['lowDtePct'] is not None else float('nan')):>6} "
                      f"{(r['oiConfirmPct'] if r['oiConfirmPct'] is not None else float('nan')):>6} "
                      f"{r['confirmN']:>5}")
        return 0
    finally:
        await eng.db.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
