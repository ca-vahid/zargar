"""Frozen comparison: FULL vs COMPACT intake-review context on captured reviews (ADV-04, 2026-09-23). Paid; guarded.

Each captured review is replayed twice on the production model with the conversation cache on: once with its exact
captured header (FULL) and once with `review_context.compact_review_header` applied (COMPACT). Both arms are compared
with the production review's own instructions (`review_frozen.compare`: target, stop levels, fractions, quantities),
so the FULL arm measures the model's run-to-run noise and the COMPACT arm has to match it, not beat a perfect score.
Management cases are drawn first - a lost management instruction is the costly failure.

    python -m zargar.tools.tip_context_compare --cases 8 --cap 12 --env-file C:/Cursor/zargar/backend/.env

The cap is an ESTIMATE-BASED spending guard, not a guaranteed maximum. No production setting changes here.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
import json
import os
import sys

from ..techniques.tip import review_frozen as rf
from ..techniques.tip.review_context import compact_review_header, tickers_in
from .tip_cache_pilot import _load_env, price

VERSION = "context-compare-v1"


def arm_summary(reps: list[dict], rate: dict) -> dict:
    cmp_ = [r.get("compare") or {} for r in reps]
    return {"n": len(reps), "agree": sum(1 for c in cmp_ if c.get("outcome") == "agree"),
            "disagree": sum(1 for c in cmp_ if c.get("outcome") == "disagree"),
            "inconclusive": sum(1 for c in cmp_ if c.get("outcome") == "inconclusive"),
            "invalid": sum(1 for c in cmp_ if c.get("outcome") == "invalid"),
            "missedManagement": sum(1 for c in cmp_ if c.get("missed")),
            "changedManagement": sum(1 for c in cmp_ if c.get("changed")),
            "cost": round(sum(price(r.get("tokens") or {}, rate) for r in reps), 4)}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--cases", type=int, default=8)
    ap.add_argument("--cap", type=float, default=12.0)
    ap.add_argument("--model", default="claude-opus-5")
    ap.add_argument("--env-file", default=None)
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    _load_env(a.env_file)
    key = os.environ.get("ZARGAR_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("no API key (pass --env-file)"); return 2
    import anthropic
    import asyncpg
    c = await asyncpg.connect(a.db, server_settings={"default_transaction_read_only": "on"})
    try:
        v = await c.fetchval("select value from settings where key = 'llm.rates'")
        rates = json.loads(v) if isinstance(v, str) else v
        rate = rates.get("v", rates).get(a.model)
        mgmt = await c.fetch("""select id, source, created_at, opinion, trace, model from tip_analyst_runs
                                where kind='intake' and verdict='review' and status='done' and trace::text like '%reviewManifest%'
                                  and (opinion->'toolsUsed')::text ~ '(update_exit_plan|close_position|disarm_plan)'
                                order by created_at desc limit $1""", max(1, a.cases * 3 // 4))
        rest = await c.fetch("""select id, source, created_at, opinion, trace, model from tip_analyst_runs
                                where kind='intake' and verdict='review' and status='done' and trace::text like '%reviewManifest%'
                                  and (opinion->'toolsUsed')::text !~ '(update_exit_plan|close_position|disarm_plan)'
                                order by created_at desc limit $1""", max(1, a.cases - len(mgmt)))
    finally:
        await c.close()
    cases = []
    for r in list(mgmt) + list(rest):
        op = r["opinion"] if isinstance(r["opinion"], dict) else json.loads(r["opinion"] or "{}")
        tr = r["trace"] if isinstance(r["trace"], list) else json.loads(r["trace"] or "[]")
        cases.append(rf.build_case({"id": r["id"], "source": r["source"], "created_at": r["created_at"],
                                    "opinion": op, "trace": tr, "model": r["model"]}))
    budget = rf.SuiteBudget(a.cap, {a.model: rate}, ledger_path=a.ledger)
    client = anthropic.AsyncAnthropic(api_key=key)
    full, compact, rows = [], [], []
    for case in cases:
        head = (case.get("manifest") or {}).get("header") or ""
        msg = head[head.find("MESSAGE:"):head.find("PER-SIGNAL")]
        tx = lambda h, _t=tickers_in(msg), _s=case.get("source"): compact_review_header(h, tickers=_t, source=_s)  # noqa: E731
        rf_ = await rf.replay_review(case, client=client, model=a.model, budget=budget, prompt_cache="conversation")
        rc_ = await rf.replay_review(case, client=client, model=a.model, budget=budget, prompt_cache="conversation",
                                     header_transform=tx)
        full.append(rf_); compact.append(rc_)
        rows.append({"runId": case["runId"], "source": case["source"], "baseline": case["baseline"]["instructions"],
                     "full": {"outcome": (rf_.get("compare") or {}).get("outcome"), "instructions": rf_.get("instructions"), "error": rf_.get("error")},
                     "compact": {"outcome": (rc_.get("compare") or {}).get("outcome"), "instructions": rc_.get("instructions"), "error": rc_.get("error")},
                     "headerChars": {"full": len(head), "compact": len(tx(head))}})
        print(case["runId"][:8], case["source"], "full:", rows[-1]["full"]["outcome"], "compact:", rows[-1]["compact"]["outcome"])
    out = {"version": VERSION, "at": dt.datetime.now(dt.timezone.utc).isoformat(), "model": a.model,
           "full": arm_summary(full, rate), "compact": arm_summary(compact, rate), "budget": budget.summary(), "rows": rows}
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, default=str)
    print(json.dumps({k: out[k] for k in ("full", "compact", "budget")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
