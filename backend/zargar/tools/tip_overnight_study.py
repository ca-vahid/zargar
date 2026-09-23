"""Overnight carry of held Tips positions, close -> next open (ADV-09, 2026-09-23). Read-only research.

The desk's worst loss class is long options held overnight that exit in the first seconds of the next session
(6 of 6 losers, -$829.85, 09-08..09-22). Before any policy ("close short-dated long options at 15:50") this measures,
from the hold study's own samples (`tip_hold_snapshots`: a 15:50 pre-close quote and a next-open quote per position),
what holding actually did: the bid-to-bid change per unit and in dollars, by vehicle and by DTE bucket. Winners and
losers are counted together; a sample that is not `fresh` on both ends is excluded and counted.

    python -m zargar.tools.tip_overnight_study
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
import json
import re
import statistics

OCC = re.compile(r"^([A-Z.]{1,6})(\d{6})([CP])(\d{8})$")


def dte_bucket(symbol: str, session_date: dt.date) -> str:
    m = OCC.match(symbol or "")
    if not m:
        return "shares"
    exp = dt.datetime.strptime(m.group(2), "%y%m%d").date()
    sd = session_date if isinstance(session_date, dt.date) else dt.date.fromisoformat(str(session_date)[:10])
    d = (exp - sd).days
    return "0-7 DTE" if d <= 7 else "8-30 DTE" if d <= 30 else "31+ DTE"


def carry(row: dict) -> dict | None:
    """Bid at the pre-close sample -> bid at the next-open sample: what an exit at each would have realised."""
    pc, no = row.get("preclose") or {}, row.get("nextOpen") or {}
    try:
        b0, b1 = float(pc.get("bid") or 0), float(no.get("bid") or 0)
    except (TypeError, ValueError):
        return None
    if b0 <= 0:
        return None
    mult = 100.0 if OCC.match(row.get("symbol") or "") else 1.0
    return {"perUnit": b1 - b0, "pct": (b1 - b0) / b0 * 100.0, "dollars": (b1 - b0) * float(row.get("qty") or 0) * mult}


async def build(conn) -> dict:
    rows = await conn.fetch("""select leg_symbol, symbol, sec_type, qty, session_date, preclose_quote, next_open_quote,
                                      preclose_status, next_open_status, book_kind
                               from tip_hold_snapshots where coalesce(book_kind, 'sim') = 'sim'""")
    groups: dict[str, list] = collections.defaultdict(list)
    excluded = collections.Counter()
    for r in rows:
        if r["next_open_status"] != "fresh" or r["preclose_status"] not in ("fresh", "outside_window"):
            excluded[f"{r['preclose_status']}/{r['next_open_status']}"] += 1
            continue
        pc = r["preclose_quote"] if isinstance(r["preclose_quote"], dict) else json.loads(r["preclose_quote"] or "{}")
        no = r["next_open_quote"] if isinstance(r["next_open_quote"], dict) else json.loads(r["next_open_quote"] or "{}")
        sym = r["leg_symbol"] or r["symbol"]
        c = carry({"symbol": sym, "qty": r["qty"], "preclose": pc, "nextOpen": no})
        if c is None:
            excluded["no pre-close bid"] += 1
            continue
        groups[dte_bucket(sym, r["session_date"])].append({**c, "symbol": sym, "session": str(r["session_date"])})
    out = {}
    for k, g in groups.items():
        out[k] = {"n": len(g), "worse": sum(1 for x in g if x["perUnit"] < 0), "better": sum(1 for x in g if x["perUnit"] > 0),
                  "medianPct": round(statistics.median(x["pct"] for x in g), 1), "meanPct": round(statistics.mean(x["pct"] for x in g), 1),
                  "dollars": round(sum(x["dollars"] for x in g), 2)}
    return {"groups": out, "excluded": dict(excluded), "rows": {k: g for k, g in groups.items()}}


def render(res: dict) -> str:
    L = ["# Overnight carry of held Tips Practice positions (close -> next open, bid to bid)\n",
         "| vehicle / DTE | samples | worse at the open | better | median % | mean % | $ (sum) |", "|---|---:|---:|---:|---:|---:|---:|"]
    for k in ("0-7 DTE", "8-30 DTE", "31+ DTE", "shares"):
        g = res["groups"].get(k)
        if g:
            L.append(f"| {k} | {g['n']} | {g['worse']} | {g['better']} | {g['medianPct']:+.1f} | {g['meanPct']:+.1f} | {g['dollars']:+,.2f} |")
    L.append(f"\nExcluded (a sample not fresh on both ends): {res['excluded'] or 'none'}. Bid-to-bid is what an exit at each "
             "sample would have realised; it is not the trade's P&L. Small samples: a direction, not a rule.")
    return "\n".join(L)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    a = ap.parse_args()
    import asyncpg
    c = await asyncpg.connect(a.db, server_settings={"default_transaction_read_only": "on"})
    try:
        print(render(await build(c)))
    finally:
        await c.close()


if __name__ == "__main__":
    asyncio.run(main())
