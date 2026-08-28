"""Signal ingestion, signals, and proposals routes.

NOTE: no `from __future__ import annotations` — see api/app.py.
"""
from fastapi import HTTPException, Request
from pydantic import BaseModel


def build_signal_routes(app, eng, auth, config) -> None:

    # --- inbound email webhook (Cloudflare Email Worker posts here) ----------
    @app.post("/api/ingest/email")
    async def ingest_email(request: Request):
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
