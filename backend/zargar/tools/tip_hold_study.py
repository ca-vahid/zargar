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
    """Rows with their book provenance. A row captured before book_status existed gets its
    scope resolved from the DURABLE relationship (position -> portfolio -> kind / quarantined,
    as they stand now, labeled `resolvedFrom=durable`); what cannot be resolved stays unknown -
    never assumed Practice (HOLD-SCOPE-01/02)."""
    from ..models import ManagedPositionRow, Portfolio
    async with sf() as session:
        q = select(TipHoldSnapshotRow).order_by(TipHoldSnapshotRow.session_date, TipHoldSnapshotRow.symbol)
        if since:
            q = q.where(TipHoldSnapshotRow.session_date >= since)
        rows = (await session.execute(q)).scalars().all()
        out = [hs.row_dict(r) for r in rows]
        need = [d for d in out if d.get("quarantined") is None or not d.get("bookKind")]
        if need:
            pos_ids = {d["positionId"] for d in need if d.get("positionId")}
            mp = {m.id: m for m in (await session.execute(select(ManagedPositionRow).where(ManagedPositionRow.id.in_(pos_ids)))).scalars().all()} if pos_ids else {}
            pids = {d.get("portfolioId") for d in need if d.get("portfolioId")} | {m.portfolio_id for m in mp.values()}
            pf = {p.id: p for p in (await session.execute(select(Portfolio).where(Portfolio.id.in_(pids)))).scalars().all()} if pids else {}
            for d in need:
                m = mp.get(d.get("positionId"))
                pid = d.get("portfolioId") or (m.portfolio_id if m else None)
                p = pf.get(pid)
                if p is None:
                    d["scopeResolution"] = "unresolved: no durable book found - scope unknown"
                    continue
                d["portfolioId"] = pid
                d["bookKind"] = d.get("bookKind") or p.kind
                d["quarantined"] = bool(getattr(p, "quarantined", False))
                d["quarantineReason"] = getattr(p, "quarantine_note", None)
                d["positionStatus"] = d.get("positionStatus") or (m.status if m else None)
                d["scopeResolution"] = "resolved from the durable book as it stands now (not as captured)"
    return out


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
            from ..db import create_all
            await create_all(db)                # additive only: a report may run before the build that added a column is deployed
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
        print("| book kind | setup | obs | positions | adequate pairs | insufficient | ineligible (diagnostic) | quote-drift carry net | intraday net | mean carry R | mean intraday R | paired diff R | managed known | managed net | sacrificed winners |")
        print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for name, b in sorted(agg["setups"].items()):
            obs = sum(b["arms"].values())
            print(f"| {b['bookKind']} | {b['setup']} | {obs} | {b['distinctPositions']} | {b['n']} | {b['insufficient']} | {b['ineligible']} | {b['carryNet']} | {b['intradayNet']} | {b['meanCarryR']} | "
                  f"{b['meanIntradayR']} | {b['pairedDiffR']} | {b['managedKnown']} | {b['managedNet']} | {b['sacrificedWinners']} |")
        print("\nPooled across book kinds (DIAGNOSTIC ONLY - not Tips Practice expectancy):")
        for name, b in sorted(agg["pooledDiagnostic"].items()):
            print(f"  {name}: obs={sum(b['arms'].values())} adequate={b['n']} insufficient={b['insufficient']} ineligible={b['ineligible']} books={b['books']} carryNet={b['carryNet']} intradayNet={b['intradayNet']}")
        print("\nPer observation (eligibility):")
        for x in results:
            print(f"  {x.get('bookKind')} {x['symbol']} {x['arm']} -> {x['eligibility']}"
                  + (f" ({x['eligibilityReason']})" if x.get("eligibilityReason") else "")
                  + f"; adequate={x['adequate']}" + (f"; reason={x['reason']}" if x.get("reason") else ""))
        n_ad = sum(1 for x in results if x["adequate"]); n_dg = sum(1 for x in results if x.get("diagnosticOnly"))
        print(f"\n{len(rows)} observation(s) ({agg['unit']}); {n_ad} adequate pair(s); {n_dg} diagnostic-only (quarantined/attention/unknown scope). {agg['disclaimer']}")
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                json.dump({"rows": rows, "results": results, "aggregate": agg}, fh, indent=2, default=str)
            print("written:", a.json)
    asyncio.run(run())


if __name__ == "__main__":
    main()
