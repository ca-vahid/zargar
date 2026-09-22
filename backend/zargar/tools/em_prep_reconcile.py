"""Reconcile a preparation batch: what was reviewed, what was paid for, what is unresolved (`prep-reconcile-v1`).

Why this exists. On 2026-09-21 the baseline's evening batch was interrupted three times and restarted, and the
restart skips symbols that already have a completed review. It is tempting to conclude from that alone that
nothing was paid for twice. It does not follow: reuse prevents duplicate REVIEWS, not duplicate or interrupted
billable REQUESTS. A run that asked a model and was then killed consumed tokens and produced no verdict, and a
symbol reviewed twice was paid for twice even though only one verdict survives.

So this counts three different things and never conflates them:

  * **symbols** - unique names with a usable verdict, which is what the session actually has;
  * **runs** - every attempt, including duplicates per symbol and the ones that died;
  * **requests** - model calls, with the ones that never completed reported as unresolved rather than free.

The cost is an ESTIMATE at the current price card, never an invoice, and it is never netted against trading
money. Read-only: it changes nothing and arms nothing.

    python -m zargar.tools.em_prep_reconcile --date 2026-09-22
    python -m zargar.tools.em_prep_reconcile --date 2026-09-22 --json
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
import json
import os

from ..technique import model_costs as mc

VERSION = "prep-reconcile-v1"
BOOKS = {"baseline": "045d8c35b3f149628ea001ae90a58edb", "experiment": "07ef1e867cad4150bc81e072a8fd600a"}


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


async def build(date: str, *, trigger: str = "promote") -> dict:
    import asyncpg
    url = os.environ.get("ZARGAR_DATABASE_URL") or ""
    c = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        await c.execute("set default_transaction_read_only = on")
        rows = [dict(r) for r in await c.fetch(
            "select id, symbol, status, created_at, llm, usage, result from technique_runs "
            "where trigger = $1 and result->'plan'->>'planFor' = $2 order by created_at", trigger, date)]
        for r in rows:
            for k in ("llm", "usage", "result"):
                r[k] = _j(r[k])

        # ---- symbols: what the session actually has -------------------------------------------------
        verdict_of: dict[str, str] = {}
        per_symbol_runs: dict[str, int] = collections.Counter()
        for r in rows:
            sym = str(r["symbol"])
            per_symbol_runs[sym] += 1
            v = ((r["result"] or {}).get("analysis") or {}).get("verdict")
            if r["status"] == "done" and v:
                verdict_of[sym] = v                       # last completed verdict wins
        verdicts = collections.Counter(verdict_of.values())

        # ---- runs: every attempt, including the ones that died ---------------------------------------
        by_status = collections.Counter(r["status"] for r in rows)
        unfinished = [r for r in rows if r["status"] not in ("done",)]
        duplicates = {s: n for s, n in per_symbol_runs.items() if n > 1}
        # a duplicate is only WASTE where the extra runs were themselves completed reviews
        dup_completed = {}
        for s in duplicates:
            done = sum(1 for r in rows if str(r["symbol"]) == s and r["status"] == "done"
                       and ((r["result"] or {}).get("analysis") or {}).get("verdict"))
            if done > 1:
                dup_completed[s] = done

        # ---- requests: the billable unit -------------------------------------------------------------
        # The price card must be the live one. Passing an empty table makes EVERY request look unresolved and
        # the estimate None, which reads as "nothing completed" when it only means "nothing was priceable".
        raw_rates = await c.fetchval("select value from settings where key='llm.rates'")
        rates = _j(raw_rates)
        if isinstance(rates, dict) and set(rates) == {"v"}:
            rates = rates["v"]
        reqs = mc.requests_from_runs(rows)
        cost = mc.summarize(reqs, table=(rates if isinstance(rates, dict) else {}))

        # ---- arms, per book --------------------------------------------------------------------------
        arms = {}
        for who, pid in BOOKS.items():
            got = await c.fetch("select status, count(*) n from technique_armed where portfolio_id=$1 and plan_for=$2 "
                                "and technique='enhanced_market' group by 1", pid, date)
            arms[who] = {r["status"]: int(r["n"]) for r in got}
        return {
            "version": VERSION, "date": date, "trigger": trigger,
            "symbols": {"withVerdict": len(verdict_of), "verdicts": dict(verdicts)},
            "runs": {"total": len(rows), "byStatus": dict(by_status),
                     "symbolsWithMoreThanOneRun": duplicates,
                     "symbolsReviewedMoreThanOnce": dup_completed,
                     "unfinished": [{"id": r["id"], "symbol": r["symbol"], "status": r["status"],
                                     "at": r["created_at"].isoformat()} for r in unfinished[:40]]},
            "requests": {"counted": len(reqs), "unresolved": cost.get("unknown"), "byModel": cost.get("byModel"),
                         "note": "an unresolved request asked a model and recorded no completion: killed, failed or "
                                 "still running. It is not free and it is not an invoice line either"},
            "estimatedCost": {"usd": (cost.get("estimated") or {}).get("usd"),
                              "basis": "current price card; an ESTIMATE, never an invoice, never netted into trading P&L",
                              "invoiceVerified": cost.get("invoiceVerified"),
                              "priceCardLoaded": bool(isinstance(rates, dict) and rates)},
            "arms": arms,
        }
    finally:
        await c.close()


def render(d: dict) -> str:
    s, r, q = d["symbols"], d["runs"], d["requests"]
    L = [f"# EM preparation reconciliation - {d['date']} ({d['version']})", "",
         "Three different counts, never conflated: symbols are what the session has, runs are every attempt, "
         "requests are what was billable.", "",
         f"- **Unique symbols with a usable verdict: {s['withVerdict']}** -> {s['verdicts'] or 'none'}",
         f"- Runs of every kind: {r['total']} -> {r['byStatus']}",
         f"- Symbols with more than one run: {len(r['symbolsWithMoreThanOneRun'])}"
         + (f" -> {r['symbolsWithMoreThanOneRun']}" if r["symbolsWithMoreThanOneRun"] else ""),
         f"- Symbols actually REVIEWED more than once (paid twice): {len(r['symbolsReviewedMoreThanOnce'])}"
         + (f" -> {r['symbolsReviewedMoreThanOnce']}" if r["symbolsReviewedMoreThanOnce"] else ""),
         f"- Model requests counted: {q['counted']}; **unresolved: {(q.get('unresolved') or {}).get('requests')}**",
         f"- Estimated cost: **{(d.get('estimatedCost') or {}).get('usd')} USD** ({(d.get('estimatedCost') or {}).get('basis')})",
         ""]
    if r["unfinished"]:
        L += ["Unfinished runs (each one asked for work that produced no verdict):", ""]
        L += [f"- {u['at'][11:19]} {u['symbol']} {u['status']} ({u['id'][:8]})" for u in r["unfinished"][:20]]
        L += [""]
    L += ["Arms by book:", ""]
    for who, got in (d.get("arms") or {}).items():
        L.append(f"- {who}: {got or 'nothing armed'}")
    L += ["", q["note"], ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="reconcile a preparation batch (read-only)")
    ap.add_argument("--date", required=True)
    ap.add_argument("--trigger", default="promote")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    d = asyncio.run(build(a.date, trigger=a.trigger))
    print(json.dumps(d, indent=1, default=str) if a.json else render(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
