"""Measured prompt-cache pilot on CAPTURED intake reviews (ADV-03, 2026-09-23). Paid; bounded by an estimate-based guard.

The 2026-09-17 plan measured only the system+tools prefix (~11% of a call) and concluded caching was small. The bulk
of a multi-turn review is the per-run header (rulebook + notes) and the conversation re-sent every turn. This pilot
replays the SAME captured request (`review_frozen`, tools served from the case, management tools never executed)
twice per case - cache OFF and cache `conversation` - on the production model, and reports what the provider actually
billed: input, cache-read and cache-write tokens, priced at the `llm.rates` card.

    python -m zargar.tools.tip_cache_pilot --cases 5 --cap 10 --env-file C:/Cursor/zargar/backend/.env

The cap is an ESTIMATE-BASED spending guard (review_frozen.SuiteBudget), not a guaranteed maximum. No production
setting changes. Model outputs differ run to run with or without caching; the pilot measures cost, not decisions.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys

from ..techniques.tip import review_frozen as rf

VERSION = "cache-pilot-v1"


def price(u: dict, rate: dict) -> float:
    return (u.get("in", 0) / 1e6 * rate["in"] + u.get("out", 0) / 1e6 * rate["out"]
            + u.get("cacheRead", 0) / 1e6 * rate["cacheRead"] + u.get("cacheWrite", 0) / 1e6 * rate["cacheWrite"])


def summarize(rows: list[dict], rate: dict) -> dict:
    off = [r["off"] for r in rows if r.get("off") and not r["off"].get("error")]
    on = [r["on"] for r in rows if r.get("on") and not r["on"].get("error")]
    c_off = sum(price(r["tokens"], rate) for r in off)
    c_on = sum(price(r["tokens"], rate) for r in on)
    return {"cases": len(rows), "offOk": len(off), "onOk": len(on), "costOff": round(c_off, 4), "costOn": round(c_on, 4),
            "saving": round(1 - c_on / c_off, 3) if c_off else None,
            "cacheReadTokens": sum(r["tokens"].get("cacheRead", 0) for r in on),
            "cacheWriteTokens": sum(r["tokens"].get("cacheWrite", 0) for r in on)}


def _load_env(path: str | None) -> None:
    if not path or not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--cases", type=int, default=5)
    ap.add_argument("--cap", type=float, default=10.0)
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
        rates = rates.get("v", rates)
        rate = rates.get(a.model)
        # the most recent captured reviews with at least one tool turn (multi-turn = where the conversation repeats)
        runs = await c.fetch("""select id, source, created_at, opinion, trace, model from tip_analyst_runs
                                where kind = 'intake' and verdict = 'review' and status = 'done'
                                  and trace::text like '%reviewManifest%'
                                  and jsonb_array_length(coalesce(opinion->'toolsUsed', '[]'::jsonb)) >= 2
                                order by created_at desc limit $1""", a.cases)
    finally:
        await c.close()
    cases = []
    for r in runs:
        op = r["opinion"] if isinstance(r["opinion"], dict) else json.loads(r["opinion"] or "{}")
        tr = r["trace"] if isinstance(r["trace"], list) else json.loads(r["trace"] or "[]")
        cases.append(rf.build_case({"id": r["id"], "source": r["source"], "created_at": r["created_at"], "opinion": op,
                                    "trace": tr, "model": r["model"]}))
    budget = rf.SuiteBudget(a.cap, {a.model: rate}, ledger_path=a.ledger)
    client = anthropic.AsyncAnthropic(api_key=key)
    rows = []
    for case in cases:
        row = {"runId": case["runId"], "source": case["source"]}
        for label, mode in (("off", None), ("on", "conversation")):
            rep = await rf.replay_review(case, client=client, model=a.model, budget=budget, prompt_cache=mode)
            row[label] = {"tokens": rep.get("tokens") or {}, "error": rep.get("error"), "valid": rep.get("valid"),
                          "outcome": (rep.get("compare") or {}).get("outcome")}
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("runId", "source")}), json.dumps(row["off"]["tokens"]), json.dumps(row["on"]["tokens"]))
    s = summarize(rows, rate)
    s["budget"] = budget.summary()
    out = {"version": VERSION, "at": dt.datetime.now(dt.timezone.utc).isoformat(), "model": a.model, "rate": rate,
           "summary": s, "rows": rows}
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, default=str)
    print(json.dumps(s, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
