"""Signal pipeline service: raw content → extraction → grounding → verification → proposal.

Rebuilt 2026-08-27 for the tip technique (docs/techniques/tip/PLAN.md §A):
extraction v2 carries the whole trade (instrument/strike/expiry/horizon),
screenshots of the user's own client are transcribed and extracted, duplicate
tips attach to the original as "seen again" instead of minting a second
proposal, price-position failures *park* a signal (the tip technique waits for
the level) instead of killing it, and every verified signal shadow-trades so
the per-source scorecard exists regardless of the human decision.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hashlib
import logging
import time as _time

from sqlalchemy import select

from .. import bus as topics
from .. import events as ev
from ..domain import new_id
from ..models import ChatAsset, Portfolio as PortfolioRow, RawContent, Signal
from .extraction import Extractor, ground_signal
from .schemas import ExtractionResult, TradeSignal
from .sources import SourcePolicy, resolve_policy
from .verification import verify_signal

log = logging.getLogger("zargar.signals")


def signal_dict(row: Signal) -> dict:
    return {
        "id": row.id,
        "rawContentId": row.raw_content_id,
        "sourceName": row.source_name,
        "ticker": row.ticker,
        "exchangeHint": row.exchange_hint,
        "direction": row.direction,
        "action": row.action,
        "instrument": row.instrument,
        "strike": row.strike,
        "premium": row.premium,
        "expiry": row.expiry,
        "dteHintDays": row.dte_hint_days,
        "horizonSessions": row.horizon_sessions,
        "catalyst": row.catalyst,
        "seenCount": row.seen_count,
        "lastSeenAt": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "entryPrice": row.entry_price,
        "entryType": row.entry_type,
        "targetPrice": row.target_price,
        "stopPrice": row.stop_price,
        "timeframe": row.timeframe,
        "thesisSummary": row.thesis_summary,
        "confidence": row.confidence,
        "isActionable": row.is_actionable,
        "extraction": row.extraction,
        "verification": row.verification,
        "status": row.status,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


def dedupe_key_for(source: str | None, sig: TradeSignal) -> str:
    """Semantic identity of a tip: same source + same trade = the same tip,
    however it was worded. Repeat mentions bump `seen_count` on the original."""
    raw = "|".join([
        (source or "unknown").lower(), sig.ticker.upper(), sig.direction,
        sig.instrument, f"{sig.strike:g}" if sig.strike else "", sig.expiry or "",
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:40]


def experiment_tag(extraction: dict | None) -> str | None:
    """The out-of-band experiment batch a signal belongs to, or None
    (KNOWLEDGE plan §E). Experiment rows are evidence for review — they never
    reach scorecards, shadow books, dedupe, proposals, arming, retros or the
    rule audit."""
    tag = (extraction or {}).get("experiment")
    return str(tag) if tag else None


class SignalService:
    def __init__(self, engine, extractor: Extractor) -> None:
        self.engine = engine
        self.extractor = extractor
        self._replay_fetch = None      # tests inject a bars fetcher for replays
        self._analyst_client = None    # tests inject a fake Anthropic client
        self._discord_catalog: dict | None = None   # last catalog the gateway reported
        self._discord_peek_queue: set[str] = set()  # channelIds the UI asked to peek
        self._discord_peek_results: dict[str, dict] = {}  # channelId -> last-message preview
        self._discord_process_queue: set[str] = set()  # channelIds to fetch+ingest as a tip
        self._discord_process_results: dict[str, dict] = {}  # channelId -> what happened

    # ---------------------------------------------------- analyst run history
    async def analyst_runs(self, limit: int = 40) -> list[dict]:
        from ..models import TipAnalystRun
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(TipAnalystRun).order_by(TipAnalystRun.created_at.desc()).limit(limit)
            )).scalars().all()
        return [{"id": r.id, "ticker": r.ticker, "source": r.source, "status": r.status,
                 "kind": getattr(r, "kind", "appraise") or "appraise",
                 "verdict": r.verdict, "model": r.model, "signalId": r.signal_id,
                 "parentId": getattr(r, "parent_id", None),
                 "traceSteps": len(r.trace or []),
                 "createdAt": r.created_at.isoformat() if r.created_at else None,
                 "finishedAt": r.finished_at.isoformat() if r.finished_at else None}
                for r in rows]

    async def analyst_run(self, run_id: str) -> dict:
        from ..models import TipAnalystRun
        async with self.engine.sf() as session:
            r = await session.get(TipAnalystRun, run_id)
            kids = (await session.execute(
                select(TipAnalystRun)
                .where(TipAnalystRun.parent_id == run_id)
                .order_by(TipAnalystRun.created_at.asc()))).scalars().all() if r else []
        if r is None:
            raise KeyError(f"analyst run {run_id} not found")
        return {"id": r.id, "ticker": r.ticker, "source": r.source, "status": r.status,
                "kind": getattr(r, "kind", "appraise") or "appraise",
                "verdict": r.verdict, "model": r.model, "signalId": r.signal_id,
                "parentId": getattr(r, "parent_id", None),
                "children": [{"id": k.id, "ticker": k.ticker, "verdict": k.verdict,
                              "status": k.status} for k in kids],
                "tools": r.tools or [], "trace": r.trace or [], "opinion": r.opinion or {},
                "tip": r.tip or {}, "error": r.error,
                "createdAt": r.created_at.isoformat() if r.created_at else None,
                "finishedAt": r.finished_at.isoformat() if r.finished_at else None}

    # ---------------------------------------------------- shared tips knowledge
    # Notes are the desk's memory: durable context a tip carried ("the SPY put
    # hedges the source's Oct-Dec calls"), lessons, per-tip details. The analyst
    # reads matching notes before every run and writes new ones (save_note).
    @staticmethod
    def note_dict(n) -> dict:
        return {"id": n.id, "scope": n.scope, "text": n.text, "author": n.author,
                "signalId": n.signal_id, "runId": n.run_id,
                "supersededBy": getattr(n, "superseded_by", None),
                "needsHuman": bool(getattr(n, "needs_human", False)),
                "createdAt": n.created_at.isoformat() if n.created_at else None}

    async def tip_notes(self, scopes: list[str] | None = None,
                        limit: int = 100, *, include_superseded: bool = False) -> list[dict]:
        from ..models import TipNote
        async with self.engine.sf() as session:
            q = select(TipNote).order_by(TipNote.created_at.desc()).limit(limit)
            if scopes:
                q = q.where(TipNote.scope.in_(scopes))
            if not include_superseded:
                # superseded rules are history, not live knowledge (A8.2)
                q = q.where(TipNote.superseded_by.is_(None))
            rows = (await session.execute(q)).scalars().all()
        return [self.note_dict(r) for r in rows]

    async def supersede_tip_notes(self, note_ids: list[str], by: str) -> int:
        """Rule lifecycle (A8.2): mark rules superseded — never delete. `by` is
        the refined rule's id, or 'expired:<run8>'."""
        from ..models import TipNote
        n = 0
        async with self.engine.sf() as session:
            for nid in note_ids:
                row = await session.get(TipNote, nid)
                if row is not None and row.superseded_by is None:
                    row.superseded_by = str(by)[:80]
                    n += 1
            await session.commit()
        return n

    async def flag_tip_notes(self, note_ids: list[str], *, needs_human: bool) -> int:
        """A8.3: raise (the audit) or clear (the human's click) the
        needs-your-call flag on notes. Journaled by the caller."""
        from ..models import TipNote
        n = 0
        async with self.engine.sf() as session:
            for nid in note_ids:
                row = await session.get(TipNote, nid)
                if row is not None and bool(row.needs_human) != needs_human:
                    row.needs_human = needs_human
                    n += 1
            await session.commit()
        return n

    async def add_tip_note(self, scope: str, text: str, *, author: str = "user",
                           signal_id: str | None = None,
                           run_id: str | None = None) -> dict:
        from ..models import TipNote
        scope = (scope or "general").strip() or "general"
        text = (text or "").strip()
        if not text:
            raise ValueError("empty note")
        row = TipNote(id=new_id(), scope=scope[:160], text=text[:2000],
                      author=author[:80], signal_id=signal_id, run_id=run_id)
        async with self.engine.sf() as session:
            session.add(row)
            await session.commit()
        note = self.note_dict(row)
        await self.engine.journal.append(ev.TIP_NOTE_ADDED, note,
                                         aggregate_type="signal",
                                         aggregate_id=signal_id or row.id)
        return note

    async def update_tip_note(self, note_id: str, *, text: str | None = None,
                              scope: str | None = None) -> dict | None:
        """Edit a knowledge note in place (Knowledge tab). Journaled; None =
        unknown id. An empty text is a ValueError, not a silent wipe."""
        from ..models import TipNote
        if text is not None and not text.strip():
            raise ValueError("empty note")
        async with self.engine.sf() as session:
            row = await session.get(TipNote, note_id)
            if row is None:
                return None
            if text is not None:
                row.text = text.strip()[:2000]
            if scope is not None and scope.strip():
                row.scope = scope.strip()[:160]
            await session.commit()
            note = self.note_dict(row)
        await self.engine.journal.append(ev.TIP_NOTE_EDITED, note,
                                         aggregate_type="signal",
                                         aggregate_id=note_id)
        return note

    async def delete_tip_note(self, note_id: str) -> bool:
        from ..models import TipNote
        async with self.engine.sf() as session:
            row = await session.get(TipNote, note_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
        return True

    async def notes_for_tip(self, ticker: str | None, source: str | None,
                            signal_id: str | None = None,
                            limit: int = 12) -> list[dict]:
        """The notes an analyst run should see: this tip's own, its ticker's,
        its source's, and the general ones — newest first, capped."""
        scopes = ["general"]
        if ticker:
            scopes.append(f"ticker:{ticker.upper()}")
        if source:
            scopes.append(f"source:{source}")
        if signal_id:
            scopes.append(f"signal:{signal_id}")
        return await self.tip_notes(scopes, limit=limit)

    # ---------------------------------------------------- discord message mirror
    # The source's own history is context ("bought NVDA" → "sold 40%"): every
    # message the gateway sees in a MONITORED channel is mirrored here for the
    # analyst to search and cross-reference (ANALYST.md; user 2026-08-28).
    @staticmethod
    def _msg_dict(m) -> dict:
        return {"id": m.id, "channelId": m.channel_id, "source": m.source_name,
                "guild": m.guild_name, "author": m.author, "isBot": m.is_bot,
                "text": m.text, "images": m.images or [],
                "localImages": list(getattr(m, "local_images", None) or []),
                "postedAt": m.posted_at.isoformat() if m.posted_at else None}

    # --- mirrored media: image BYTES live locally (CDN links expire and the
    # --- analyst LLM cannot fetch URLs — user, 2026-08-29) ---------------------
    MEDIA_DIR = "discord_media"
    MEDIA_MAX_BYTES = 8 * 1024 * 1024

    def discord_media_dir(self):
        from pathlib import Path
        d = Path(self.MEDIA_DIR)
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def _download_media(self, message_id: str, urls: list[str],
                              offset: int = 0) -> list[str]:
        """CDN URLs -> local files (message-id-based names). Best-effort; only
        files that landed are recorded. Tests may inject `_media_fetch`."""
        from ..technique.llm import sniff_media_type
        ext_for = {"image/png": "png", "image/jpeg": "jpg",
                   "image/gif": "gif", "image/webp": "webp"}
        out: list[str] = []
        fetch = getattr(self, "_media_fetch", None)
        d = self.discord_media_dir()
        for i, url in enumerate(urls[:6], start=offset):
            try:
                if fetch is not None:
                    blob = await fetch(url)
                else:
                    import httpx
                    async with httpx.AsyncClient(timeout=30) as http:
                        r = await http.get(url)
                        blob = r.content if r.status_code == 200 else None
                if not blob or len(blob) > self.MEDIA_MAX_BYTES:
                    continue
                try:
                    mt = sniff_media_type(blob)
                except ValueError:
                    continue                        # not an image we understand
                name = f"{message_id}-{i}.{ext_for[mt]}"
                (d / name).write_bytes(blob)
                out.append(name)
            except Exception:
                log.debug("media download failed for %s image %d", message_id, i)
        return out

    async def _download_media_for(self, ids_with_urls: list[tuple[str, list[str]]]) -> None:
        """Background task: fetch the images of freshly-mirrored messages while
        the CDN links are still signed, then record the local filenames."""
        from ..models import DiscordMessage
        for mid, urls in ids_with_urls:
            names = await self._download_media(mid, urls)
            if not names:
                continue
            try:
                async with self.engine.sf() as session:
                    row = await session.get(DiscordMessage, mid)
                    if row is not None:
                        row.local_images = names
                        await session.commit()
            except Exception:
                log.exception("recording local media failed for %s", mid)

    async def discord_media_catchup(self, limit: int = 2000) -> dict:
        """One-shot rescue: download images for mirrored messages that only
        hold CDN URLs (rows from before the local store existed, or whose
        download failed). Runs in the background at startup — links younger
        than ~24h are still signed, so a prompt restart saves them."""
        from ..models import DiscordMessage
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(DiscordMessage.id, DiscordMessage.images, DiscordMessage.local_images)
                .order_by(DiscordMessage.posted_at.desc()).limit(limit))).all()
        todo = [(mid, list(urls or [])) for mid, urls, local in rows
                if (urls or []) and not (local or [])]
        saved = failed = 0
        for mid, urls in todo:
            names = await self._download_media(mid, urls)
            if names:
                saved += 1
                async with self.engine.sf() as session:
                    row = await session.get(DiscordMessage, mid)
                    if row is not None:
                        row.local_images = names
                        await session.commit()
            else:
                failed += 1
            await asyncio.sleep(0.2)               # gentle on the CDN
        if todo:
            log.info("mirror media catch-up: %d message(s) saved, %d unavailable "
                     "(links likely expired)", saved, failed)
        return {"candidates": len(todo), "saved": saved, "unavailable": failed}

    def start_media_catchup(self) -> None:
        """Spawn the catch-up as a background task (called at startup)."""
        asyncio.create_task(self.discord_media_catchup(), name="discord-media-catchup")

    async def analyze_mirrored_message(self, message_id: str) -> None:
        """Ad-hoc analysis of one MIRRORED message (user, 2026-08-29: trigger a
        tips analysis on any past message to fine-tune the process). Runs the
        normal pipeline — extraction → verification → analyst; a stale message
        replays on history like any old tip. Progress/outcome land in the
        process-result store under key `msg:<id>` (same banner as '▶ tip')."""
        key = f"msg:{message_id}"
        m = await self.discord_get_message(message_id)
        if m is None:
            self.discord_set_process_result(key, {"ok": False, "error": "message not in the mirror"})
            return
        image = media_type = None
        if m.get("images"):
            got = await self.discord_media_bytes(message_id, 0)
            if got is not None:
                image, media_type = got[0], got[1]
        try:
            out = await self.ingest_manual(
                m.get("text") or "", source_name=m.get("source") or "auto",
                subject=f"mirror: {m.get('author') or '?'} @ {(m.get('postedAt') or '')[:16]}",
                image=image, image_media_type=media_type or "image/png")
        except Exception as exc:
            log.exception("ad-hoc mirror analysis failed for %s", message_id)
            self.discord_set_process_result(key, {"ok": False, "error": str(exc)[:300]})
            return
        sigs = []
        for item in (out.get("signals") or []):
            srow = item.get("signal") or {}
            sigs.append({"id": srow.get("id"), "ticker": srow.get("ticker"),
                         "status": srow.get("status"),
                         "analystRunId": ((srow.get("extraction") or {})
                                          .get("analyst") or {}).get("runId")})
        note = out.get("note") or ""
        if not sigs and not note:
            note = ("the message did not extract as a trade tip "
                    "(or it duplicated a tip already on the desk)")
        self.discord_set_process_result(key, {
            "ok": True, "signals": sigs, "note": note,
            "author": m.get("author") or "", "text": (m.get("text") or "")[:200]})

    def start_mirror_analysis(self, message_id: str) -> str:
        """Spawn the ad-hoc analysis; returns the process-result key to poll."""
        key = f"msg:{message_id}"
        # a pending marker keeps the UI honest: the analysis is APP-side (a
        # multi-signal message takes minutes) — never "is the intake dead?"
        self.discord_set_process_result(key, {
            "pending": True,
            "note": "analysing — extraction, verification and per-signal appraisals "
                    "can take a few minutes on a multi-signal message"})
        asyncio.create_task(self.analyze_mirrored_message(message_id),
                            name=f"mirror-analyze-{message_id[:8]}")
        return key

    async def discord_get_message(self, message_id: str) -> dict | None:
        from ..models import DiscordMessage
        async with self.engine.sf() as session:
            row = await session.get(DiscordMessage, str(message_id))
        return self._msg_dict(row) if row is not None else None

    async def discord_media_bytes(self, message_id: str, index: int = 0) -> tuple[bytes, str] | None:
        """(bytes, media_type) of one mirrored image — from disk, or fetched on
        the spot if the link is still alive; None when unavailable."""
        from ..technique.llm import sniff_media_type
        m = await self.discord_get_message(message_id)
        if m is None:
            return None
        local = m.get("localImages") or []
        if index < len(local):
            p = self.discord_media_dir() / local[index]
            if p.exists():
                blob = p.read_bytes()
                try:
                    return blob, sniff_media_type(blob)
                except ValueError:
                    return None
        urls = m.get("images") or []
        if index < len(urls):                       # last chance: link may still be signed
            names = await self._download_media(str(message_id), [urls[index]], offset=index)
            if names:
                p = self.discord_media_dir() / names[0]
                blob = p.read_bytes()
                async with self.engine.sf() as session:   # remember it for next time
                    from ..models import DiscordMessage
                    row = await session.get(DiscordMessage, str(message_id))
                    if row is not None and names[0] not in (row.local_images or []):
                        row.local_images = list(row.local_images or []) + names
                        await session.commit()
                return blob, sniff_media_type(blob)
        return None

    async def discord_store_messages(self, messages: list[dict]) -> int:
        """Upsert mirrored messages (id = the discord message id); prune the
        mirror past techniques.tip.mirror_max_messages, oldest first."""
        from ..models import DiscordMessage
        stored = 0
        to_fetch: list[tuple[str, list[str]]] = []   # new messages with images
        async with self.engine.sf() as session:
            for m in messages[:200]:
                mid = str(m.get("id") or "").strip()
                if not mid:
                    continue
                row = await session.get(DiscordMessage, mid)
                if row is not None:
                    continue
                posted = None
                try:
                    ts = str(m.get("postedAt") or "")
                    posted = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
                except ValueError:
                    posted = None
                urls = [str(u) for u in (m.get("images") or [])][:6]
                session.add(DiscordMessage(
                    id=mid, channel_id=str(m.get("channelId") or ""),
                    source_name=(m.get("source") or None),
                    guild_name=(m.get("guild") or None),
                    author=str(m.get("author") or "")[:128],
                    author_id=(str(m.get("authorId")) if m.get("authorId") else None),
                    is_bot=bool(m.get("isBot")),
                    text=str(m.get("text") or "")[:8000],
                    images=urls,
                    posted_at=posted))
                stored += 1
                if urls:
                    to_fetch.append((mid, urls))
            await session.commit()
        if to_fetch:
            # download the bytes NOW, while the CDN links are still signed —
            # local copies are what the viewer and the analyst's view_image use
            asyncio.create_task(self._download_media_for(to_fetch),
                                name=f"discord-media-{to_fetch[0][0][:8]}")
        if stored:
            await self._prune_mirror()
        return stored

    async def _prune_mirror(self) -> None:
        from sqlalchemy import delete, func
        from ..models import DiscordMessage
        cap = int(self.engine.settings.get("techniques.tip.mirror_max_messages", 20000))
        async with self.engine.sf() as session:
            n = (await session.execute(
                select(func.count()).select_from(DiscordMessage))).scalar() or 0
            if n <= cap:
                return
            cutoff_rows = (await session.execute(
                select(DiscordMessage.id)
                .order_by(DiscordMessage.posted_at.asc().nulls_first())
                .limit(n - cap))).scalars().all()
            if cutoff_rows:
                await session.execute(delete(DiscordMessage)
                                      .where(DiscordMessage.id.in_(cutoff_rows)))
                await session.commit()

    async def discord_search_messages(self, *, source: str | None = None,
                                      channel_id: str | None = None,
                                      contains: str | None = None,
                                      hours: float | None = None,
                                      before: str | None = None,
                                      limit: int = 30) -> list[dict]:
        """The analyst's (and the viewer's) history search: newest first,
        filtered by source name, channel, substring (case-insensitive),
        lookback hours, and `before` (ISO — pagination for 'load older')."""
        from ..models import DiscordMessage
        q = select(DiscordMessage).order_by(DiscordMessage.posted_at.desc()) \
            .limit(max(1, min(int(limit), 200)))
        if source:
            q = q.where(DiscordMessage.source_name == source)
        if channel_id:
            q = q.where(DiscordMessage.channel_id == str(channel_id))
        if contains:
            q = q.where(DiscordMessage.text.ilike(f"%{contains}%"))
        if hours:
            cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=float(hours))
            q = q.where(DiscordMessage.posted_at >= cutoff)
        if before:
            try:
                b = dt.datetime.fromisoformat(str(before).replace("Z", "+00:00"))
                q = q.where(DiscordMessage.posted_at < b)
            except ValueError:
                pass
        async with self.engine.sf() as session:
            rows = (await session.execute(q)).scalars().all()
        return [self._msg_dict(r) for r in rows]

    async def discord_mirror_stats(self) -> dict:
        """Per-channel mirror coverage {channelId: {count, oldestId, oldestAt,
        newestAt}} — the gateway reads it to decide how far an onboarding
        backfill must reach (no re-downloads)."""
        from sqlalchemy import func
        from ..models import DiscordMessage
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(DiscordMessage.channel_id,
                       func.count(DiscordMessage.id),
                       func.min(DiscordMessage.posted_at),
                       func.max(DiscordMessage.posted_at))
                .group_by(DiscordMessage.channel_id))).all()
            out: dict = {}
            for cid, n, oldest, newest in rows:
                oldest_id = (await session.execute(
                    select(DiscordMessage.id)
                    .where(DiscordMessage.channel_id == cid)
                    .order_by(DiscordMessage.posted_at.asc()).limit(1))).scalar()
                out[str(cid)] = {"count": int(n), "oldestId": oldest_id,
                                 "oldestAt": oldest.isoformat() if oldest else None,
                                 "newestAt": newest.isoformat() if newest else None}
        return out

    def discord_queue_process(self, channel_id: str) -> None:
        self._discord_process_queue.add(str(channel_id))
        self._discord_process_results.pop(str(channel_id), None)

    def discord_take_processes(self) -> list[str]:
        out = sorted(self._discord_process_queue)
        self._discord_process_queue.clear()
        return out

    def discord_set_process_result(self, channel_id: str, result: dict) -> None:
        """The gateway reports what 'process last message' actually did — the
        UI shows it, so a message that extracts as NO tip is not silence."""
        self._discord_process_results[str(channel_id)] = {
            **result, "at": dt.datetime.now(dt.timezone.utc).isoformat()}

    def discord_get_process_result(self, channel_id: str) -> dict | None:
        return self._discord_process_results.get(str(channel_id))

    # ---------------------------------------------------- discord intake config
    # The gateway (zargar/tools/discord_gateway.py) reports the DMs/channels it
    # can see (the CATALOG); the user picks which to monitor (the WATCHLIST, in
    # settings). The gateway polls the watchlist and only ingests matches — an
    # allowlist, so personal DMs never become tips (user, 2026-08-28).
    def discord_set_catalog(self, catalog: dict) -> None:
        self._discord_catalog = {**catalog,
                                 "at": dt.datetime.now(dt.timezone.utc).isoformat()}

    def discord_get_catalog(self) -> dict:
        return self._discord_catalog or {"dms": [], "guilds": [], "user": None, "at": None}

    def discord_get_watch(self) -> list[dict]:
        return list(self.engine.settings.get("techniques.tip.discord.watch") or [])

    async def discord_set_watch(self, watch: list[dict]) -> list[dict]:
        clean: list[dict] = []
        for w in watch or []:
            cid = str(w.get("channelId") or "").strip()
            if not cid:
                continue
            clean.append({
                "channelId": cid,
                "kind": "dm" if w.get("kind") == "dm" else "channel",
                "sourceName": str(w.get("sourceName") or "").strip() or "auto",
                "label": str(w.get("label") or "")[:120],
                "guildName": str(w.get("guildName") or "")[:120],
                "botsOnly": bool(w.get("botsOnly", w.get("kind") != "dm")),
                "enabled": bool(w.get("enabled", True)),
                # onboarding: mirror this many days of history (gateway, <= 90 —
                # raised from 17 for the historical-tips experiment)
                "onboardDays": max(0, min(90, int(w.get("onboardDays") or 0))),
                # "tips" auto-processes matching posts; "context" = mirror +
                # digest only, never auto-tips (KNOWLEDGE plan C1)
                "mode": "context" if w.get("mode") == "context" else "tips",
            })
        await self.engine.settings.set("techniques.tip.discord.watch", clean)
        return clean

    # peek: the UI asks to see a channel's last message (a connection test); the
    # gateway (which holds the token) fetches it and posts the result back.
    def discord_queue_peek(self, channel_id: str) -> None:
        self._discord_peek_queue.add(str(channel_id))
        self._discord_peek_results.pop(str(channel_id), None)

    def discord_take_peeks(self) -> list[str]:
        out = sorted(self._discord_peek_queue)
        self._discord_peek_queue.clear()
        return out

    def discord_set_peek_result(self, channel_id: str, result: dict) -> None:
        self._discord_peek_results[str(channel_id)] = {
            **result, "at": dt.datetime.now(dt.timezone.utc).isoformat()}

    def discord_get_peek_result(self, channel_id: str) -> dict | None:
        return self._discord_peek_results.get(str(channel_id))

    # ------------------------------------------------------------- intake
    async def ingest_email(self, payload: dict) -> dict:
        """Store an inbound email (Cloudflare Email Worker webhook shape) and process it."""
        eng = self.engine
        sender = payload.get("from", "")
        source_name = self._match_source(sender) or sender
        row = RawContent(
            id=new_id(),
            source_type="email",
            source_name=source_name,
            sender=sender,
            subject=payload.get("subject", ""),
            body_text=payload.get("text") or "",
            body_html=payload.get("html") or "",
            meta={
                "to": payload.get("to"),
                "headers": payload.get("headers", {}),
                "spf": payload.get("spf"),
                "dkim": payload.get("dkim"),
            },
        )
        async with eng.sf() as session:
            session.add(row)
            await session.commit()
        await eng.journal.append(
            ev.CONTENT_RECEIVED,
            {"id": row.id, "source": source_name, "subject": row.subject,
             "sourceType": "email"},
            aggregate_type="content", aggregate_id=row.id)
        return await self.process_content(row.id)

    async def ingest_manual(self, text: str, *, source_name: str = "manual",
                            subject: str = "", image: bytes | None = None,
                            image_media_type: str = "image/png") -> dict:
        """Paste-in path — text, or a screenshot of the user's own client (the
        model transcribes it; the image is kept as evidence in chat_assets)."""
        eng = self.engine
        meta: dict = {}
        if image is not None:
            asset = ChatAsset(id=new_id(), thread_id=None, media_type=image_media_type,
                              data=image, meta={"kind": "tip_screenshot"})
            async with eng.sf() as session:
                session.add(asset)
                await session.commit()
            meta["imageAssetId"] = asset.id
        row = RawContent(id=new_id(), source_type="manual", source_name=source_name,
                         subject=subject, body_text=text, meta=meta)
        async with eng.sf() as session:
            session.add(row)
            await session.commit()
        await eng.journal.append(
            ev.CONTENT_RECEIVED, {"id": row.id, "source": source_name, "sourceType": "manual",
                                  "hasImage": image is not None},
            aggregate_type="content", aggregate_id=row.id)
        return await self.process_content(row.id)

    def _match_source(self, sender: str) -> str | None:
        registry = self.engine.settings.get("sources.registry") or []
        sender_lower = sender.lower()
        for src in registry:
            for email in src.get("emails", []):
                if email.lower() in sender_lower:
                    return src.get("name")
        return None

    async def known_sources(self) -> list[str]:
        """Every source name the app has seen: the registry + prior signals.
        Feeds the compose box's suggestions and auto-detect matching."""
        names: list[str] = []
        for src in self.engine.settings.get("sources.registry") or []:
            if src.get("name"):
                names.append(str(src["name"]))
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(Signal.source_name).distinct())).scalars().all()
        for n in rows:
            if n and n not in names:
                names.append(n)
        return sorted(names, key=str.casefold)

    async def _resolve_source(self, hint: str) -> tuple[str, bool]:
        """A detected source hint -> a canonical source name. Exact casefold
        match on known sources first, then containment either way (a screenshot
        says '#alpha-alerts' and the source is 'Alpha Alerts'); a genuinely new
        hint becomes a new source under its own (cleaned) name. Returns
        (name, matched_existing)."""
        clean = " ".join(str(hint).split()).strip("#@ ")[:64] or "unknown"

        def key(s: str) -> str:
            # punctuation/case-insensitive: '#alpha-alerts' matches 'Alpha Alerts'
            return "".join(ch for ch in s.casefold() if ch.isalnum())

        cf = key(clean)
        known = await self.known_sources()
        if cf:
            for name in known:
                if key(name) == cf:
                    return name, True
            for name in known:
                nk = key(name)
                if nk and (cf in nk or nk in cf):
                    return name, True
        return clean, False

    # ------------------------------------------------------------- pipeline
    async def process_content(self, content_id: str) -> dict:
        eng = self.engine
        async with eng.sf() as session:
            content = await session.get(RawContent, content_id)
        if content is None:
            raise ValueError("unknown content")
        image: bytes | None = None
        asset_id = (content.meta or {}).get("imageAssetId")
        if asset_id:
            async with eng.sf() as session:
                asset = await session.get(ChatAsset, asset_id)
            image = asset.data if asset else None
        text = content.body_text or content.body_html or ""
        if not text.strip() and image is None:
            await self._set_content_status(content_id, "ignored")
            return {"contentId": content_id, "status": "ignored", "signals": []}
        if not self.extractor.available:
            return {"contentId": content_id, "status": "new", "signals": [],
                    "note": "extraction unavailable: ANTHROPIC_API_KEY not configured"}

        # the intake run: this message's live play-by-play, from second zero
        from ..techniques.tip.analyst import IntakeRun
        intake = IntakeRun(eng)
        await intake.start(source=content.source_name or "auto",
                           chars=len(text), has_image=image is not None,
                           preview=text[:400])
        intake.step("extract", f"Extracting with {self.extractor.model}…"
                    + (" (image transcription included)" if image is not None else "")
                    + " — one LLM read of the whole message, usually 10–30 s.")
        await intake.checkpoint()
        try:
            result = await self.extractor.extract(
                text,
                subject=content.subject or "",
                source_name=content.source_name or "",
                received_at=content.received_at.isoformat() if content.received_at else "",
                image=image)
        except Exception as exc:
            log.exception("extraction failed for %s", content_id)
            await self._set_content_status(content_id, "error")
            await intake.finish("failed", f"Extraction failed: {exc}", failed=True)
            return {"contentId": content_id, "status": "error", "error": str(exc),
                    "signals": [], "intakeRunId": intake.id}

        sigs = result.signals or []
        intake.step("extract",
                    f"Extracted {len(sigs)} signal(s) — content type: {result.source_type}."
                    + (" Transcribed the image into text first." if (image is not None and result.source_transcript) else "")
                    + (" " + "; ".join(f"{s.ticker} {s.direction} {s.instrument}"
                                       f"{' (not an explicit call)' if not s.is_actionable else ''}"
                                       for s in sigs[:8]) if sigs else
                       " Nothing resembling a trade in this message."))
        # the run's list title: the tickers themselves ("GOOGL · AAPL · AMZN"),
        # not a cryptic "+2" (user, 2026-08-29)
        names = list(dict.fromkeys(s.ticker.upper() for s in sigs))
        label = " · ".join(names)
        if len(label) > 30 and len(names) > 2:
            label = " · ".join(names[:2]) + f" +{len(names) - 2}"
        await intake.checkpoint(ticker=(label or "no signals")[:32])

        source_text = text
        if image is not None and result.source_transcript:
            # the transcript IS the source for grounding + display; keep it
            source_text = result.source_transcript
            async with eng.sf() as session:
                db_content = await session.get(RawContent, content_id)
                if db_content is not None and not (db_content.body_text or "").strip():
                    db_content.body_text = result.source_transcript
                    await session.commit()

        out = await self.handle_extraction(content, result, source_text=source_text,
                                           intake=intake)
        await self._set_content_status(content_id, "extracted")

        # any signal that verification discarded -> the analyst reviews the
        # update against the desk's own book (positions, open tips, notes) in
        # this same run, so a recap/exit note is bookkept instead of dropped
        tradable = [o for o in out
                    if (o.get("signal") or {}).get("status")
                    in ("verified", "shadow", "parked", "replayed") or o.get("duplicateOf")]
        discarded = [o for o in out
                     if (o.get("signal") or {}).get("status") == "verification_failed"]
        if discarded:
            outcomes = [{"ticker": (o.get("signal") or {}).get("ticker"),
                         "status": "seen_again" if o.get("duplicateOf")
                         else (o.get("signal") or {}).get("status"),
                         "failed": [c["name"] for c in
                                    ((o.get("signal") or {}).get("verification") or {}).get("checks", [])
                                    if not c.get("passed")]}
                        for o in out]
            await intake.review(source=content.source_name or "unknown",
                                message_text=source_text, outcomes=outcomes,
                                client=self._analyst_client)
        else:
            n_trade = len(tradable)
            if not sigs and await self._source_has_open_items(content.source_name):
                # ARM-GAPS D1: a no-ticker message ("I'm out", "closed
                # everything") from a source with open items on the desk is a
                # follow-up, not noise — the analyst reviews it against what we
                # hold and wait for
                await intake.review(source=content.source_name or "unknown",
                                    message_text=source_text, outcomes=[],
                                    client=self._analyst_client)
            else:
                await intake.finish(
                    f"{n_trade} tip{'s' if n_trade != 1 else ''}" if sigs else "no signals",
                    f"Done — {n_trade} of {len(sigs)} signal(s) entered the tip pipeline."
                    if sigs else "Done — no trade signals in this message.")

        async with eng.sf() as session:               # source may have been auto-detected
            refreshed = await session.get(RawContent, content_id)
        return {"contentId": content_id, "status": "extracted",
                "sourceType": result.source_type, "signals": out,
                "intakeRunId": intake.id,
                "source": (refreshed.source_name if refreshed else content.source_name),
                "sourceDetected": bool((refreshed.meta or {}).get("sourceDetected")) if refreshed else False}

    async def _source_has_open_items(self, source: str | None) -> bool:
        """Does this source have anything OPEN on the desk (tips, waiting armed
        plans, managed positions)? Gates the no-ticker follow-up review (D1)."""
        eng = self.engine
        name = source or "unknown"
        async with eng.sf() as session:
            n = (await session.execute(
                select(Signal.id).where(
                    Signal.source_name == name,
                    Signal.status.in_(("verified", "parked", "shadow", "proposed")))
                .limit(1))).first()
        if n is not None:
            return True
        runner = getattr(eng, "tip_runner", None)
        if runner is not None and any(
                (ap.plan.get("context") or {}).get("source") == name
                and ap.status in ("armed", "paused")
                for ap in runner._armed.values()):
            return True
        mgr = getattr(eng, "position_manager", None)
        if mgr is not None:
            with contextlib.suppress(Exception):
                for p in mgr.positions(status="open"):
                    if p.get("technique") == "tip" and f"source:{name}" in (p.get("tags") or []):
                        return True
        return False

    async def _reappraise_seen_again(self, signal_id: str) -> None:
        """A re-posted tip with a live waiting plan gets a fresh appraisal
        (ARM-GAPS D6) — the opinion updates in place (the armed link survives);
        it re-enters no lanes on its own."""
        eng = self.engine
        async with eng.sf() as session:
            row = await session.get(Signal, signal_id)
        if row is None:
            return
        policy = resolve_policy(eng.settings, row.source_name)
        try:
            from ..techniques.tip.analyst import analyze_tip
            opinion = await analyze_tip(eng, row, row.verification or {}, policy,
                                        client=self._analyst_client)
        except Exception:
            log.exception("seen-again reappraisal failed for %s", signal_id)
            return
        if not opinion:
            return
        async with eng.sf() as session:
            db_row = await session.get(Signal, signal_id)
            if db_row is None:
                return
            old = (db_row.extraction or {}).get("analyst") or {}
            merged = dict(opinion)
            if old.get("armedRunId"):
                merged["armedRunId"] = old["armedRunId"]
            db_row.extraction = {**(db_row.extraction or {}), "analyst": merged}
            await session.commit()
            row = db_row
        await eng.journal.append(
            ev.SIGNAL_ANALYZED,
            {"seenAgain": True,
             **{k: opinion.get(k) for k in ("verdict", "contract", "rationale")}},
            aggregate_type="signal", aggregate_id=signal_id)
        eng.bus.publish(topics.SIGNALS, signal_dict(row))

    async def _find_duplicate(self, key: str, window_hours: float) -> Signal | None:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=window_hours)
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(Signal).where(Signal.dedupe_key == key,
                                     Signal.created_at >= cutoff,
                                     Signal.status != "dismissed")
                .order_by(Signal.created_at.desc()).limit(6)
            )).scalars().all()
        # experiment rows are out-of-band (KNOWLEDGE plan §E): a REAL tip must
        # never dedupe onto a replayed historical sample
        for r in rows:
            if experiment_tag(r.extraction) is None:
                return r
        return None

    async def handle_extraction(self, content: RawContent, result: ExtractionResult,
                                *, source_text: str, intake=None,
                                experiment: str | None = None) -> list[dict]:
        """Grounding → dedupe → persistence → verification → proposal, per signal.
        Split out so tests can drive it with a canned ExtractionResult (no API).
        `intake` (optional) is the message's IntakeRun — per-signal verdicts are
        streamed onto it so the whole pipeline is watchable live.
        `experiment` (KNOWLEDGE plan §E) marks an out-of-band historical batch:
        the signal is FORCED onto the replayed path regardless of age (no books,
        no proposals, no arming), skips dedupe in both directions and is excluded
        from scorecards — evidence for review, never a trade."""
        eng = self.engine

        def istep(kind: str, text: str, **extra) -> None:
            if intake is not None:
                intake.step(kind, text, **extra)
        # auto-detect the source when the user didn't name one: the extractor
        # reads attribution out of the content itself (channel name, poster's
        # handle, newsletter masthead) and we match it to a known source
        if (content.source_name or "").strip().lower() in ("", "auto") :
            detected, matched = (await self._resolve_source(result.source_hint)
                                 if result.source_hint else ("unknown", False))
            async with eng.sf() as session:
                row = await session.get(RawContent, content.id)
                if row is not None:
                    row.source_name = detected
                    row.meta = {**(row.meta or {}),
                                "sourceDetected": bool(result.source_hint),
                                "sourceHint": result.source_hint,
                                "sourceMatchedExisting": matched}
                    await session.commit()
                    content = row
        # --- freshness: a tip whose content shows an old post date is REPLAYED
        # on history, never traded against today's price (decision 2026-08-28)
        max_age = float(eng.settings.get("techniques.tip.max_tip_age_hours", 72))
        stated_ms, age_hours = self._stated_age(result.stated_at, content.received_at)
        stale = age_hours is not None and age_hours > max_age

        out: list[dict] = []
        for sig in result.signals:
            policy = resolve_policy(eng.settings, content.source_name)
            grounding = ground_signal(sig, source_text)

            # --- dedupe: the same tip seen again attaches to the original.
            # A FOLLOW-UP ("sold 40%", "close") is never a duplicate of the
            # open it refers to (ARM-GAPS D1 — found when a close-action
            # message deduped onto the open and vanished) ---
            key = dedupe_key_for(content.source_name, sig)
            window = float(eng.settings.get("techniques.tip.dedupe_window_hours", 24))
            dup = (await self._find_duplicate(key, window)
                   if sig.action in ("open", "add", "") and experiment is None else None)
            if dup is not None:
                async with eng.sf() as session:
                    db_dup = await session.get(Signal, dup.id)
                    db_dup.seen_count = int(db_dup.seen_count or 1) + 1
                    db_dup.last_seen_at = dt.datetime.now(dt.timezone.utc)
                    await session.commit()
                    dup = db_dup
                await eng.journal.append(
                    ev.SIGNAL_SEEN_AGAIN,
                    {"ticker": dup.ticker, "source": content.source_name,
                     "seenCount": dup.seen_count, "contentId": content.id},
                    aggregate_type="signal", aggregate_id=dup.id)
                eng.bus.publish(topics.SIGNALS, signal_dict(dup))
                istep("signal", f"{dup.ticker}: seen again (×{dup.seen_count}) — attached "
                                "to the original tip, not a second one.")
                # ARM-GAPS D6: repeat conviction reaches the waiting plan —
                # annotate it (and optionally extend / re-appraise)
                runner = getattr(eng, "tip_runner", None)
                if runner is not None:
                    with contextlib.suppress(Exception):
                        await runner.note_seen_again(dup.id, int(dup.seen_count or 1))
                if (bool(eng.settings.get("techniques.tip.seen_again_reappraise", True))
                        and runner is not None and runner.live_run_for_signal(dup.id)
                        and (self._analyst_client is not None
                             or getattr(eng.config, "anthropic_api_key", ""))):
                    asyncio.create_task(self._reappraise_seen_again(dup.id),
                                        name=f"tip-reappraise-{dup.id[:8]}")
                out.append({"signal": signal_dict(dup), "duplicateOf": dup.id,
                            "proposal": None, "shadowOrder": None})
                continue

            row = Signal(
                id=new_id(),
                raw_content_id=content.id,
                source_name=content.source_name,
                ticker=sig.ticker.upper(),
                exchange_hint=sig.exchange_hint,
                direction=sig.direction,
                action=sig.action,
                instrument=sig.instrument,
                strike=sig.strike,
                premium=sig.premium,
                expiry=sig.expiry,
                dte_hint_days=sig.dte_hint_days,
                horizon_sessions=sig.horizon_sessions,
                catalyst=sig.catalyst,
                dedupe_key=key,
                entry_price=sig.entry_price,
                entry_type=sig.entry_type,
                target_price=sig.target_price or (sig.target_prices[0] if sig.target_prices else None),
                stop_price=sig.stop_price,
                timeframe=sig.timeframe,
                thesis_summary=sig.thesis_summary,
                confidence=sig.confidence,
                is_actionable=sig.is_actionable,
                extraction={"signal": sig.model_dump(), "grounding": grounding,
                            "sourceType": result.source_type,
                            "policy": policy.to_dict(),
                            **({"experiment": experiment} if experiment else {})},
            )
            async with eng.sf() as session:
                session.add(row)
                await session.commit()
            await eng.journal.append(
                ev.SIGNAL_EXTRACTED,
                {"ticker": row.ticker, "direction": row.direction,
                 "instrument": row.instrument, "confidence": row.confidence,
                 "grounded": grounding["passed"], "source": content.source_name},
                aggregate_type="signal", aggregate_id=row.id)

            # ensure_symbol only REQUESTS the feed; a freshly-seen ticker (not
            # in the universe, e.g. BOIL from a Discord alert) needs a beat for
            # its first Yahoo quote to land. Wait briefly so ticker_resolves
            # doesn't fatally fail a good tip on a cold symbol (found 2026-08-28,
            # image-only BOIL alert). Bounded; a truly bad ticker still fails.
            await eng.ensure_symbol(row.ticker)
            wait_s = float(eng.settings.get("techniques.tip.quote_wait_seconds", 6.0))
            deadline = _time.monotonic() + max(0.0, wait_s)
            while eng.quotes.get(row.ticker.upper()) is None and _time.monotonic() < deadline:
                await asyncio.sleep(0.25)
            if eng.quotes.get(row.ticker.upper()) is None:
                # a cold symbol can lose the race against the feed's poll cycle
                # (Yahoo backs off to ~20 s while Alpaca is connected) — force one
                # sweep instead of failing a good tip (the AMZN case, 2026-08-28)
                poll = (getattr(eng.feed, "poll_once", None)
                        or getattr(getattr(eng.feed, "yahoo", None), "poll_once", None))
                if poll is not None:
                    with contextlib.suppress(Exception):
                        await poll()
                    deadline = _time.monotonic() + 4.0
                    while (eng.quotes.get(row.ticker.upper()) is None
                           and _time.monotonic() < deadline):
                        await asyncio.sleep(0.25)
            verification = await verify_signal(sig, eng.quotes, eng.settings,
                                               grounding=grounding)
            # ARM-GAPS D1/D4: a follow-up action ("sold 40%", "I'm out", "move
            # the stop") deterministically reaches everything it invalidates
            # BEFORE any human or auto mode can act on a stale card
            if sig.action in ("trim", "close", "update_stop"):
                if eng.proposals is not None:
                    with contextlib.suppress(Exception):
                        n_exp = await eng.proposals.expire_for_followup(
                            source=content.source_name or "unknown", ticker=row.ticker,
                            reason=f"source posted '{sig.action}' before approval")
                        if n_exp:
                            istep("note", f"{row.ticker}: {n_exp} pending proposal(s) expired — "
                                          f"the source posted '{sig.action}'.")
                runner = getattr(eng, "tip_runner", None)
                if runner is not None:
                    with contextlib.suppress(Exception):
                        flagged = await runner.note_followup(
                            source=content.source_name or "unknown", ticker=row.ticker,
                            action=sig.action, signal_id=row.id)
                        if flagged:
                            istep("note", f"{row.ticker}: {len(flagged)} waiting armed plan(s) "
                                          f"flagged for review (source follow-up).")
            # flow context rides along (informational, never a check): does the
            # options tape agree with the tip?
            flow = getattr(eng, "flow_service", None)
            if flow is not None:
                try:
                    line = await flow.context_for(row.ticker, consumer="tip", ref_id=row.id)
                    if line:
                        verification["flowContext"] = line
                except Exception:  # pragma: no cover - context is best-effort
                    log.debug("flow context lookup failed for %s", row.ticker)
            # calendar context (advisory — Yahoo dates are unconfirmed): a tip
            # riding into earnings should say so where the human decides
            cal = getattr(eng, "calendar", None)
            if cal is not None:
                try:
                    days = await cal.days_to_earnings(row.ticker)
                    horizon = row.horizon_sessions or 10
                    if days is not None and days <= horizon + 4:
                        verification["calendarContext"] = (
                            f"earnings in ~{days} calendar day(s) — inside this tip's horizon "
                            "(dates are advisory, not confirmed)")
                except Exception:  # pragma: no cover - context is best-effort
                    log.debug("calendar lookup failed for %s", row.ticker)
            replay = None
            if stale or experiment is not None:
                # too old to trade (or an out-of-band experiment sample, which is
                # NEVER traded regardless of age) — replay it on history so the
                # content still teaches something (both books' counterfactuals,
                # no orders)
                verification["checks"].append({
                    "name": "fresh", "passed": False, "fatal": True,
                    "detail": (f"experiment batch {experiment} — replayed on history, "
                               "never traded"
                               if experiment is not None and not stale else
                               f"content is ~{age_hours:.0f}h old "
                               f"(max {max_age:.0f}h) — replayed on history, not traded")})
                verification["passed"] = False
                verification["park"] = False
                verification["shadow_only"] = False
                status = "replayed"
                replay = (await self._replay_signal(row, sig, stated_ms)
                          if stated_ms is not None
                          else {"ok": False, "note": "no stated time for a replay"})
            elif verification["passed"]:
                status = "verified"
            elif verification.get("park"):
                status = "parked"
            elif verification.get("shadow_only"):
                status = "shadow"
            else:
                status = "verification_failed"
            async with eng.sf() as session:
                db_row = await session.get(Signal, row.id)
                db_row.verification = verification
                db_row.status = status
                extra = {"statedAt": result.stated_at, "ageHours": age_hours}
                if replay is not None:
                    extra["replay"] = replay
                db_row.extraction = {**(db_row.extraction or {}), **extra}
                await session.commit()
                row = db_row
            kind = {"verified": ev.SIGNAL_VERIFIED, "shadow": ev.SIGNAL_VERIFIED,
                    "parked": ev.SIGNAL_PARKED, "replayed": ev.SIGNAL_REPLAYED,
                    }.get(status, ev.SIGNAL_VERIFICATION_FAILED)
            await eng.journal.append(kind, {**verification, "status": status},
                                     aggregate_type="signal", aggregate_id=row.id)
            eng.bus.publish(topics.SIGNALS, signal_dict(row))
            failed_checks = [f"{c['name']}: {c['detail'] or 'failed'}"
                             for c in verification.get("checks", []) if not c["passed"]]
            istep("signal",
                  f"{row.ticker} → {status.replace('_', ' ').upper()}"
                  + (f" — {'; '.join(failed_checks)}" if failed_checks else " — all checks passed"),
                  ticker=row.ticker, status=status)
            if intake is not None:
                await intake.checkpoint()

            proposal = None
            shadow_order = None
            if status in ("verified", "shadow"):
                # the shadow books ALWAYS trade a verified/shadow signal — the
                # per-source track record exists regardless of the human decision
                shadow_order = await self._shadow_execute(row, sig)
                async with eng.sf() as session:   # pick up the recorded expression
                    row = await session.get(Signal, row.id) or row
            if status in ("verified", "shadow", "parked"):
                # the tips analyst appraises the tip with market tools —
                # strictly advisory, fail-open (POC 2026-08-28)
                istep("note", f"Appraising {row.ticker} with market tools — its own "
                              "run starts now (watch it in the runs list).")
                try:
                    from ..techniques.tip.analyst import analyze_tip
                    opinion = await analyze_tip(eng, row, verification, policy,
                                                client=self._analyst_client,
                                                parent_run_id=(intake.id if intake else None))
                except Exception:                  # never block the pipeline
                    log.exception("tip analyst crashed for %s", row.id)
                    opinion = None
                if opinion is not None:
                    istep("handoff",
                          f"Appraisal done: {str(opinion.get('verdict', '?')).upper()}"
                          + (f" — {opinion.get('contractLabel') or opinion.get('contract_label') or opinion.get('contract') or ''}"),
                          runId=opinion.get("runId"), ticker=row.ticker)
                if opinion is not None:
                    async with eng.sf() as session:
                        db_row = await session.get(Signal, row.id)
                        db_row.extraction = {**(db_row.extraction or {}),
                                             "analyst": opinion}
                        await session.commit()
                        row = db_row
                    await eng.journal.append(
                        ev.SIGNAL_ANALYZED,
                        {k: opinion.get(k) for k in ("verdict", "contract",
                                                     "contractLabel", "limit_price",
                                                     "quantity", "rationale")},
                        aggregate_type="signal", aggregate_id=row.id)
                    eng.bus.publish(topics.SIGNALS, signal_dict(row))
            # ---- lane decision (ARM-PLAN P1): a take that says at_level ARMS a
            # plan waiting for the analyst's price instead of proposing at market
            armed = None
            op = (row.extraction or {}).get("analyst") or {}
            wants_arm = (op.get("verdict") == "take" and op.get("entry_mode") == "at_level"
                         and status in ("verified", "parked")
                         and getattr(eng, "tip_runner", None) is not None)
            if wants_arm:
                try:
                    armed = await eng.tip_runner.arm_from_analyst(row, op, policy)
                    async with eng.sf() as session:      # link the arm onto the opinion
                        db_row = await session.get(Signal, row.id)
                        db_row.extraction = {**(db_row.extraction or {}),
                                             "analyst": {**op, "armedRunId": armed.get("runId")}}
                        # ...and onto the analyst RUN itself, so its header can
                        # link the plan it created (ARM-GAPS F3)
                        if op.get("runId"):
                            from ..models import TipAnalystRun
                            arun = await session.get(TipAnalystRun, op["runId"])
                            if arun is not None:
                                arun.opinion = {**(arun.opinion or {}),
                                                "armedRunId": armed.get("runId")}
                        await session.commit()
                        row = db_row
                    armed_mode = (armed.get("config") or {}).get("mode") or armed.get("mode")
                    await eng.journal.append(
                        ev.TIP_LANE_DECIDED,
                        {"signalId": row.id, "lane": "arm", "mode": armed_mode,
                         "armedRunId": armed.get("runId"),
                         "entryLevel": op.get("entry_level")},
                        aggregate_type="signal", aggregate_id=row.id)
                    istep("handoff",
                          f"{row.ticker}: analyst chose AT-LEVEL — armed a plan waiting for "
                          f"{op.get('entry_level') or row.entry_price} "
                          f"({armed_mode} mode, run {str(armed.get('runId'))[:8]}). "
                          f"No tip-time proposal.", ticker=row.ticker,
                          armedRunId=armed.get("runId"))
                    eng.bus.publish(topics.SIGNALS, signal_dict(row))
                except Exception as exc:
                    log.exception("analyst arm failed for %s — falling back to the proposal lane",
                                  row.id)
                    istep("note", f"{row.ticker}: at-level arm failed ({exc}) — "
                                  "falling back to the proposal lane.")
                    armed = None
            if status == "verified" and armed is None:
                # proposals need an explicit call (status "shadow" never proposes)
                if (eng.proposals is not None and policy.mode in ("proposal", "auto")
                        and policy.meets_conviction(sig.confidence)):
                    proposal = await eng.proposals.create_from_signal(row, sig, verification)
                    if proposal is not None and op:
                        await eng.journal.append(
                            ev.TIP_LANE_DECIDED,
                            {"signalId": row.id, "lane": "proposal",
                             "entryMode": op.get("entry_mode") or "now"},
                            aggregate_type="signal", aggregate_id=row.id)
                # full auto: a "take" from the analyst self-approves the proposal —
                # same path a human click takes (RiskGate inside OrderManager.place).
                # A live portfolio additionally needs techniques.tip.allow_live_auto.
                if proposal is not None and policy.mode == "auto":
                    verdict = ((row.extraction or {}).get("analyst") or {}).get("verdict")
                    pf = eng.positions.portfolio(proposal["portfolioId"]) or {}
                    live_ok = (pf.get("kind") != "live"
                               or bool(eng.settings.get("techniques.tip.allow_live_auto", False)))
                    if verdict not in (None, "take"):
                        log.info("auto mode: analyst said %r — leaving proposal %s for the human",
                                 verdict, proposal["id"])
                    elif not live_ok:
                        log.warning("auto mode: live portfolio without allow_live_auto — "
                                    "leaving proposal %s pending", proposal["id"])
                    else:
                        try:
                            decided = await eng.proposals.approve(proposal["id"], via="auto")
                            proposal = decided["proposal"]
                        except Exception:
                            log.exception("auto-approve failed for proposal %s", proposal["id"])
            out.append({"signal": signal_dict(row), "proposal": proposal,
                        "armed": armed, "shadowOrder": shadow_order})
        return out

    @staticmethod
    def _stated_age(stated_at: str | None,
                    received: dt.datetime | None) -> tuple[int | None, float | None]:
        """(stated_at as epoch ms, age in hours at receipt). (None, None) when the
        content shows no parseable date. Naive timestamps are assumed ET; a bare
        date is treated as noon ET — generous in the tip's favour."""
        if not stated_at:
            return None, None
        try:
            s = stated_at.strip()
            if len(s) == 10:                      # YYYY-MM-DD
                parsed = dt.datetime.fromisoformat(s + "T12:00")
            else:
                parsed = dt.datetime.fromisoformat(s)
        except ValueError:
            return None, None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone(dt.timedelta(hours=-4)))
        ref = received or dt.datetime.now(dt.timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=dt.timezone.utc)
        age = (ref - parsed).total_seconds() / 3600
        return int(parsed.timestamp() * 1000), age

    async def _replay_signal(self, row: Signal, sig: TradeSignal,
                             stated_ms: int | None) -> dict:
        """Run the stale tip's history replay (techniques/tip/replay.py)."""
        if stated_ms is None:
            return {"ok": False, "note": "no parseable tip time"}
        from ..techniques.tip.replay import replay_tip
        policy = resolve_policy(self.engine.settings, row.source_name)
        try:
            kwargs = {}
            if self._replay_fetch is not None:            # test injection
                kwargs["fetch"] = self._replay_fetch
            return await replay_tip(
                symbol=row.ticker, direction=row.direction, stated_at_ms=stated_ms,
                tip_entry=sig.entry_price, tip_stop=sig.stop_price,
                tip_targets=tuple(sig.target_prices or
                                  ([sig.target_price] if sig.target_price else [])),
                horizon_sessions=sig.horizon_sessions or policy.horizon_sessions,
                source=row.source_name, thesis=sig.thesis_summary, **kwargs)
        except Exception as exc:                          # replay is best-effort
            log.exception("replay failed for signal %s", row.id)
            return {"ok": False, "note": f"replay failed: {exc}"}

    async def shadow_portfolio(self, source: str, book: str) -> dict:
        """The per-source shadow account for one BOOK: 'immediate' (buy at tip
        time — the source's raw quality) or 'armed' (wait for the level, managed
        exits — what the app actually does). Two books per source so the
        scorecard can compare the strategies without blending their P&L
        (user decision 2026-08-27). Pre-split rows (book NULL) are immediate."""
        eng = self.engine

        def match(p: dict) -> bool:
            if p["kind"] != "shadow" or p.get("sourceName") != source:
                return False
            b = p.get("book")
            return b == book or (b is None and book == "immediate")

        shadow = next((p for p in eng.positions.portfolios() if match(p)), None)
        if shadow is None:
            name = f"Shadow: {source}" + (" (armed)" if book == "armed" else "")
            row = PortfolioRow(id=new_id(), name=name, kind="shadow",
                               starting_cash=10_000.0, cash=10_000.0,
                               source_name=source, book=book)
            async with eng.sf() as session:
                session.add(row)
                await session.commit()
            eng.positions.register_portfolio(row)
            shadow = eng.positions.portfolio(row.id)
        return shadow

    async def _shadow_execute(self, signal_row: Signal, sig: TradeSignal) -> dict | None:
        """Every verified signal also trades in the source's IMMEDIATE shadow
        book, so the 'what if we'd bought the moment they spoke' record exists
        regardless of the human decision (the armed book is the tip runner's).

        Phase B (BUILD-PLAN T1): the per-tip vehicle rule — a tip that names an
        option buys the CONTRACT (buy-and-hold counterfactual: no bracket,
        expiry settlement closes it); anything else buys shares with the tip's
        bracket as before. A failed pick falls back to shares, recorded on the
        signal — the book never silently skips a tip."""
        import math

        from ..orders import BracketSpec, OrderIntent
        from ..techniques.tip.express import pick_tip_contract, tip_is_option

        eng = self.engine
        source = signal_row.source_name or "unknown"
        shadow = await self.shadow_portfolio(source, "immediate")
        policy = resolve_policy(eng.settings, source)
        expression: dict = {"vehicle": "shares"}

        try:
            # stated 2-leg spread (ARM-PLAN P5): the immediate book expresses it
            # as the defined-risk pair, leg-sequenced like the real lane
            sig_legs = ((signal_row.extraction or {}).get("signal") or {}).get("legs") or []
            if len(sig_legs) == 2:
                from ..techniques.tip.express import pick_spread
                pick = await pick_spread(
                    eng, symbol=sig.ticker.upper(), legs=sig_legs,
                    expiry=signal_row.expiry,
                    dte_min=policy.dte_min, dte_max=policy.dte_max)
                if pick.get("available"):
                    from ..techniques.tip.lifecycle import open_spread
                    for leg in pick["legs"]:
                        await eng.ensure_symbol(leg["symbol"])
                    net, width = float(pick["net"]), float(pick["width"])
                    max_loss = net if net > 0 else max(width - abs(net), 0.01)
                    qty = max(1, int(policy.budget_per_tip // (max_loss * 100)))
                    expression.update({"vehicle": "spread", "qty": qty, "net": net,
                                       "legs": [l["symbol"] for l in pick["legs"]],
                                       "warnings": pick.get("warnings") or []})
                    await self._record_expression(signal_row.id, expression)
                    try:
                        pos = await open_spread(
                            eng, portfolio_id=shadow["id"],
                            underlying=sig.ticker.upper(), direction=sig.direction,
                            legs=pick["legs"], qty=qty, source=source,
                            signal_id=signal_row.id)
                        return {"positionId": pos["id"], "spread": True}
                    except Exception as exc:
                        expression["fallback"] = f"spread shadow failed: {exc}"
                        await self._record_expression(signal_row.id, expression)
                        # journaled, never swallowed (ARM-GAPS B3): the scorecard
                        # reader must see the book expressed a DIFFERENT vehicle
                        with contextlib.suppress(Exception):
                            await eng.journal.append(
                                ev.TIP_LANE_DECIDED,
                                {"signalId": signal_row.id, "lane": "shadow",
                                 "downgrade": f"spread -> single-leg: {exc}"},
                                aggregate_type="signal", aggregate_id=signal_row.id)
                        # falls through to the single-leg expression below
                else:
                    expression["fallback"] = f"spread: {pick.get('error')}"
            if tip_is_option(signal_row):
                targets = ((signal_row.extraction or {}).get("signal") or {}).get("target_prices") \
                    or ([sig.target_price] if sig.target_price else [])
                cap = float(targets[-1]) if targets else None
                pick = await pick_tip_contract(
                    eng, symbol=sig.ticker.upper(), direction=sig.direction,
                    dte_min=policy.dte_min, dte_max=policy.dte_max,
                    strike=signal_row.strike, expiry=signal_row.expiry,
                    stated_min_dte=int(eng.settings.get("techniques.tip.entry_cutoff_dte", 2)),
                    max_strike=cap if sig.direction == "long" else None,
                    min_strike=cap if sig.direction == "short" else None)
                ask = float(pick.get("ask") or pick.get("mid") or 0) if pick.get("available") else 0.0
                if pick.get("available") and pick.get("symbol") and ask > 0:
                    from ..execution.sizing import size_by_budget
                    contracts = size_by_budget(policy.budget_per_tip, ask,
                                               max_units=1_000, multiplier=100.0)
                    if contracts < 1:
                        contracts = 1     # one contract slightly over budget beats skipping the tip
                        expression["note"] = (f"premium ${ask * 100:,.0f} exceeds the "
                                              f"${policy.budget_per_tip:,.0f} budget — 1 contract anyway")
                    occ_sym = str(pick["symbol"])
                    await eng.ensure_symbol(occ_sym)      # track + quotes so sim can fill
                    expression.update({"vehicle": "option", "contract": occ_sym,
                                       "display": pick.get("display"), "ask": ask,
                                       "contracts": contracts,
                                       "warnings": pick.get("warnings") or []})
                    await self._record_expression(signal_row.id, expression)
                    return await eng.orders.place(OrderIntent(
                        portfolio_id=shadow["id"], symbol=occ_sym, sec_type="OPT",
                        side="BUY", qty=contracts, order_type="MKT",
                        source="auto", signal_id=signal_row.id,
                        technique_id="tip", tags=[f"source:{source}"]))
                expression["fallback"] = pick.get("error") or "no usable contract"

            if sig.direction == "short":
                # shorts are puts only (never-listed share shorting) — a short tip
                # with no usable contract cannot be expressed; record that honestly
                expression["note"] = "short tip needs a put — " + str(
                    expression.get("fallback") or "no chain") + "; not expressed"
                await self._record_expression(signal_row.id, expression)
                return None

            symbol = sig.ticker.upper()
            quote = eng.quotes.get(symbol)
            ref = (quote.ask if quote and quote.ask > 0 else None) or sig.entry_price
            if not ref or ref <= 0:
                expression["note"] = "no reference price — nothing bought"
                await self._record_expression(signal_row.id, expression)
                return None
            # shares are sized by the SAME per-tip budget as options — the two
            # books/vehicles must be dollar-comparable on the scorecard
            # (decision 2026-08-28; was 5% of equity, which dwarfed option tips)
            qty = max(1, math.floor(policy.budget_per_tip / ref))
            bracket = None
            if sig.target_price or sig.stop_price:
                bracket = BracketSpec(take_profit=sig.target_price, stop_loss=sig.stop_price)
            # a bracket-less share position must still die: the morning loop
            # closes it once the tip's thesis window has passed
            from ..techniques.tip.horizon import add_sessions, hold_sessions_cap, tip_expiry
            today = dt.datetime.now(dt.timezone.utc).date()
            cap = hold_sessions_cap(
                expiry=tip_expiry(signal_row.expiry, signal_row.dte_hint_days, today),
                today=today, fallback=policy.horizon_sessions)
            expression.update({"qty": qty, "entryRef": round(float(ref), 4),
                               "closeAfter": add_sessions(today, cap).isoformat()})
            await self._record_expression(signal_row.id, expression)
            return await eng.orders.place(OrderIntent(
                portfolio_id=shadow["id"], symbol=symbol,
                side="BUY" if sig.direction == "long" else "SELL",
                qty=qty, order_type="MKT", bracket=bracket,
                source="auto", signal_id=signal_row.id,
                technique_id="tip", tags=[f"source:{source}"]))
        except Exception:
            log.exception("shadow execution failed for signal %s", signal_row.id)
            return None

    async def _record_expression(self, signal_id: str, expression: dict) -> None:
        """How the immediate book expressed this tip (vehicle, contract,
        fallback reason) — kept on the signal so the scorecard and the UI can
        show it; no new journal kind (the order path journals the money)."""
        async with self.engine.sf() as session:
            row = await session.get(Signal, signal_id)
            if row is not None:
                row.extraction = {**(row.extraction or {}), "shadowExpression": expression}
                await session.commit()

    async def _set_content_status(self, content_id: str, status: str) -> None:
        async with self.engine.sf() as session:
            row = await session.get(RawContent, content_id)
            if row is not None:
                row.status = status
                await session.commit()

    # ------------------------------------------------------------- tip plans
    async def build_tip_plan_for(self, signal_id: str, *,
                                 entry_override: float | None = None,
                                 force_level_touch: bool = False,
                                 scale_ins: list[dict] | None = None,
                                 guards: list[dict] | None = None) -> dict:
        """Signal → the tip SessionPlan the runner will arm (preview; no side
        effects). Verified and parked signals both plan — parked is exactly the
        case where the plan waits at the level. `entry_override` is the
        analyst's chosen level (ARM-PLAN P1); `force_level_touch` makes an
        analyst-armed tip wait for the level even on a tip_time source."""

        from ..marketstructure.history import fetch_window
        from ..techniques.tip import build_tip_plan

        eng = self.engine
        async with eng.sf() as session:
            row = await session.get(Signal, signal_id)
        if row is None:
            raise ValueError("unknown signal")
        if row.status not in ("verified", "parked", "proposed"):
            raise ValueError(f"signal is {row.status} — only verified/parked tips plan")
        policy = resolve_policy(eng.settings, row.source_name)
        # an options tip dies at its contract's expiry: the wait window is capped
        # by (expiry - entry_cutoff_dte), never just the policy horizon
        from ..techniques.tip.horizon import effective_wait_sessions, tip_expiry
        today = dt.datetime.now(dt.timezone.utc).date()
        expiry = tip_expiry(row.expiry, row.dte_hint_days,
                            (row.created_at.date() if row.created_at else today))
        wait = effective_wait_sessions(
            policy_horizon=policy.horizon_sessions, tip_horizon=row.horizon_sessions,
            expiry=expiry, today=today,
            entry_cutoff_dte=int(eng.settings.get("techniques.tip.entry_cutoff_dte", 2)))
        if wait <= 0:
            raise ValueError(
                f"too late — the tip's contract expires {expiry} and the entry cutoff "
                f"({eng.settings.get('techniques.tip.entry_cutoff_dte', 2)}d before expiry) has passed")
        now_ms = int(_time.time() * 1000)
        bars = await fetch_window(row.ticker, "5m", now_ms - 10 * 86_400_000, now_ms)
        quote = eng.quotes.get(row.ticker)
        ref = (quote.last if quote and quote.last > 0 else None) or (bars[-1].close if bars else None)
        if not ref:
            raise ValueError(f"no price for {row.ticker}")
        extraction_sig = (row.extraction or {}).get("signal") or {}
        # scale-in / zone entries (ARM-PLAN P3): an explicit ladder from the
        # caller (the analyst) wins; else the tip's own stated ladder; else a
        # stated entry ZONE becomes a 2-rung ladder (near edge first)
        if scale_ins is None:
            stated_ladder = extraction_sig.get("scale_in") or []
            if stated_ladder:
                scale_ins = stated_ladder
            else:
                lo = extraction_sig.get("entry_zone_low")
                hi = extraction_sig.get("entry_zone_high")
                if lo and hi and float(lo) < float(hi):
                    near, far = ((float(hi), float(lo)) if row.direction == "long"
                                 else (float(lo), float(hi)))
                    scale_ins = [{"price": near, "fraction": 0.5},
                                 {"price": far, "fraction": 0.5}]
        plan = build_tip_plan(
            symbol=row.ticker,
            direction=row.direction,
            reference_price=float(ref),
            bars=bars,
            as_of_ms=now_ms,
            entry_mode="level_touch" if force_level_touch else policy.entry,
            tip_entry=(float(entry_override) if entry_override else row.entry_price),
            tip_stop=row.stop_price,
            tip_targets=extraction_sig.get("target_prices")
            or ([row.target_price] if row.target_price else []),
            horizon_sessions=wait,
            stop_atr_mult=float(eng.settings.get("techniques.tip.stop_atr_mult", 1.0)),
            target_r=tuple(eng.settings.get("techniques.tip.target_r") or (1.5, 3.0)),
            signal_id=row.id,
            source=row.source_name,
            thesis=row.thesis_summary or "",
            instrument_hint=row.instrument,
            scale_ins=scale_ins,
            guards=(guards if guards is not None
                    else extraction_sig.get("entry_conditions") or None),
        )
        return plan.to_dict()

    # ------------------------------------------------------------- queries
    async def list_signals(self, limit: int = 100) -> list[dict]:
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(Signal).where(Signal.status != "dismissed")
                .order_by(Signal.created_at.desc()).limit(limit)
            )).scalars().all()
        return [signal_dict(r) for r in rows]

    async def dismiss_signals(self, ids: list[str]) -> int:
        """User-deleted tips (single or bulk): SOFT delete — status becomes
        `dismissed` (rows stay for the audit trail; the journal is append-only),
        the tip leaves every list and the dedupe window, any live armed plan
        for it disarms, and any pending proposal expires."""
        from ..models import Proposal
        eng = self.engine
        runner = getattr(eng, "tip_runner", None)
        n = 0
        for sid in ids:
            async with eng.sf() as session:
                row = await session.get(Signal, sid)
                if row is None or row.status == "dismissed":
                    continue
                prev = row.status
                row.status = "dismissed"
                await session.commit()
                row_dict = signal_dict(row)
            n += 1
            if runner is not None:
                with contextlib.suppress(Exception):
                    rid = runner.live_run_for_signal(sid)
                    if rid:
                        await runner.disarm(rid, reason="tip deleted by the user")
            if eng.proposals is not None:
                with contextlib.suppress(Exception):
                    async with eng.sf() as session:
                        pending = (await session.execute(
                            select(Proposal).where(Proposal.signal_id == sid,
                                                   Proposal.status == "pending"))).scalars().all()
                        for p in pending:
                            p.status = "expired"
                            p.decided_at = dt.datetime.now(dt.timezone.utc)
                            p.context = {**(p.context or {}),
                                         "expiredReason": "tip deleted by the user"}
                        await session.commit()
            await eng.journal.append(ev.SIGNAL_DISMISSED,
                                     {"ticker": row_dict.get("ticker"),
                                      "source": row_dict.get("sourceName"),
                                      "was": prev},
                                     aggregate_type="signal", aggregate_id=sid)
            eng.bus.publish(topics.SIGNALS, row_dict)
        return n

    async def content_bundle(self, content_id: str) -> dict:
        """Everything about one Extract & verify by its id — the raw content
        (text/transcript, source detection meta) plus every signal it produced
        with full extraction + verification. This is the record behind the
        UI's copyable #id: quote the id, pull this, discuss the run."""
        async with self.engine.sf() as session:
            row = await session.get(RawContent, content_id)
            if row is None:
                raise KeyError(f"content {content_id} not found")
            sigs = (await session.execute(
                select(Signal).where(Signal.raw_content_id == content_id)
                .order_by(Signal.created_at))).scalars().all()
        return {
            "id": row.id, "sourceType": row.source_type, "sourceName": row.source_name,
            "sender": row.sender, "subject": row.subject, "status": row.status,
            "receivedAt": row.received_at.isoformat() if row.received_at else None,
            "bodyText": row.body_text, "meta": row.meta or {},
            "hasImage": bool((row.meta or {}).get("imageAssetId")),
            "signals": [signal_dict(s) for s in sigs],
        }

    async def list_content(self, limit: int = 50) -> list[dict]:
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(RawContent).order_by(RawContent.received_at.desc()).limit(limit)
            )).scalars().all()
        return [{
            "id": r.id, "sourceType": r.source_type, "sourceName": r.source_name,
            "sender": r.sender, "subject": r.subject, "status": r.status,
            "receivedAt": r.received_at.isoformat() if r.received_at else None,
            "preview": (r.body_text or "")[:280],
            "hasImage": bool((r.meta or {}).get("imageAssetId")),
        } for r in rows]

    async def source_scorecards(self) -> list[dict]:
        """Per-source track record, TWO books side by side (user decision
        2026-08-27): 'immediate' = buy the moment the tip verified (the
        source's raw quality); 'armed' = wait for the level with managed exits
        (what the app actually does). The comparison is what decides whether a
        source has EARNED tip-time entry — if immediate beats armed for a
        source, their tips run away and waiting costs money."""
        eng = self.engine
        async with eng.sf() as session:
            rows = (await session.execute(select(Signal))).scalars().all()
        by_source: dict[str, dict] = {}

        def card_for(src: str) -> dict:
            return by_source.setdefault(src, {
                "source": src, "signals": 0, "verified": 0, "parked": 0,
                "failed": 0, "expiredUnfilled": 0, "seenAgain": 0, "lastSignalAt": None,
                "books": {"immediate": {}, "armed": {}}})

        for r in rows:
            if experiment_tag(r.extraction) is not None:
                continue                # out-of-band experiment rows never score a source
            card = card_for(r.source_name or "unknown")
            card["signals"] += 1
            card["seenAgain"] += max(0, int(r.seen_count or 1) - 1)
            if r.status in ("verified", "proposed", "shadow"):
                card["verified"] += 1      # shadow = verified for the books (implied call)
            elif r.status == "parked":
                card["parked"] += 1
            elif r.status == "verification_failed":
                card["failed"] += 1
            elif r.status == "expired":
                card["expiredUnfilled"] += 1      # the level never came before the tip died
            ts = r.created_at.isoformat() if r.created_at else None
            if ts and (card["lastSignalAt"] is None or ts > card["lastSignalAt"]):
                card["lastSignalAt"] = ts

        for p in eng.positions.portfolios():
            if p.get("kind") != "shadow" or not p.get("sourceName"):
                continue
            book = p.get("book") or "immediate"
            if book not in ("immediate", "armed"):
                continue
            card = card_for(p["sourceName"])
            try:
                equity = await eng.positions.equity(p["id"])
            except Exception:  # pragma: no cover - portfolio math hiccup
                equity = None
            start = p.get("startingCash") or 10_000.0
            card["books"][book] = {
                "portfolioId": p["id"], "equity": equity,
                "pnl": (equity - start) if equity is not None else None,
                "pnlPct": ((equity - start) / start * 100) if equity is not None and start else None,
            }

        # armed-book activity: managed positions opened by the tip runner, per source tag
        mgr = getattr(eng, "position_manager", None)
        if mgr is not None:
            with contextlib.suppress(Exception):
                for pos in mgr.positions():
                    if pos.get("technique") != "tip":
                        continue
                    src = next((t.split(":", 1)[1] for t in (pos.get("tags") or [])
                                if t.startswith("source:")), None)
                    if not src:
                        continue
                    book = card_for(src)["books"]["armed"]
                    book["positions"] = int(book.get("positions") or 0) + 1
                    if pos.get("status") == "closed":
                        book["closed"] = int(book.get("closed") or 0) + 1
                        book["realizedPnl"] = round(
                            float(book.get("realizedPnl") or 0) + float(pos.get("realizedPnl") or 0), 2)

        # R-based armed-book outcomes (BUILD-PLAN T3): every tip run's trigger
        # outcome, grouped by the run's source. Expectancy counts an unfilled
        # (never-triggered) tip as 0R — it measures the strategy per tip taken.
        from ..models import TechniqueOutcome, TechniqueRun
        async with eng.sf() as session:
            runs = (await session.execute(
                select(TechniqueRun.id, TechniqueRun.config)
                .where(TechniqueRun.technique == "tip"))).all()
        run_src = {r.id: ((r.config or {}).get("source") or "unknown") for r in runs}
        if run_src:
            async with eng.sf() as session:
                outs = (await session.execute(
                    select(TechniqueOutcome)
                    .where(TechniqueOutcome.run_id.in_(list(run_src))))).scalars().all()
            per: dict[str, dict] = {}
            for o in outs:
                if not (o.plan_source or "").startswith("trigger:") or o.status != "scored":
                    continue
                st = per.setdefault(run_src.get(o.run_id) or "unknown",
                                    {"n": 0, "fired": 0, "wins": 0, "sumR": 0.0, "never": 0})
                st["n"] += 1
                if o.r_multiple is not None:
                    st["fired"] += 1
                    st["sumR"] += float(o.r_multiple)
                    if o.r_multiple > 0:
                        st["wins"] += 1
                else:
                    st["never"] += 1
            for src, st in per.items():
                card_for(src)["books"]["armed"]["outcomes"] = {
                    "scored": st["n"], "fired": st["fired"], "neverTriggered": st["never"],
                    "winRate": round(st["wins"] / st["fired"], 3) if st["fired"] else None,
                    "avgR": round(st["sumR"] / st["fired"], 3) if st["fired"] else None,
                    "expectancyR": round(st["sumR"] / st["n"], 3) if st["n"] else None,
                }

        cards = list(by_source.values())
        min_n = int(eng.settings.get("techniques.tip.scorecard_min_n", 20))
        for c in cards:
            policy = resolve_policy(eng.settings, c["source"])
            c["policy"] = policy.to_dict()
            # back-compat fields (UI + older callers): the immediate book
            imm = c["books"]["immediate"]
            c["shadowPortfolioId"] = imm.get("portfolioId")
            c["shadowEquity"] = imm.get("equity")
            c["shadowPnl"] = imm.get("pnl")
            c["shadowPnlPct"] = imm.get("pnlPct")
            # the bar judges the ARMED book — real money would trade the armed
            # way. Once enough outcomes are SCORED the bar flips on expectancy
            # in R (the honest per-tip measure); until then, book P&L in $.
            oc = c["books"]["armed"].get("outcomes") or {}
            armed_pnl = c["books"]["armed"].get("pnl")
            if (oc.get("scored") or 0) >= min_n:
                c["barCleared"] = bool((oc.get("expectancyR") or 0) > 0)
                c["barBasis"] = "expectancyR"
            else:
                c["barCleared"] = bool(c["verified"] >= min_n and armed_pnl is not None and armed_pnl > 0)
                c["barBasis"] = "pnl"
            # tip-time entry is EARNED when immediate demonstrably beats armed
            imm_pnl = imm.get("pnl")
            c["tipTimeEarned"] = bool(
                c["verified"] >= min_n and imm_pnl is not None and armed_pnl is not None
                and imm_pnl > 0 and imm_pnl > armed_pnl)
        cards.sort(key=lambda c: -(c.get("signals") or 0))
        return cards


async def attach_signal_layer(engine) -> None:
    """Called from the FastAPI lifespan after the engine starts."""
    from ..approvals.proposals import ProposalService

    if getattr(engine, "signals_service", None) is not None:
        return
    extractor = Extractor(engine.config.anthropic_api_key, engine.config.extraction_model)
    engine.signals_service = SignalService(engine, extractor)
    engine.proposals = ProposalService(engine)
    engine.proposals.start()
    # rescue any mirrored images that only have (expiring) CDN links
    engine.signals_service.start_media_catchup()
