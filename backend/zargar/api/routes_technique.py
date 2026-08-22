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
        plan: bool | None = None         # force plan mode (default: auto when asOf is outside the session)
        withVision: bool | None = None   # run the vision passes in plan mode

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
                                           wait=body.wait, plan=body.plan, with_vision=body.withVision)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # --- session plans / walk-forward / arming --------------------------------------------
    class PlanBody(BaseModel):
        symbol: str
        asOf: int | None = None          # default: now (plan for the next session)
        tf: str | None = None            # trigger timeframe
        withVision: bool | None = None
        wait: bool = True

    @app.post("/api/technique/plan", dependencies=[auth])
    async def technique_plan(body: PlanBody):
        try:
            return await _svc(eng).analyze(body.symbol, as_of_ms=body.asOf, primary_tf=body.tf, trigger="manual",
                                           plan=True, with_vision=body.withVision, wait=body.wait)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    class SweepBody(BaseModel):
        symbols: list[str] = []
        start: str
        end: str
        structureTfs: list[str] | None = None
        triggerTf: str | None = None
        includeInvalid: bool = False
        label: str = ""
        wait: bool = False

    @app.post("/api/technique/walkforward", dependencies=[auth])
    async def technique_sweep(body: SweepBody):
        svc = _svc(eng)
        syms = body.symbols or list(eng.settings.get("technique.walkforward.symbols", []))
        try:
            return await svc.start_sweep(syms, body.start, body.end, structure_tfs=body.structureTfs,
                                         trigger_tf=body.triggerTf, include_invalid=body.includeInvalid,
                                         label=body.label, wait=body.wait)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/technique/walkforward", dependencies=[auth])
    async def technique_sweeps(limit: int = 50):
        return await _svc(eng).list_sweeps(limit=min(limit, 200))

    @app.get("/api/technique/walkforward/{sweep_id}", dependencies=[auth])
    async def technique_sweep_get(sweep_id: str, rows: bool = True):
        d = await _svc(eng).get_sweep(sweep_id, rows=rows)
        if d is None:
            raise HTTPException(status_code=404, detail="sweep not found")
        return d

    class PromoteBody(BaseModel):
        symbol: str
        session: str
        withVision: bool = False

    @app.post("/api/technique/walkforward/{sweep_id}/promote", dependencies=[auth])
    async def technique_promote(sweep_id: str, body: PromoteBody):
        try:
            return await _svc(eng).promote(sweep_id, body.symbol, body.session, with_vision=body.withVision)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/technique/armed", dependencies=[auth])
    async def technique_armed():
        return _svc(eng).armed_plans()

    @app.get("/api/technique/armed/options", dependencies=[auth])
    async def technique_arm_options():
        return _svc(eng).arm_options()

    @app.get("/api/technique/armed/history", dependencies=[auth])
    async def technique_armed_history(limit: int = 50):
        return await _svc(eng).armed_history(limit=min(limit, 200))

    @app.get("/api/technique/armed/{run_id}", dependencies=[auth])
    async def technique_armed_detail(run_id: str):
        d = _svc(eng).armed_detail(run_id)
        if d is None:
            raise HTTPException(status_code=404, detail="not armed")
        return d

    @app.get("/api/technique/armed/{run_id}/audit", dependencies=[auth])
    async def technique_armed_audit(run_id: str, limit: int = 200):
        return await _svc(eng).armed_audit(run_id, limit=min(limit, 1000))

    class ArmBody(BaseModel):
        portfolioId: str | None = None
        mode: str | None = None            # alert | proposal | auto
        instrument: str | None = None      # options | shares
        contracts: int | None = None       # options: fixed contracts (R5); omit to size by risk %
        maxContracts: int | None = None
        singleContractExit: str | None = None
        riskPct: float | None = None
        maxQty: float | None = None
        qty: float | None = None
        useCritic: bool | None = None
        allowLive: bool = False
        flattenMinutesBeforeClose: int | None = None
        slippagePct: float | None = None

    def _arm_config(body: ArmBody | None) -> dict:
        if body is None:
            return {}
        return {k: v for k, v in body.model_dump().items() if v is not None}

    @app.post("/api/technique/runs/{run_id}/arm", dependencies=[auth])
    async def technique_arm(run_id: str, body: ArmBody | None = None):
        try:
            return await _svc(eng).arm_plan(run_id, _arm_config(body))
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.delete("/api/technique/runs/{run_id}/arm", dependencies=[auth])
    async def technique_disarm(run_id: str, flatten: bool = False):
        return {"disarmed": await _svc(eng).disarm_plan(run_id, flatten=flatten)}

    @app.post("/api/technique/armed/{run_id}/pause", dependencies=[auth])
    async def technique_pause(run_id: str):
        try:
            return await _svc(eng).pause_plan(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="not armed")

    @app.post("/api/technique/armed/{run_id}/resume", dependencies=[auth])
    async def technique_resume(run_id: str):
        try:
            return await _svc(eng).resume_plan(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="not armed")

    @app.post("/api/technique/armed/stop-all", dependencies=[auth])
    async def technique_stop_all(flatten: bool = False):
        return {"disarmed": await _svc(eng).stop_all_armed(flatten=flatten)}

    class ArmTodayBody(ArmBody):
        symbol: str = ""
        withVision: bool | None = None

    @app.post("/api/technique/arm-today", dependencies=[auth])
    async def technique_arm_today(body: ArmTodayBody):
        cfg = {k: v for k, v in body.model_dump().items() if v is not None and k not in ("symbol", "withVision")}
        try:
            return await _svc(eng).arm_today(body.symbol, cfg, with_vision=body.withVision)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/technique/runs", dependencies=[auth])
    async def technique_runs(limit: int = 50, symbol: str | None = None, verdict: str | None = None,
                             reviewed: bool | None = None, outcome: str | None = None,
                             review_verdict: str | None = Query(default=None, alias="reviewVerdict"),
                             process_version: str | None = Query(default=None, alias="processVersion"),
                             trigger: str | None = None):
        return await _svc(eng).list_runs(limit=min(limit, 500), symbol=symbol, verdict=verdict,
                                         reviewed=reviewed, outcome=outcome, review_verdict=review_verdict,
                                         process_version=process_version, trigger=trigger)

    @app.get("/api/technique/runs/{run_id}", dependencies=[auth])
    async def technique_run(run_id: str):
        r = await _svc(eng).get_run(run_id)
        if r is None:
            raise HTTPException(status_code=404, detail="run not found")
        return r

    # --- review loop: outcomes, reviews, replay, diff, bundle ----------------------------
    @app.get("/api/technique/review/taxonomy", dependencies=[auth])
    async def technique_review_taxonomy():
        from ..technique.review import REVIEW_VERDICTS, ROOT_CAUSE_STAGES
        return {"reviewVerdicts": REVIEW_VERDICTS, "rootCauseStages": ROOT_CAUSE_STAGES}

    @app.post("/api/technique/runs/{run_id}/score", dependencies=[auth])
    async def technique_score(run_id: str, horizon: int | None = Query(default=None, alias="horizonBars"),
                              force: bool = True):
        try:
            return await _svc(eng).score_run(run_id, horizon_bars=horizon, force=force)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")

    @app.post("/api/technique/outcomes/score", dependencies=[auth])
    async def technique_score_pending(limit: int = 25):
        return await _svc(eng).score_pending(limit=min(limit, 200))

    class ReviewBody(BaseModel):
        reviewVerdict: str
        reviewer: str = "user"
        expectedVerdict: str | None = None
        expectedSetupType: str | None = None
        expectedPlan: dict | None = None
        expectationNote: str = ""
        rootCauseStage: str | None = None
        notes: str = ""
        actions: list = []

    @app.get("/api/technique/runs/{run_id}/reviews", dependencies=[auth])
    async def technique_reviews(run_id: str):
        return await _svc(eng).list_reviews(run_id)

    @app.post("/api/technique/runs/{run_id}/reviews", dependencies=[auth])
    async def technique_add_review(run_id: str, body: ReviewBody):
        try:
            return await _svc(eng).add_review(
                run_id, review_verdict=body.reviewVerdict, reviewer=body.reviewer,
                expected_verdict=body.expectedVerdict, expected_setup_type=body.expectedSetupType,
                expected_plan=body.expectedPlan, expectation_note=body.expectationNote,
                root_cause_stage=body.rootCauseStage, notes=body.notes, actions=body.actions)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/technique/reviews", dependencies=[auth])
    async def technique_all_reviews(limit: int = 200):
        return await _svc(eng).list_reviews(None, limit=min(limit, 1000))

    class ReplayBody(BaseModel):
        thresholds: dict | None = None
        useSnapshot: bool = True
        note: str = ""
        wait: bool = False

    @app.post("/api/technique/runs/{run_id}/replay", dependencies=[auth])
    async def technique_replay(run_id: str, body: ReplayBody):
        try:
            return await _svc(eng).replay_run(run_id, thresholds=body.thresholds, use_snapshot=body.useSnapshot,
                                              note=body.note, wait=body.wait)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/technique/runs/{run_id}/diff/{other_id}", dependencies=[auth])
    async def technique_diff(run_id: str, other_id: str):
        try:
            return await _svc(eng).diff(run_id, other_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/technique/runs/{run_id}/bundle", dependencies=[auth])
    async def technique_bundle(run_id: str, format: str = "zip"):
        from ..technique.bundle import build_bundle, zip_bundle
        try:
            if format == "json":
                return await build_bundle(_svc(eng), run_id)
            data = await zip_bundle(_svc(eng), run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        return Response(content=data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="run-{run_id}.zip"'})

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
        primeWindowsOnly: bool = True

    @app.post("/api/technique/backtest", dependencies=[auth])
    async def technique_backtest(body: BacktestBody):
        try:
            return await _svc(eng).backtest(body.symbol, body.tf, days=body.days,
                                            start_ms=body.startMs, end_ms=body.endMs,
                                            horizon_bars=body.horizonBars, step_bars=body.stepBars,
                                            prime_windows_only=body.primeWindowsOnly)
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
