"""Signal ingestion, signals, and proposals routes.

NOTE: no `from __future__ import annotations` — see api/app.py.
"""
from fastapi import HTTPException, Request
from pydantic import BaseModel


def build_signal_routes(app, eng, auth, config) -> None:

    # --- inbound email webhook (Cloudflare Email Worker posts here) ----------
    @app.post("/api/ingest/email")
    async def ingest_email(request: Request):
        # W1: HMAC beats the static key when configured — the signature covers
        # the exact body, so a leaked URL alone can inject nothing
        if config.ingest_hmac_secret:
            import hashlib
            import hmac as _hmac
            import json as _json
            raw = await request.body()
            want = _hmac.new(config.ingest_hmac_secret.encode(), raw,
                             hashlib.sha256).hexdigest()
            got = request.headers.get("x-zargar-signature", "")
            if not got or not _hmac.compare_digest(got.lower(), want):
                raise HTTPException(status_code=401, detail="bad or missing signature")
            try:
                payload = _json.loads(raw)
            except ValueError:
                raise HTTPException(status_code=400, detail="body is not JSON")
        else:
            if config.ingest_key:
                if request.headers.get("x-zargar-ingest-key", "") != config.ingest_key:
                    raise HTTPException(status_code=401, detail="bad ingest key")
            payload = await request.json()
        return await eng.signals_service.ingest_email(payload)

    class ManualIngest(BaseModel):
        text: str = ""
        source_name: str = "manual"
        subject: str = ""
        imageDataUrl: str | None = None   # screenshot of the user's own client

    @app.post("/api/ingest/manual", dependencies=[auth])
    async def ingest_manual(body: ManualIngest):
        image = None
        media_type = "image/png"
        if body.imageDataUrl:
            from ..technique.llm import decode_data_url
            try:
                image, media_type = decode_data_url(body.imageDataUrl)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        if not body.text.strip() and image is None:
            raise HTTPException(status_code=400, detail="text or imageDataUrl required")
        return await eng.signals_service.ingest_manual(
            body.text, source_name=body.source_name, subject=body.subject,
            image=image, image_media_type=media_type)

    @app.get("/api/signals/sources", dependencies=[auth])
    async def source_scorecards():
        return await eng.signals_service.source_scorecards()

    @app.get("/api/signals/source-names", dependencies=[auth])
    async def source_names():
        return await eng.signals_service.known_sources()

    @app.get("/api/signals/{sid}/runs", dependencies=[auth])
    async def signal_runs(sid: str):
        """The tip's plan runs + its LIVE armed state (ARM-GAPS F2)."""
        runner = getattr(eng, "tip_runner", None)
        if runner is None:
            return {"runs": [], "armed": None}
        runs = await runner.runs_for_signal(sid)
        rid = runner.live_run_for_signal(sid)
        armed = runner.detail(rid) if rid else None
        return {"runs": runs, "armed": armed}

    @app.get("/api/signals/{sid}/plan", dependencies=[auth])
    async def signal_tip_plan(sid: str):
        try:
            return await eng.signals_service.build_tip_plan_for(sid)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc))

    class ArmTipBody(BaseModel):
        portfolioId: str | None = None
        mode: str | None = None          # alert | proposal | auto
        instrument: str | None = None    # shares (v1 default)
        riskPct: float | None = None
        qty: float | None = None
        dailyLossLimit: float | None = None
        allowLive: bool = False

    @app.post("/api/signals/shadow-arm", dependencies=[auth])
    async def shadow_arm_now():
        """Run the armed-book morning loop on demand (it also runs on the
        scheduler at techniques.tip.shadow_arm_at)."""
        runner = getattr(eng, "tip_runner", None)
        if runner is None:
            raise HTTPException(status_code=503, detail="tip runner not attached")
        return await runner.shadow_arm_open_tips()

    @app.post("/api/signals/{sid}/arm", dependencies=[auth])
    async def arm_tip(sid: str, body: ArmTipBody | None = None):
        runner = getattr(eng, "tip_runner", None)
        if runner is None:
            raise HTTPException(status_code=503, detail="tip runner not attached")
        body = body or ArmTipBody()
        cfg = {k: v for k, v in {
            "portfolioId": body.portfolioId, "mode": body.mode, "instrument": body.instrument,
            "riskPct": body.riskPct, "qty": body.qty, "dailyLossLimit": body.dailyLossLimit,
            "allowLive": body.allowLive}.items() if v is not None}
        try:
            return await runner.arm_signal(sid, cfg or None)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # --- signals / content ----------------------------------------------------
    @app.get("/api/signals", dependencies=[auth])
    async def list_signals(limit: int = 100):
        return await eng.signals_service.list_signals(limit)

    class DismissBody(BaseModel):
        ids: list[str]

    @app.post("/api/signals/dismiss", dependencies=[auth])
    async def dismiss_signals(body: DismissBody):
        """Delete tips (bulk): soft-dismiss — the rows stay for the audit trail
        but leave every list, any waiting armed plan disarms and any pending
        proposal expires."""
        n = await eng.signals_service.dismiss_signals(body.ids)
        return {"dismissed": n}

    @app.delete("/api/signals/{sid}", dependencies=[auth])
    async def delete_signal(sid: str):
        n = await eng.signals_service.dismiss_signals([sid])
        if not n:
            raise HTTPException(status_code=404, detail="signal not found (or already dismissed)")
        return {"dismissed": n}

    @app.get("/api/content", dependencies=[auth])
    async def list_content(limit: int = 50):
        return await eng.signals_service.list_content(limit)

    @app.get("/api/content/{cid}", dependencies=[auth])
    async def content_bundle(cid: str):
        """The full record behind one Extract & verify (the UI's copyable #id)."""
        try:
            return await eng.signals_service.content_bundle(cid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    # --- discord intake: catalog (from the gateway) + watchlist (from the UI) --
    @app.post("/api/tip/discord/catalog", dependencies=[auth])
    async def discord_report_catalog(request: Request):
        """The gateway reports the DMs/channels it can see so the UI can offer them."""
        eng.signals_service.discord_set_catalog(await request.json())
        return {"ok": True}

    @app.get("/api/tip/discord/catalog", dependencies=[auth])
    async def discord_catalog():
        return eng.signals_service.discord_get_catalog()

    @app.get("/api/tip/discord/watch", dependencies=[auth])
    async def discord_watch():
        """The allowlist the gateway polls: which DMs/channels to ingest."""
        return {"watch": eng.signals_service.discord_get_watch()}

    class DiscordWatchBody(BaseModel):
        watch: list = []

    @app.put("/api/tip/discord/watch", dependencies=[auth])
    async def discord_set_watch(body: DiscordWatchBody):
        return {"watch": await eng.signals_service.discord_set_watch(body.watch)}

    class PeekBody(BaseModel):
        channelId: str = ""

    @app.post("/api/tip/discord/peek", dependencies=[auth])
    async def discord_peek(body: PeekBody):
        """UI: show a channel/DM's last message (a connection test)."""
        if not body.channelId:
            raise HTTPException(status_code=400, detail="channelId required")
        eng.signals_service.discord_queue_peek(body.channelId)
        return {"ok": True, "queued": body.channelId}

    @app.get("/api/tip/discord/peek", dependencies=[auth])
    async def discord_peek_result(channelId: str = ""):
        return {"result": eng.signals_service.discord_get_peek_result(channelId)}

    @app.get("/api/tip/discord/peek-pending", dependencies=[auth])
    async def discord_peek_pending():
        """Gateway polls this: channels the UI wants peeked (taken once)."""
        return {"channelIds": eng.signals_service.discord_take_peeks()}

    class PeekResultBody(BaseModel):
        channelId: str = ""
        text: str = ""
        author: str = ""
        messageAt: str = ""
        error: str = ""

    @app.post("/api/tip/discord/peek-result", dependencies=[auth])
    async def discord_peek_report(body: PeekResultBody):
        eng.signals_service.discord_set_peek_result(body.channelId, {
            "text": body.text, "author": body.author,
            "messageAt": body.messageAt, "error": body.error})
        return {"ok": True}

    @app.post("/api/tip/discord/process-last", dependencies=[auth])
    async def discord_process_last(body: PeekBody):
        """Fetch a channel's last message and run it through the tip pipeline."""
        if not body.channelId:
            raise HTTPException(status_code=400, detail="channelId required")
        eng.signals_service.discord_queue_process(body.channelId)
        return {"ok": True, "queued": body.channelId}

    @app.get("/api/tip/discord/process-pending", dependencies=[auth])
    async def discord_process_pending():
        return {"channelIds": eng.signals_service.discord_take_processes()}

    # --- discord message mirror (the source's own history, analyst-searchable) --
    class MirrorBody(BaseModel):
        messages: list = []

    @app.post("/api/tip/discord/messages", dependencies=[auth])
    async def discord_mirror_messages(body: MirrorBody):
        """The gateway mirrors every message it sees in a monitored channel."""
        stored = await eng.signals_service.discord_store_messages(body.messages)
        return {"stored": stored}

    @app.get("/api/tip/discord/messages", dependencies=[auth])
    async def discord_messages(source: str = "", channelId: str = "",
                               contains: str = "", hours: float = 0,
                               before: str = "", limit: int = 30):
        return await eng.signals_service.discord_search_messages(
            source=source or None, channel_id=channelId or None,
            contains=contains or None, hours=hours or None,
            before=before or None, limit=limit)

    @app.get("/api/tip/discord/mirror-stats", dependencies=[auth])
    async def discord_mirror_stats():
        """Per-channel mirror coverage — drives the gateway's onboarding backfill."""
        return await eng.signals_service.discord_mirror_stats()

    class AnalyzeMessageBody(BaseModel):
        messageId: str = ""

    @app.post("/api/tip/discord/analyze-message", dependencies=[auth])
    async def discord_analyze_message(body: AnalyzeMessageBody):
        """Ad-hoc: run the tip pipeline on one MIRRORED message (fine-tuning).
        Returns the process-result key the UI polls (same banner as ▶ tip)."""
        if not body.messageId:
            raise HTTPException(status_code=400, detail="messageId required")
        if await eng.signals_service.discord_get_message(body.messageId) is None:
            raise HTTPException(status_code=404, detail="message not in the mirror")
        return {"ok": True, "key": eng.signals_service.start_mirror_analysis(body.messageId)}

    @app.get("/api/tip/discord/media/{message_id}/{index}", dependencies=[auth])
    async def discord_media(message_id: str, index: int = 0):
        """A mirrored image, served from OUR store (CDN links expire)."""
        from fastapi.responses import Response
        got = await eng.signals_service.discord_media_bytes(message_id, index)
        if got is None:
            raise HTTPException(status_code=404,
                                detail="image not in the mirror (and the CDN link has expired)")
        blob, media_type = got
        return Response(content=blob, media_type=media_type,
                        headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/api/tip/discord/process-result", dependencies=[auth])
    async def discord_process_result(channelId: str = ""):
        """UI polls this after 'process last message' — what actually happened
        (no tip in the message, error, or the signals + analyst runs it made)."""
        return {"result": eng.signals_service.discord_get_process_result(channelId)}

    class ProcessResultBody(BaseModel):
        channelId: str = ""
        ok: bool = False
        note: str = ""
        error: str = ""
        author: str = ""
        text: str = ""
        signals: list = []
        intakeRunId: str = ""

    @app.post("/api/tip/discord/process-result", dependencies=[auth])
    async def discord_process_report(body: ProcessResultBody):
        eng.signals_service.discord_set_process_result(body.channelId, {
            "ok": body.ok, "note": body.note, "error": body.error,
            "author": body.author, "text": body.text, "signals": body.signals,
            "intakeRunId": body.intakeRunId})
        return {"ok": True}

    # --- tips analyst run history (the play-by-play, per run) -----------------
    @app.get("/api/tip/analyst/runs", dependencies=[auth])
    async def analyst_runs(limit: int = 40):
        return await eng.signals_service.analyst_runs(limit)

    @app.get("/api/tip/analyst/runs/{run_id}", dependencies=[auth])
    async def analyst_run(run_id: str):
        try:
            return await eng.signals_service.analyst_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    # --- shared tips knowledge (notes the analyst reads before every run) -----
    @app.get("/api/tip/notes", dependencies=[auth])
    async def tip_notes(scope: str = "", limit: int = 100, superseded: bool = False):
        scopes = [s.strip() for s in scope.split(",") if s.strip()] or None
        return await eng.signals_service.tip_notes(scopes, limit=limit,
                                                   include_superseded=superseded)

    class NoteBody(BaseModel):
        scope: str = "general"
        text: str

    @app.post("/api/tip/notes", dependencies=[auth])
    async def add_tip_note(body: NoteBody):
        try:
            return await eng.signals_service.add_tip_note(body.scope, body.text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    class NotePatch(BaseModel):
        text: str | None = None
        scope: str | None = None

    @app.patch("/api/tip/notes/{note_id}", dependencies=[auth])
    async def update_tip_note(note_id: str, body: NotePatch):
        try:
            out = await eng.signals_service.update_tip_note(
                note_id, text=body.text, scope=body.scope)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if out is None:
            raise HTTPException(status_code=404, detail="note not found")
        return out

    @app.delete("/api/tip/notes/{note_id}", dependencies=[auth])
    async def delete_tip_note(note_id: str):
        if not await eng.signals_service.delete_tip_note(note_id):
            raise HTTPException(status_code=404, detail="note not found")
        return {"ok": True}

    @app.post("/api/tip/notes/{note_id}/resolve", dependencies=[auth])
    async def resolve_tip_note(note_id: str):
        """A8.3: the human resolved a contradiction the rule audit surfaced —
        clears the needs-your-call flag (keeping/deleting rules is separate)."""
        from .. import events as ev
        if not await eng.signals_service.flag_tip_notes([note_id], needs_human=False):
            raise HTTPException(status_code=404, detail="note not found or not flagged")
        await eng.journal.append(ev.TIP_RULE_AUDITED,
                                 {"resolved": note_id, "by": "user"},
                                 aggregate_type="signal", aggregate_id=note_id)
        return {"ok": True}

    # --- historical experiment harness (KNOWLEDGE plan Phase 2) --------------
    class ExperimentBody(BaseModel):
        batch: str
        sample: int = 20
        seed: int = 7
        since: str = ""
        channels: list = []

    @app.post("/api/tip/experiment/run", dependencies=[auth])
    async def tip_experiment_run(body: ExperimentBody):
        """Start one out-of-band historical batch in the background. Progress +
        results via GET /api/tip/experiment/{batch}."""
        import asyncio as _asyncio

        from ..techniques.tip import experiment as exp
        batch = body.batch.strip()
        if not batch:
            raise HTTPException(status_code=400, detail="batch name required")
        state = getattr(eng.signals_service, "_experiments", {})
        if state.get(batch, {}).get("running"):
            raise HTTPException(status_code=409, detail=f"batch {batch} is already running")
        msgs = await exp.sample_messages(eng, sample=body.sample, seed=body.seed,
                                         since=body.since,
                                         channels=[str(c) for c in body.channels] or None)
        if not msgs:
            raise HTTPException(status_code=400,
                                detail="no unprocessed mirrored messages match the filters")
        _asyncio.create_task(
            exp.run_batch(eng, batch=batch, sample=body.sample, seed=body.seed,
                          since=body.since,
                          channels=[str(c) for c in body.channels] or None),
            name=f"tip-exp-{batch}")
        return {"ok": True, "batch": batch, "sampled": len(msgs)}

    @app.get("/api/tip/experiment/{batch}", dependencies=[auth])
    async def tip_experiment_status(batch: str):
        from ..techniques.tip import experiment as exp
        return await exp.batch_status(eng, batch)

    @app.post("/api/tip/experiment/{batch}/review", dependencies=[auth])
    async def tip_experiment_review(batch: str):
        """The batch review run: the rubric over every item; summary saved as an
        experiment-scoped note. Synchronous (one LLM call, ~1 min)."""
        from ..techniques.tip import experiment as exp
        try:
            out = await exp.review_batch(eng, batch)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if out is None:
            raise HTTPException(status_code=503, detail="no analyst client configured")
        return out

    # --- proposals -----------------------------------------------------------
    @app.get("/api/proposals", dependencies=[auth])
    async def list_proposals(all: bool = False, limit: int = 100):
        if eng.proposals is None:
            return []
        return await (eng.proposals.list_all(limit) if all else eng.proposals.list_pending())

    class DecisionBody(BaseModel):
        half: bool = False

    @app.post("/api/proposals/{pid}/approve", dependencies=[auth])
    async def approve(pid: str, body: DecisionBody | None = None):
        try:
            return await eng.proposals.approve(pid, via="app",
                                               half=bool(body and body.half))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/proposals/{pid}/reject", dependencies=[auth])
    async def reject(pid: str):
        try:
            return await eng.proposals.reject(pid, via="app")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
