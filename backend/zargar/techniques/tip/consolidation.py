"""Apply the REVIEWED consolidation batches through the audited knowledge paths
(consolidation packet 2026-09-13; reviewer GO 2026-09-14). Nothing here is
scheduled or automatic: the caller passes the exact manifest (`tools/
tip_consolidation.py`), and every step is a revision transition with a
receipt — routine maintenance stays propose-only.

Order (each step idempotent on its receipt / state):
  A. resolve the listed disputes (journaled `resolved`; the human decision is
     the manifest's stated reason) — an audit batch can never touch a
     `needs_human` row, so this is a deliberate, separate act
  B. the geometry family merge via `apply_knowledge_batch(mode="apply")`
     (revision-checked against the manifest; receipt row = batch id)
  C. the kill-switch merge, same path
  D. the evidence records (`evidence:<family>`, never injected), skipped when
     a record for that source id already exists
"""
from __future__ import annotations

import logging

log = logging.getLogger("zargar.tip.consolidation")


async def apply_consolidation(eng, *, manifest_hash: str, resolve: list[str], family: dict,
                              kill_switch: dict, evidence: list[dict]) -> dict:
    from sqlalchemy import select
    from ... import events as ev
    from ...models import TipKnowledgeBatch, TipNote
    svc = eng.signals_service
    out: dict = {"manifestHash": manifest_hash, "resolved": [], "batches": {}, "evidence": []}
    # ---- A: disputes (deliberate human decision, journaled). Releasing a
    # dispute is itself a revision transition; the merge below is checked
    # against the revision the reviewer READ, so the transition this call
    # caused (and only that one) is carried forward explicitly.
    shift: dict[str, tuple[int, int]] = {}
    for nid in resolve or []:
        async with eng.sf() as session:
            before = await session.scalar(select(TipNote.revision_no).where(TipNote.id == nid))
        n = await svc.flag_tip_notes([nid], needs_human=False)
        if n:
            async with eng.sf() as session:
                after = await session.scalar(select(TipNote.revision_no).where(TipNote.id == nid))
            shift[nid] = (int(before or 1), int(after or 1))
            out["resolved"].append(nid)
            await eng.journal.append(ev.TIP_RULE_AUDITED,
                                     {"resolved": nid, "by": "user", "via": "consolidation",
                                      "manifestHash": manifest_hash,
                                      "revisionFrom": shift[nid][0], "revisionTo": shift[nid][1]},
                                     aggregate_type="signal", aggregate_id=nid)
    out["revisionTransitions"] = {k: list(v) for k, v in shift.items()}
    # ---- B + C: audited merges (revision-checked, receipts)
    for key, batch in (("family", family), ("killSwitch", kill_switch)):
        if not batch or not (batch.get("merge") or {}).get("supersedes"):
            out["batches"][key] = {"skipped": "nothing to merge"}
            continue
        live_ids = set(batch["merge"]["supersedes"])
        async with eng.sf() as session:
            rows = (await session.execute(select(TipNote.id, TipNote.superseded_by, TipNote.needs_human)
                                          .where(TipNote.id.in_(sorted(live_ids))))).all()
        gone = [i for i, sup, _ in rows if sup is not None]
        disputed = [i for i, _, nh in rows if nh]
        if gone or disputed:
            prior = None
            async with eng.sf() as session:
                prior = await session.get(TipKnowledgeBatch, batch["batchId"])
            if prior is not None and prior.status == "applied":
                out["batches"][key] = {"alreadyApplied": True, "batchId": batch["batchId"]}
                continue
            out["batches"][key] = {"refused": f"superseded {gone} / still disputed {disputed}"}
            continue
        applied = await svc.apply_knowledge_batch(
            scope=batch.get("scope") or "rule",
            merges=[{"supersedes": list(batch["merge"]["supersedes"]), "new_rule": batch["merge"]["new_rule"]}],
            expires=[], contradictions=[], author=batch.get("author") or "consolidation",
            run_id=f"consolidation:{manifest_hash[:12]}", live_ids=live_ids, batch_id=batch["batchId"],
            expected_revisions={k: (shift[k][1] if k in shift and int(v) == shift[k][0] else int(v))
                                for k, v in (batch.get("expected_revisions") or {}).items()},
            mode="apply")
        out["batches"][key] = {"batchId": batch["batchId"], "merged": applied.get("merged"),
                               "newRules": applied.get("newRules"), "rejected": applied.get("rejected"),
                               "alreadyApplied": applied.get("alreadyApplied", False)}
    # ---- D: evidence records (never injected)
    for e in evidence or []:
        marker = f"cites rule {e['sourceId']}"
        async with eng.sf() as session:
            exists = (await session.execute(select(TipNote.id).where(
                TipNote.scope == e["scope"], TipNote.text.contains(marker)))).scalars().first()
        if exists:
            out["evidence"].append({"sourceId": e["sourceId"], "existing": exists})
            continue
        note = await svc.add_tip_note(e["scope"], e["text"], author="consolidation:2026-09-14",
                                      family_dedupe=False)
        out["evidence"].append({"sourceId": e["sourceId"], "id": note["id"]})
    await eng.journal.append(ev.TIP_RULE_AUDITED, {"consolidation": out, "manifestHash": manifest_hash},
                             aggregate_type="technique", aggregate_id="tip")
    return out
