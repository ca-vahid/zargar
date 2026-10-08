"""Scout routes (research only) - READ-ONLY in P1: candidates and ingest status.

NOTE: no `from __future__ import annotations` - see api/app.py.
"""
from fastapi import HTTPException


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
