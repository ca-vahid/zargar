"""Apply a REVIEWED consolidation payload through the audited knowledge paths
(consolidation packet 2026-09-13; reviewer GO 2026-09-14; hardened per the
completion packet KFIN-05, 2026-09-14). Nothing here is scheduled or automatic:
the caller passes the exact payload, and every step is a revision transition
with a receipt — routine maintenance stays propose-only.

Integrity model (KFIN-05):
  * ONE canonical payload hash (`payload_hash`) shared by the client tool and
    this server path. It covers every resolution action (id + the revision the
    reviewer examined), every merge/expire batch (batch id, scope, sorted
    source ids, expected revisions, sha256 of the exact output text / reason)
    and every evidence record (scope, source id, source revision, sha256 of
    the content). A payload whose text changed under the same claimed hash is
    refused before anything is written.
  * Every reviewed revision is validated BEFORE any mutation, including the
    dispute releases (a stale revision during resolution refuses the whole
    payload, nothing partial).
  * A durable wrapper receipt (`tip_knowledge_batches` id
    `consolidation:<hash>`) records progress step by step; a replay checks
    identity through the hash even after the sources were superseded and
    returns the recorded receipt (idempotent); a different payload under an
    already-applied batch id is refused (identity = sources + output text).
  * Evidence identity = source id + source revision + content hash, carried in
    the note's marker; a changed evidence revision is a different payload.
  * Rollback guards are generated from the ACTUAL receipt transitions
    (`rollback_plan`), never from an assumed "+1 per source".
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging

log = logging.getLogger("zargar.tip.consolidation")

WRAPPER_SCOPE = "consolidation"


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def evidence_marker(source_id: str, source_revision: int, text_hash: str) -> str:
    """The identity every evidence record carries in its text."""
    return f"cites rule {source_id} rev {int(source_revision)} sha {text_hash[:12]}"


def _batch_ids(b: dict) -> list[str]:
    return list((b.get("merge") or {}).get("supersedes") or (b.get("expire") or {}).get("ids") or [])


def canonical_payload(*, resolve, batches: list[dict], evidence: list[dict]) -> dict:
    """The exact reviewed content, in a canonical shape (texts as hashes)."""
    res = []
    for r in resolve or []:
        if isinstance(r, str):
            res.append({"id": r, "revision": None})
        else:
            res.append({"id": str(r.get("id")), "revision": (int(r["revision"]) if r.get("revision") is not None else None)})
    res.sort(key=lambda x: x["id"])
    bs = []
    for b in batches or []:
        kind = "merge" if b.get("merge") else ("expire" if b.get("expire") else "empty")
        if kind == "merge":
            body = {"supersedes": sorted(str(x) for x in (b["merge"].get("supersedes") or [])),
                    "textSha": _sha(str(b["merge"].get("new_rule") or ""))}
        elif kind == "expire":
            body = {"ids": sorted(str(x) for x in (b["expire"].get("ids") or [])),
                    "reasonSha": _sha(str(b["expire"].get("reason") or ""))}
        else:
            body = {}
        bs.append({"batchId": str(b.get("batchId") or ""), "scope": str(b.get("scope") or "rule"), "kind": kind,
                   "expectedRevisions": {str(k): int(v) for k, v in (b.get("expected_revisions") or {}).items()},
                   **body})
    bs.sort(key=lambda x: x["batchId"])
    ev = sorted(({"scope": str(e.get("scope") or ""), "sourceId": str(e.get("sourceId") or ""),
                  "sourceRevision": int(e.get("sourceRevision") or 0), "textSha": _sha(str(e.get("text") or ""))}
                 for e in (evidence or [])), key=lambda x: (x["sourceId"], x["scope"]))
    return {"v": 2, "resolve": res, "batches": bs, "evidence": ev}


def payload_hash(*, resolve, batches, evidence) -> str:
    return hashlib.sha256(json.dumps(canonical_payload(resolve=resolve, batches=batches, evidence=evidence),
                                     sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _batch_identity(b: dict) -> str:
    return payload_hash(resolve=[], batches=[{k: v for k, v in b.items() if not k.startswith("_")}], evidence=[])


def rollback_plan(receipt: dict) -> list[dict]:
    """Exact, per-id rollback instructions derived from what actually happened
    (the receipt's transitions), for a person to review — never executed here."""
    plan: list[dict] = []
    for t in (receipt.get("resolved") or []):
        plan.append({"step": "re-dispute", "id": t["id"], "revisionAfter": t.get("revisionTo"),
                     "note": "flag needs_human again ONLY if the note is still live at this revision"})
    for _key, b in (receipt.get("batches") or {}).items():
        for s in (b.get("superseded") or []):
            plan.append({"step": "restore-superseded", "id": s["id"], "revisionAtSupersede": s.get("revision"),
                         "supersededBy": b.get("newRuleId"),
                         "note": "clear superseded_by only if revision_no still equals revisionAtSupersede + 1 (the supersede snapshot)"})
        for x in (b.get("expired") or []):
            plan.append({"step": "un-expire", "id": x["id"], "revisionAtExpire": x.get("revision")})
        if b.get("newRuleId"):
            plan.append({"step": "expire-new-rule", "id": b["newRuleId"], "reason": "rollback"})
    for e in (receipt.get("evidence") or []):
        if e.get("id"):
            plan.append({"step": "keep", "id": e["id"], "note": "evidence records stay (research), tombstone only on request"})
    return plan


async def _applied_batch_matches(session, existing, b: dict) -> bool:
    """Is the batch receipt on file the SAME reviewed batch (sources + output)?
    New receipts carry the wrapper identity; a receipt written before KFIN-05
    is matched on its recorded merged/expired ids and the new rule's text."""
    from sqlalchemy import select
    from ...models import TipNote
    applied = dict(existing.applied or {})
    if applied.get("consolidationIdentity"):
        return applied["consolidationIdentity"] == _batch_identity(b)[:40]
    ids = sorted(_batch_ids(b))
    if b.get("merge"):
        new_ids = list(applied.get("newRules") or [])
        if len(new_ids) != 1:
            return False
        text = await session.scalar(select(TipNote.text).where(TipNote.id == new_ids[0]))
        if _sha(str(text or "").strip()) != _sha(str(b["merge"].get("new_rule") or "").strip()):
            return False
        sup = await session.execute(select(TipNote.id).where(TipNote.superseded_by == new_ids[0]))
        return sorted(str(x) for x in sup.scalars().all()) == ids
    exp = sorted(str(x) for x in (applied.get("expired") or []))
    return exp == ids if exp else False


async def apply_consolidation(eng, *, manifest_hash: str, resolve: list | None = None, family: dict | None = None,
                              kill_switch: dict | None = None, evidence: list[dict] | None = None,
                              batches: list[dict] | None = None, actor: str = "user") -> dict:
    """Validate the whole payload against the live rows, then apply it step by
    step under a durable receipt. `family`/`kill_switch` are kept for the
    2026-09-14 caller shape; `batches` is the general form (each a merge or an
    expire batch). Raises ValueError with NO mutation on any identity or
    revision mismatch."""
    from sqlalchemy import select
    from ... import events as ev
    from ...models import TipKnowledgeBatch, TipNote
    svc = eng.signals_service
    batches = list(batches or [])
    for key, b in (("family", family), ("killSwitch", kill_switch)):
        if b and _batch_ids(b):
            batches.append({**b, "_key": key})
    resolve = list(resolve or [])
    evidence = list(evidence or [])
    # ---- 0. identity: the client's hash must be the hash of THIS payload
    computed = payload_hash(resolve=resolve, batches=[{k: v for k, v in b.items() if not k.startswith("_")} for b in batches],
                            evidence=evidence)
    if str(manifest_hash) != computed:
        raise ValueError(f"payload identity mismatch: supplied hash {str(manifest_hash)[:12]}… is not the payload's "
                         f"canonical hash {computed[:12]}… (text, revision or evidence changed) — nothing applied")
    receipt_id = f"{WRAPPER_SCOPE}:{computed}"
    # ---- 1. replay: an applied receipt for this exact payload IS the answer
    async with eng.sf() as session:
        prior = await session.get(TipKnowledgeBatch, receipt_id)
        prior_applied = dict(prior.applied or {}) if prior is not None else None
        prior_status = prior.status if prior is not None else None
    if prior is not None and prior_status == "applied":
        return {**prior_applied, "replay": True, "manifestHash": computed}
    progress: dict = prior_applied or {"manifestHash": computed, "resolved": [], "batches": {}, "evidence": []}
    done_resolve = {t["id"] for t in progress.get("resolved") or []}
    done_batches = set((progress.get("batches") or {}).keys())
    done_evidence = {e["sourceId"] for e in progress.get("evidence") or [] if e.get("id") or e.get("existing")}
    # ---- 2. validate EVERYTHING still to do, before any mutation
    problems: list[str] = []
    release_ids = {(r if isinstance(r, str) else str(r.get("id"))) for r in resolve}
    async with eng.sf() as session:
        for r in resolve:
            rid = r if isinstance(r, str) else str(r.get("id"))
            exp = None if isinstance(r, str) else r.get("revision")
            if rid in done_resolve:
                continue
            row = await session.get(TipNote, rid)
            if row is None:
                problems.append(f"resolve {rid[:8]}: note does not exist"); continue
            if not row.needs_human:
                problems.append(f"resolve {rid[:8]}: not disputed (nothing to release)")
            if exp is not None and int(row.revision_no or 1) != int(exp):
                problems.append(f"resolve {rid[:8]}: revision {row.revision_no} differs from the reviewed {exp}")
        for b in batches:
            key = b.get("_key") or str(b.get("batchId"))
            bid = str(b.get("batchId") or "")
            if not bid:
                problems.append("a batch without batchId"); continue
            existing = await session.get(TipKnowledgeBatch, bid)
            if existing is not None and existing.status == "applied":
                if key in done_batches or await _applied_batch_matches(session, existing, b):
                    continue                     # identical batch already applied (idempotent)
                problems.append(f"batch {bid}: already applied with a DIFFERENT payload (sources or output text changed)")
                continue
            exp_rev = {str(k): int(v) for k, v in (b.get("expected_revisions") or {}).items()}
            for nid in _batch_ids(b):
                row = await session.get(TipNote, nid)
                if row is None:
                    problems.append(f"batch {bid}: source {nid[:8]} does not exist"); continue
                if row.superseded_by is not None:
                    problems.append(f"batch {bid}: source {nid[:8]} is already superseded by {row.superseded_by[:8]}"); continue
                if nid not in exp_rev:
                    problems.append(f"batch {bid}: no reviewed revision for source {nid[:8]}"); continue
                have = int(row.revision_no or 1)
                allowed = {exp_rev[nid]} | ({exp_rev[nid] + 1} if (nid in release_ids and nid in done_resolve) else set())
                if have not in allowed:
                    problems.append(f"batch {bid}: source {nid[:8]} is revision {have}, judged at {exp_rev[nid]}")
                if row.needs_human and nid not in release_ids:
                    problems.append(f"batch {bid}: source {nid[:8]} is disputed and this payload does not release it")
        for e in evidence:
            sid = str(e.get("sourceId") or "")
            if sid in done_evidence:
                continue
            row = await session.get(TipNote, sid)
            if row is None:
                problems.append(f"evidence for {sid[:8]}: source does not exist"); continue
            want = int(e.get("sourceRevision") or 0)
            have = int(row.revision_no or 1)
            moved_by_us = (1 if sid in release_ids and sid in done_resolve else 0) + \
                          (1 if any(sid in _batch_ids(b) and (b.get("_key") or str(b.get("batchId"))) in done_batches for b in batches) else 0)
            if have != want + moved_by_us:
                problems.append(f"evidence for {sid[:8]}: source is revision {have}, judged at {want}")
    if problems:
        raise ValueError("payload refused before any mutation: " + "; ".join(problems))
    # ---- 3. durable wrapper receipt (proposed -> applied), progress persisted per step
    canon = canonical_payload(resolve=resolve, batches=[{k: v for k, v in b.items() if not k.startswith("_")} for b in batches],
                              evidence=evidence)

    async def _save(status: str):
        async with eng.sf() as session:
            row = await session.get(TipKnowledgeBatch, receipt_id)
            if row is None:
                row = TipKnowledgeBatch(id=receipt_id, run_id=f"{WRAPPER_SCOPE}:{computed[:12]}", scope=WRAPPER_SCOPE,
                                        status=status, payload_hash=computed[:40], proposal={"canonical": canon},
                                        applied=dict(progress))
                session.add(row)
            else:
                row.status = status
                row.applied = dict(progress)
            await session.commit()
    await _save("proposed")
    # ---- A: releases (each a revision transition, journaled with from/to)
    shift: dict[str, tuple[int, int]] = {t["id"]: (t["revisionFrom"], t["revisionTo"]) for t in progress.get("resolved") or []}
    for r in resolve:
        rid = r if isinstance(r, str) else str(r.get("id"))
        if rid in done_resolve:
            continue
        async with eng.sf() as session:
            before = int(await session.scalar(select(TipNote.revision_no).where(TipNote.id == rid)) or 1)
        n = await svc.flag_tip_notes([rid], needs_human=False)
        if n:
            async with eng.sf() as session:
                after = int(await session.scalar(select(TipNote.revision_no).where(TipNote.id == rid)) or 1)
            shift[rid] = (before, after)
            progress["resolved"].append({"id": rid, "revisionFrom": before, "revisionTo": after})
            await eng.journal.append(ev.TIP_RULE_AUDITED,
                                     {"resolved": rid, "by": actor, "via": "consolidation", "manifestHash": computed,
                                      "revisionFrom": before, "revisionTo": after},
                                     aggregate_type="signal", aggregate_id=rid)
            await _save("proposed")
    # ---- B: batches through apply_knowledge_batch (row-locked, revision-checked, receipt in the same txn)
    for b in batches:
        key = b.get("_key") or str(b.get("batchId"))
        bid = str(b.get("batchId"))
        if key in done_batches:
            continue
        async with eng.sf() as session:
            existing = await session.get(TipKnowledgeBatch, bid)
        if existing is not None and existing.status == "applied":
            progress["batches"][key] = {"batchId": bid, "alreadyApplied": True}
            await _save("proposed")
            continue
        exp_rev = {str(k): int(v) for k, v in (b.get("expected_revisions") or {}).items()}
        for nid, (b0, b1) in shift.items():
            if nid in exp_rev and exp_rev[nid] == b0:
                exp_rev[nid] = b1                   # the release THIS payload performed, carried forward explicitly
        ids = _batch_ids(b)
        async with eng.sf() as session:
            revs_at = {nid: int(await session.scalar(select(TipNote.revision_no).where(TipNote.id == nid)) or 1) for nid in ids}
        if b.get("merge"):
            applied = await svc.apply_knowledge_batch(
                scope=b.get("scope") or "rule",
                merges=[{"supersedes": list(ids), "new_rule": b["merge"]["new_rule"]}],
                expires=[], contradictions=[], author=b.get("author") or "consolidation",
                run_id=f"{WRAPPER_SCOPE}:{computed[:12]}", live_ids=set(ids), batch_id=bid,
                expected_revisions=exp_rev, mode="apply")
            new_ids = list(applied.get("newRules") or [])
            progress["batches"][key] = {"batchId": bid, "kind": "merge", "merged": applied.get("merged"),
                                        "newRuleId": (new_ids[0] if new_ids else None), "newRules": new_ids,
                                        "rejected": applied.get("rejected"),
                                        "superseded": [{"id": nid, "revision": revs_at[nid]} for nid in ids]}
        else:
            reason = str(b["expire"].get("reason") or "reviewed rejection")
            applied = await svc.apply_knowledge_batch(
                scope=b.get("scope") or "rule", merges=[],
                expires=[{"id": nid, "reason": reason} for nid in ids], contradictions=[],
                author=b.get("author") or "consolidation", run_id=f"{WRAPPER_SCOPE}:{computed[:12]}",
                live_ids=set(ids), batch_id=bid, expected_revisions=exp_rev, mode="apply")
            progress["batches"][key] = {"batchId": bid, "kind": "expire", "reason": reason,
                                        "expired": [{"id": nid, "revision": revs_at[nid]} for nid in ids],
                                        "rejected": applied.get("rejected")}
        # the batch receipt row records the wrapper identity so a later DIFFERENT payload is refused
        async with eng.sf() as session:
            brow = await session.get(TipKnowledgeBatch, bid)
            if brow is not None:
                brow.applied = {**dict(brow.applied or {}), "consolidationIdentity": _batch_identity(b)[:40],
                                "consolidationReceipt": receipt_id}
                await session.commit()
        await _save("proposed")
    # ---- D: evidence records (never injected; identity = source id + revision + content)
    for e in evidence:
        sid = str(e.get("sourceId") or "")
        if sid in done_evidence:
            continue
        marker = evidence_marker(sid, int(e.get("sourceRevision") or 0), _sha(str(e.get("text") or "")))
        async with eng.sf() as session:
            exists = (await session.execute(select(TipNote.id).where(
                TipNote.scope == e["scope"], TipNote.text.contains(marker)))).scalars().first()
        if exists:
            progress["evidence"].append({"sourceId": sid, "existing": exists, "marker": marker})
        else:
            text = str(e.get("text") or "")
            if marker not in text:
                text = f"[{marker}] " + text
            note = await svc.add_tip_note(e["scope"], text, author=str(e.get("author") or "consolidation"),
                                          family_dedupe=False)
            progress["evidence"].append({"sourceId": sid, "id": note["id"], "marker": marker})
        await _save("proposed")
    progress["rollbackPlan"] = rollback_plan(progress)
    progress["appliedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    await _save("applied")
    await eng.journal.append(ev.TIP_RULE_AUDITED, {"consolidation": progress, "manifestHash": computed},
                             aggregate_type="technique", aggregate_id="tip")
    return dict(progress)
