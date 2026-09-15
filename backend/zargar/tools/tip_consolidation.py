"""The reviewed knowledge batches (consolidation packet 2026-09-13, reviewer GO
2026-09-14): PLAN (default) or APPLY (gated) through the audited paths.

    python -m zargar.tools.tip_consolidation                 # print the manifest (exact text, ids, revisions)
    python -m zargar.tools.tip_consolidation --out <dir>     # also write manifest.json + manifest.md
    python -m zargar.tools.tip_consolidation --apply --confirm <manifestHash>

Batches (applied in this order, each an audited revision transition):
  A. resolve the two disputed kill-switch rules (the human decision is made: the
     approved policy is the execution-integrity pause) — journaled `resolved`
  B. `consolidation-geometry-2026-09-14`: the 28 geometry-family rules (27 clean +
     the base note dbfd8177 whose geometry content folds in) -> ONE canonical
     family rule via `apply_knowledge_batch(mode="apply")` (revision-checked,
     receipt in `tip_knowledge_batches`)
  C. `consolidation-killswitch-2026-09-14`: 7e72fd7f (clock-vs-geometry kill
     switch) -> the incident-based session-pause rule (same path)
  D. 14 evidence records in `evidence:adoption-geometry` (never injected)
     citing their source ids
Rollback = revision transitions: supersede the new notes with `expired:rollback`
and restore `superseded_by = NULL` on each source ONLY at its recorded revision.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import asyncio
import hashlib
import json
import os
import sys

import asyncpg

DEFAULT_DB = os.environ.get("ZARGAR_DATABASE_URL_SYNC", "postgresql://zargar:zargar@127.0.0.1:5433/zargar")
DEFAULT_API = os.environ.get("ZARGAR_API", "http://127.0.0.1:8420")

FAMILY_PREFIXES = {
    # 27 clean members + the base note; verified ids (8-char prefixes) from the packet §1a
    "dbfd8177": "base: all five checks (its clock clause is superseded by batch C)",
    "f120c2b9": "1 SIGN — wrong-side ladder is a direction-label error",
    "779fbcf3": "4 STALENESS gate", "cac7bd77": "4 STALENESS — consumed risk (threshold: HYPOTHESIS)",
    "17ec9915": "2 STOP WIDTH — >= 1x ATR of the plan timeframe", "eff8c28b": "2/5 enforcement of checks 2 + 5",
    "e306ebce": "2 STOP WIDTH — token stop voids designed risk", "3d08ab90": "2 momentum-chase stop below the impulse origin",
    "c4d3b50c": "2 high-beta branch (HYPOTHESIS)", "557e30da": "3 TARGET WIDTH (threshold: HYPOTHESIS); recycled-levels red flag",
    "d45362c1": "3 time box must match the ladder", "6f6e925b": "3 premium-% stop translated to an underlying move",
    "f39cf0b6": "3 never a premium ratchet on a debit spread", "6083fce5": "5 stop KIND matches the stated invalidation",
    "4ccdf6ed": "2 pre-adoption arithmetic gate (case 5)", "2de9051d": "2 15m extra floor (HYPOTHESIS, case 7)",
    "827e4527": "2 high-priced names: percent not dollars (case 10)", "26c38231": "2 high-beta branch (HYPOTHESIS, case 8)",
    "595642da": "2/3 high-beta branch (HYPOTHESIS, case 9)", "779afa13": "5 duplicate-ticket detector (case 11)",
    "bca1cac4": "1 SIGN third confirming case + cost dimension", "0477b92b": "2 a token stop that PAYS is still a defect",
    "1d301597": "affirmative counterpart — a PASSING adoption", "7101b397": "affirmative counterpart, extended",
    "395ce53e": "affirmative counterpart — third passing case", "e6794b52": "case 6 — AMZN memo (engine-defect evidence)",
    "082d17b5": "case 12", "0db23ca6": "case 13 + duplicate reduce-order hygiene",
}
KILLSWITCH_PREFIX = "7e72fd7f"
EVIDENCE_PREFIXES = ["4ccdf6ed", "2de9051d", "827e4527", "26c38231", "595642da", "779afa13", "bca1cac4",
                     "0477b92b", "1d301597", "7101b397", "395ce53e", "e6794b52", "082d17b5", "0db23ca6"]

FAMILY_TEXT = """RULE (adoption geometry — canonical family, consolidated 2026-09-14 from 28 rules; the code gate `techniques.tip.geometry_gate=enforce` validates -> repairs -> resizes -> revalidates BEFORE entry, and this rule is the analyst's statement of the same policy):
1. SIGN — long: stop < entry and every target > entry; short/put: mirrored. A wrong-side ladder is usually a DIRECTION-LABEL error (the level set fits the opposite direction): treat it as a defective plan, never "let the engine sort it out".
2. STOP WIDTH — the stop sits OUTSIDE the underlying's noise on the plan timeframe. Formulas are direction-explicit and in UNDERLYING units: long stopWidthPct = (entry − stop) / spot; short stopWidthPct = (stop − entry) / spot; a non-positive width is a SIGN failure. Momentum-chase entries: the stop sits below (long) / above (short) the impulse ORIGIN. High-priced names: judge percent, not dollars. A token stop that happens to PAY is still a defect. Numeric floors (0.75%, 1x plan-timeframe ATR) are the code gate's engineering floors, not this rule's authority; the high-beta / sub-$25 (1.5% or 1x daily ATR when the 5-session range > 10% of spot) and 15m-timeframe extra floors are HYPOTHESES under observation, not operative policy.
3. TARGET WIDTH — the first target clears the noise floor and the time box is long enough for the ladder; a premium-% stop must be translated to an underlying move and sit outside the stated invalidation; never a premium ratchet on a debit spread. The TP1 >= max(0.5x ATR, ~1R) figure is a HYPOTHESIS, not operative policy.
4. STALENESS — compare the plan entry to LIVE spot before adopting; consumed risk = long (entry − spot)/(entry − stop), short (spot − entry)/(stop − entry). A missing or stale spot, a missing ATR or a zero denominator means CANNOT JUDGE (recorded as such) — neither a pass nor a refusal. The 0.5 consumed-risk threshold is a HYPOTHESIS.
5. DUPLICATE-TICKET / STOP-KIND — the same defective geometry re-handed with a cosmetically re-cut ladder is ONE defect; a source's daily-close invalidation is never translated into an intraday GTC.
Evidence for every clause lives in scope evidence:adoption-geometry (14 dated cases, never injected). Repeated processing of one trade is not independent support. The AMZN/MU "absolute auto-refuse" memos were engine-defect evidence; with the pre-entry gate they are moot."""

KILLSWITCH_TEXT = """RULE (session kill-switch — execution-integrity pause; replaces the 2026-09-04 clock clause and the 2026-09-11 geometry refinement, approved 2026-09-14): a fast stop on a trade whose final geometry, sizing, quote evidence and fills were all valid is a CLEAN losing trade — it produces a diagnostic, never a session-wide refusal; the daily-loss limits own that decision independently. Automated tip entries pause on an execution-integrity INCIDENT: a filled trade outside its risk plan, an exit on unconfirmed or delayed evidence, duplicate or unreconciled fills, a repeatedly failing entry path, or an identified shared-component failure. An incident is a persisted record (it survives restarts and date rollovers), scoped to what its evidence implicates, honoured by every automated entry path — auto-approval, already-armed plans, retries — never by exits, and released only on evidence bound to it that proves the repair (or an explicit, labeled human override). Missing evidence is a HOLD, not proof of validity. Runtime: techniques.tip.entry_pause_mode = integrity."""


def _walk_evidence_text(row: dict) -> str:
    t = row["text"]
    return t if len(t) <= 4000 else t[:4000]


async def plan(db: str) -> dict:
    conn = await asyncpg.connect(db)
    try:
        live = await conn.fetch("SELECT id, revision_no, needs_human, superseded_by, text, created_at, author "
                                "FROM tip_notes WHERE scope='rule' AND superseded_by IS NULL ORDER BY created_at")
        by_prefix = {r["id"][:8]: r for r in live}
        missing = [p for p in list(FAMILY_PREFIXES) + [KILLSWITCH_PREFIX] if p not in by_prefix]
        family = [{"id": by_prefix[p]["id"], "prefix": p, "revision": int(by_prefix[p]["revision_no"] or 1),
                   "disputed": bool(by_prefix[p]["needs_human"]), "clause": c}
                  for p, c in FAMILY_PREFIXES.items() if p in by_prefix]
        ks = by_prefix.get(KILLSWITCH_PREFIX)
        evidence = []
        for p in EVIDENCE_PREFIXES:
            r = by_prefix.get(p)
            if r is None:
                continue
            evidence.append({"scope": "evidence:adoption-geometry", "sourceId": r["id"], "sourceRevision": int(r["revision_no"] or 1),
                             "text": f"[EVIDENCE — cites rule {r['id']} rev {r['revision_no']}, {r['created_at']:%Y-%m-%d}, by {r['author']}; "
                                     f"superseded by the canonical adoption-geometry family on 2026-09-14; research record, never injected]\n"
                                     + _walk_evidence_text(dict(r))})
    finally:
        await conn.close()
    resolve = [{"id": r["id"], "revision": r["revision"]} for r in family if r["disputed"]] + \
              ([{"id": ks["id"], "revision": int(ks["revision_no"] or 1)}] if ks is not None and ks["needs_human"] else [])
    batches = {
        "A_resolveDisputes": {"ids": [x["id"] for x in resolve], "resolve": resolve,
                              "reason": "human decision 2026-09-14: the approved session policy is the execution-integrity pause (batch C); the geometry base note folds into the canonical family (batch B)"},
        "B_geometryFamily": {"batchId": "consolidation-geometry-2026-09-14", "scope": "rule",
                             "merge": {"supersedes": [r["id"] for r in family], "new_rule": FAMILY_TEXT},
                             "expected_revisions": {r["id"]: r["revision"] for r in family},
                             "author": "consolidation:2026-09-14"},
        "C_killSwitch": {"batchId": "consolidation-killswitch-2026-09-14", "scope": "rule",
                         "merge": {"supersedes": [ks["id"]] if ks is not None else [], "new_rule": KILLSWITCH_TEXT},
                         "expected_revisions": {ks["id"]: int(ks["revision_no"] or 1)} if ks is not None else {},
                         "author": "consolidation:2026-09-14"},
        "D_evidence": evidence,
        "missing": missing,
    }
    # KFIN-05: ONE canonical payload hash shared with the server (`consolidation.payload_hash`):
    # every release (id + reviewed revision), every batch (id, scope, sources, expected
    # revisions, exact output text) and every evidence record (scope, source id + revision,
    # content). The server recomputes it from the payload it receives — a changed text
    # under the same hash is refused before any write.
    from ..techniques.tip.consolidation import payload_hash as _payload_hash
    server_batches = [b for b in (batches["B_geometryFamily"], batches["C_killSwitch"]) if b["merge"]["supersedes"]]
    batches["manifestHash"] = _payload_hash(resolve=resolve, batches=server_batches, evidence=evidence)
    batches["rollback"] = ("rollback guards are generated from the ACTUAL receipt after apply "
                           "(`tip_knowledge_batches` id consolidation:<hash>, field applied.rollbackPlan): per source the "
                           "revision at supersede time, the new rule id, the release transitions and the evidence note ids; "
                           "never assume +1 per source; evidence records stay; re-dispute a rule only if the policy question reopens")
    return batches


def to_markdown(m: dict) -> str:
    fam = m["B_geometryFamily"]
    lines = [f"# Consolidation batches — manifest hash `{m['manifestHash']}`", "",
             f"Missing ids: {m['missing'] or 'none'}", "",
             "## A — resolve disputes", *[f"- `{i}`" for i in m["A_resolveDisputes"]["ids"]], "",
             f"## B — geometry family `{fam['batchId']}` ({len(fam['merge']['supersedes'])} sources)", "",
             "| id | revision |", "|---|---|",
             *[f"| `{i}` | {r} |" for i, r in fam["expected_revisions"].items()], "",
             "### Exact family text", "", "```", FAMILY_TEXT, "```", "",
             f"## C — kill-switch `{m['C_killSwitch']['batchId']}`", "", "```", KILLSWITCH_TEXT, "```", "",
             f"## D — {len(m['D_evidence'])} evidence records (scope evidence:adoption-geometry)", "",
             *[f"- source `{e['sourceId']}` rev {e['sourceRevision']} ({len(e['text'])} chars)" for e in m["D_evidence"]], "",
             "## Rollback", "", m["rollback"], ""]
    return "\n".join(lines)


async def apply(m: dict, api: str, token: str) -> dict:
    import httpx
    out: dict = {}
    async with httpx.AsyncClient(base_url=api, headers={"Authorization": f"Bearer {token}"}, timeout=60) as c:
        r = await c.post("/api/tip/knowledge/consolidate", json={
            "manifestHash": m["manifestHash"], "resolve": m["A_resolveDisputes"]["resolve"],
            "family": m["B_geometryFamily"], "killSwitch": m["C_killSwitch"], "evidence": m["D_evidence"]})
        out["status"] = r.status_code
        out["body"] = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:400]
    return out


async def plan_rejection(db: str, ids: list[str], rationale: str, *, batch_id: str) -> dict:
    """A reviewed REJECTION of model-proposed rules (KFIN packet disposition,
    2026-09-14): each proposal is released at its reviewed revision, expired in
    ONE batch with the stated reason, and preserved verbatim as an
    `evidence:policy-proposals` record (research, never injected). Identity =
    the shared payload hash; the server refuses any drift before writing."""
    from ..techniques.tip.consolidation import payload_hash as _payload_hash
    conn = await asyncpg.connect(db)
    try:
        rows = await conn.fetch("SELECT id, revision_no, needs_human, superseded_by, text, created_at, author, valid_until "
                                "FROM tip_notes WHERE id = ANY($1::text[])", ids)
    finally:
        await conn.close()
    by_id = {r["id"]: r for r in rows}
    missing = [i for i in ids if i not in by_id]
    resolve = [{"id": i, "revision": int(by_id[i]["revision_no"] or 1)} for i in ids if i in by_id and by_id[i]["needs_human"]]
    expire = {"batchId": batch_id, "scope": "rule",
              "expire": {"ids": [i for i in ids if i in by_id], "reason": f"reviewed rejection {batch_id}: hypothesis, not policy"},
              "expected_revisions": {i: int(by_id[i]["revision_no"] or 1) for i in ids if i in by_id},
              "author": "review:2026-09-14"}
    evidence = [{"scope": "evidence:policy-proposals", "sourceId": i, "sourceRevision": int(by_id[i]["revision_no"] or 1),
                 "author": "review:2026-09-14",
                 "text": (f"[REJECTED PROPOSAL — rule {i} rev {by_id[i]['revision_no']}, {by_id[i]['created_at']:%Y-%m-%d}, by {by_id[i]['author']}] "
                          f"Reviewer disposition: {rationale.strip()}\n--- original text ---\n{by_id[i]['text']}")}
                for i in ids if i in by_id]
    payload = {"resolve": resolve, "batches": [expire], "evidence": evidence, "missing": missing}
    payload["manifestHash"] = _payload_hash(resolve=resolve, batches=[expire], evidence=evidence)
    return payload


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reject-proposals", default="", help="comma-separated note ids to reject through the audited wrapper")
    ap.add_argument("--rationale-file", default="", help="markdown/text with the reviewer's rationale (required with --reject-proposals)")
    ap.add_argument("--batch-id", default="rejection-policy-proposals-2026-09-14")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--confirm", default="")
    ap.add_argument("--api", default=DEFAULT_API)
    args = ap.parse_args()
    a = args
    if a.reject_proposals:
        ids = [x.strip() for x in a.reject_proposals.split(",") if x.strip()]
        rationale = open(a.rationale_file, encoding="utf-8").read() if a.rationale_file else ""
        if not rationale:
            print("REFUSED: --rationale-file is required"); return
        m = await plan_rejection(a.db, ids, rationale, batch_id=a.batch_id)
        print(f"rejection manifestHash {m['manifestHash']}; ids {len(ids)} (missing {m['missing']}); release {len(m['resolve'])}; "
              f"expire {len(m['batches'][0]['expire']['ids'])}; evidence {len(m['evidence'])}")
        if a.out:
            out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
            (out / "rejection-manifest.json").write_text(json.dumps(m, indent=1, default=str), encoding="utf-8")
            print("wrote", out / "rejection-manifest.json")
        if a.apply:
            if not a.confirm or a.confirm != m["manifestHash"]:
                print(f"REFUSED: --confirm must equal the fresh manifest hash ({m['manifestHash']})"); return
            token = subprocess.run([sys.executable, "-m", "zargar.tools.mint_session"], capture_output=True, text=True,
                                   check=True).stdout.strip().splitlines()[-1]
            async with httpx.AsyncClient(base_url=a.api, headers={"Authorization": f"Bearer {token}"}, timeout=120) as c:
                r = await c.post("/api/tip/knowledge/consolidate", json={
                    "manifestHash": m["manifestHash"], "resolve": m["resolve"], "batches": m["batches"], "evidence": m["evidence"]})
                print(json.dumps({"status": r.status_code, "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:400]}, indent=1)[:3000])
        return
    m = await plan(args.db)
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2, ensure_ascii=False, default=str)
        with open(os.path.join(args.out, "manifest.md"), "w", encoding="utf-8") as f:
            f.write(to_markdown(m))
    print(f"manifestHash {m['manifestHash']}; family {len(m['B_geometryFamily']['merge']['supersedes'])} ids; "
          f"evidence {len(m['D_evidence'])}; missing {m['missing']}")
    if args.apply:
        if not args.confirm or args.confirm != m["manifestHash"]:
            print(f"REFUSED: --confirm must equal the fresh manifest hash ({m['manifestHash']})")
            sys.exit(2)
        import subprocess
        token = subprocess.run([sys.executable, "-m", "zargar.tools.mint_session"], capture_output=True, text=True,
                               check=True).stdout.strip().splitlines()[-1]
        print(json.dumps(await apply(m, args.api, token), indent=1, default=str)[:3000])


if __name__ == "__main__":
    asyncio.run(main())
