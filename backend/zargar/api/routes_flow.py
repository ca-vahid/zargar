"""Flow technique routes — reads and the on-demand scan.

NOTE: no `from __future__ import annotations` — see api/app.py.
"""
from fastapi import HTTPException
from pydantic import BaseModel


def _svc(eng):
    svc = getattr(eng, "flow_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="flow layer not attached")
    return svc


def build_flow_routes(app, eng, auth, config) -> None:

    @app.get("/api/flow/reads", dependencies=[auth])
    async def flow_reads(day: str | None = None, limit: int = 100):
        return await _svc(eng).reads(day=day, limit=limit)

    @app.get("/api/flow/context/{symbol}", dependencies=[auth])
    async def flow_context(symbol: str):
        line = await _svc(eng).context_for(symbol)
        return {"symbol": symbol.upper(), "context": line}

    @app.get("/api/flow/days", dependencies=[auth])
    async def flow_days(limit: int = 10):
        return await _svc(eng).days(limit=min(30, max(1, limit)))

    @app.get("/api/flow/symbol/{symbol}", dependencies=[auth])
    async def flow_symbol(symbol: str, days: int = 6):
        return await _svc(eng).story(symbol, days=min(20, max(1, days)))

    @app.get("/api/flow/brief", dependencies=[auth])
    async def flow_brief(day: str | None = None):
        return await _svc(eng).brief(day=day)

    class ScanBody(BaseModel):
        day: str | None = None
        symbols: list[str] | None = None

    @app.post("/api/flow/scan", dependencies=[auth])
    async def flow_scan(body: ScanBody | None = None):
        body = body or ScanBody()
        try:
            return await _svc(eng).scan(day=body.day, symbols=body.symbols)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))

    @app.get("/api/flow/status", dependencies=[auth])
    async def flow_status():
        return {"lastScan": _svc(eng).last_scan}
