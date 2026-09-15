"""PROF-03 report: overnight carry versus a predeclared intraday close, paired
by setup on contemporaneous qualified quotes. Research only, read-only.

    python -m zargar.tools.tip_hold_study report [--since 2026-09-15] [--json out.json]
    python -m zargar.tools.tip_hold_study rows   [--since 2026-09-15]
    python -m zargar.tools.tip_hold_study requalify      # one-shot: v1 rows captured outside their window -> outside_window
"""
from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import select

from ..config import AppConfig
from ..db import make_engine, make_session_factory
from ..models import TipHoldSnapshotRow
from ..techniques.tip import holdstudy as hs


async def load_rows(sf, *, since: str) -> list[dict]:
    async with sf() as session:
        q = select(TipHoldSnapshotRow).order_by(TipHoldSnapshotRow.session_date, TipHoldSnapshotRow.symbol)
        if since:
            q = q.where(TipHoldSnapshotRow.session_date >= since)
        rows = (await session.execute(q)).scalars().all()
    return [hs.row_dict(r) for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["report", "rows", "requalify"])
    ap.add_argument("--since", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    cfg = AppConfig()
    db = make_engine(cfg.database_url)
    sf = make_session_factory(db)

    async def run():
        try:
            if a.cmd == "requalify":
                from ..db import create_all
                await create_all(db)            # additive: the v2 columns/index on an older live table
                n = await hs.requalify_legacy(sf)
                print(f"requalified {n} row(s): v1 observations outside their pre-close window are now outside_window")
                return
            rows = await load_rows(sf, since=a.since)
        finally:
            await db.dispose()
        if a.cmd == "rows":
            for r in rows:
                print(r["sessionDate"], r["arm"], r["symbol"], r["legSymbol"], "qty", r["qty"], "pre", r["precloseStatus"],
                      "next", r["nextOpenStatus"], "expected", r["expectedNextSession"], "gaps", r["gaps"])
            print(f"{len(rows)} row(s)")
            return
        results = []
        for r in rows:
            fees = r.get("fees") or {}
            res = hs.compare_row(r, fee_per_contract=float(fees.get("perContract") or 0),
                                 stock_commission=float(fees.get("stockCommission") or 0),
                                 reg_per_contract=float(fees.get("regPerContract") or 0))
            results.append(res)
        agg = hs.aggregate(results)
        print("| setup | obs | positions | insufficient | quote-drift carry net | intraday net | mean carry R | mean intraday R | paired diff R | managed known | managed net | sacrificed winners |")
        print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for name, b in sorted(agg["setups"].items()):
            print(f"| {name} | {b['n']} | {b['distinctPositions']} | {b['insufficient']} | {b['carryNet']} | {b['intradayNet']} | {b['meanCarryR']} | "
                  f"{b['meanIntradayR']} | {b['pairedDiffR']} | {b['managedKnown']} | {b['managedNet']} | {b['sacrificedWinners']} |")
        print(f"\n{len(rows)} observation(s) ({agg['unit']}); {sum(1 for x in results if x['adequate'])} adequate pair(s). {agg['disclaimer']}")
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                json.dump({"rows": rows, "results": results, "aggregate": agg}, fh, indent=2, default=str)
            print("written:", a.json)
    asyncio.run(run())


if __name__ == "__main__":
    main()
