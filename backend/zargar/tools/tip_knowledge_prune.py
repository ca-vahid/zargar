"""Knowledge that earns its place (sharp-pencil review #3, Q6 + Q8, 2026-09-27): PLAN (default) or APPLY (gated).

    python -m zargar.tools.tip_knowledge_prune --rules consolidated.json --out <dir>     # manifest.json + manifest.md + hash
    python -m zargar.tools.tip_knowledge_prune --rules consolidated.json --apply --confirm <manifestHash>

One reviewed manifest through the audited consolidation path (`POST /api/tip/knowledge/consolidate`, the 2026-09-14 path):
  Q6  the rulebook: each consolidated rule is a MERGE batch superseding its source rules (revision-checked); the rules
      the review retires are one EXPIRE batch; disputed (pending) sources are released inside the same transaction.
  Q8  notes: per `source:<name>` scope the `--keep` most relied-on notes stay (cited, then last cited, then newest),
      the rest expire; `general` notes supplied more than `--general-min-supplied` times and never cited expire.
      Pinned (core) and disputed notes are never touched by Q8.
Nothing is deleted: every change is a revision transition with a receipt; `consolidation.rollback_plan` lists the exact
reversal. The hash covers every id, revision and text - a changed note since planning refuses the whole apply.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import asyncpg

DEFAULT_DB = os.environ.get("ZARGAR_DATABASE_URL_SYNC", "postgresql://zargar:zargar@127.0.0.1:5433/zargar")
DEFAULT_API = os.environ.get("ZARGAR_API", "http://127.0.0.1:8420")
LIVE = "deleted_at is null and superseded_by is null and (valid_until is null or valid_until > now())"


def plan_rules(consolidated: dict, live: dict[str, dict], *, tag: str) -> tuple[list, list, list[str]]:
    """(resolve, batches, problems) for the consolidated rulebook. Pure."""
    problems: list[str] = []
    rules = consolidated.get("rules") or []
    expire = consolidated.get("expire") or []
    covered = [i for r in rules for i in r.get("supersedes") or []] + [e["id"] for e in expire]
    dup = {i for i in covered if covered.count(i) > 1}
    if dup:
        problems.append(f"ids covered twice: {sorted(dup)[:5]}")
    missing = sorted(set(live) - set(covered))
    if missing:
        problems.append(f"{len(missing)} live rules not covered by the consolidation: {missing[:5]}")
    unknown = sorted(set(covered) - set(live))
    if unknown:
        problems.append(f"{len(unknown)} ids are not live rules any more: {unknown[:5]}")
    resolve = [{"id": i, "revision": int(live[i]["revision"])} for i in covered if i in live and live[i]["needs_human"]]
    batches = []
    for n, r in enumerate(rules, 1):
        if not str(r.get("text") or "").startswith("RULE ("):
            problems.append(f"rule {n} does not start with 'RULE ('")
        ids = [i for i in r.get("supersedes") or [] if i in live]
        batches.append({"batchId": f"{tag}-rule-{n:02d}", "scope": "rule",
                        "merge": {"supersedes": ids, "new_rule": r["text"]},
                        "expected_revisions": {i: int(live[i]["revision"]) for i in ids}})
    ex_ids = [e["id"] for e in expire if e["id"] in live]
    if ex_ids:
        reasons = "; ".join(f"{e['id'][:8]}: {e.get('reason', '')}" for e in expire)
        batches.append({"batchId": f"{tag}-rule-expire", "scope": "rule",
                        "expire": {"ids": ex_ids, "reason": f"retired by sharp-pencil review #3 ({reasons})"[:4000]},
                        "expected_revisions": {i: int(live[i]["revision"]) for i in ex_ids}})
    return resolve, batches, problems


def plan_notes(notes: list[dict], *, keep: int, general_min_supplied: int, tag: str) -> list[dict]:
    """Q8 expire batches (pure): per source scope keep the `keep` most relied-on; general never-cited retire."""
    batches: list[dict] = []
    by_scope: dict[str, list[dict]] = {}
    for n in notes:
        by_scope.setdefault(n["scope"], []).append(n)
    for scope in sorted(by_scope):
        rows = [r for r in by_scope[scope] if not r["core"] and not r["needs_human"]]
        if scope.startswith("source:"):
            rows.sort(key=lambda r: (-(r["cited_count"] or 0), -(r["last_cited"] or 0), -(r["created"] or 0)))
            drop = rows[keep:]
            why = f"Q8 note cap: {scope} keeps its {keep} most relied-on notes"
        elif scope == "general":
            drop = [r for r in rows if (r["cited_count"] or 0) == 0 and (r["supplied_count"] or 0) > general_min_supplied]
            why = f"Q8: supplied more than {general_min_supplied} times, never cited"
        else:
            continue
        if not drop:
            continue
        safe = "".join(ch if ch.isalnum() else "-" for ch in scope)[:60]
        batches.append({"batchId": f"{tag}-notes-{safe}", "scope": scope,
                        "expire": {"ids": [r["id"] for r in drop], "reason": why},
                        "expected_revisions": {r["id"]: int(r["revision"]) for r in drop}})
    return batches


async def plan(db: str, rules_path: str, *, keep: int, general_min_supplied: int, tag: str) -> dict:
    from ..techniques.tip.consolidation import payload_hash
    conn = await asyncpg.connect(db)
    try:
        rrows = await conn.fetch(f"select id, revision_no, needs_human from tip_notes where scope='rule' and {LIVE}")
        nrows = await conn.fetch(
            f"""select id, scope, revision_no, needs_human, core, cited_count, supplied_count,
                       extract(epoch from last_cited_at) lc, extract(epoch from created_at) cr
                from tip_notes where (scope like 'source:%' or scope = 'general') and {LIVE}""")
    finally:
        await conn.close()
    live = {r["id"]: {"revision": r["revision_no"] or 1, "needs_human": bool(r["needs_human"])} for r in rrows}
    resolve, batches, problems = ([], [], [])
    if rules_path:
        consolidated = json.loads(Path(rules_path).read_text(encoding="utf-8"))
        resolve, batches, problems = plan_rules(consolidated, live, tag=tag)
    notes = [{"id": r["id"], "scope": r["scope"], "revision": r["revision_no"] or 1, "needs_human": bool(r["needs_human"]),
              "core": bool(r["core"]), "cited_count": r["cited_count"], "supplied_count": r["supplied_count"],
              "last_cited": float(r["lc"] or 0), "created": float(r["cr"] or 0)} for r in nrows]
    batches += plan_notes(notes, keep=keep, general_min_supplied=general_min_supplied, tag=tag)
    m = {"resolve": resolve, "batches": batches, "evidence": [], "problems": problems}
    m["manifestHash"] = payload_hash(resolve=resolve, batches=batches, evidence=[])
    m["summary"] = {
        "rulesLive": len(live), "rulesNew": sum(1 for b in batches if b.get("merge")),
        "rulesExpired": sum(len(b["expire"]["ids"]) for b in batches if b.get("expire") and b["scope"] == "rule"),
        "released": len(resolve),
        "notesExpired": sum(len(b["expire"]["ids"]) for b in batches if b.get("expire") and b["scope"] != "rule"),
        "noteScopes": sum(1 for b in batches if b.get("expire") and b["scope"] != "rule")}
    return m


def to_markdown(m: dict) -> str:
    L = [f"# Tips knowledge manifest `{m['manifestHash']}`", "", "```", json.dumps(m["summary"], indent=1), "```", ""]
    if m["problems"]:
        L += ["## PROBLEMS (apply refuses)", *[f"- {p}" for p in m["problems"]], ""]
    for b in m["batches"]:
        if b.get("merge"):
            L += [f"## {b['batchId']} - supersedes {len(b['merge']['supersedes'])}", "", b["merge"]["new_rule"], ""]
    for b in m["batches"]:
        if b.get("expire"):
            L += [f"- {b['batchId']} ({b['scope']}): expire {len(b['expire']['ids'])} - {b['expire']['reason'][:200]}"]
    return "\n".join(L) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rules", default="", help="consolidated rulebook JSON {rules:[{family,text,supersedes}], expire:[{id,reason}]}")
    ap.add_argument("--keep", type=int, default=15, help="notes kept per source scope")
    ap.add_argument("--general-min-supplied", type=int, default=20)
    ap.add_argument("--tag", default="review3-2026-09-27")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--confirm", default="")
    ap.add_argument("--api", default=DEFAULT_API)
    a = ap.parse_args()
    m = await plan(a.db, a.rules, keep=a.keep, general_min_supplied=a.general_min_supplied, tag=a.tag)
    print(f"manifestHash {m['manifestHash']}; {json.dumps(m['summary'])}")
    for p in m["problems"]:
        print("PROBLEM:", p)
    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "manifest.json").write_text(json.dumps(m, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        (out / "manifest.md").write_text(to_markdown(m), encoding="utf-8")
        print("wrote", out / "manifest.md")
    if a.apply:
        if m["problems"]:
            print("REFUSED: the manifest has problems"); sys.exit(2)
        if not a.confirm or a.confirm != m["manifestHash"]:
            print(f"REFUSED: --confirm must equal the fresh manifest hash ({m['manifestHash']})"); sys.exit(2)
        import httpx
        token = subprocess.run([sys.executable, "-m", "zargar.tools.mint_session"], capture_output=True, text=True,
                               check=True).stdout.strip().splitlines()[-1]
        async with httpx.AsyncClient(base_url=a.api, headers={"Authorization": f"Bearer {token}"}, timeout=300) as c:
            r = await c.post("/api/tip/knowledge/consolidate", json={
                "manifestHash": m["manifestHash"], "resolve": m["resolve"], "batches": m["batches"], "evidence": []})
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:400]
            print(json.dumps({"status": r.status_code, "body": body}, indent=1, default=str)[:4000])


if __name__ == "__main__":
    asyncio.run(main())
