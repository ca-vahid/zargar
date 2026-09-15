"""EM method ingestion - the author's channels -> notes -> board check.

docs/techniques/enhanced-market/INGESTION-PLAN.md. EM-ONLY: this module reads
only `techniques.enhanced_market.*` settings and writes only
`technique_method_notes`; it never touches Tip's intake, mirror or notes.

Flow: the shared read-only Discord gateway forwards messages from the EM
channel set to `store_message`; a video link becomes a `pending_transcript`
note the `zargar.tools.em_ingest` worker picks up (yt-dlp -> ffmpeg ->
faster-whisper) and completes via `store_transcript`; `extract` runs ONE
flat-schema LLM read (summary, board, claims, vetoes); `board_check` runs
deterministic plan runs (no LLM) on the named symbols and records, per symbol,
whether an armed EM plan already covers it, a fresh plan is valid (grade, run id
-> the UI's Arm button), or our gates rejected it (and why). Arming stays a
human click unless `ingest.auto_arm` is on. Nothing here changes a live
parameter - method claims are candidate theories for TRADING-RULES section 3.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import re
from dataclasses import replace as dc_replace

from pydantic import BaseModel
import hashlib

from sqlalchemy import select

from .. import bus as topics
from .. import events as ev
from . import source_revisions as srcrev
from ..domain import new_id
from ..models import TechniqueMethodNote, TechniqueSourceArtifact
from .llm import stream_message

log = logging.getLogger("zargar.technique.ingest")

TECHNIQUE = "enhanced_market"
PREFIX = "techniques.enhanced_market."

# links the worker can turn into audio: X broadcasts / tweets with video, YouTube, raw media
MEDIA_RE = re.compile(
    r"https?://(?:www\.)?(?:x\.com|twitter\.com)/i/broadcasts/\w+"
    r"|https?://(?:www\.)?(?:x\.com|twitter\.com)/\w+/status/\d+"
    r"|https?://(?:www\.)?(?:youtube\.com/watch\?\S+|youtu\.be/\S+)"
    r"|https?://\S+\.(?:mp4|m3u8|m4a|mp3)(?:\?\S*)?",
    re.IGNORECASE)
NOT_TICKERS = {"A", "I", "AM", "PM", "ET", "THE", "AND", "OR", "TO", "AT", "ON", "IN", "IF", "IT", "IS",
               "OF", "SO", "UP", "US", "WE", "BE", "BY", "DO", "GO", "NO", "OK", "VS", "PT", "TP", "SL",
               "OTM", "ITM", "ATM", "EOD", "HOD", "LOD", "PDH", "PDL", "VWAP", "EMA", "SMA", "RSI",
               "SPX", "NDX", "VIX", "CPI", "PMI", "FOMC", "GDP", "ISM", "USD", "CAD", "ATH", "ATL",
               "LOL", "IMO", "FYI", "AKA", "ETA", "CALL", "PUT", "CALLS", "PUTS", "LONG", "SHORT",
               "BUY", "SELL", "ODTE", "DTE", "R", "RR", "EM", "EMS", "VIP", "DM", "DMS", "CC"}


class MethodExtraction(BaseModel):
    """FLAT schema (nested models blow the grammar budget - see CLAUDE.md)."""
    material: str               # setups_brief | alert | recap | other  (what this item IS)
    summary: str
    stance: str                 # aggressive | neutral | cautious | sit_on_hands
    symbols: list[str]          # tickers named as actionable today (upper-case)
    board: list[str]            # one line per setup: "SYMBOL | long/short | trigger ... | target ... | note"
    claims: list[str]           # method statements: how he picks levels/entries/exits/vetoes
    vetoes: list[str]           # things he refuses today and why (earnings, bad contracts, no structure)


EXTRACT_SYSTEM = (
    "You read a day-trading educator's pre-market material (a transcript of his morning setups "
    "video, or a watch-list post) for a research pipeline that studies HIS current method. "
    "Extract, faithfully and without inventing:\n"
    "- material: setups_brief (the pre-market rundown of today's setups), alert (a live trade "
    "alert / entry / exit), recap (a review of past trades), or other (anything else - promo, "
    "chatter, schedule notes).\n"
    "- summary: 2-3 sentences, what he thinks today is.\n"
    "- stance: aggressive | neutral | cautious | sit_on_hands (his own words decide).\n"
    "- symbols: every ticker he calls ACTIONABLE today (watch/trade), upper-case, no $ sign; "
    "skip tickers he explicitly dismisses ('nothing there').\n"
    "- board: one line per actionable setup: 'SYMBOL | long or short | trigger: <level/condition> "
    "| target: <level/gap fill/next zone> | note: <his caveat>'. Numbers exactly as spoken.\n"
    "- claims: statements about HOW he decides - level selection, what counts as confirmation, "
    "targets, exits, sizing, what he avoids - phrased as testable rules, one per item.\n"
    "- vetoes: what he refuses today and why (earnings, bad option contracts, gaps, chop).\n"
    "Transcripts are speech-to-text: fix obvious mis-hearings of tickers from context "
    "('SpaceX' is SPCX, 'Chipotle' CMG, 'the video'/'Nvidia' NVDA, 'Q-Com' QCOM, "
    "'Affirm' AFRM, 'Crowd' CRWD, 'Fig' FIG); when a name is ambiguous, prefer the ticker "
    "of the company he describes.\n"
    "Dismissed names and small talk are not board items. Be terse."
)


def _h(s: str | None) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:32]


def _media_in(text: str | None) -> str | None:
    """The media link of a source state (the transcription input identity), else None."""
    m = MEDIA_RE.search(text or "")
    return m.group(0) if m else None


class StaleWorker(RuntimeError):
    """The caller's lease/fence is not current (or another worker holds the job): nothing was written."""


def _int_or_none(v):
    try:
        return int(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_ts(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def note_dict(n: TechniqueMethodNote, *, full: bool = True) -> dict:
    tr = n.transcript or ""
    return {
        "id": n.id, "technique": n.technique, "messageId": n.message_id,
        "channelId": n.channel_id, "channelName": n.channel_name, "author": n.author,
        "kind": n.kind, "status": n.status, "text": n.text if full else (n.text or "")[:400],
        "images": list(n.images or []), "mediaUrl": n.media_url,
        "transcript": tr if full else (tr[:400] + ("..." if len(tr) > 400 else "")),
        "transcriptChars": len(tr),
        "extraction": dict(n.extraction or {}), "boardCheck": dict(n.board_check or {}),
        "meta": dict(n.meta or {}), "error": n.error,
        "postedAt": n.posted_at.isoformat() if n.posted_at else None,
        "createdAt": n.created_at.isoformat() if n.created_at else None,
        "updatedAt": n.updated_at.isoformat() if n.updated_at else None,
    }


class MethodIngestService:
    def __init__(self, engine, technique) -> None:
        self.engine = engine
        self.technique = technique          # TechniqueService (analyze / armer / llm client)
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------ settings
    def _get(self, key: str, default=None):
        return self.engine.settings.get(PREFIX + key, default)

    def _num(self, key: str, default):
        """A numeric knob where 0 is a legitimate value (`or default` would swallow it)."""
        v = self._get(key, None)
        return default if v is None or v == "" else v

    def enabled(self) -> bool:
        return bool(self._get("ingest.enabled", True))

    def channels(self) -> list[dict]:
        out = []
        for c in (self._get("discord.channels", []) or []):
            if isinstance(c, dict) and c.get("channelId"):
                out.append({"channelId": str(c["channelId"]), "label": str(c.get("label") or "")})
            elif isinstance(c, str) and c.strip():
                out.append({"channelId": c.strip(), "label": ""})
        return out

    def _spawn(self, coro, name: str) -> None:
        t = asyncio.create_task(coro, name=name)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def stop(self) -> None:
        for t in list(self._tasks):
            t.cancel()

    def _publish(self, note: dict) -> None:
        with contextlib.suppress(Exception):
            self.engine.bus.publish(topics.TECHNIQUE, {"kind": "method_note", "note": {
                k: note.get(k) for k in ("id", "kind", "status", "channelName", "author", "postedAt", "error")}})

    # ------------------------------------------------------------ intake
    async def store_message(self, payload: dict) -> dict:
        """One forwarded Discord message -> a note (dedupe on the message id)."""
        mid = str(payload.get("id") or payload.get("messageId") or "").strip() or None
        text = str(payload.get("text") or "")
        images = [str(u) for u in (payload.get("images") or [])][:6]
        media = MEDIA_RE.search(text)
        media_url = media.group(0) if media else None
        kind = "video" if media_url else ("chart" if images else "post")
        async with self.engine.sf() as session:
            if mid:
                existing = (await session.execute(
                    select(TechniqueMethodNote).where(TechniqueMethodNote.message_id == mid))).scalar_one_or_none()
                if existing is not None:
                    return {**note_dict(existing, full=False), "duplicate": True}
            status = "pending_transcript" if (kind == "video" and self._get("ingest.auto_transcribe", True)) else "new"
            dup_of = None
            if media_url:
                # the same link re-posted (pinned, edited, echoed by a bot) within a day is
                # ONE video: keep the note for the channel's history, never transcribe twice
                since = _now() - dt.timedelta(hours=20)
                prior = (await session.execute(
                    select(TechniqueMethodNote)
                    .where(TechniqueMethodNote.media_url == media_url, TechniqueMethodNote.created_at >= since)
                    .order_by(TechniqueMethodNote.created_at.asc()))).scalars().first()
                if prior is not None:
                    dup_of, status = prior.id, "duplicate"
            n = TechniqueMethodNote(
                id=new_id(), technique=TECHNIQUE, message_id=mid,
                channel_id=str(payload.get("channelId") or ""),
                channel_name=str(payload.get("channelName") or payload.get("label") or "")[:128],
                author=str(payload.get("author") or "")[:128],
                kind=kind, status=status, text=text[:20000], images=images, media_url=media_url,
                posted_at=_parse_ts(payload.get("postedAt")),
                meta={"attempts": 0, **({"duplicateOf": dup_of} if dup_of else {})})
            session.add(n)
            await session.flush()
            # Delivery B: revision 1 is written WITH the note (one commit) - the immutable observation
            rev = await srcrev.record_delivery(session, note_id=n.id, payload=payload, kind="create",
                                               gateway_seq=_int_or_none(payload.get("gatewaySeq")))
            await session.commit()
            d = {**note_dict(n), "revision": rev.get("revision"), "revisionId": rev.get("revisionId")}
        log.info("ingest: %s note %s from #%s (%s)", kind, d["id"][:8], d["channelName"] or d["channelId"], status)
        self._publish(d)
        # a text-only post with substance goes straight to extraction
        if status != "duplicate" and kind != "video" and self._get("ingest.auto_extract", True) and len(text.strip()) >= 60:
            self._spawn(self._extract_and_check(d["id"]), f"em-ingest-extract-{d['id'][:8]}")
        return {**d, "duplicate": False}

    async def store_revision(self, payload: dict) -> dict:
        """An EDIT or DELETE of a forwarded message (Delivery B contract 1): a new immutable revision when
        the accepted source state changes; a stale (older) delivery is refused and journaled; an identical
        redelivery is a receipt. Absent text/images keep the accepted values. The note row keeps showing
        the LATEST accepted text; dependent artifacts are not rewritten (a later revision gets its own).

        WI-02: the note's MEDIA identity follows the accepted revision. Replacement media (a new broadcast link)
        makes the note pending for its own transcription and drops the superseded transcript from the
        projection; unchanged media keeps the transcript (an identical input is reusable)."""
        mid = str(payload.get("id") or payload.get("messageId") or "").strip()
        kind = str(payload.get("kind") or "update")
        kind = "delete" if kind in ("delete", "deleted") else "update"
        async with self.engine.sf() as session:
            note = (await session.execute(
                select(TechniqueMethodNote).where(TechniqueMethodNote.message_id == mid)
                .with_for_update())).scalar_one_or_none() if mid else None
            if note is None:
                return {"ok": False, "why": "unknown message", "messageId": mid}
            rev = await srcrev.record_delivery(session, note_id=note.id, payload=payload, kind=kind,
                                               gateway_seq=_int_or_none(payload.get("gatewaySeq")))
            if rev["outcome"] == "recorded":
                cur = await srcrev.current_revision(session, note.id)
                note.text = cur.text[:20000]
                note.images = list(cur.attachments or [])
                media = _media_in(cur.text)
                if (media or None) != (note.media_url or None):
                    # replacement media: the projection follows the CURRENT inputs
                    note.media_url = media
                    note.kind = "video" if media else ("chart" if note.images else "post")
                    if media and not cur.deleted:
                        reusable = await self._transcript_for_media(session, note.id, media)
                        if reusable is not None:
                            note.transcript = reusable
                            note.status = "transcribed" if note.status in ("new", "pending_transcript", "failed") else note.status
                        else:
                            note.transcript = None
                            note.status = "pending_transcript" if self._get("ingest.auto_transcribe", True) else "new"
                            note.error = None
                    elif not media:
                        note.transcript = None
                        if note.status == "pending_transcript":
                            note.status = "new"
                note.meta = {**(note.meta or {}), "revision": cur.revision, "deleted": bool(cur.deleted),
                             "revisionKind": cur.kind, "mediaHash": (_h(media) if media else None)}
                note.updated_at = _now()
            await session.commit()
            d = note_dict(note)
        if rev["outcome"] == "stale":
            log.warning("ingest: stale %s for note %s ignored: %s", kind, d["id"][:8], rev.get("why"))
        else:
            log.info("ingest: %s -> note %s revision %s (%s)", kind, d["id"][:8], rev.get("revision"), rev["outcome"])
        # a tombstone / edit is a SOURCE fact: it is journaled and the history kept; it never disarms, flattens or
        # re-owns anything - managed positions and their protective exits stay with their exit owner (next-PR contract)
        journal = getattr(self.engine, "journal", None)
        if journal is not None and rev["outcome"] in ("recorded", "stale", "unordered"):
            with contextlib.suppress(Exception):
                await journal.append(ev.TECHNIQUE_SOURCE_REVISED, {
                    "noteId": d["id"], "messageId": mid, "revision": rev.get("revision"), "kind": kind,
                    "outcome": rev["outcome"], "deleted": bool((note.meta or {}).get("deleted")) if rev["outcome"] == "recorded" else None,
                    "why": rev.get("why")}, aggregate_type="technique_note", aggregate_id=d["id"])
        self._publish(d)
        return {**d, **{k: rev.get(k) for k in ("outcome", "revision", "revisionId", "why")}, "ok": True}

    async def _transcript_for_media(self, session, note_id: str, media: str) -> str | None:
        """The persisted transcript of an IDENTICAL media input for this note (any revision), else None."""
        rows = (await session.execute(
            select(TechniqueSourceArtifact).where(TechniqueSourceArtifact.note_id == note_id,
                                                  TechniqueSourceArtifact.kind == "transcript",
                                                  TechniqueSourceArtifact.input_hash == _h(media))
            .order_by(TechniqueSourceArtifact.created_at.desc()).limit(1))).scalars().first()
        if rows is None:
            return None
        text = (rows.payload or {}).get("text")
        return str(text) if text else None

    async def _source_is_current(self, note_id: str, revision_id: str | None) -> bool:
        """Is `revision_id` still the note's current, non-tombstoned revision? (checked before every side effect)"""
        async with self.engine.sf() as session:
            cur = await srcrev.current_revision(session, note_id)
        if cur is None:
            return True
        return (revision_id is None or cur.id == revision_id) and not cur.deleted

    async def sweep_expired(self) -> int:
        """Delivery B: release expired worker leases (fenced) - run on every gateway delivery; claims nothing."""
        async with self.engine.sf() as session:
            n = await srcrev.sweep_expired(session)
            await session.commit()
        return n

    async def resume_unfinished(self, *, owner: str = "engine") -> list[dict]:
        """Delivery B: re-lease every job whose lease is free/expired at its recorded stage (fenced).
        Called on every gateway delivery and every worker poll; cheap when nothing is pending."""
        async with self.engine.sf() as session:
            jobs = await srcrev.resume_unfinished(session, owner=owner)
            await session.commit()
        return jobs

    async def pending(self, *, owner: str = "em-ingest") -> list[dict]:
        """Video notes waiting for the worker (oldest first), each with a fenced LEASE for `owner` (WI-01: a
        worker INSTANCE identity - two instances never share a fence; a note leased by another live owner is
        not handed out). A note deferred because its broadcast was still LIVE is hidden until `nextCheckAt`;
        past `ingest.live_max_wait_minutes` the worker is told to take whatever replay exists (`forcePartial`).
        WI-02: the media and the job come from the note's CURRENT revision; a note whose current media already
        has a transcript artifact (identical input) is not transcribed again."""
        max_wait = float(self._num("ingest.live_max_wait_minutes", 45))
        lease = int(self._num("ingest.worker_lease_seconds", srcrev.DEFAULT_LEASE_SECONDS))
        owner = str(owner or "em-ingest")[:64]
        now = _now()
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(TechniqueMethodNote)
                .where(TechniqueMethodNote.status == "pending_transcript")
                .order_by(TechniqueMethodNote.created_at.asc()).limit(10))).scalars().all()
            out = []
            for r in rows:
                m = r.meta or {}
                nxt = _parse_ts(m.get("nextCheckAt"))
                if nxt and nxt > now:
                    continue
                cur = await srcrev.current_revision(session, r.id)
                if cur is not None and cur.deleted:
                    continue
                media = (_media_in(cur.text) if cur is not None else None) or r.media_url
                if not media:
                    continue
                if await self._transcript_for_media(session, r.id, media) is not None:
                    continue                                   # identical media input already transcribed
                first_live = _parse_ts(m.get("firstSeenLiveAt"))
                force = bool(first_live and (now - first_live).total_seconds() / 60 >= max_wait)
                job = await srcrev.claim_for_note(session, r.id, owner=owner, now=now, lease_seconds=lease, retry=True)
                if job is None and await srcrev.job_for_note(session, r.id) is not None:
                    continue
                out.append({"id": r.id, "mediaUrl": media, "mediaHash": _h(media), "attempts": int(m.get("attempts") or 0),
                            "deferrals": int(m.get("deferrals") or 0), "forcePartial": force,
                            "postedAt": r.posted_at.isoformat() if r.posted_at else None,
                            "jobId": job["id"] if job else None, "fenceToken": job["fenceToken"] if job else None,
                            "revisionId": job["revisionId"] if job else None, "owner": owner})
            await session.commit()
            return out

    async def store_transcript(self, note_id: str, *, transcript: str | None = None,
                               error: str | None = None, meta: dict | None = None,
                               deferred: bool = False, job_id: str | None = None,
                               fence_token: int | None = None) -> dict:
        """The worker's result: a transcript (-> extraction), a DEFERRAL (the broadcast is still live - check
        again in `ingest.live_recheck_seconds`, no attempt spent), or a failure (retry up to
        transcribe_max_attempts, then `failed` - never silent).

        The transcript is an immutable ARTIFACT of the revision the job was leased for (output key = revision +
        media hash + model), written with the job checkpoint in ONE commit under the worker's fence.
        WI-01: the COMPLETE lease context is validated before any write - the job must belong to this note, the
        fence and lease must be current (checkpoint), and the media identity is the leased revision's own; a
        mismatch is `StaleWorker` (HTTP 409) with no artifact, checkpoint or projection change.
        WI-02: the note's projection (transcript/status) is updated only when the job's media is the CURRENT
        revision's media; a superseded media's transcript is archived under its revision and the replacement
        media stays pending for its own transcription."""
        max_attempts = int(self._num("ingest.transcribe_max_attempts", 5))
        recheck = int(self._num("ingest.live_recheck_seconds", 60))
        async with self.engine.sf() as session:
            n = await session.get(TechniqueMethodNote, note_id, with_for_update=True)
            if n is None:
                raise KeyError(note_id)
            cur = await srcrev.current_revision(session, note_id)
            if job_id is None:
                job = await srcrev.claim_for_note(session, note_id, owner="engine", retry=True)
                if job is None and await srcrev.job_for_note(session, note_id) is not None:
                    raise StaleWorker("another worker holds this note's job")
                job_id = job["id"] if job else None
                fence_token = job["fenceToken"] if job else None
            job_row = await srcrev.job_by_id(session, job_id) if job_id else None
            if job_id and (job_row is None or job_row.note_id != note_id):
                raise StaleWorker(f"job {str(job_id)[:8]} does not belong to note {note_id[:8]} - nothing written")
            leased_rev = await srcrev.revision_by_id(session, job_row.revision_id) if job_row is not None else cur
            job_media = (_media_in(leased_rev.text) if leased_rev is not None else None) or n.media_url
            cur_media = (_media_in(cur.text) if cur is not None else None) or n.media_url
            applies = (cur is not None and not cur.deleted and job_media and cur_media and _h(job_media) == _h(cur_media))
            try:
                m = dict(n.meta or {})
                m.update({k: v for k, v in (meta or {}).items() if v is not None})
                now = _now()
                if deferred and not (transcript and transcript.strip()):
                    m["deferrals"] = int(m.get("deferrals") or 0) + 1
                    m.setdefault("firstSeenLiveAt", now.isoformat())
                    nxt = now + dt.timedelta(seconds=recheck)
                    m["nextCheckAt"] = nxt.isoformat()
                    m["lastDeferReason"] = (error or "broadcast still live")[:200]
                    if job_id:
                        await srcrev.checkpoint(session, job_id=job_id, fence_token=int(fence_token), item_key="deferral",
                                                outcome="retryable", error=m["lastDeferReason"], next_due_at=nxt, now=now)
                    if applies:
                        n.status = "pending_transcript"
                        n.meta = m
                        n.updated_at = now
                    await session.commit()
                    d = note_dict(n)
                    self._publish(d)
                    return {**d, "applied": bool(applies)}
                if transcript and transcript.strip():
                    if job_id:
                        await srcrev.checkpoint(session, job_id=job_id, fence_token=int(fence_token), item_key="transcript",
                                                stage="transcribed", now=now, release=True,
                                                artifact={"kind": "transcript", "inputHash": _h(job_media or n.id),
                                                          "configHash": str(m.get("model") or "unknown"),
                                                          "payload": {"text": transcript.strip(), "mediaUrl": job_media,
                                                                      "durationSeconds": m.get("durationSeconds"),
                                                                      "partial": bool(m.get("partial"))}})
                    if applies:
                        n.transcript = transcript.strip()
                        n.status = "transcribed"
                        n.error = None
                else:
                    m["attempts"] = int(m.get("attempts") or 0) + 1
                    m["lastError"] = (error or "no transcript")[:500]
                    failed = m["attempts"] >= max_attempts
                    if job_id:
                        await srcrev.checkpoint(session, job_id=job_id, fence_token=int(fence_token), item_key=f"attempt-{m['attempts']}",
                                                outcome=("permanent" if failed else "retryable"),
                                                error=m["lastError"], next_due_at=now, now=now)
                    if applies:
                        n.status = "failed" if failed else "pending_transcript"
                        n.error = m["lastError"] if failed else None
                if applies:
                    n.meta = m
                    n.updated_at = now
                await session.commit()
            except srcrev.FenceMismatch as exc:
                await session.rollback()
                raise StaleWorker(str(exc)) from exc
            d = note_dict(n)
        if not applies:
            log.info("ingest: transcript for note %s archived under a superseded revision (media changed)", note_id[:8])
        self._publish(d)
        if d["status"] == "transcribed" and applies and self._get("ingest.auto_extract", True):
            self._spawn(self._extract_and_check(note_id), f"em-ingest-extract-{note_id[:8]}")
        return {**d, "applied": bool(applies)}

    # ------------------------------------------------------------ extraction
    async def _extract_and_check(self, note_id: str) -> None:
        """Extraction, then the deterministic board for setup material. WI-04: a lease conflict (`StaleWorker`)
        is not a failure of this note - nothing is mutated; an extraction failure is recorded by `extract`
        itself under ITS job context; a board failure is recorded under the revision the board was authorized
        for. WI-03: a superseded/deleted source never reaches planning."""
        try:
            d = await self.extract(note_id)
        except StaleWorker as exc:
            log.info("ingest: extraction for %s skipped - %s", note_id[:8], exc)
            return
        except Exception:                              # noqa: BLE001 - already recorded on the note by extract()
            log.exception("ingest: extraction failed for %s", note_id[:8])
            return
        if d.get("superseded"):
            return
        material = (d.get("extraction") or {}).get("material") or "other"
        # only setup material earns plan runs; a recap or promo is stored, not traded on
        if self._get("ingest.auto_plan_board", True) and material in ("setups_brief", "alert"):
            try:
                await self.board_check(note_id, revision_id=d.get("revisionId"))
            except StaleWorker as exc:
                log.info("ingest: board for %s skipped - %s", note_id[:8], exc)
            except Exception as exc:                   # noqa: BLE001 - surfaced on the note, never swallowed
                log.exception("ingest: board check failed for %s", note_id[:8])
                await self._fail(note_id, f"{type(exc).__name__}: {exc}"[:500], revision_id=d.get("revisionId"))

    async def _fail(self, note_id: str, error: str, *, job: dict | None = None, revision_id: str | None = None) -> None:
        """Record a failure under the ORIGINAL work context only (WI-04): the job the attempt held (its fence
        must still be current) or the revision it was authorized for. The note's projection turns `failed`
        only when that revision is still the current one; an old attempt's failure never overwrites a newer
        revision's success, and no context means no mutation at all."""
        async with self.engine.sf() as session:
            n = await session.get(TechniqueMethodNote, note_id, with_for_update=True)
            if n is None:
                return
            cur = await srcrev.current_revision(session, note_id)
            rev_id = revision_id or (job or {}).get("revisionId")
            if job is None and rev_id is not None and cur is not None and cur.id == rev_id and not cur.deleted:
                job = await srcrev.claim_for_note(session, note_id, owner="engine", retry=True)
            if job is None and rev_id is None:
                log.warning("ingest: failure for %s without a work context is not recorded on the note: %s", note_id[:8], error[:120])
                return
            if job is not None:
                try:
                    await srcrev.checkpoint(session, job_id=job["id"], fence_token=job["fenceToken"], item_key="failure",
                                            outcome="permanent", error=error)
                except srcrev.FenceMismatch as exc:
                    await session.rollback()
                    log.info("ingest: failure for %s not recorded - %s", note_id[:8], exc)
                    return
            if cur is not None and rev_id is not None and cur.id == rev_id and not cur.deleted:
                n.status = "failed"
                n.error = error
                n.updated_at = _now()
            await session.commit()
            self._publish(note_dict(n))

    async def _llm_extract(self, source: str, body: str) -> dict:
        """ONE structured read. Separated so tests can stub it."""
        cfg = self.technique.llm_config()
        if not cfg.available:
            raise RuntimeError("LLM not configured (no API key)")
        cfg = dc_replace(cfg, effort="low")
        client = self.technique._get_client()
        msg = await stream_message(
            client, cfg, on_event=None,
            system=[{"type": "text", "text": EXTRACT_SYSTEM}],
            messages=[{"role": "user", "content": [{"type": "text", "text": f"SOURCE: {source}\n\n{body[:60000]}"}]}],
            output_format=MethodExtraction, max_tokens=4000)
        po = getattr(msg, "parsed_output", None)
        if po is not None:
            return po.model_dump() if hasattr(po, "model_dump") else dict(po)
        text = "".join(getattr(b, "text", "") for b in (msg.content or []))
        try:
            return MethodExtraction.model_validate_json(text).model_dump()
        except Exception as exc:
            raise RuntimeError(f"extraction did not return the schema: {exc}") from exc

    @staticmethod
    def _clean_symbols(ex: dict) -> list[str]:
        syms: list[str] = []
        for s in ex.get("symbols") or []:
            s = str(s).upper().strip().lstrip("$")
            if 1 <= len(s) <= 5 and s.isalpha() and s not in NOT_TICKERS and s not in syms:
                syms.append(s)
        return syms

    async def extract(self, note_id: str, *, reprocess: bool = False) -> dict:
        """One structured read of the CURRENT revision's inputs (transcript when its media is current, plus the
        caption/context), claimed BEFORE the paid call and bound to that revision (WI-03). After the call the
        source is re-read under the lock: if it was edited or tombstoned meanwhile, the result is archived as
        an artifact of the leased revision and marked `superseded` - it never updates the current projection
        or another revision's job. WI-05: when the output key already exists, the PERSISTED artifact is the
        projection (a different model answer for identical inputs is not displayed unpersisted); `reprocess`
        gives a deliberate re-run its own processing identity."""
        async with self.engine.sf() as session:
            n = await session.get(TechniqueMethodNote, note_id, with_for_update=True)
            if n is None:
                raise KeyError(note_id)
            cur = await srcrev.current_revision(session, note_id)
            if cur is not None and cur.deleted:
                raise StaleWorker("the source is tombstoned - nothing to extract")
            transcript = (n.transcript or "").strip()
            caption = (n.text or "").strip()
            body = (f"{transcript}\n\nCAPTION / POST TEXT:\n{caption}" if transcript and caption else (transcript or caption))
            source = f"{n.kind} in #{n.channel_name or n.channel_id} by {n.author} at {n.posted_at}"
            if not body:
                raise RuntimeError("nothing to extract (no transcript, no text)")
            job = await srcrev.claim_for_note(session, note_id, owner="engine", retry=True)
            if job is None and await srcrev.job_for_note(session, note_id) is not None:
                raise StaleWorker("another worker holds this note's job")
            rev_id = cur.id if cur is not None else None
            attempts = int(((n.meta or {}).get("extractAttempts") or 0)) + 1
            await session.commit()
        model = self.technique.llm_config().model
        config_id = _h(f"{model}|{EXTRACT_SYSTEM}") + (f"#reprocess-{attempts}" if reprocess else "")
        try:
            ex = await self._llm_extract(source, body)
        except Exception as exc:                       # noqa: BLE001 - recorded under THIS job, then surfaced
            await self._fail(note_id, f"{type(exc).__name__}: {exc}"[:500], job=job, revision_id=rev_id)
            raise
        ex["symbols"] = self._clean_symbols(ex)
        ex["extractedAt"] = _now().isoformat()
        ex["model"] = model
        ex["revisionId"] = rev_id
        if job:
            ex["artifactId"] = srcrev.artifact_key(job["revisionId"], "extraction", _h(body), config_id)
        async with self.engine.sf() as session:
            n = await session.get(TechniqueMethodNote, note_id, with_for_update=True)
            now_cur = await srcrev.current_revision(session, note_id)
            still_current = (now_cur is None) or (rev_id is not None and now_cur.id == rev_id and not now_cur.deleted)
            reused = False
            if job:
                try:
                    res = await srcrev.checkpoint(session, job_id=job["id"], fence_token=job["fenceToken"], item_key="extraction",
                                                  stage="extracted", release=True,
                                                  outcome=(None if still_current else "superseded"),
                                                  artifact={"kind": "extraction", "inputHash": _h(body),
                                                            "configHash": config_id, "payload": ex})
                except srcrev.FenceMismatch as exc:
                    await session.rollback()
                    raise StaleWorker(str(exc)) from exc
                reused = bool(res.get("artifactReused"))
                if reused and res.get("artifactPayload") is not None:
                    ex = dict(res["artifactPayload"])    # the persisted output IS the projection (WI-05)
            if still_current:
                n.extraction = ex
                n.status = "extracted"
                n.error = None
                n.meta = {**(n.meta or {}), "extractAttempts": attempts}
                n.updated_at = _now()
            await session.commit()
            d = note_dict(n)
        if not still_current:
            log.info("ingest: extraction for %s archived - the source changed during the read (superseded)", note_id[:8])
            return {**d, "superseded": True, "revisionId": rev_id}
        log.info("ingest: extracted %s -> %d symbol(s), %d claim(s)%s", note_id[:8], len(ex.get("symbols") or []),
                 len(ex.get("claims") or []), " (persisted artifact reused)" if reused else "")
        self._publish(d)
        return {**d, "revisionId": rev_id, "artifactReused": reused}

    # ------------------------------------------------------------ board check
    def _armed_em_symbols(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        armer = getattr(self.technique, "armer", None)
        if armer is None:
            return out
        with contextlib.suppress(Exception):
            for a in armer.armed(slim=True):
                if a.get("status") in ("armed", "paused") and (a.get("technique") or TECHNIQUE) == TECHNIQUE:
                    out[str(a.get("symbol") or "").upper()] = a
        return out

    async def board_check(self, note_id: str, *, revision_id: str | None = None) -> dict:
        """Deterministic: for each symbol on the board, is it covered by an armed EM plan; else build our own plan
        (no LLM) and report valid/rejected. WI-03: the board is AUTHORIZED for one revision (the extraction's);
        the job is claimed before any planning side effect and the source is re-checked before every plan run,
        before every arm and before publication - an edit or tombstone in between stops the board, arms nothing
        and completes no newer revision's job (the leased job ends `superseded`)."""
        async with self.engine.sf() as session:
            n = await session.get(TechniqueMethodNote, note_id, with_for_update=True)
            if n is None:
                raise KeyError(note_id)
            cur = await srcrev.current_revision(session, note_id)
            rev_id = revision_id or (cur.id if cur is not None else None)
            if cur is not None and (cur.deleted or (revision_id is not None and cur.id != revision_id)):
                raise StaleWorker("the source changed before the board started - nothing planned")
            job = await srcrev.claim_for_note(session, note_id, owner="engine", retry=True)
            if job is None and await srcrev.job_for_note(session, note_id) is not None:
                raise StaleWorker("another worker holds this note's job")
            symbols = list((n.extraction or {}).get("symbols") or [])
            await session.commit()
        max_syms = int(self._num("ingest.board_max_symbols", 12))
        armed = self._armed_em_symbols()
        rows: list[dict] = []
        superseded = False
        for sym in symbols[:max_syms]:
            if not await self._source_is_current(note_id, rev_id):
                superseded = True
                break
            if sym in armed:
                a = armed[sym]
                rows.append({"symbol": sym, "status": "armed", "runId": a.get("runId"), "grade": a.get("grade"),
                             "note": (a.get("summary") or "")[:120]})
                continue
            try:
                run = await self.technique.analyze(sym, plan=True, with_vision=False, wait=True,
                                                   trigger="ingest", tags=["ingest"])
            except Exception as exc:                   # noqa: BLE001
                rows.append({"symbol": sym, "status": "error", "reason": f"{type(exc).__name__}: {exc}"[:200]})
                continue
            plan = ((run or {}).get("result") or {}).get("plan") or {}
            trigs = plan.get("triggers") or []
            valid = [t for t in trigs if t.get("valid")]
            if valid:
                best = max(valid, key=lambda t: ((t.get("assessment") or {}).get("score") or 0, t.get("riskReward") or 0))
                row = {"symbol": sym, "status": "new", "runId": run.get("id"),
                       "grade": (best.get("assessment") or {}).get("grade"), "kind": best.get("kind"),
                       "level": best.get("levelPrice"), "riskReward": best.get("riskReward"),
                       "note": (best.get("note") or best.get("summary") or "")[:120]}
                if self._get("ingest.auto_arm", False):
                    # 2026-09-04 (user decision): arm what passes OUR gates - the plan is
                    # ours (deterministic), the source only pointed at the symbol; the
                    # loss halt and the account come from the normal arm path. The run
                    # carries tag `ingest`, so auto-armed plans stay distinguishable.
                    min_grade = str(self._get("ingest.auto_arm_min_grade", "B") or "B").upper()
                    grade = str(row.get("grade") or "").upper()
                    if grade and grade > min_grade:          # letters sort A < B < C
                        row["armSkipped"] = f"grade {grade} below the auto-arm floor {min_grade}"
                    elif not await self._source_is_current(note_id, rev_id):
                        row["armSkipped"] = "source changed before arming (superseded)"
                        superseded = True
                    else:
                        try:
                            await self.technique.arm_plan(run.get("id"), {})
                            row["status"] = "armed"
                            row["autoArmed"] = True
                        except Exception as exc:           # noqa: BLE001
                            row["armError"] = str(exc)[:200]
                rows.append(row)
                if superseded:
                    break
            else:
                # the closest miss explains the rejection (usually R2)
                inv = [t for t in trigs if not t.get("valid")]
                why = ""
                if inv:
                    closest = max(inv, key=lambda t: t.get("riskReward") or 0)
                    why = "; ".join((closest.get("noTradeReasons") or [])[:2])[:220]
                    why = f"{closest.get('id')} {closest.get('kind')} @ {closest.get('levelPrice')}: {why}" if why else ""
                rows.append({"symbol": sym, "status": "rejected", "runId": run.get("id"),
                             "reason": why or "no triggers built"})
        result = {"checkedAt": _now().isoformat(), "rows": rows,
                  "counts": {k: sum(1 for r in rows if r["status"] == k) for k in ("armed", "new", "rejected", "error")},
                  "skipped": symbols[max_syms:], "revisionId": rev_id}
        async with self.engine.sf() as session:
            n = await session.get(TechniqueMethodNote, note_id, with_for_update=True)
            now_cur = await srcrev.current_revision(session, note_id)
            still_current = (not superseded) and ((now_cur is None) or (rev_id is not None and now_cur.id == rev_id and not now_cur.deleted))
            if job:
                try:
                    await srcrev.checkpoint(session, job_id=job["id"], fence_token=job["fenceToken"], item_key="board_check",
                                            stage="board_checked", outcome=("done" if still_current else "superseded"))
                except srcrev.FenceMismatch as exc:
                    await session.rollback()
                    raise StaleWorker(str(exc)) from exc
            if still_current:
                n.board_check = result
                n.status = "checked"
                n.updated_at = _now()
            await session.commit()
            d = note_dict(n)
        if not still_current:
            log.info("ingest: board for %s not published - the source changed during planning (superseded)", note_id[:8])
            return {**d, "superseded": True, "revisionId": rev_id}
        log.info("ingest: board check %s -> %s", note_id[:8], result["counts"])
        self._publish(d)
        return d

    # ------------------------------------------------------------ reads
    async def list_notes(self, limit: int = 20) -> list[dict]:
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(TechniqueMethodNote).where(TechniqueMethodNote.technique == TECHNIQUE)
                .order_by(TechniqueMethodNote.created_at.desc()).limit(max(1, min(200, limit))))).scalars().all()
            return [note_dict(r, full=False) for r in rows]

    async def get_note(self, note_id: str) -> dict | None:
        async with self.engine.sf() as session:
            n = await session.get(TechniqueMethodNote, note_id)
            return note_dict(n) if n is not None else None

    async def latest_board(self) -> dict | None:
        """The newest note that carries an extraction (today's board, normally)."""
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(TechniqueMethodNote).where(TechniqueMethodNote.technique == TECHNIQUE)
                .order_by(TechniqueMethodNote.created_at.desc()).limit(25))).scalars().all()
            for r in rows:
                if r.extraction:
                    return note_dict(r)
            return note_dict(rows[0]) if rows else None

    async def today_board(self) -> dict:
        """The day's material as one view: `note` = the primary item (the newest
        VIDEO setups brief of the day, else the newest extracted note), `others` =
        the rest of the day's notes newest first (supplementary posts, charts,
        pending/duplicate videos) so a follow-up never hides the morning brief."""
        et = dt.timezone(dt.timedelta(hours=-4))          # the day boundary is an ET calendar day
        start = dt.datetime.now(et).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc)
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(TechniqueMethodNote)
                .where(TechniqueMethodNote.technique == TECHNIQUE, TechniqueMethodNote.created_at >= start)
                .order_by(TechniqueMethodNote.created_at.desc()).limit(40))).scalars().all()
            if not rows:
                return {"note": await self.latest_board(), "others": [], "today": False}
            primary = (next((r for r in rows if r.kind == "video" and r.extraction
                             and r.extraction.get("material") in (None, "setups_brief")), None)
                       or next((r for r in rows if r.extraction), None)
                       or next((r for r in rows if r.kind == "video" and r.status != "duplicate"), None)
                       or rows[0])
            others = [note_dict(r, full=False) for r in rows if r.id != primary.id and r.status != "duplicate"]
            return {"note": note_dict(primary), "others": others, "today": True}
