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
    batches = {
        "A_resolveDisputes": {"ids": [r["id"] for r in family if r["disputed"]] + ([ks["id"]] if ks is not None and ks["needs_human"] else []),
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
    canon = json.dumps({"B": batches["B_geometryFamily"]["expected_revisions"], "C": batches["C_killSwitch"]["expected_revisions"],
                        "familyText": hashlib.sha256(FAMILY_TEXT.encode()).hexdigest(),
                        "ksText": hashlib.sha256(KILLSWITCH_TEXT.encode()).hexdigest(),
                        "evidence": [(e["sourceId"], e["sourceRevision"]) for e in evidence]}, sort_keys=True)
    batches["manifestHash"] = hashlib.sha256(canon.encode()).hexdigest()
    batches["rollback"] = ("supersede the family note and the kill-switch note with expired:rollback (snapshot), then "
                           "restore superseded_by=NULL on each source ONLY where its revision_no still equals the value in "
                           "expected_revisions (+1 for the supersede snapshot); evidence records stay; re-dispute the two rules "
                           "if the policy question reopens")
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
            "manifestHash": m["manifestHash"], "resolve": m["A_resolveDisputes"]["ids"],
            "family": m["B_geometryFamily"], "killSwitch": m["C_killSwitch"], "evidence": m["D_evidence"]})
        out["status"] = r.status_code
        out["body"] = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:400]
    return out


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--confirm", default="")
    ap.add_argument("--api", default=DEFAULT_API)
    args = ap.parse_args()
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
