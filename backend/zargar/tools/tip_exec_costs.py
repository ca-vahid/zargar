"""Tips execution-cost ledger (v0.9 V7.2, 2026-10-05): what each FILL in a book cost beyond the decision.

Read-only (a read-only transaction on the given DB). One row per execution in the book:

* commission     = the execution's own commission (as the venue/executor booked it)
* spread paid    = BUY: (fill - mid) x qty x multiplier; SELL: (mid - fill) x ... - the half-spread actually paid,
                   on the DECISION quote (TipFillVsQuote's decision sample for entries; the exit's recorded mark
                   `bid=` for exits); unknown when no quote was recorded (never estimated)
* slippage       = vs the decision quote's executable side: BUY fill - ask, SELL bid - fill (positive = worse)
* vs limit       = BUY fill - limit, SELL limit - fill (negative = price improvement)
* FX             = the book's base currency vs the instrument's (USD listings); a non-USD book is flagged - the
                   conversion rate/spread is NOT recorded per fill, so it is reported as unknown, never guessed

Usage (from backend/):
  .venv/Scripts/python -m zargar.tools.tip_exec_costs [--book <id>] [--since 2026-10-01] [--json out.json]
  (default book: settings ibkr.portfolio_id, the IBKR book)
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import re

VERSION = "tip-exec-costs-v1"
OCC = re.compile(r"^([A-Z.]{1,6})(\d{6})([CP])(\d{8})$")
_BID = re.compile(r"bid=([0-9]*\.?[0-9]+)")
_ASK = re.compile(r"ask=([0-9]*\.?[0-9]+)")


def J(v):
    return (json.loads(v) if isinstance(v, str) else v) or {}


def mult(symbol: str) -> float:
    return 100.0 if OCC.match(symbol or "") else 1.0


def instrument_currency(symbol: str) -> str:
    s = str(symbol or "").upper()
    return "CAD" if (s.endswith(".TO") or s.endswith(".V") or s.endswith(".NE")) else "USD"


def fill_cost(*, side: str, qty: float, price: float, multiplier: float, commission: float,
              bid: float | None, ask: float | None, limit: float | None) -> dict:
    """Pure: the cost decomposition of one fill (dollars, positive = cost)."""
    side = str(side).upper()
    q = abs(float(qty or 0)) * float(multiplier or 1)
    out = {"commission": round(float(commission or 0), 4), "spreadPaid": None, "slippage": None, "vsLimit": None,
           "unknown": []}
    if bid and ask and bid > 0 and ask >= bid:
        mid = (bid + ask) / 2.0
        out["spreadPaid"] = round(((price - mid) if side == "BUY" else (mid - price)) * q, 4)
        out["slippage"] = round(((price - ask) if side == "BUY" else (bid - price)) * q, 4)
    elif side == "SELL" and bid and bid > 0:
        out["slippage"] = round((bid - price) * q, 4)
        out["unknown"].append("ask (exit mark carried the bid only)")
    else:
        out["unknown"].append("decision quote")
    if limit and limit > 0:
        out["vsLimit"] = round(((price - limit) if side == "BUY" else (limit - price)) * q, 4)
    known = [v for v in (out["commission"], out["spreadPaid"]) if v is not None]
    out["allIn"] = round(sum(known), 4)
    return out


async def build(conn, *, book: str, since: dt.datetime) -> dict:
    pf = await conn.fetchrow("select id, name, kind, base_currency from portfolios where id = $1", book)
    base = (pf["base_currency"] if pf else None) or "USD"
    ex = await conn.fetch("""select e.id, e.order_id, e.symbol, e.side, e.qty, e.price, e.commission, e.ts,
                                    o.limit_price, o.order_type, o.proposal_id, o.source, o.technique
                             from executions e left join orders o on o.id = e.order_id
                             where e.portfolio_id = $1 and e.ts >= $2 order by e.ts""", book, since)
    fvq = {}
    for r in await conn.fetch("""select payload from events where type = 'TipFillVsQuote' and ts >= $1""",
                              since - dt.timedelta(days=1)):
        p = J(r["payload"])
        if p.get("orderId"):
            fvq[p["orderId"]] = p
    exit_marks = {}
    for r in await conn.fetch("""select state from managed_positions where portfolio_id = $1 and technique = 'tip'
                                 and updated_at >= $2""", book, since - dt.timedelta(days=1)):
        for x in (J(r["state"]).get("exits") or []):
            if x.get("orderId"):
                txt = str(x.get("reason") or "")
                b, a = _BID.search(txt), _ASK.search(txt)
                exit_marks[x["orderId"]] = {"bid": float(b.group(1)) if b else None, "ask": float(a.group(1)) if a else None,
                                            "kind": x.get("kind")}
    rows, tot = [], {"commission": 0.0, "spreadPaid": 0.0, "slippage": 0.0, "fills": 0, "unknownQuote": 0}
    for e in ex:
        sym, side = e["symbol"], str(e["side"]).upper()
        bid = ask = None
        role = None
        if side == "BUY" and e["order_id"] in fvq:
            p = fvq[e["order_id"]]
            bid, ask, role = p.get("quoteBid"), p.get("quoteAsk"), "decision"
        elif side == "SELL" and e["order_id"] in exit_marks:
            m = exit_marks[e["order_id"]]
            bid, ask, role = m.get("bid"), m.get("ask"), f"exit mark ({m.get('kind')})"
        c = fill_cost(side=side, qty=float(e["qty"]), price=float(e["price"]), multiplier=mult(sym),
                      commission=float(e["commission"] or 0), bid=bid, ask=ask, limit=e["limit_price"])
        cur = instrument_currency(sym)
        fx = {"book": base, "instrument": cur, "conversion": (base != cur),
              **({"note": "conversion rate/spread not recorded per fill - unknown"} if base != cur else {})}
        rows.append({"ts": e["ts"].isoformat(), "symbol": sym, "side": side, "qty": float(e["qty"]),
                     "price": float(e["price"]), "limit": e["limit_price"], "orderType": e["order_type"],
                     "source": e["source"], "quoteRole": role, "bid": bid, "ask": ask, **c, "fx": fx})
        tot["fills"] += 1
        tot["commission"] += c["commission"]
        if c["spreadPaid"] is not None:
            tot["spreadPaid"] += c["spreadPaid"]
        else:
            tot["unknownQuote"] += 1
        if c["slippage"] is not None:
            tot["slippage"] += c["slippage"]
    return {"version": VERSION, "book": book, "name": (pf["name"] if pf else None), "kind": (pf["kind"] if pf else None),
            "baseCurrency": base, "since": since.isoformat(), "rows": rows,
            "totals": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in tot.items()}}


def render(res: dict) -> str:
    t = res["totals"]
    out = [f"Execution costs - {res.get('name') or res['book']} ({res.get('kind')}, {res['baseCurrency']}) since {res['since'][:10]}",
           f"{t['fills']} fills | commission ${t['commission']:,.2f} | spread paid ${t['spreadPaid']:,.2f} | slippage vs "
           f"decision ${t['slippage']:,.2f} | {t['unknownQuote']} fill(s) with no recorded decision quote", ""]
    out.append(f"{'time (UTC)':<17}{'symbol':<22}{'side':<5}{'qty':>8}{'price':>10}{'comm':>8}{'spread':>9}{'slip':>9}{'vsLmt':>9}  quote")
    for r in res["rows"]:
        def f(v):
            return f"{v:,.2f}" if isinstance(v, (int, float)) else "?"
        out.append(f"{r['ts'][5:16]:<17}{r['symbol']:<22}{r['side']:<5}{r['qty']:>8g}{r['price']:>10.2f}{f(r['commission']):>8}"
                   f"{f(r['spreadPaid']):>9}{f(r['slippage']):>9}{f(r['vsLimit']):>9}  {r['quoteRole'] or 'none'}"
                   + (" | FX" if r["fx"]["conversion"] else ""))
    return "\n".join(out)


async def main() -> None:
    import asyncpg
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--book", default="", help="book id (default: settings ibkr.portfolio_id)")
    ap.add_argument("--since", default="", help="ISO date (default: 30 days ago)")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    conn = await asyncpg.connect(a.db, server_settings={"default_transaction_read_only": "on"})
    try:
        book = a.book
        if not book:
            v = J(await conn.fetchval("select value from settings where key='ibkr.portfolio_id'"))
            book = v.get("v") if isinstance(v, dict) else v
        if not book:
            raise SystemExit("no --book and no ibkr.portfolio_id setting")
        since = (dt.datetime.fromisoformat(a.since).replace(tzinfo=dt.timezone.utc) if a.since
                 else dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30))
        res = await build(conn, book=str(book), since=since)
        print(render(res))
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                json.dump(res, fh, indent=1, default=str)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
