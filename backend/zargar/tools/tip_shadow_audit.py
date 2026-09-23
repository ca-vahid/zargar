"""Shadow research-book integrity audit (ADV-02, 2026-09-23).

A shadow book whose FIFO census has UNALLOCATED sells (a sell with no matching buy - duplicated exit executions, a
same-symbol-leg runaway) has a meaningless P&L: eva's immediate book read +$145,506 on 21 unallocated sells. Such a
book must never be read as evidence - not in the scorecard, not in `get_source_stats`, and not in earned-auto trust
(which reads the immediate book's marks).

    python -m zargar.tools.tip_shadow_audit            # report every shadow book: valid / UNRELIABLE and why
    python -m zargar.tools.tip_shadow_audit --apply    # quarantine the unreliable ones through the running app's
                                                       # journaled route (POST /api/portfolios/{id}/quarantine)

Quarantine only removes a book from evidence and grading; it places no order and changes no position. It is reversible
through the same route (`on: false`) once the book is rebuilt.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import subprocess
import sys

from . import tip_outcomes

VERSION = "shadow-audit-v1"
RUNTIME_BACKEND = "C:/Cursor/zargar/backend"


def judge(book: dict) -> dict:
    """Pure: a book is valid evidence only with no unallocated sells and no negative open lot."""
    reasons = []
    if int(book.get("unallocated") or 0) > 0:
        reasons.append(f"{book['unallocated']} unallocated sell(s) - FIFO P&L is not computable")
    if int(book.get("negativeLots") or 0) > 0:
        reasons.append(f"{book['negativeLots']} negative open lot(s) - the book is short shares it never bought")
    return {**book, "reliable": not reasons, "reasons": reasons}


async def audit(conn, *, since: str = "2026-08-01") -> list[dict]:
    out = []
    for pf in await conn.fetch("""select id, name, quarantined, book from portfolios
                                  where kind = 'shadow' and archived is not true order by name"""):
        sd = await tip_outcomes.build_census(conn, since_text=since, portfolio=pf["id"], kinds=("shadow",))
        neg = await conn.fetchval("select count(*) from positions where portfolio_id = $1 and qty < 0", pf["id"])
        out.append(judge({"id": pf["id"], "name": pf["name"], "book": pf["book"], "quarantined": bool(pf["quarantined"]),
                          "unallocated": len(sd["unallocated"]), "negativeLots": int(neg or 0),
                          "realizedNet": round(sum(r["gross"] - r["fees"] for r in sd["realizations"]), 2)}))
    return out


def render(rows: list[dict]) -> str:
    L = [f"# Shadow research-book integrity ({VERSION}, {dt.date.today().isoformat()})\n",
         "| book | quarantined | realized net (FIFO) | unallocated sells | negative lots | evidence |",
         "|---|---|---:|---:|---:|---|"]
    for r in rows:
        ev = "valid" if r["reliable"] else "UNRELIABLE: " + "; ".join(r["reasons"])
        rn = f"{r['realizedNet']:+,.2f}" if r["reliable"] else "(not computable)"
        L.append(f"| {r['name']} | {'YES' if r['quarantined'] else ''} | {rn} | {r['unallocated']} | {r['negativeLots']} | {ev} |")
    L.append("\nAn unreliable book is never evidence. `--apply` quarantines the unreliable books that are not quarantined yet.")
    return "\n".join(L)


def _apply(rows: list[dict], api: str) -> list[dict]:
    import httpx
    # the session is minted by the RUNTIME checkout (its .env holds the signing secret)
    tok = subprocess.run([sys.executable, "-m", "zargar.tools.mint_session"], capture_output=True, text=True,
                         cwd=RUNTIME_BACKEND).stdout.strip().splitlines()[-1]
    done = []
    for r in rows:
        if r["reliable"] or r["quarantined"]:
            continue
        note = ("ADV-02 " + dt.date.today().isoformat() + ": " + "; ".join(r["reasons"]))[:400]
        resp = httpx.post(f"{api}/api/portfolios/{r['id']}/quarantine", json={"on": True, "note": note},
                          headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        done.append({"book": r["name"], "status": resp.status_code})
    return done


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--api", default="http://127.0.0.1:8420")
    a = ap.parse_args()
    import asyncpg
    c = await asyncpg.connect(a.db, server_settings={"default_transaction_read_only": "on"})
    try:
        rows = await audit(c)
    finally:
        await c.close()
    print(render(rows))
    if a.apply:
        print("\napplied:", json.dumps(_apply(rows, a.api)))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
