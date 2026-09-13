"""Tips outcome table — idea-level net-expectancy accounting (reviewer spec,
2026-09-13): source × setup (DTE bucket / shares) with dispositions, net
realized P&L, fees, risk used, latency, fill-vs-quote, and policy-based
missed executions SEPARATED from actual results. Plus entry-study coverage
and per-turn input-token shape. Read-only; prints markdown.

Usage (from backend/):
  .venv/Scripts/python -m zargar.tools.tip_outcomes
  .venv/Scripts/python -m zargar.tools.tip_outcomes --db postgresql://zargar:zargar@127.0.0.1:5433/zargar --since 2026-09-08
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import re
import statistics
from collections import defaultdict

import asyncpg

OCC = re.compile(r"^([A-Z.]{1,6})(\d{6})([CP])(\d{8})$")


def bucket(symbol: str, fill_date: dt.date | None) -> str:
    m = OCC.match(symbol or "")
    if not m:
        return "shares"
    exp = dt.datetime.strptime(m.group(2), "%y%m%d").date()
    if fill_date is None:
        return "opt-unfilled"
    d = (exp - fill_date).days
    return "0-4dte" if d <= 4 else ("5-29dte" if d <= 29 else "30+dte")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--since", default="2026-09-08")   # the Practice-book reset
    a = ap.parse_args()
    conn = await asyncpg.connect(a.db)
    since = dt.datetime.fromisoformat(a.since).replace(tzinfo=dt.timezone.utc)

    sigs = await conn.fetch(
        """SELECT id, source_name, status, created_at, extraction FROM signals
           WHERE created_at >= $1 AND (extraction->>'experiment') IS NULL""", since)
    props = await conn.fetch(
        """SELECT signal_id, symbol, qty, status, decided_via, context, created_at
           FROM proposals WHERE created_at >= $1""", since)
    orders = await conn.fetch(
        """SELECT o.id, o.signal_id, o.symbol, o.side, o.filled_qty, o.limit_price,
                  o.avg_fill_price, o.status, o.portfolio_id
           FROM orders o JOIN portfolios pf ON pf.id = o.portfolio_id
           WHERE o.created_at >= $1 AND pf.kind = 'sim' AND pf.archived IS NOT TRUE""", since)
    execs = await conn.fetch(
        """SELECT e.order_id, e.symbol, e.side, e.qty, e.price, e.commission, e.ts
           FROM executions e JOIN portfolios pf ON pf.id = e.portfolio_id
           WHERE e.ts >= $1 AND pf.kind = 'sim' AND pf.archived IS NOT TRUE""", since)

    props_by_sig: dict[str, list] = defaultdict(list)
    for p in props:
        if p["signal_id"]:
            props_by_sig[p["signal_id"]].append(p)
    orders_by_sig: dict[str, list] = defaultdict(list)
    order_ids = {}
    for o in orders:
        if o["signal_id"]:
            orders_by_sig[o["signal_id"]].append(o)
        order_ids[o["id"]] = o
    ex_by_order: dict[str, list] = defaultdict(list)
    ex_by_symbol: dict[str, list] = defaultdict(list)
    for e in execs:
        ex_by_order[e["order_id"]].append(e)
        ex_by_symbol[e["symbol"]].append(e)

    rows = []
    for s in sigs:
        sid = s["id"]
        sp = props_by_sig.get(sid, [])
        so = orders_by_sig.get(sid, [])
        verdicts = []
        for p in sp:
            ctx = p["context"] if isinstance(p["context"], dict) else json.loads(p["context"] or "{}")
            verdicts.append(((ctx.get("analyst") or {}) or {}).get("verdict"))
        took = any(v == "take" for v in verdicts)
        fills = [e for o in so for e in ex_by_order.get(o["id"], [])]
        buys = [e for e in fills if e["side"] == "BUY"]
        # EXIT orders come from the position manager and carry no signal_id —
        # attribute every fill on the idea's exact contract in the Practice
        # book to this idea (v1 caveat: re-entries on the same contract by a
        # different idea would collide; the book's dedupe/caps make that rare)
        sells = ([e for e in ex_by_symbol.get(buys[0]["symbol"], []) if e["side"] == "SELL"]
                 if buys else [e for e in fills if e["side"] == "SELL"])
        fills = buys + sells
        first_buy = min(buys, key=lambda e: e["ts"]) if buys else None
        sym = (so[0]["symbol"] if so else (sp[0]["symbol"] if sp else "")) or ""
        mult = 100.0 if OCC.match(sym) else 1.0
        cost = sum(float(e["qty"]) * float(e["price"]) for e in buys) * mult
        proceeds = sum(float(e["qty"]) * float(e["price"]) for e in sells) * mult
        fees = sum(float(e["commission"] or 0) for e in fills)
        bought = sum(float(e["qty"]) for e in buys)
        sold = sum(float(e["qty"]) for e in sells)
        open_qty = max(0.0, bought - sold)
        # realized on the closed portion only (avg-cost basis)
        realized = (proceeds - (sold / bought) * cost - fees) if bought and sold else (0.0 - fees if fills else 0.0)
        completed = bool(bought) and open_qty <= 1e-9
        missed = any(p["status"] in ("failed", "expired") for p in sp) and took and not buys
        # disposition
        if buys:
            disp = "filled-closed" if completed else "filled-open"
        elif missed:
            disp = "take-missed"
        elif took:
            disp = "take-nofill"
        elif any(v in ("skip", "watch") for v in verdicts):
            disp = "skipped"
        elif s["status"] in ("verification_failed",):
            disp = "ungrounded/failed-verify"
        elif s["status"] in ("parked", "shadow", "expired", "replayed"):
            disp = s["status"]
        else:
            disp = s["status"] or "?"
        lat_s = None
        if first_buy is not None and s["created_at"]:
            lat_s = (first_buy["ts"] - s["created_at"]).total_seconds()
        slip = None
        if buys and so:
            lp = next((float(o["limit_price"]) for o in so if o["side"] == "BUY" and o["limit_price"]), None)
            if lp:
                avg = sum(float(e["qty"]) * float(e["price"]) for e in buys) / max(bought, 1e-9)
                slip = avg - lp
        rows.append({
            "source": s["source_name"] or "unknown", "signal": sid[:8],
            "bucket": bucket(sym, first_buy["ts"].date() if first_buy else None) if sym else "none",
            "disp": disp, "completed": completed, "realized": realized,
            "cost": cost, "open_cost": (open_qty / bought * cost) if bought else 0.0,
            "fees": fees, "latency_s": lat_s, "slip": slip,
        })

    print(f"# Tips outcome table — ideas since {a.since} (generated {dt.date.today()})\n")
    print("Idea-level, Tips Practice book only; experiment rows excluded. Open marks are")
    print("reported AT COST (no live quotes in this read-only census). Missed executions")
    print("are policy-based estimates, separated from actual results.\n")
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        groups[(r["source"], r["bucket"])].append(r)
    print("| source | setup | ideas | taken | filled | closed | open($cost) | skipped | no-fill/missed | net realized | fees | mean win | mean loss | expectancy/idea | med latency s | med slip |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for (src, bkt), g in sorted(groups.items()):
        comp = [r for r in g if r["completed"]]
        wins = [r["realized"] for r in comp if r["realized"] > 0]
        losses = [r["realized"] for r in comp if r["realized"] <= 0]
        lat = [r["latency_s"] for r in g if r["latency_s"] is not None]
        slips = [r["slip"] for r in g if r["slip"] is not None]
        exp = (sum(wins) + sum(losses)) / len(comp) if comp else None
        cells = [
            src, bkt, str(len(g)),
            str(sum(1 for r in g if r["disp"].startswith(("filled", "take")))),
            str(sum(1 for r in g if r["disp"].startswith("filled"))),
            str(len(comp)),
            f"{sum(r['open_cost'] for r in g):.0f}",
            str(sum(1 for r in g if r["disp"] == "skipped")),
            str(sum(1 for r in g if r["disp"] in ("take-nofill", "take-missed"))),
            f"{sum(r['realized'] for r in comp):+.2f}",
            f"{sum(r['fees'] for r in g):.2f}",
            (f"{statistics.mean(wins):+.2f} x{len(wins)}" if wins else "—"),
            (f"{statistics.mean(losses):+.2f} x{len(losses)}" if losses else "—"),
            (f"{exp:+.2f} (n={len(comp)})" if exp is not None else "n=0"),
            (f"{statistics.median(lat):.0f}" if lat else "—"),
            (f"{statistics.median(slips):+.3f}" if slips else "—"),
        ]
        print("| " + " | ".join(cells) + " |")
    ncomp = sum(1 for r in rows if r["completed"])
    print(f"\nCompleted-idea cohort n={ncomp}; every expectancy above carries that group's "
          "sample size — none is a validated edge claim.\n")

    # entry-study coverage
    st = await conn.fetch("""SELECT payload FROM events WHERE type='TipEntryStudy' AND ts >= $1""", since)
    created = sum(1 for r in st if (r["payload"] if isinstance(r["payload"], dict) else json.loads(r["payload"])).get("phase") == "created")
    delayed = [r for r in st if (r["payload"] if isinstance(r["payload"], dict) else json.loads(r["payload"])).get("phase") == "delayed"]
    valid = sum(1 for r in delayed
                if ((r["payload"] if isinstance(r["payload"], dict) else json.loads(r["payload"])).get("atDecision") or {}).get("ask")
                and ((r["payload"] if isinstance(r["payload"], dict) else json.loads(r["payload"])).get("afterDelay") or {}).get("ask"))
    print(f"## Entry-study coverage\ncreated rows {created} · delayed rows {len(delayed)} · valid pairs {valid} · "
          f"eligible-idea cohort NOT yet covered (proposal-path only — skips without proposals are absent).\n")

    # inPerCall shape
    runs = await conn.fetch("""SELECT kind, opinion FROM tip_analyst_runs
        WHERE created_at >= $1 AND opinion IS NOT NULL""", since)
    per = defaultdict(list)
    for r in runs:
        op = r["opinion"] if isinstance(r["opinion"], dict) else json.loads(r["opinion"] or "{}")
        for i, v in enumerate((op.get("usage") or {}).get("inPerCall") or []):
            per[(r["kind"], i)].append(v)
    if per:
        print("## Analyst per-turn input tokens (median by turn index)\n")
        print("| kind | turn | n | median in-tokens |")
        print("|---|---|---|---|")
        for (k, i), vals in sorted(per.items()):
            print(f"| {k} | {i + 1} | {len(vals)} | {statistics.median(vals):,.0f} |")
    else:
        print("## Analyst per-turn input tokens\n(no inPerCall data yet — recorded from v0.7.54)")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
