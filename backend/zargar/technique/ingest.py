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
from sqlalchemy import select

from .. import bus as topics
from ..domain import new_id
from ..models import TechniqueMethodNote
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
            await session.commit()
            d = note_dict(n)
        log.info("ingest: %s note %s from #%s (%s)", kind, d["id"][:8], d["channelName"] or d["channelId"], status)
        self._publish(d)
        # a text-only post with substance goes straight to extraction
        if status != "duplicate" and kind != "video" and self._get("ingest.auto_extract", True) and len(text.strip()) >= 60:
            self._spawn(self._extract_and_check(d["id"]), f"em-ingest-extract-{d['id'][:8]}")
        return {**d, "duplicate": False}

    async def pending(self) -> list[dict]:
        """Video notes waiting for the worker (oldest first). A note deferred
        because its broadcast was still LIVE is hidden until `nextCheckAt`;
        past `ingest.live_max_wait_minutes` the worker is told to take whatever
        replay exists (`forcePartial`) rather than wait forever."""
        max_wait = float(self._num("ingest.live_max_wait_minutes", 45))
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
                first_live = _parse_ts(m.get("firstSeenLiveAt"))
                force = bool(first_live and (now - first_live).total_seconds() / 60 >= max_wait)
                out.append({"id": r.id, "mediaUrl": r.media_url, "attempts": int(m.get("attempts") or 0),
                            "deferrals": int(m.get("deferrals") or 0), "forcePartial": force,
                            "postedAt": r.posted_at.isoformat() if r.posted_at else None})
            return out

    async def store_transcript(self, note_id: str, *, transcript: str | None = None,
                               error: str | None = None, meta: dict | None = None,
                               deferred: bool = False) -> dict:
        """The worker's result: a transcript (-> extraction), a DEFERRAL (the
        broadcast is still live - check again in `ingest.live_recheck_seconds`,
        no attempt spent), or a failure (retry up to transcribe_max_attempts,
        then `failed` - never silent)."""
        max_attempts = int(self._num("ingest.transcribe_max_attempts", 5))
        recheck = int(self._num("ingest.live_recheck_seconds", 60))
        async with self.engine.sf() as session:
            n = await session.get(TechniqueMethodNote, note_id)
            if n is None:
                raise KeyError(note_id)
            m = dict(n.meta or {})
            m.update({k: v for k, v in (meta or {}).items() if v is not None})
            if deferred and not (transcript and transcript.strip()):
                m["deferrals"] = int(m.get("deferrals") or 0) + 1
                m.setdefault("firstSeenLiveAt", _now().isoformat())
                m["nextCheckAt"] = (_now() + dt.timedelta(seconds=recheck)).isoformat()
                m["lastDeferReason"] = (error or "broadcast still live")[:200]
                n.status = "pending_transcript"
                n.meta = m
                n.updated_at = _now()
                await session.commit()
                d = note_dict(n)
                self._publish(d)
                return d
            if transcript and transcript.strip():
                n.transcript = transcript.strip()
                n.status = "transcribed"
                n.error = None
            else:
                m["attempts"] = int(m.get("attempts") or 0) + 1
                m["lastError"] = (error or "no transcript")[:500]
                n.status = "failed" if m["attempts"] >= max_attempts else "pending_transcript"
                n.error = m["lastError"] if n.status == "failed" else None
            n.meta = m
            n.updated_at = _now()
            await session.commit()
            d = note_dict(n)
        self._publish(d)
        if d["status"] == "transcribed" and self._get("ingest.auto_extract", True):
            self._spawn(self._extract_and_check(note_id), f"em-ingest-extract-{note_id[:8]}")
        return d

    # ------------------------------------------------------------ extraction
    async def _extract_and_check(self, note_id: str) -> None:
        try:
            d = await self.extract(note_id)
            material = (d.get("extraction") or {}).get("material") or "other"
            # only setup material earns plan runs; a recap or promo is stored, not traded on
            if self._get("ingest.auto_plan_board", True) and material in ("setups_brief", "alert"):
                await self.board_check(note_id)
        except Exception as exc:                       # noqa: BLE001 - surfaced on the note, never swallowed
            log.exception("ingest: extract/check failed for %s", note_id[:8])
            await self._fail(note_id, f"{type(exc).__name__}: {exc}"[:500])

    async def _fail(self, note_id: str, error: str) -> None:
        async with self.engine.sf() as session:
            n = await session.get(TechniqueMethodNote, note_id)
            if n is not None:
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

    async def extract(self, note_id: str) -> dict:
        async with self.engine.sf() as session:
            n = await session.get(TechniqueMethodNote, note_id)
            if n is None:
                raise KeyError(note_id)
            body = (n.transcript or "").strip() or (n.text or "").strip()
            source = f"{n.kind} in #{n.channel_name or n.channel_id} by {n.author} at {n.posted_at}"
        if not body:
            raise RuntimeError("nothing to extract (no transcript, no text)")
        ex = await self._llm_extract(source, body)
        ex["symbols"] = self._clean_symbols(ex)
        ex["extractedAt"] = _now().isoformat()
        ex["model"] = self.technique.llm_config().model
        async with self.engine.sf() as session:
            n = await session.get(TechniqueMethodNote, note_id)
            n.extraction = ex
            n.status = "extracted"
            n.error = None
            n.updated_at = _now()
            await session.commit()
            d = note_dict(n)
        log.info("ingest: extracted %s -> %d symbol(s), %d claim(s)", note_id[:8], len(ex["symbols"]), len(ex.get("claims") or []))
        self._publish(d)
        return d

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

    async def board_check(self, note_id: str) -> dict:
        """Deterministic: for each symbol on the board, is it covered by an armed
        EM plan; else build our own plan (no LLM) and report valid/rejected."""
        async with self.engine.sf() as session:
            n = await session.get(TechniqueMethodNote, note_id)
            if n is None:
                raise KeyError(note_id)
            symbols = list((n.extraction or {}).get("symbols") or [])
        max_syms = int(self._num("ingest.board_max_symbols", 12))
        armed = self._armed_em_symbols()
        rows: list[dict] = []
        for sym in symbols[:max_syms]:
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
                       "direction": best.get("direction"), "level": best.get("levelPrice"),
                       "rr": best.get("riskReward"), "triggerId": best.get("id")}
                if self._get("ingest.auto_arm", False):
                    # 2026-09-04 (user decision): arm what passes OUR gates - the plan is
                    # already valid (R2) and this adds the grade floor; the critic, the
                    # loss halt and the account come from the normal arm path. The run
                    # carries tag `ingest`, so auto-armed plans stay distinguishable.
                    min_grade = str(self._get("ingest.auto_arm_min_grade", "B") or "B").upper()
                    grade = str(row.get("grade") or "").upper()
                    if grade and grade > min_grade:          # letters sort A < B < C
                        row["armSkipped"] = f"grade {grade} below the auto-arm floor {min_grade}"
                    else:
                        try:
                            await self.technique.arm_plan(run.get("id"), {})
                            row["status"] = "armed"
                            row["autoArmed"] = True
                        except Exception as exc:           # noqa: BLE001
                            row["armError"] = str(exc)[:200]
                rows.append(row)
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
                  "skipped": symbols[max_syms:]}
        async with self.engine.sf() as session:
            n = await session.get(TechniqueMethodNote, note_id)
            n.board_check = result
            n.status = "checked"
            n.updated_at = _now()
            await session.commit()
            d = note_dict(n)
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
