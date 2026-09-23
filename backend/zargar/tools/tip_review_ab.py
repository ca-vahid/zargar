"""Frozen A/B of intake-review ARMS on captured reviews (2026-09-23, cost levers 2 + 4). Paid; one guarded budget.

An arm is `name=model[:context]` with context full | notes | compact. Every captured review in the sample is replayed
once per arm, with the conversation cache on and the analyst's pinned effort, served ONLY the evidence the original
review saw (`review_frozen`: mutating tools are recorded as proposals, never executed).

Judgement (fixed before the run): the FIRST arm is the reference - it measures the model's run-to-run noise against
the production review. A later arm PASSES only when, against production, it has
  * no more missed-or-changed management instructions than the reference arm,
  * no more invalid replies than the reference arm, and
  * no more missed-entry flag differences than the reference arm.
The result opens a decision; it changes no setting.

    python -m zargar.tools.tip_review_ab --arm ref=claude-opus-5-5 --arm notes=claude-opus-5-5:notes \
        --arm sonnet=claude-sonnet-5 --cases 30 --cap 20 --env-file C:/Cursor/zargar/backend/.env --out ab.json

The cap is an ESTIMATE-BASED spending guard (review_frozen.SuiteBudget), not a guaranteed maximum.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys

from ..techniques.tip import review_frozen as rf
from ..techniques.tip.review_context import compact_review_header, tickers_in
from .tip_cache_pilot import _load_env, price

VERSION = "review-ab-v1"
CONTEXTS = ("full", "notes", "compact")


def parse_arm(spec: str) -> dict:
    name, _, rest = spec.partition("=")
    model, _, ctx = rest.partition(":")
    ctx = ctx or "full"
    if not name or not model or ctx not in CONTEXTS:
        raise ValueError(f"bad arm {spec!r} - expected name=model[:full|notes|compact]")
    return {"name": name, "model": model, "context": ctx}


def transform(ctx: str, case: dict):
    if ctx == "full":
        return None
    head = (case.get("manifest") or {}).get("header") or ""
    msg = head[head.find("MESSAGE:"):head.find("PER-SIGNAL")]
    tk, src = tickers_in(msg), case.get("source")
    return lambda h: compact_review_header(h, tickers=tk, source=src, notes_only=(ctx == "notes"))


def arm_summary(reps: list[dict], rate: dict | None) -> dict:
    cmp_ = [r.get("compare") or {} for r in reps if not r.get("skipped")]
    return {"n": len(cmp_), "agree": sum(1 for c in cmp_ if c.get("outcome") == "agree"),
            "disagree": sum(1 for c in cmp_ if c.get("outcome") == "disagree"),
            "inconclusive": sum(1 for c in cmp_ if c.get("outcome") == "inconclusive"),
            "invalid": sum(1 for c in cmp_ if c.get("outcome") == "invalid"),
            "missedOrChangedManagement": sum(1 for c in cmp_ if c.get("missed") or c.get("changed")),
            "missedManagement": sum(1 for c in cmp_ if c.get("missed")),
            "changedManagement": sum(1 for c in cmp_ if c.get("changed")),
            "extraManagement": sum(1 for c in cmp_ if c.get("extra")),
            "missedEntryFlagDiffers": sum(1 for c in cmp_ if not (c.get("missedEntryFlag") or {"same": True})["same"]),
            "cost": round(sum(price(r.get("tokens") or {}, rate) for r in reps if rate), 4) if rate else None}


def verdict(ref: dict, arm: dict) -> dict:
    """Pure: the pre-registered rule above."""
    checks = {"management": arm["missedOrChangedManagement"] <= ref["missedOrChangedManagement"],
              "invalid": arm["invalid"] <= ref["invalid"],
              "missedEntryFlag": arm["missedEntryFlagDiffers"] <= ref["missedEntryFlagDiffers"]}
    return {"pass": all(checks.values()), "checks": checks}


async def load_cases(db: str, n: int) -> list[dict]:
    import asyncpg
    q = """select id, source, created_at, opinion, trace, model from tip_analyst_runs
           where kind='intake' and verdict='review' and status='done' and trace::text like '%reviewManifest%' and {cond}
           order by created_at desc limit $1"""
    mg = "(opinion->'toolsUsed')::text ~ '(update_exit_plan|close_position|disarm_plan)'"
    me = "coalesce(opinion->>'missedTip','') not in ('','null')"
    c = await asyncpg.connect(db, server_settings={"default_transaction_read_only": "on"})
    try:
        a = await c.fetch(q.format(cond=mg), max(1, n * 2 // 5))
        b = await c.fetch(q.format(cond=f"{me} and not {mg}"), max(1, n // 5))
        seen = {r["id"] for r in list(a) + list(b)}
        rest = [r for r in await c.fetch(q.format(cond=f"not {mg} and not {me}"), n) if r["id"] not in seen]
    finally:
        await c.close()
    rows = (list(a) + list(b) + rest)[:n]
    out = []
    for r in rows:
        op = r["opinion"] if isinstance(r["opinion"], dict) else json.loads(r["opinion"] or "{}")
        tr = r["trace"] if isinstance(r["trace"], list) else json.loads(r["trace"] or "[]")
        out.append(rf.build_case({"id": r["id"], "source": r["source"], "created_at": r["created_at"],
                                  "opinion": op, "trace": tr, "model": r["model"]}))
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--arm", action="append", required=True)
    ap.add_argument("--cases", type=int, default=30)
    ap.add_argument("--cap", type=float, default=20.0)
    ap.add_argument("--effort", default="high")
    ap.add_argument("--env-file", default=None)
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    arms = [parse_arm(x) for x in a.arm]
    _load_env(a.env_file)
    key = os.environ.get("ZARGAR_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("no API key (pass --env-file)"); return 2
    import anthropic
    import asyncpg
    c = await asyncpg.connect(a.db, server_settings={"default_transaction_read_only": "on"})
    try:
        v = await c.fetchval("select value from settings where key = 'llm.rates'")
    finally:
        await c.close()
    rates = json.loads(v) if isinstance(v, str) else v
    rates = rates.get("v", rates)
    missing = [x["model"] for x in arms if not rates.get(x["model"])]
    if missing:
        print(f"no llm.rates entry for {missing} - refusing an unpriced paid run"); return 2
    cases = await load_cases(a.db, a.cases)
    budget = rf.SuiteBudget(a.cap, {x["model"]: rates[x["model"]] for x in arms}, ledger_path=a.ledger)
    client = anthropic.AsyncAnthropic(api_key=key)
    reps: dict[str, list] = {x["name"]: [] for x in arms}
    rows = []
    for case in cases:
        row = {"runId": case["runId"], "source": case["source"], "baseline": case["baseline"]["instructions"],
               "baselineMissedTip": case["baseline"]["missedTip"]}
        for x in arms:
            kw = {"output_config": {"effort": a.effort}} if a.effort and not x["model"].startswith("claude-haiku") else {}
            r = await rf.replay_review(case, client=client, model=x["model"], budget=budget, prompt_cache="conversation",
                                       header_transform=transform(x["context"], case), extra_kw=kw)
            reps[x["name"]].append(r)
            row[x["name"]] = {"outcome": (r.get("compare") or {}).get("outcome"), "instructions": r.get("instructions"),
                              "missedTip": r.get("missedTip"), "error": r.get("error")}
        rows.append(row)
        print(case["runId"][:8], case["source"], " ".join(f"{x['name']}:{row[x['name']]['outcome']}" for x in arms), flush=True)
    summ = {x["name"]: {**arm_summary(reps[x["name"]], rates.get(x["model"])), "model": x["model"], "context": x["context"]}
            for x in arms}
    ref = arms[0]["name"]
    verdicts = {x["name"]: verdict(summ[ref], summ[x["name"]]) for x in arms[1:]}
    out = {"version": VERSION, "at": dt.datetime.now(dt.timezone.utc).isoformat(), "effort": a.effort, "reference": ref,
           "cases": len(cases), "arms": summ, "verdicts": verdicts, "budget": budget.summary(), "rows": rows}
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, default=str)
    print(json.dumps({k: out[k] for k in ("arms", "verdicts", "budget")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
