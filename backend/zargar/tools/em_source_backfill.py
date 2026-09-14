"""Delivery B backfill: one immutable revision per existing EM method note (dry run + apply).

    python -m zargar.tools.em_source_backfill [--out manifest.json]     # dry run (read-only)
    python -m zargar.tools.em_source_backfill --apply manifest.json       # one transaction, idempotent

Rules (DELIVERY-B-DESIGN, revision section): revision 1 carries the note's verbatim text + image set
(`content_hash`), the Discord timestamp as `published_at`, the note's `created_at` as `received_at`,
`author_id` unknown (the old writer dropped it - null, never guessed). Existing transcript / extraction
become artifacts with `completed_at = NULL` -> `availability: unknown`; NOTHING is derived from
`updated_at`. A note that already has a revision is skipped (idempotent).

What the apply is AUTHORIZED to copy (B-05, first-PR review): exactly the reviewed evidence. The manifest's
own digest (`planHash` over every item field) is verified first; then, per note, UNDER THE ROW LOCK and
inside the one transaction, the complete item is rebuilt from the locked row and compared with the reviewed
item - source identity, text/images hash, media reference, transcript hash, extraction hash, artifact keys,
stage and outcome. Any difference refuses the WHOLE apply before anything is inserted: a changed transcript
under an unchanged caption is not the reviewed artifact, and a source edited between the dry run and the
lock is not the reviewed source. The CLI exits 2 on a refusal.
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
EVIDENCE_FIELDS = ("noteId", "messageId", "technique", "channelId", "channelName", "authorName", "contentHash",
                   "mediaUrl", "transcriptHash", "extractionHash", "publishedAt", "receivedAt", "stage", "outcome",
                   "artifacts")


class ManifestRefused(ValueError):
    """The manifest is not the reviewed snapshot of the live notes: nothing was written."""


def _h(s: str | None) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:32]


def _canon(v) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)


def _plan_hash(items: list[dict]) -> str:
    """The digest of EVERY evidence field of every item (not just the caption)."""
    return hashlib.sha256(_canon([{k: i.get(k) for k in EVIDENCE_FIELDS} for i in items]).encode()).hexdigest()[:16]


def item_for(n: TechniqueMethodNote) -> dict:
    """The reviewed evidence of one note, rebuilt from the row (the dry run and the locked recheck use
    this same function, so 'what was reviewed' and 'what is copied' cannot drift)."""
    arts = []
    if n.transcript:
        arts.append({"kind": "transcript", "inputHash": _h(n.media_url), "configHash": "legacy",
                     "outputHash": _h(n.transcript), "availability": "unknown"})
    if n.extraction:
        arts.append({"kind": "extraction", "inputHash": _h(n.transcript or n.text or ""), "configHash": "legacy",
                     "outputHash": _h(_canon(n.extraction)), "availability": "unknown"})
    status = str(n.status or "new")
    return {"noteId": n.id, "messageId": n.message_id, "technique": n.technique, "revision": 1, "kind": "create",
            "contentHash": content_hash(n.text, n.images or []),
            "mediaUrl": n.media_url, "transcriptHash": _h(n.transcript) if n.transcript else None,
            "extractionHash": _h(_canon(n.extraction)) if n.extraction else None,
            "publishedAt": n.posted_at.isoformat() if n.posted_at else None,
            "receivedAt": n.created_at.isoformat() if n.created_at else None,
            "authorId": None, "authorName": n.author or "", "channelId": n.channel_id, "channelName": n.channel_name,
            "stage": STAGE_FOR_STATUS.get(status, "received"),
            "outcome": "done" if status in ("checked", "extracted", "duplicate") else ("permanent" if status == "failed" else "retryable"),
            "artifacts": arts}


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
        items.append(item_for(n))
    return {"generatedAt": int(time.time() * 1000), "delivery": "B-backfill", "items": items,
            "alreadyRevisioned": skipped, "planHash": _plan_hash(items)}


def _evidence_diff(reviewed: dict, live: dict) -> list[str]:
    return [k for k in EVIDENCE_FIELDS if reviewed.get(k) != live.get(k)]


async def apply(sf, manifest: dict, *, raise_on_refusal: bool = False) -> int:
    """ONE transaction: revision 1 + artifacts + job per note. Refuses (raises `ManifestRefused`, nothing
    written) when the manifest digest is wrong, when a note's live evidence differs from the reviewed item
    (rechecked UNDER the row lock, inside the transaction), or when the preflight already disagrees. A note
    that gained a revision since the dry run is skipped (idempotent)."""
    try:
        return await _apply(sf, manifest)
    except ManifestRefused as exc:
        print(f"REFUSED: {exc}")
        if raise_on_refusal:
            raise
        return 0


async def _apply(sf, manifest: dict) -> int:
    items = list(manifest.get("items") or [])
    if manifest.get("planHash") != _plan_hash(items):
        raise ManifestRefused("manifest digest does not match its items - not the reviewed manifest; nothing written")
    # preflight (read-only): an early, cheap refusal; the authoritative check is the locked one below
    preflight = {i["noteId"]: i for i in (await build_manifest(sf))["items"]}
    for i in items:
        live = preflight.get(i["noteId"])
        if live is not None and _evidence_diff(i, live):
            raise ManifestRefused(f"note {i['noteId'][:8]}: {_evidence_diff(i, live)} changed since the dry run - re-run the dry run")
    n = 0
    now = utcnow()
    async with sf() as session:
        try:
            for i in items:
                note = await session.get(TechniqueMethodNote, i["noteId"], with_for_update=True)
                if note is None:
                    continue
                exists = (await session.execute(select(TechniqueSourceRevision.id).where(
                    TechniqueSourceRevision.note_id == note.id).limit(1))).scalars().first()
                if exists:
                    continue                                    # already revisioned: idempotent skip
                live = item_for(note)                           # the LOCKED state, rebuilt the same way
                diff = _evidence_diff(i, live)
                if diff:
                    raise ManifestRefused(f"note {note.id[:8]}: {diff} differ under the row lock - the reviewed "
                                          f"manifest is stale; nothing written")
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
                    payload = {"availability": "unknown", "legacy": True, "outputHash": a.get("outputHash")}
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
            await session.commit()                              # all notes, or none
        except Exception:
            await session.rollback()
            raise
    print(f"backfilled {n} note(s) (skipped {len(items) - n} already revisioned)")
    return n


async def run(args) -> int:
    eng = Engine(AppConfig())
    try:
        if args.apply:
            manifest = json.load(open(args.apply, encoding="utf-8"))
            try:
                await apply(eng.sf, manifest, raise_on_refusal=True)
            except ManifestRefused:
                return 2
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
    p.add_argument("--apply", help="manifest JSON from a dry run to apply (one transaction; exit 2 on refusal)")
    p.add_argument("--out", help="where to write the dry-run manifest")
    return asyncio.run(run(p.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
