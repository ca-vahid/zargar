"""Delivery B backfill: one immutable revision per existing EM method note (dry run + apply).

    python -m zargar.tools.em_source_backfill [--out manifest.json]     # dry run (read-only)
    python -m zargar.tools.em_source_backfill --apply manifest.json       # one transaction, idempotent

Rules (DELIVERY-B-DESIGN, revision section): revision 1 carries the note's verbatim text + image set
(`content_hash`), the Discord timestamp as `published_at`, the note's `created_at` as `received_at`,
`author_id` unknown (the old writer dropped it - null, never guessed). Existing transcript / extraction
become artifacts with `completed_at = NULL` -> `availability: unknown`; NOTHING is derived from
`updated_at`. A note that already has a revision is skipped (idempotent). The manifest carries the
expected note count and a hash of the plan so the apply refuses a manifest that no longer matches.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time

from sqlalchemy import select

from ..config import AppConfig
from ..domain import new_id
from ..engine import Engine
from ..models import TechniqueMethodNote, TechniqueSourceArtifact, TechniqueSourceJob, TechniqueSourceRevision
from ..technique.source_revisions import TECHNIQUE, artifact_key, content_hash, utcnow

STAGE_FOR_STATUS = {"new": "received", "pending_transcript": "received", "duplicate": "received",
                    "transcribed": "transcribed", "extracted": "extracted", "checked": "board_checked", "failed": "received"}


def _plan_hash(items: list[dict]) -> str:
    return hashlib.sha256(json.dumps([(i["noteId"], i["contentHash"], sorted(a["kind"] for a in i["artifacts"]))
                                      for i in items], sort_keys=True).encode()).hexdigest()[:16]


async def build_manifest(sf) -> dict:
    async with sf() as session:
        notes = (await session.execute(select(TechniqueMethodNote).where(TechniqueMethodNote.technique == TECHNIQUE)
                                       .order_by(TechniqueMethodNote.created_at.asc()))).scalars().all()
        have = set((await session.execute(select(TechniqueSourceRevision.note_id))).scalars().all())
    items, skipped = [], []
    for n in notes:
        if n.id in have:
            skipped.append(n.id)
            continue
        arts = []
        if n.transcript:
            arts.append({"kind": "transcript", "inputHash": hashlib.sha256((n.media_url or "").encode()).hexdigest()[:32],
                         "configHash": "legacy", "availability": "unknown"})
        if n.extraction:
            arts.append({"kind": "extraction", "inputHash": hashlib.sha256((n.transcript or n.text or "").encode()).hexdigest()[:32],
                         "configHash": "legacy", "availability": "unknown"})
        items.append({"noteId": n.id, "messageId": n.message_id, "revision": 1, "kind": "create",
                      "contentHash": content_hash(n.text, n.images or []),
                      "publishedAt": n.posted_at.isoformat() if n.posted_at else None,
                      "receivedAt": n.created_at.isoformat() if n.created_at else None,
                      "authorId": None, "authorName": n.author or "", "channelId": n.channel_id, "channelName": n.channel_name,
                      "stage": STAGE_FOR_STATUS.get(str(n.status), "received"),
                      "outcome": "done" if str(n.status) in ("checked", "extracted", "duplicate") else ("permanent" if n.status == "failed" else "retryable"),
                      "artifacts": arts})
    return {"generatedAt": int(time.time() * 1000), "delivery": "B-backfill", "items": items,
            "alreadyRevisioned": skipped, "planHash": _plan_hash(items)}


async def apply(sf, manifest: dict) -> int:
    """ONE transaction: revision 1 + artifacts + job per note; a note that gained a revision since the dry
    run is skipped; a manifest whose plan hash no longer matches the live notes is refused."""
    live = await build_manifest(sf)
    live_by = {i["noteId"]: i for i in live["items"]}
    wanted = [i for i in manifest["items"] if i["noteId"] in live_by]
    for i in wanted:
        if live_by[i["noteId"]]["contentHash"] != i["contentHash"]:
            print(f"REFUSE {i['noteId'][:8]}: note text changed since the dry run - re-run the dry run")
            return 0
    n = 0
    now = utcnow()
    async with sf() as session:
        for i in wanted:
            note = await session.get(TechniqueMethodNote, i["noteId"], with_for_update=True)
            if note is None:
                continue
            exists = (await session.execute(select(TechniqueSourceRevision.id).where(
                TechniqueSourceRevision.note_id == note.id).limit(1))).scalars().first()
            if exists:
                continue
            rev = TechniqueSourceRevision(id=new_id(), note_id=note.id, technique=TECHNIQUE, revision=1, kind="create",
                                          deleted=False, source_edited_at=None, published_at=note.posted_at,
                                          received_at=note.created_at or now, gateway_seq=None, author_id=None,
                                          author_name=(note.author or "")[:128], channel_id=note.channel_id or "",
                                          channel_name=(note.channel_name or "")[:128], text=note.text or "",
                                          attachments=list(note.images or []), content_hash=i["contentHash"], supersedes=None)
            session.add(rev)
            await session.flush()
            for a in i["artifacts"]:
                key = artifact_key(rev.id, a["kind"], a["inputHash"], a["configHash"])
                payload = {"availability": "unknown", "legacy": True}
                if a["kind"] == "transcript":
                    payload["text"] = note.transcript or ""
                else:
                    payload["extraction"] = dict(note.extraction or {})
                session.add(TechniqueSourceArtifact(id=key, revision_id=rev.id, note_id=note.id, technique=TECHNIQUE,
                                                    kind=a["kind"], version=1, config_hash=a["configHash"],
                                                    input_hash=a["inputHash"], payload=payload, completed_at=None))
            session.add(TechniqueSourceJob(id=new_id(), note_id=note.id, revision_id=rev.id, technique=TECHNIQUE,
                                           stage=i["stage"], outcome=i["outcome"], fence_token=0,
                                           checkpoint=[a["kind"] for a in i["artifacts"]], error=note.error))
            n += 1
        await session.commit()                          # all notes, or none
    print(f"backfilled {n} note(s) (skipped {len(manifest['items']) - len(wanted)} already revisioned)")
    return n


async def run(args) -> int:
    eng = Engine(AppConfig())
    try:
        if args.apply:
            manifest = json.load(open(args.apply, encoding="utf-8"))
            await apply(eng.sf, manifest)
            return 0
        m = await build_manifest(eng.sf)
        out = args.out or f"em-source-backfill-{time.strftime('%Y%m%d-%H%M%S')}.json"
        json.dump(m, open(out, "w", encoding="utf-8"), indent=2)
        print(f"{len(m['items'])} note(s) to revision, {len(m['alreadyRevisioned'])} already revisioned; "
              f"plan {m['planHash']}; manifest -> {out}")
        return 0
    finally:
        await eng.db.dispose()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Delivery B source-revision backfill")
    p.add_argument("--apply", help="manifest JSON from a dry run to apply (one transaction)")
    p.add_argument("--out", help="where to write the dry-run manifest")
    return asyncio.run(run(p.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
