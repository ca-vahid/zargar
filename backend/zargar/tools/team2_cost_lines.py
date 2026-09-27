"""Team2 venue-cost lines (plan of record 2026-09-24 §5 P1.2) — READ-ONLY reporting.

Restates each Team2 book's closed option P&L under the costs of the venues the user could trade on, because at a few
percent of edge headroom the fee assumption decides every verdict. It changes nothing and books nothing.

    cd backend
    .venv/bin/python -m zargar.tools.team2_cost_lines [--since 2026-09-08] [--json]

Lines (per contract per side; premium x 100 per contract):
  gross          no commission at all (the price edge alone)
  ibkr_0.65      IBKR Pro fixed-style ~$0.65 (NOT verified against a statement)
  webull_1.04    the sim's own fee ($0.99 + $0.05, matches the 2026-08-21 Webull CA preview)
  webull_fx1.5   webull_1.04 plus a 1.5% CAD->USD conversion on the premium both ways, an UPPER bound for a CAD
                 account without a USD wallet (docs/OPTIONS-PLAN.md) — not a measured charge
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
from collections import defaultdict

BOOKS = {"4b28156b": "Team2 Control", "012f595c": "Team2 Sizing 0.5", "2eaa3d96": "Team2 C1 Conjunction",
         "b9dcd8db": "Team2 Practice (archived)"}
LINES = {"gross": (0.0, 0.0), "ibkr_0.65": (0.65, 0.0), "webull_1.04": (1.04, 0.0), "webull_fx1.5": (1.04, 0.015)}


def cost_lines(executions: list[dict]) -> dict:
    """Pure: {book: {line: net, "contracts": n, "premiumBought": $, "roundTrips": k}} over fully closed contracts
    (`roundTrips` counts closed option SERIES — two trades in one contract on one day are one series).

    `executions` rows: {book, symbol, side (BUY|SELL), qty, price}. A contract is counted only once its sells equal its
    buys (open or partly closed contracts are left out and counted under `openContracts`)."""
    by = defaultdict(lambda: defaultdict(lambda: {"buyQty": 0.0, "sellQty": 0.0, "buy$": 0.0, "sell$": 0.0}))
    for r in executions:
        s = by[r["book"]][r["symbol"]]
        q, px = float(r["qty"]), float(r["price"]) * 100.0
        if str(r["side"]).upper() == "BUY":
            s["buyQty"] += q
            s["buy$"] += q * px
        else:
            s["sellQty"] += q
            s["sell$"] += q * px
    out = {}
    for book, syms in by.items():
        row = {k: 0.0 for k in LINES}
        row.update({"contracts": 0.0, "premiumBought": 0.0, "roundTrips": 0, "openContracts": 0})
        for s in syms.values():
            if abs(s["buyQty"] - s["sellQty"]) > 1e-9:
                row["openContracts"] += 1
                continue
            row["roundTrips"] += 1
            row["contracts"] += s["buyQty"]
            row["premiumBought"] += s["buy$"]
            for name, (fee, fx) in LINES.items():
                row[name] += (s["sell$"] - s["buy$"]) - fee * (s["buyQty"] + s["sellQty"]) - fx * (s["sell$"] + s["buy$"])
        out[book] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in row.items()}
    return out


async def _load(since: str) -> list[dict]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from ..config import get_config
    eng = create_async_engine(get_config().database_url)
    lo = dt.datetime.fromisoformat(since).replace(tzinfo=dt.timezone.utc)
    async with eng.connect() as c:
        rows = (await c.execute(text("""select substr(portfolio_id,1,8) as book, symbol, side, qty, price from executions
            where ts >= :lo and substr(portfolio_id,1,8) = any(:books) order by ts"""), {"lo": lo, "books": list(BOOKS)})).all()
    await eng.dispose()
    return [dict(r._mapping) for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser(description="Team2 venue-cost lines (read-only)")
    ap.add_argument("--since", default="2026-09-08")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = cost_lines(asyncio.run(_load(a.since)))
    if a.json:
        print(json.dumps(res, indent=2))
        return
    print(f"Team2 closed option P&L since {a.since}, restated per venue (simulated books; reporting only)")
    print(f"{'book':28}{'series':>7}{'contracts':>10}" + "".join(f"{k:>14}" for k in LINES))
    tot = defaultdict(float)
    for book, r in sorted(res.items()):
        print(f"{BOOKS.get(book, book):28}{r['roundTrips']:>7}{r['contracts']:>10.0f}" + "".join(f"{r[k]:>14.2f}" for k in LINES))
        for k in LINES:
            tot[k] += r[k]
    print(f"{'ALL':28}{'':>7}{'':>10}" + "".join(f"{tot[k]:>14.2f}" for k in LINES))


if __name__ == "__main__":
    main()
