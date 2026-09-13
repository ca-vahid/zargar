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
    ap.add_argument("--portfolio", default="",
                    help="Tips Practice book id (default: techniques.tip.default_portfolio)")
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
        """SELECT e.id, e.order_id, e.portfolio_id, e.symbol, e.side, e.qty, e.price,
                  e.commission, e.ts
           FROM executions e JOIN portfolios pf ON pf.id = e.portfolio_id
           WHERE e.ts >= $1 AND pf.kind = 'sim' AND pf.archived IS NOT TRUE""", since)
    # explicit Practice-book scope (C59-02): the intended book, never "every
    # sim portfolio" by accident. --portfolio wins; else the tips default
    # setting; else (offline/unknown) all active sim books, stated below.
    pf_scope = str(getattr(a, "portfolio", "") or "")
    if not pf_scope:
        try:
            srow = await conn.fetchrow(
                """SELECT value FROM settings WHERE key = 'techniques.tip.default_portfolio'""")
            v = srow["value"] if srow else None
            if isinstance(v, str) and v.strip().startswith("{"):
                v = json.loads(v)                      # json column returned as text
            if isinstance(v, dict):                    # settings rows are {"v": <value>}
                v = v.get("v", v.get("value"))
            if isinstance(v, str):
                pf_scope = v.strip().strip('"')
        except Exception:
            pf_scope = ""
    if pf_scope:
        orders = [o for o in orders if o["portfolio_id"] == pf_scope]
        execs = [e for e in execs if e["portfolio_id"] == pf_scope]

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
    ex_by_book_symbol: dict[tuple, list] = defaultdict(list)
    for e in execs:
        ex_by_order[e["order_id"]].append(e)
        ex_by_book_symbol[(e["portfolio_id"], e["symbol"])].append(e)

    # ---------------- FIFO LOT ENGINE (Codex 2026-09-13 follow-up: a sale
    # must be consumed exactly once across ideas, and a re-entry must never
    # rewrite an earlier episode's basis). Each BUY execution becomes a LOT
    # owned by its idea, carrying its own price and per-unit fee; each SELL
    # in the same (book, symbol) consumes open lots (lot.ts <= sell.ts) in
    # FIFO order, realizing against the LOT's basis and allocating the sell
    # fee per unit. Whatever remains open keeps its own cost + fees.
    buys_by_idea: dict[str, list] = defaultdict(list)
    for sg in sigs:
        for o in orders_by_sig.get(sg["id"], []):
            for e in ex_by_order.get(o["id"], []):
                if e["side"] == "BUY":
                    buys_by_idea[sg["id"]].append(e)
    lots_by_key: dict[tuple, list] = defaultdict(list)
    for sid_, blist in buys_by_idea.items():
        for e in blist:
            q = float(e["qty"])
            lots_by_key[(e["portfolio_id"], e["symbol"])].append({
                "idea": sid_, "ts": e["ts"], "qty": q, "px": float(e["price"]),
                "fee_unit": float(e["commission"] or 0) / q if q else 0.0,
                "order_id": str(e.get("order_id") or ""),
                "exec_id": str(e.get("id") or e.get("order_id") or "")})
    acct: dict[str, dict] = defaultdict(lambda: {
        "realized": 0.0, "sold": 0.0, "fees_alloc": 0.0})
    unallocated: list[dict] = []       # every sell quantity that found no lot (C59-02)

    def _oid(e) -> str:
        return str(e.get("id") or e.get("order_id") or "")

    def _order_key(e):
        return (e["ts"], str(e.get("order_id") or ""), _oid(e))

    for key in lots_by_key:
        lots_by_key[key].sort(key=lambda l: (l["ts"], l["order_id"], l["exec_id"]))
    # iterate the SELL keys (all in-scope sells), not just the keys with lots —
    # a pre-window holding's sale must surface as an exception, never vanish
    sell_keys = {k for k, es in ex_by_book_symbol.items() if any(e["side"] == "SELL" for e in es)}
    for key in sorted(sell_keys):
        lots = lots_by_key.get(key, [])
        lmult = 100.0 if OCC.match(key[1]) else 1.0
        sells_here = sorted((e for e in ex_by_book_symbol.get(key, [])
                             if e["side"] == "SELL"), key=_order_key)
        for se in sells_here:
            sq = float(se["qty"])
            sfee_unit = float(se["commission"] or 0) / sq if sq else 0.0
            for lot in lots:
                if sq <= 1e-9:
                    break
                if lot["qty"] <= 1e-9 or lot["ts"] > se["ts"]:
                    continue
                take = min(sq, lot["qty"])
                acc_i = acct[lot["idea"]]
                acc_i["realized"] += (take * (float(se["price"]) - lot["px"]) * lmult
                                      - take * sfee_unit - take * lot["fee_unit"])
                acc_i["fees_alloc"] += take * (sfee_unit + lot["fee_unit"])
                acc_i["sold"] += take
                lot["qty"] -= take
                sq -= take
            if sq > 1e-9:
                unallocated.append({
                    "exec": _oid(se), "symbol": key[1], "book": key[0], "qty": sq,
                    "proceeds": sq * float(se["price"]) * lmult,
                    "fee": sq * sfee_unit,
                    "reason": ("no recognized lot in window (opening inventory unknown)"
                               if not lots else "oversold beyond recognized lots")})
    unallocated_sells = len(unallocated)
    open_by_idea: dict[str, dict] = defaultdict(lambda: {"cost": 0.0, "fees": 0.0, "qty": 0.0})
    for key, lots in lots_by_key.items():
        lmult = 100.0 if OCC.match(key[1]) else 1.0
        for lot in lots:
            if lot["qty"] > 1e-9:
                ob_i = open_by_idea[lot["idea"]]
                ob_i["cost"] += lot["qty"] * lot["px"] * lmult
                ob_i["fees"] += lot["qty"] * lot["fee_unit"]
                ob_i["qty"] += lot["qty"]

    rows = []
    for s in sigs:
        sid = s["id"]
        sp = props_by_sig.get(sid, [])
        so = orders_by_sig.get(sid, [])
        verdicts = []
        for p2 in sp:
            ctx = p2["context"] if isinstance(p2["context"], dict) else json.loads(p2["context"] or "{}")
            verdicts.append(((ctx.get("analyst") or {}) or {}).get("verdict"))
        took = any(v == "take" for v in verdicts)
        buys = buys_by_idea.get(sid, [])
        first_buy = min(buys, key=lambda e: e["ts"]) if buys else None
        sym = (so[0]["symbol"] if so else (sp[0]["symbol"] if sp else "")) or ""
        bought = sum(float(e["qty"]) for e in buys)
        a_i = acct.get(sid) or {"realized": 0.0, "sold": 0.0, "fees_alloc": 0.0}
        ob = open_by_idea.get(sid) or {"cost": 0.0, "fees": 0.0, "qty": 0.0}
        realized = a_i["realized"]
        fees_alloc = a_i["fees_alloc"]           # attributable to the realized portion
        unalloc_fees = ob["fees"]                # entry fees riding on open lots
        fees = fees_alloc + unalloc_fees         # PAID (matched inventory); C59-01
        open_qty = ob["qty"]
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
            "open_cost": ob["cost"],
            "fees": fees, "fees_alloc": fees_alloc, "unalloc_fees": unalloc_fees,
            "latency_s": lat_s, "slip": slip,
        })

    print(f"# Tips outcome table — ideas since {a.since} (generated {dt.date.today()})\n")
    print("Idea-level, Tips Practice book only; experiment rows excluded. Open marks are")
    print("reported AT COST (no live quotes in this read-only census). Missed executions")
    print("are policy-based estimates, separated from actual results.\n")
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        groups[(r["source"], r["bucket"])].append(r)
    print("| source | setup | ideas | taken | filled | closed | open($cost) | skipped | no-fill/missed | net realized (incl. partials) | fees paid | mean win | mean loss | expectancy/completed idea | med latency s | med slip | open-lot entry fees | fees allocated to realized |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
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
            f"{sum(r['realized'] for r in g):+.2f}",
            f"{sum(r['fees'] for r in g):.2f}",
            (f"{statistics.mean(wins):+.2f} x{len(wins)}" if wins else "—"),
            (f"{statistics.mean(losses):+.2f} x{len(losses)}" if losses else "—"),
            (f"{exp:+.2f} (n={len(comp)})" if exp is not None else "n=0"),
            (f"{statistics.median(lat):.0f}" if lat else "—"),
            (f"{statistics.median(slips):+.3f}" if slips else "—"),
            f"{sum(r['unalloc_fees'] for r in g):.2f}",
            f"{sum(r['fees_alloc'] for r in g):.2f}",
        ]
        print("| " + " | ".join(cells) + " |")
    ncomp = sum(1 for r in rows if r["completed"])
    print(f"\nCompleted-idea cohort n={ncomp}; every expectancy above carries that group's "
          "sample size — none is a validated edge claim."
          + (f" Unallocated sells (oversold/pre-lot): {unallocated_sells}." if unallocated_sells else "")
          + "\n")
    if unallocated:
        print("### Reconciliation exceptions (no P&L invented for these)\n")
        print("| execution | book | symbol | qty | proceeds | fee | reason |")
        print("|---|---|---|---|---|---|---|")
        for u in unallocated:
            print(f"| {u['exec'][:8]} | {u['book'][:8]} | {u['symbol']} | {u['qty']:g} "
                  f"| {u['proceeds']:.2f} | {u['fee']:.2f} | {u['reason']} |")
        print()
    print(f"Scope: {'portfolio ' + pf_scope if pf_scope else 'ALL active sim books (no default portfolio resolved)'}."
          " Fees: paid = allocated-to-realized + open-lot entry fees; unallocated-sell fees"
          " are listed in exceptions only.\n")

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
