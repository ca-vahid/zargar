"""Technique pipeline + chat routes.

NOTE: no `from __future__ import annotations` — see api/app.py.
"""
from fastapi import HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from ..technique.llm import decode_data_url


def _svc(eng):
    if eng.technique is None:
        raise HTTPException(status_code=503, detail="technique layer not attached")
    return eng.technique


def _chat(eng):
    if eng.chat is None:
        raise HTTPException(status_code=503, detail="chat layer not attached")
    return eng.chat


def build_technique_routes(app, eng, auth, config) -> None:

    # --- status / rules ------------------------------------------------------------
    @app.get("/api/technique/status", dependencies=[auth])
    async def technique_status():
        return await _svc(eng).status()

    @app.get("/api/technique/rules", dependencies=[auth])
    async def technique_rules():
        from ..technique.rulebook import RULES
        return RULES

    # --- analyze ------------------------------------------------------------------
    class AnalyzeBody(BaseModel):
        symbol: str = ""
        tf: str | None = None
        asOf: int | None = None          # epoch ms; null = now
        note: str = ""
        imageDataUrl: str | None = None  # data:image/png;base64,...
        wait: bool = False

    @app.post("/api/technique/analyze", dependencies=[auth])
    async def technique_analyze(body: AnalyzeBody):
        image = None
        if body.imageDataUrl:
            try:
                image, _ = decode_data_url(body.imageDataUrl)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        try:
            return await _svc(eng).analyze(body.symbol, as_of_ms=body.asOf, primary_tf=body.tf,
                                           image=image, note=body.note, trigger="manual",
                                           wait=body.wait)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/technique/runs", dependencies=[auth])
    async def technique_runs(limit: int = 50, symbol: str | None = None, verdict: str | None = None):
        return await _svc(eng).list_runs(limit=min(limit, 500), symbol=symbol, verdict=verdict)

    @app.get("/api/technique/runs/{run_id}", dependencies=[auth])
    async def technique_run(run_id: str):
        r = await _svc(eng).get_run(run_id)
        if r is None:
            raise HTTPException(status_code=404, detail="run not found")
        return r

    @app.post("/api/technique/runs/{run_id}/cancel", dependencies=[auth])
    async def technique_cancel(run_id: str):
        return {"cancelled": await _svc(eng).cancel_run(run_id)}

    @app.get("/api/technique/setups", dependencies=[auth])
    async def technique_setups(limit: int = 100, valid: bool = False):
        return await _svc(eng).list_setups(limit=min(limit, 500), valid_only=valid)

    # --- backtest -------------------------------------------------------------------
    class BacktestBody(BaseModel):
        symbol: str
        tf: str = "5m"
        days: int = 10
        horizonBars: int = 60
        stepBars: int = 5
        startMs: int | None = None
        endMs: int | None = None

    @app.post("/api/technique/backtest", dependencies=[auth])
    async def technique_backtest(body: BacktestBody):
        try:
            return await _svc(eng).backtest(body.symbol, body.tf, days=body.days,
                                            start_ms=body.startMs, end_ms=body.endMs,
                                            horizon_bars=body.horizonBars, step_bars=body.stepBars)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # --- options --------------------------------------------------------------------
    @app.get("/api/technique/options/{symbol}", dependencies=[auth])
    async def technique_options(symbol: str, direction: str = "long"):
        return await _svc(eng).option_pick(symbol, direction)

    # --- scan -----------------------------------------------------------------------
    @app.post("/api/technique/scan", dependencies=[auth])
    async def technique_scan():
        return await _svc(eng).scan_once(force=True)

    # --- chart PNG (for the UI / quick look) ------------------------------------------
    @app.get("/api/technique/chart/{symbol}", dependencies=[auth])
    async def technique_chart(symbol: str, tf: str = "1m", bars: int = 150, levels: bool = True,
                              as_of: int | None = Query(default=None, alias="asOf")):
        from ..technique.analysis import AnalysisRequest, compute_facts, gather_bars
        from ..technique.render import render_chart
        req = AnalysisRequest(symbol=symbol, primary_tf=tf, context_tfs=(), as_of_ms=as_of,
                              thresholds=_svc(eng).thresholds())
        b, notes = await gather_bars(req)
        blist = b.get(tf) or []
        if not blist:
            raise HTTPException(status_code=404, detail="no bars: " + "; ".join(notes))
        lv = None
        wedge = None
        if levels:
            facts = compute_facts(req, {tf: blist}, notes)
            lv = facts.get("keyLevels", [])[:8]
            wedge = (facts.get("wedge") or {}).get(tf)
        png = render_chart(blist[-min(bars, 400):], title=f"{symbol.upper()} {tf}", tf=tf,
                           levels=lv, wedge=wedge)
        return Response(content=png, media_type="image/png")

    # --- chat ------------------------------------------------------------------------
    class ThreadBody(BaseModel):
        title: str = ""
        symbol: str | None = None

    @app.get("/api/chat/threads", dependencies=[auth])
    async def chat_threads(limit: int = 100, archived: bool = False, kind: str | None = None):
        return await _chat(eng).list_threads(limit=min(limit, 500), include_archived=archived, kind=kind)

    @app.post("/api/chat/threads", dependencies=[auth])
    async def chat_create(body: ThreadBody):
        return await _chat(eng).create_thread(title=body.title, symbol=body.symbol)

    @app.get("/api/chat/threads/{thread_id}", dependencies=[auth])
    async def chat_get(thread_id: str):
        t = await _chat(eng).get_thread(thread_id)
        if t is None:
            raise HTTPException(status_code=404, detail="thread not found")
        return t

    class ThreadPatch(BaseModel):
        title: str | None = None
        archived: bool | None = None

    @app.patch("/api/chat/threads/{thread_id}", dependencies=[auth])
    async def chat_patch(thread_id: str, body: ThreadPatch):
        t = await _chat(eng).update_thread(thread_id, title=body.title, archived=body.archived)
        if t is None:
            raise HTTPException(status_code=404, detail="thread not found")
        return t

    class SendBody(BaseModel):
        text: str = ""
        images: list[str] = []     # data URLs

    @app.post("/api/chat/threads/{thread_id}/messages", dependencies=[auth])
    async def chat_send(thread_id: str, body: SendBody):
        imgs: list[bytes] = []
        for u in body.images or []:
            try:
                data, _ = decode_data_url(u)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            imgs.append(data)
        try:
            return await _chat(eng).send(thread_id, body.text, imgs)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/api/chat/threads/{thread_id}/cancel", dependencies=[auth])
    async def chat_cancel(thread_id: str):
        return {"cancelled": await _chat(eng).cancel(thread_id)}

    @app.get("/api/chat/search", dependencies=[auth])
    async def chat_search(q: str, limit: int = 50):
        return await _chat(eng).search(q, limit=min(limit, 200))

    @app.get("/api/chat/assets/{asset_id}", dependencies=[auth])
    async def chat_asset(asset_id: str):
        got = await _chat(eng).get_asset(asset_id)
        if got is None:
            raise HTTPException(status_code=404, detail="asset not found")
        data, mt = got
        return Response(content=data, media_type=mt,
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})
