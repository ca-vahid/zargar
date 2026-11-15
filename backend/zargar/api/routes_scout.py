"""Scout routes (research only). Reads: candidates (with both lanes' verdicts, lane-book entries, SEC
links), lanes (per-book after-cost P&L), status (ingest, spend vs budget, schedule, settings, reports).
No route places an order or changes a setting (settings go through the generic /api/settings).

NOTE: no `from __future__ import annotations` - see api/app.py.
"""
from fastapi import HTTPException
from pydantic import BaseModel


class DossierRequest(BaseModel):
    ticker: str
    refresh: bool = False


def _svc(eng):
    svc = getattr(eng, "scout_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="scout layer not attached")
    return svc


def build_scout_routes(app, eng, auth, config) -> None:

    @app.get("/api/scout/candidates", dependencies=[auth])
    async def scout_candidates(days: int = 7, kind: str | None = None):
        return await _svc(eng).candidates(days=min(365, max(0, days)), kind=kind)

    @app.get("/api/scout/status", dependencies=[auth])
    async def scout_status():
        return await _svc(eng).status()

    @app.get("/api/scout/lanes", dependencies=[auth])
    async def scout_lanes():
        svc = _svc(eng)
        await svc.desk.sync_entries()
        return await svc.desk.lanes()

    @app.get("/api/scout/dossiers", dependencies=[auth])
    async def scout_dossiers(limit: int = 30, ticker: str | None = None):
        return await _svc(eng).dossier.list(limit=min(100, max(1, limit)), ticker=ticker)

    @app.get("/api/scout/dossiers/{dossier_id}", dependencies=[auth])
    async def scout_dossier(dossier_id: str):
        d = await _svc(eng).dossier.get(dossier_id)
        if d is None:
            raise HTTPException(status_code=404, detail="no such dossier")
        return d

    @app.post("/api/scout/dossiers", dependencies=[auth])
    async def scout_dossier_request(body: DossierRequest):
        """Start (or reuse today's) research note for one ticker. Reads public data and makes at most one
        model call under its own daily cap; places no order and changes no setting."""
        try:
            return await _svc(eng).dossier.request(body.ticker, refresh=body.refresh)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/scout/reports", dependencies=[auth])
    async def scout_reports(limit: int = 10):
        return await _svc(eng).desk.reports(limit=min(60, max(1, limit)))

    # ---- the research agent (PLAN section 9; simulated research books only)
    @app.get("/api/scout/agent", dependencies=[auth])
    async def scout_agent():
        svc = _svc(eng)
        await svc.desk.sync_entries()
        await svc.agent.enrich_cases()
        lanes = [l for l in await svc.desk.lanes() if l["lane"].startswith("agent_")]
        return {"runs": await svc.agent.runs(limit=20), "scorecard": await svc.agent.scorecard(),
                "lessons": await svc.agent.lessons(), "lanes": lanes,
                "enabled": bool(svc.s("agent_enabled", True)),
                "schedule": [j for j in eng.scheduler.status() if j["name"].startswith("scout_agent")]}

    @app.get("/api/scout/agent/runs/{run_id}", dependencies=[auth])
    async def scout_agent_run(run_id: str):
        r = await _svc(eng).agent.run(run_id)
        if r is None:
            raise HTTPException(status_code=404, detail="no such run")
        return r

    @app.post("/api/scout/agent/run", dependencies=[auth])
    async def scout_agent_run_now():
        """Run today's agent now (normally 07:30 ET). Idempotent per day and lane; its entries are attempted
        in the usual 10:00-11:30 ET window on the simulated research books."""
        import asyncio
        svc = _svc(eng)
        if not bool(svc.s("agent_enabled", True)):
            raise HTTPException(status_code=400, detail="techniques.scout.agent_enabled is off")
        task = asyncio.create_task(svc.agent.run_day())
        svc.agent.tasks.add(task)
        task.add_done_callback(svc.agent.tasks.discard)
        return {"started": True}
