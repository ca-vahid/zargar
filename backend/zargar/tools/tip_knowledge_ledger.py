"""Knowledge ledger: what the rulebook and the notes COST and whether they EARN it (ADV-11, 2026-09-23). Read-only,
plus a manifest for a reviewed, reversible retirement.

Every operative rule and every supplied note is re-sent on every analyst call, so a rule is a permanent tax. This
report prints, per operative rule: characters (its cost on every call), dated cases it cites (evidence binding), how
often it was SUPPLIED and how often a run RELIED on it (cited), and flags:
  * `unbound`   - fewer than MIN_CASES dated cases cited (a rule written from one trade);
and the reliance gap (rules are never cited by id, so their reliance is unknown);
and, for notes, the ones never relied on in RETIRE_DAYS days (retirement candidates).

    python -m zargar.tools.tip_knowledge_ledger                    # report
    python -m zargar.tools.tip_knowledge_ledger --manifest out.json  # write a retirement manifest (tombstones via the
                                                                     # audited batch path after a human review; nothing is changed here)
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import re

MIN_CASES = 3
RETIRE_DAYS = 30
RULE_BUDGET_SUGGESTED = 15
_CASE = re.compile(r"\b(?:\d{1,2}/\d{1,2}|2026-\d{2}-\d{2})\b")


def cases_cited(text: str) -> int:
    """Distinct dated cases a rule cites (`9/04`, `2026-09-14`) - the evidence it claims to generalise from."""
    return len(set(_CASE.findall(text or "")))


def judge_rule(r: dict) -> list[str]:
    flags = []
    if cases_cited(r["text"]) < MIN_CASES:
        flags.append("unbound")
    # reliance is NOT recorded for rules today (runs cite notes by id; rules carry no id in the prompt), so a rule's
    # `cited_count` is always 0 - flagging it "unused" would be false. The gap is reported instead (ADV-11).
    return flags


async def build(conn, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    rules = [dict(r) for r in await conn.fetch("""select id, text, core, supplied_count, cited_count, created_at, revision_no
                                                  from tip_notes where scope = 'rule' and superseded_by is null
                                                  and deleted_at is null and not coalesce(needs_human, false)
                                                  order by created_at""")]
    for r in rules:
        r["chars"] = len(r["text"] or "")
        r["cases"] = cases_cited(r["text"])
        r["flags"] = judge_rule(r)
    cutoff = now - dt.timedelta(days=RETIRE_DAYS)
    notes = [dict(r) for r in await conn.fetch("""select id, scope, revision_no, length(text) as chars, supplied_count, cited_count,
                                                  last_cited_at, created_at, core
                                                  from tip_notes where scope not in ('rule') and superseded_by is null
                                                  and deleted_at is null and not coalesce(needs_human, false)
                                                  and scope not like 'evidence:%' and scope not like 'experiment:%'""")]
    retire = [n for n in notes if not n["core"] and n["created_at"] < cutoff
              and (n["last_cited_at"] is None or n["last_cited_at"] < cutoff)]
    return {"rules": rules, "notes": notes, "retire": retire, "cutoff": cutoff.isoformat()}


def render(res: dict) -> str:
    rules = res["rules"]
    total = sum(r["chars"] for r in rules)
    L = ["# Tips knowledge ledger (ADV-11)\n",
         f"Operative rules: **{len(rules)}**, {total:,} chars (~{total // 4:,} tokens) re-sent on every analyst call. "
         f"Suggested budget: {RULE_BUDGET_SUGGESTED} pinned/core rules; the rest proposals until they bind >= {MIN_CASES} dated cases.\n",
         "| rule (first line) | chars | dated cases | supplied | relied | core | flags |", "|---|---:|---:|---:|---:|---|---|"]
    for r in sorted(rules, key=lambda x: (-len(x["flags"]), -x["chars"])):
        first = re.sub(r"\s+", " ", r["text"])[:90].replace("|", "/")
        L.append(f"| {first} | {r['chars']:,} | {r['cases']} | {r['supplied_count'] or 0} | {r['cited_count'] or 0} | "
                 f"{'yes' if r['core'] else ''} | {', '.join(r['flags']) or '-'} |")
    ub = sum(1 for r in rules if "unbound" in r["flags"])
    L.append(f"\n{ub} rule(s) cite fewer than {MIN_CASES} dated cases. **Measurement gap:** reliance is not recorded for "
             "rules (every rule shows 0 relied) - runs cite notes by id and rules carry no id in the prompt - so whether a "
             "rule ever changed a decision is unknown. Closing it means giving rules ids the model can cite (a prompt change).")
    notes = res["notes"]
    by = {}
    for n in notes:
        fam = n["scope"].split(":", 1)[0]
        g = by.setdefault(fam, {"n": 0, "chars": 0, "never": 0})
        g["n"] += 1; g["chars"] += int(n["chars"] or 0); g["never"] += 0 if (n["cited_count"] or 0) else 1
    L.append("\n| note family | live notes | chars | never relied on |\n|---|---:|---:|---:|")
    for fam, g in sorted(by.items(), key=lambda kv: -kv[1]["n"]):
        L.append(f"| {fam} | {g['n']} | {g['chars']:,} | {g['never']} |")
    L.append(f"\nRetirement candidates (not core, older than {RETIRE_DAYS} days, not relied on since {res['cutoff'][:10]}): "
             f"**{len(res['retire'])}** notes. Retirement is a TOMBSTONE through the audited batch path after a human reads "
             "the manifest - reversible, never a delete.")
    return "\n".join(L)


def manifest(res: dict) -> dict:
    items = [{"id": n["id"], "scope": n["scope"], "revision": int(n["revision_no"] or 1)} for n in res["retire"]]
    body = json.dumps(items, sort_keys=True)
    return {"kind": "tip-note-retirement", "version": 1, "cutoff": res["cutoff"], "count": len(items), "items": items,
            "manifestHash": hashlib.sha256(body.encode()).hexdigest()[:16],
            "apply": "human review first; apply as an `expire` batch via POST /api/tip/knowledge/consolidate (reason "
                     "'ADV-11 not relied on in 30 days'); rollback = the batch receipt"}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--manifest", default=None)
    a = ap.parse_args()
    import asyncpg
    c = await asyncpg.connect(a.db, server_settings={"default_transaction_read_only": "on"})
    try:
        res = await build(c)
    finally:
        await c.close()
    print(render(res))
    if a.manifest:
        with open(a.manifest, "w", encoding="utf-8") as fh:
            json.dump(manifest(res), fh, indent=1, default=str)


if __name__ == "__main__":
    asyncio.run(main())
