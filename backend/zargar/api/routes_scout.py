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
