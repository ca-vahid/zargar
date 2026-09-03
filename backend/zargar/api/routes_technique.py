"""Technique pipeline + chat routes.

NOTE: no `from __future__ import annotations` — see api/app.py.
"""
import contextlib

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
    @app.get("/api/techniques", dependencies=[auth])
    async def techniques_list():
        """The technique registry — what the nav lists (platform plan phase 0)."""
        from ..techniques import all_techniques
        return [t.to_dict() for t in all_techniques()]

    def _tech(tid: str):
        from ..techniques import get_technique
        info = get_technique(tid)
        svc = (getattr(eng, "techniques", None) or {}).get(tid)
        if info is None or svc is None:
            raise HTTPException(status_code=404, detail=f"unknown technique: {tid}")
        return info, svc

    @app.get("/api/positions/managed", dependencies=[auth])
    async def managed_positions(status: str | None = None):
        return eng.position_manager.positions(status=status)

    @app.get("/api/positions/context", dependencies=[auth])
    async def positions_context(limit: int = 400):
        """Provenance for open positions: the entry order behind each
        (portfolio, symbol), the tip it came from, and whether the durable
        manager runs it — so the blotter can say WHERE a position came from."""
        from sqlalchemy import select
        from ..models import Order, Signal
        out: dict[str, dict] = {}
        async with eng.sf() as session:
            rows = (await session.execute(
                select(Order, Signal)
                .outerjoin(Signal, Order.signal_id == Signal.id)
                .where(Order.side == "BUY")
                .order_by(Order.created_at.desc()).limit(limit))).all()
        for o, sig in rows:
            key = f"{o.portfolio_id}:{o.symbol}"
            if key in out:                       # newest entry order wins
                continue
            out[key] = {
                "portfolioId": o.portfolio_id, "symbol": o.symbol,
                "origin": "tip" if o.signal_id else (o.source or "manual"),
                "orderId": o.id,
                "orderAt": o.created_at.isoformat() if o.created_at else None,
                "fillPrice": o.avg_fill_price,
                "source": o.source, "technique": o.technique,
                "proposalId": o.proposal_id, "signalId": o.signal_id,
                "sourceName": sig.source_name if sig is not None else None,
                "ticker": sig.ticker if sig is not None else None,
                "thesis": sig.thesis_summary if sig is not None else None,
            }
        for m in eng.position_manager.positions():
            if m.get("status") == "closed":
                continue
            for leg in m.get("legs") or []:
                key = f"{m['portfolioId']}:{leg.get('symbol')}"
                ctx = out.setdefault(key, {"portfolioId": m["portfolioId"],
                                           "symbol": leg.get("symbol")})
                ctx["managedId"] = m["id"]
                ctx["managedStatus"] = m["status"]
                ctx["managedTechnique"] = m.get("technique")
        return list(out.values())

    @app.post("/api/positions/managed/{pid}/policy", dependencies=[auth])
    async def managed_policy(pid: str, body: dict):
        """Replace the position's exit policy (validated; stops may only come
        from the new doc — same seam the analyst's update_exit_plan uses).
        Journaled ManagedPositionPolicyChanged."""
        try:
            out = await eng.position_manager.set_policy(pid, dict(body or {}))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if out is None:
            raise HTTPException(status_code=404, detail="unknown position")
        return out

    @app.post("/api/positions/managed/{pid}/close", dependencies=[auth])
    async def managed_close(pid: str, fraction: float = 1.0):
        out = await eng.position_manager.close(pid, fraction=fraction, reason="manual close (API)")
        if out is None:
            raise HTTPException(status_code=404, detail="unknown position")
        return out

    @app.post("/api/positions/managed/{pid}/reconcile-clear", dependencies=[auth])
    async def managed_clear(pid: str):
        p = eng.position_manager.get(pid)
        if p is None:
            raise HTTPException(status_code=404, detail="unknown position")
        eng.position_manager.clear_entry_halt(p.symbol)
        p.halt_entries = False
        p.attention.clear()
        if p.status == "attention" and p.open_legs:
            p.status = "open"
        return p.to_dict()

    @app.get("/api/techniques/{tid}", dependencies=[auth])
    async def technique_info(tid: str):
        info, svc = _tech(tid)
        paused = bool(eng.settings.get(f"techniques.{tid}.paused", False))
        armed = [a for a in svc.armer.armed(slim=True) if (a.get("technique") or tid) == tid]
        return {**info.to_dict(), "paused": paused,
                "armed": len(armed), "inTrade": sum(1 for a in armed if a.get("openPositions"))}

    @app.post("/api/techniques/{tid}/pause", dependencies=[auth])
    async def technique_pause(tid: str):
        """Stop ONE technique: no new arms, no new fires — every armed plan is paused
        and the technique flag blocks future arms. Exits and open-position management
        keep running (reduce-only exempt, exactly like the kill switch); the global
        HALT is untouched."""
        info, svc = _tech(tid)
        await eng.settings.set(f"techniques.{tid}.paused", True)
        paused = []
        for a in list(svc.armer.armed(slim=True)):
            if (a.get("technique") or tid) == tid and a.get("status") == "armed":
                with contextlib.suppress(Exception):
                    await svc.armer.pause(a["runId"])
                    paused.append(a["runId"])
        return {"technique": tid, "paused": True, "plansPaused": len(paused)}

    @app.post("/api/techniques/{tid}/resume", dependencies=[auth])
    async def technique_resume(tid: str):
        info, svc = _tech(tid)
        await eng.settings.set(f"techniques.{tid}.paused", False)
        resumed = []
        for a in list(svc.armer.armed(slim=True)):
            if (a.get("technique") or tid) == tid and a.get("status") == "paused":
                with contextlib.suppress(Exception):
                    await svc.armer.resume(a["runId"])
                    resumed.append(a["runId"])
        return {"technique": tid, "paused": False, "plansResumed": len(resumed)}

    @app.get("/api/techniques/{tid}/runs", dependencies=[auth])
    async def technique_runs_scoped(tid: str, limit: int = 50, symbol: str | None = None,
                                    tag: str | None = None):
        _tech(tid)
        return await _svc(eng).list_runs(limit=min(limit, 500), symbol=symbol, tag=tag, technique=tid)

    @app.get("/api/techniques/{tid}/armed", dependencies=[auth])
    async def technique_armed_scoped(tid: str):
        _, svc = _tech(tid)
        return [a for a in svc.armer.armed() if (a.get("technique") or tid) == tid]

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

    # --- EM method ingestion (INGESTION-PLAN.md) - EM-only inbox for the author's channels ----
    def _ingest(eng_):
        svc = _svc(eng_)
        ing = getattr(svc, "ingest", None)
        if ing is None:
            raise HTTPException(status_code=503, detail="ingestion not attached")
        return ing

    @app.get("/api/technique/ingest/channels", dependencies=[auth])
    async def ingest_channels():
        """The gateway polls this: which Discord channels to forward to EM."""
        ing = _ingest(eng)
        return {"enabled": ing.enabled(), "channels": ing.channels()}

    class IngestMessageBody(BaseModel):
        id: str = ""
        channelId: str = ""
        channelName: str = ""
        guild: str | None = None
        author: str = ""
        authorId: str | None = None
        text: str = ""
        images: list[str] = []
        postedAt: str | None = None

    @app.post("/api/technique/ingest/message", dependencies=[auth])
    async def ingest_message(body: IngestMessageBody):
        return await _ingest(eng).store_message(body.model_dump())

    @app.get("/api/technique/ingest/pending", dependencies=[auth])
    async def ingest_pending():
        """The em_ingest worker polls this: video notes waiting for a transcript."""
        return {"notes": await _ingest(eng).pending()}

    class IngestTranscriptBody(BaseModel):
        noteId: str
        transcript: str | None = None
        error: str | None = None
        deferred: bool = False           # broadcast still live - check again later, no attempt spent
        partial: bool = False            # transcript taken before the broadcast ended (max wait hit)
        durationSeconds: float | None = None
        model: str | None = None
        seconds: float | None = None

    @app.post("/api/technique/ingest/transcript", dependencies=[auth])
    async def ingest_transcript(body: IngestTranscriptBody):
        try:
            return await _ingest(eng).store_transcript(
                body.noteId, transcript=body.transcript, error=body.error, deferred=body.deferred,
                meta={"durationSeconds": body.durationSeconds, "model": body.model, "seconds": body.seconds,
                      "partial": True if body.partial else None})
        except KeyError:
            raise HTTPException(status_code=404, detail="note not found")

    @app.get("/api/technique/ingest/notes", dependencies=[auth])
    async def ingest_notes(limit: int = 20):
        return await _ingest(eng).list_notes(limit)

    @app.get("/api/technique/ingest/board", dependencies=[auth])
    async def ingest_board():
        """Today's material: the primary item (morning video brief) + the day's
        supplementary notes, so a follow-up post never hides the brief."""
        return await _ingest(eng).today_board()

    @app.get("/api/technique/ingest/notes/{note_id}", dependencies=[auth])
    async def ingest_note(note_id: str):
        d = await _ingest(eng).get_note(note_id)
        if d is None:
            raise HTTPException(status_code=404, detail="note not found")
        return d

    @app.post("/api/technique/ingest/notes/{note_id}/extract", dependencies=[auth])
    async def ingest_extract(note_id: str):
        try:
            return await _ingest(eng).extract(note_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="note not found")
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/technique/ingest/notes/{note_id}/board-check", dependencies=[auth])
    async def ingest_board_check(note_id: str):
        try:
            return await _ingest(eng).board_check(note_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="note not found")

    # --- session plans / walk-forward / arming --------------------------------------------
    @app.get("/api/technique/universe", dependencies=[auth])
    async def technique_universe():
        return _svc(eng).universe_cached()

    @app.post("/api/technique/universe/refresh", dependencies=[auth])
    async def technique_universe_refresh():
        return await _svc(eng).refresh_universe(force=True)

    class PlanBody(BaseModel):
        symbol: str
        asOf: int | None = None          # default: now (plan for the next session)
        tf: str | None = None            # trigger timeframe
        withVision: bool | None = None
        wait: bool = True
        referencePrice: float | None = None   # pre-open re-plan: judge the map against this price, not the close

    @app.post("/api/technique/plan", dependencies=[auth])
    async def technique_plan(body: PlanBody):
        try:
            return await _svc(eng).analyze(body.symbol, as_of_ms=body.asOf, primary_tf=body.tf, trigger="manual",
                                           plan=True, with_vision=body.withVision, wait=body.wait,
                                           reference_price=body.referencePrice)
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
        syms = body.symbols or await svc.universe()
        try:
            return await svc.start_sweep(syms, body.start, body.end, structure_tfs=body.structureTfs,
                                         trigger_tf=body.triggerTf, include_invalid=body.includeInvalid,
                                         label=body.label, wait=body.wait)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/technique/walkforward", dependencies=[auth])
    async def technique_sweeps(limit: int = 50):
        return await _svc(eng).list_sweeps(limit=min(limit, 200))

    class SheetBody(BaseModel):
        symbols: list[str] = []
        label: str = ""
        wait: bool = False

    @app.post("/api/technique/walkforward/next", dependencies=[auth])
    async def technique_plan_sheet(body: SheetBody):
        syms = body.symbols or await _svc(eng).universe()
        try:
            return await _svc(eng).start_plan_sheet(syms, label=body.label, wait=body.wait)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/technique/walkforward/{sweep_id}/score", dependencies=[auth])
    async def technique_sheet_score(sweep_id: str):
        d = await _svc(eng).score_sheet(sweep_id)
        if d is None:
            raise HTTPException(status_code=404, detail="sweep not found")
        return d

    class SweepPatchBody(BaseModel):
        label: str

    @app.patch("/api/technique/walkforward/{sweep_id}", dependencies=[auth])
    async def technique_sweep_rename(sweep_id: str, body: SweepPatchBody):
        d = await _svc(eng).rename_sweep(sweep_id, body.label)
        if d is None:
            raise HTTPException(status_code=404, detail="sweep not found")
        return d

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
        wait: bool = True           # False: return the (running) run at once — the UI batches LLM reads
        force: bool = False         # re-read even when a finished analyst read exists for this symbol/session

    @app.post("/api/technique/walkforward/{sweep_id}/promote", dependencies=[auth])
    async def technique_promote(sweep_id: str, body: PromoteBody):
        try:
            return await _svc(eng).promote(sweep_id, body.symbol, body.session, with_vision=body.withVision, force=body.force,
                                           wait=body.wait)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    class ArmedExitBody(BaseModel):
        trigger: str | None = None       # null = every open trade of the plan

    @app.post("/api/technique/armed/{run_id}/exit", dependencies=[auth])
    async def technique_armed_exit(run_id: str, body: ArmedExitBody):
        runner = _svc(eng).runner_for(run_id)
        d = await runner.flatten_trade(run_id, body.trigger) if runner is not None else None
        if d is None:
            raise HTTPException(status_code=404, detail="plan is not armed")
        return d

    @app.get("/api/technique/armed", dependencies=[auth])
    async def technique_armed(slim: bool = False):
        return _svc(eng).armed_plans(slim=slim)

    @app.get("/api/technique/armed/summary", dependencies=[auth])
    async def technique_armed_summary():
        return await _svc(eng).armed_summary()

    @app.get("/api/technique/armed/options", dependencies=[auth])
    async def technique_arm_options():
        return _svc(eng).arm_options()

    class CounterfactualBody(BaseModel):
        triggerId: str
        reason: str
        orderSymbol: str | None = None
        limitPrice: float | None = None
        qty: float | None = None
        firedTs: int | None = None

    @app.post("/api/technique/runs/{run_id}/counterfactual", dependencies=[auth])
    async def technique_counterfactual(run_id: str, body: CounterfactualBody):
        """What a trade the app MISSED through a bug would have done: replay the
        fired order through the runner's exit rules on the real bars and record
        it in the counterfactual ledger (never a portfolio fill)."""
        from ..execution import counterfactual as cf
        try:
            return await cf.reconstruct(eng, run_id, body.triggerId, reason=body.reason, order_symbol=body.orderSymbol,
                                        limit_price=body.limitPrice, qty=body.qty, fired_ts=body.firedTs)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/technique/counterfactuals", dependencies=[auth])
    async def technique_counterfactuals(limit: int = 100, technique: str | None = None):
        from ..execution import counterfactual as cf
        return await cf.list_rows(eng, limit=min(limit, 500), technique=technique)

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
        maxOpenTrades: int | None = None
        dailyLossLimit: float | None = None
        skipWideSpread: bool | None = None
        skipElevatedIv: bool | None = None
        entryFallback: str | None = None   # "off" | "shares"

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

    @app.post("/api/technique/runs/{run_id}/arm/preflight", dependencies=[auth])
    async def technique_arm_preflight(run_id: str, body: ArmBody | None = None):
        try:
            return await _svc(eng).arm_preflight(run_id, _arm_config(body))
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.delete("/api/technique/runs/{run_id}/arm", dependencies=[auth])
    async def technique_disarm(run_id: str, flatten: bool = False):
        return {"disarmed": await _svc(eng).disarm_plan(run_id, flatten=flatten)}

    class ArmedModeBody(BaseModel):
        mode: str | None = None
        allowLive: bool = False
        entryFallback: str | None = None      # "off" | "shares"

    @app.post("/api/technique/armed/{run_id}/mode", dependencies=[auth])
    async def technique_armed_mode(run_id: str, body: ArmedModeBody):
        try:
            runner = _svc(eng).runner_for(run_id)
            if runner is None:
                raise KeyError(run_id)
            return await runner.set_mode(run_id, body.mode, allow_live=body.allowLive,
                                         entry_fallback=body.entryFallback)
        except KeyError:
            raise HTTPException(status_code=404, detail="not armed")
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

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
                             trigger: str | None = None, tag: str | None = None,
                             technique: str | None = None):
        return await _svc(eng).list_runs(limit=min(limit, 500), symbol=symbol, verdict=verdict,
                                         reviewed=reviewed, outcome=outcome, review_verdict=review_verdict,
                                         process_version=process_version, trigger=trigger,
                                         tag=tag, technique=technique)

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
