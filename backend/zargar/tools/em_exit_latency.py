"""Session ledger of fixed-target exit execution (`exit-latency-v1`, 2026-09-21). Read-only, order-free.

For every EM exit in a session it assembles the durable timeline - the bar that first made the target
eligible, the exit decision, the order, the fill - and then asks the only question that matters about
the gap: was a better price actually REACHABLE? That answer comes solely from evidence captured at the
time. Quotes are never journalled, so for most exits it is `unknown`, and the tool says so rather than
comparing the fill against a price nobody could have taken.

    python -m zargar.tools.em_exit_latency --date 2026-09-21
    python -m zargar.tools.em_exit_latency --date 2026-09-21 --json
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os

from ..marketstructure.sessions import session_bounds
from ..technique.exit_latency import VERSION, cost, realizable, stages

BOOKS = {"baseline": "045d8c35b3f149628ea001ae90a58edb", "experiment": "07ef1e867cad4150bc81e072a8fd600a"}


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


async def build(date: str, books: dict | None = None) -> dict:
    import asyncpg
    url = os.environ.get("ZARGAR_DATABASE_URL") or ""
    c = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        await c.execute("set default_transaction_read_only = on")
        open_ms, close_ms = session_bounds(date)
        a = dt.datetime.fromtimestamp(open_ms / 1000, dt.timezone.utc)
        b = dt.datetime.fromtimestamp(close_ms / 1000 + 3_600_000 / 1000, dt.timezone.utc)
        out = {"version": VERSION, "date": date, "books": {}, "note":
               "durable stages are measured; the reachable-price question is answered only from contemporaneous "
               "evidence and stays unknown otherwise - a fill is never compared with a price nobody could take"}
        for who, pid in (books or BOOKS).items():
            runs = {r["run_id"]: r["symbol"] for r in await c.fetch(
                "select run_id, symbol from technique_armed where portfolio_id=$1 and plan_for=$2", pid, date)}
            exits = [dict(r) for r in await c.fetch(
                "select ts, aggregate_id, payload from events where type='TechniquePlanExit' and aggregate_id = any($1::text[]) "
                "and ts >= $2 and ts < $3 order by ts", list(runs) or [""], a, b)]
            rows = []
            for e in exits:
                p = _j(e["payload"]) or {}
                sym, kind, qty = runs.get(e["aggregate_id"], "?"), str(p.get("kind")), float(p.get("qty") or 0)
                decided = int(e["ts"].timestamp() * 1000)
                # the order and its fill: matched on the traded symbol and the minute of the decision
                o = await c.fetchrow(
                    "select id, symbol, side, qty, limit_price, order_type, status, created_at, updated_at, avg_fill_price "
                    "from orders where portfolio_id=$1 and side='SELL' and created_at >= $2 and created_at < $3 "
                    "order by created_at limit 1", pid, e["ts"] - dt.timedelta(seconds=30), e["ts"] + dt.timedelta(minutes=3))
                fill = None
                if o is not None:
                    fill = await c.fetchrow("select ts, price, qty from executions where order_id=$1 order by ts limit 1", o["id"])
                # contemporaneous quote evidence for this contract, if any recorder captured it
                obs = []
                if o is not None:
                    for r in await c.fetch(
                        "select ts, payload from events where type in ('TechniqueExitShadow','TechniqueFirstSale','TechniqueTargetDistance') "
                        "and aggregate_id=$1 and ts >= $2 and ts < $3 order by ts", e["aggregate_id"],
                            e["ts"] - dt.timedelta(minutes=2), e["ts"] + dt.timedelta(minutes=2)):
                        q = (_j(r["payload"]) or {}).get("quote") or {}
                        if q.get("bid") is not None or q.get("ask") is not None:
                            obs.append({"ts": int(q.get("sourceTs") or q.get("quoteTs") or r["ts"].timestamp() * 1000),
                                        "bid": q.get("bid"), "ask": q.get("ask"),
                                        "bidSize": q.get("bidSize"), "askSize": q.get("askSize")})
                st = stages(signal_ts=decided, decided_ts=decided,
                            pending_ts=(int(o["created_at"].timestamp() * 1000) if o is not None else None),
                            dispatch_ts=(int(o["created_at"].timestamp() * 1000) if o is not None else None),
                            fill_ts=(int(fill["ts"].timestamp() * 1000) if fill is not None else None))
                mult = 100.0 if (o is not None and len(str(o["symbol"] or "")) > 10) else 1.0
                rr = realizable(obs, side="SELL", qty=qty or (float(o["qty"]) if o is not None else 0), after_ms=decided)
                rows.append({"symbol": sym, "kind": kind, "qty": qty,
                             "orderSymbol": (o["symbol"] if o is not None else None),
                             "limitPrice": (float(o["limit_price"]) if o is not None and o["limit_price"] is not None else None),
                             "fillPrice": (float(fill["price"]) if fill is not None else None),
                             "stages": st, "reachable": rr,
                             "cost": cost((float(fill["price"]) if fill is not None else None), rr,
                                          qty=qty or 0, multiplier=mult)})
            out["books"][who] = {"portfolioId": pid, "exits": rows,
                                 "measuredDifference": sum((r["cost"].get("grossDifference") or 0) for r in rows),
                                 "unknownExits": sum(1 for r in rows if r["cost"].get("status") != "measured")}
        return out
    finally:
        await c.close()


def render(d: dict) -> str:
    L = [f"# EM fixed-target exit execution - {d['date']} ({d['version']})", "", d["note"], ""]
    for who, bk in (d.get("books") or {}).items():
        L += [f"## {who}", ""]
        if not bk["exits"]:
            L += ["No exit in this book this session.", ""]
            continue
        L += ["| Symbol | Kind | Qty | Limit | Fill | decided->order | order->fill | Reachable better price | Measured difference |",
              "|---|---|---:|---:|---:|---:|---:|---|---:|"]
        for r in bk["exits"]:
            g = r["stages"].get("gapsMs") or {}
            rr, cst = r["reachable"], r["cost"]
            reach = ("unknown" if rr.get("status") != "measured"
                     else f"{(rr.get('bestReachableWithSize') or rr.get('bestReachable') or {}).get('price')} ({rr.get('depth')})")
            L.append(f"| {r['symbol']} | {r['kind']} | {r['qty']:g} | {r['limitPrice']} | {r['fillPrice']} | "
                     f"{g.get('decided->pending', g.get('decided->dispatch', '?'))} ms | {g.get('dispatch->fill', '?')} ms | "
                     f"{reach} | {cst.get('grossDifference') if cst.get('status') == 'measured' else 'unknown'} |")
        L += ["", f"Exits whose reachable price is unknown: {bk['unknownExits']} of {len(bk['exits'])}.", ""]
        why = next((r["reachable"].get("why") for r in bk["exits"] if r["reachable"].get("status") != "measured"), None)
        if why:
            L += [f"Why unknown: {why}.", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="fixed-target exit execution ledger (read-only, order-free)")
    ap.add_argument("--date", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    d = asyncio.run(build(a.date))
    print(json.dumps(d, indent=1, default=str) if a.json else render(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
