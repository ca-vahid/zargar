"""Truncation restoration — PREPARE (default) or APPLY (gated) the exact
revision transitions for notes whose full text survives in their run trace.

Background (consolidation packet §4, reviewer GO 2026-09-13 to PREPARE): 22
notes sit at exactly 2,000 characters (the old silent cut); for 19 of them
the analyst run that saved the note still holds the `save_note` tool input
with the full text, of which the stored text is an exact prefix. Restoring
that text is a knowledge mutation, so it is a REVISION TRANSITION (snapshot
first, revision checked, journaled with the evidence hash), never a backdate
and never an in-place overwrite.

    python -m zargar.tools.tip_note_restore                      # plan -> manifest JSON + markdown on stdout
    python -m zargar.tools.tip_note_restore --out <dir>          # also write manifest.json + manifest.md
    python -m zargar.tools.tip_note_restore --apply --confirm <manifestHash>   # via the running app's API

`--apply` re-plans first and refuses unless the fresh manifest hash equals
`--confirm` (any note edited since the reviewed plan invalidates it), then
posts each transition to `POST /api/tip/notes/{id}/restore`, which checks
the revision again under a row lock.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import sys

import asyncpg

DEFAULT_DB = os.environ.get("ZARGAR_DATABASE_URL_SYNC",
                            "postgresql://zargar:zargar@127.0.0.1:5433/zargar")
DEFAULT_API = os.environ.get("ZARGAR_API", "http://127.0.0.1:8420")


def _walk(o, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str) and len(v) >= 1500:
                out.append((k, v))
            else:
                _walk(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk(v, out)


async def plan(db: str, ids: list[str] | None = None, length: int = 2000) -> dict:
    conn = await asyncpg.connect(db)
    try:
        # `deleted_at` exists from v0.7.65 on; a store one release behind is read
        # without it (a tombstone there still carries superseded_by='deleted:user')
        has_deleted = bool(await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns WHERE table_name='tip_notes' AND column_name='deleted_at'"))
        cols = ("id, scope, author, run_id, created_at, revision_no, revised_at, text, superseded_by, "
                + ("deleted_at" if has_deleted else "NULL::timestamptz AS deleted_at"))
        if ids:
            notes = await conn.fetch(
                f"SELECT {cols} FROM tip_notes WHERE id = ANY($1::text[]) ORDER BY created_at", ids)
        else:
            notes = await conn.fetch(
                f"SELECT {cols} FROM tip_notes WHERE length(text) = $1 ORDER BY created_at", length)
        entries, unproven = [], []
        for n in notes:
            stored = n["text"]
            evidence = None
            if n["run_id"]:
                run = await conn.fetchrow("SELECT id, kind, status, trace FROM tip_analyst_runs WHERE id=$1",
                                          n["run_id"])
                if run:
                    trace = run["trace"] if isinstance(run["trace"], list) else json.loads(run["trace"] or "[]")
                    cands = []
                    for step in trace:
                        if isinstance(step, dict) and step.get("kind") == "tool_call" \
                                and (step.get("tool") or "") == "save_note":
                            found: list = []
                            _walk(step, found)
                            for k, v in found:
                                if v.startswith(stored) and len(v) > len(stored):
                                    cands.append((k, v))
                    if cands:
                        k, v = max(cands, key=lambda c: len(c[1]))
                        evidence = {"runId": run["id"], "runKind": run["kind"], "field": k,
                                    "fullLength": len(v), "sha256": hashlib.sha256(v.encode("utf-8")).hexdigest(),
                                    "text": v}
            base = {"id": n["id"], "scope": n["scope"], "author": n["author"], "runId": n["run_id"],
                    "createdAt": n["created_at"].isoformat(), "currentRevision": int(n["revision_no"] or 1),
                    "revisedAt": n["revised_at"].isoformat() if n["revised_at"] else None,
                    "storedLength": len(stored),
                    "live": n["superseded_by"] is None and n["deleted_at"] is None}
            if evidence is None:
                unproven.append({**base, "verdict": "no trace evidence — left unproven, nothing proposed"})
                continue
            entries.append({
                **base,
                "evidence": {k: v for k, v in evidence.items() if k != "text"},
                "prefixMatch": evidence["text"].startswith(stored),
                "addedChars": evidence["fullLength"] - len(stored),
                "addedText": evidence["text"][len(stored):],
                "transition": {"reason": "restore", "author": f"restore-from-trace:{evidence['runId'][:8]}",
                               "expectedRevision": int(n["revision_no"] or 1),
                               "newRevision": int(n["revision_no"] or 1) + 1,
                               "text": evidence["text"]},
            })
    finally:
        await conn.close()
    canon = json.dumps([{"id": e["id"], "expectedRevision": e["transition"]["expectedRevision"],
                         "sha256": e["evidence"]["sha256"]} for e in entries], sort_keys=True)
    return {"plannedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "manifestHash": hashlib.sha256(canon.encode("utf-8")).hexdigest(),
            "restorations": entries, "unproven": unproven,
            "rule": "apply only with --confirm <manifestHash>; every entry is a revision transition "
                    "(snapshot, revision check under lock, journaled with the evidence hash); no backdating"}


def to_markdown(m: dict) -> str:
    lines = [f"# Truncation restoration manifest — planned {m['plannedAt'][:19]}Z",
             "", f"Manifest hash: `{m['manifestHash']}`  ", f"Restorations: {len(m['restorations'])}; unproven: {len(m['unproven'])}",
             "", "| id | scope | rev | run | full len | +chars | sha256 (12) |", "|---|---|---|---|---|---|---|"]
    for e in m["restorations"]:
        lines.append(f"| `{e['id']}` | {e['scope']} | {e['currentRevision']} | `{e['evidence']['runId'][:8]}` | "
                     f"{e['evidence']['fullLength']} | +{e['addedChars']} | `{e['evidence']['sha256'][:12]}` |")
    lines += ["", "## Added text (for review — restored qualifiers can affect policy)", ""]
    for e in m["restorations"]:
        lines += [f"### `{e['id'][:8]}` {e['scope']} (+{e['addedChars']} chars)", "",
                  "> " + e["addedText"].replace("\n", "\n> "), ""]
    if m["unproven"]:
        lines += ["## Unproven (nothing proposed)", ""]
        for u in m["unproven"]:
            lines.append(f"- `{u['id']}` {u['scope']} — {u['verdict']}")
    return "\n".join(lines) + "\n"


async def apply(m: dict, api: str, token: str) -> int:
    import httpx
    n = 0
    async with httpx.AsyncClient(base_url=api, headers={"Authorization": f"Bearer {token}"}, timeout=30) as c:
        for e in m["restorations"]:
            if not e["live"] or not e["prefixMatch"]:
                print(f"skip {e['id'][:8]}: not live / prefix mismatch")
                continue
            r = await c.post(f"/api/tip/notes/{e['id']}/restore", json={
                "text": e["transition"]["text"], "expectedRevision": e["transition"]["expectedRevision"],
                "sourceRunId": e["evidence"]["runId"], "evidenceSha256": e["evidence"]["sha256"]})
            print(f"{e['id'][:8]} -> {r.status_code} {r.text[:120]}")
            n += int(r.status_code == 200)
    return n


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--ids", default="", help="comma-separated note ids (default: every note at exactly --length chars)")
    ap.add_argument("--length", type=int, default=2000)
    ap.add_argument("--out", default="", help="directory for manifest.json + manifest.md")
    ap.add_argument("--apply", action="store_true", help="post the transitions to the running app (needs --confirm)")
    ap.add_argument("--confirm", default="", help="the manifestHash of the REVIEWED plan; must equal a fresh re-plan")
    ap.add_argument("--api", default=DEFAULT_API)
    args = ap.parse_args()
    ids = [i.strip() for i in args.ids.split(",") if i.strip()] or None
    m = await plan(args.db, ids, args.length)
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2, ensure_ascii=False)
        with open(os.path.join(args.out, "manifest.md"), "w", encoding="utf-8") as f:
            f.write(to_markdown(m))
        print(f"wrote {args.out}/manifest.json + manifest.md")
    print(to_markdown(m) if not args.out else f"manifestHash {m['manifestHash']}; "
          f"{len(m['restorations'])} restorations, {len(m['unproven'])} unproven")
    if args.apply:
        if not args.confirm or args.confirm != m["manifestHash"]:
            print("REFUSED: --confirm must equal the fresh manifest hash "
                  f"({m['manifestHash']}); a note changed since the reviewed plan, or no hash given")
            sys.exit(2)
        import subprocess
        token = subprocess.run([sys.executable, "-m", "zargar.tools.mint_session"],
                               capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
        n = await apply(m, args.api, token)
        print(f"applied {n}/{len(m['restorations'])}")


if __name__ == "__main__":
    asyncio.run(main())
