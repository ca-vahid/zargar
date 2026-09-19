"""EM integrated-review routes (2026-09-18): READ-ONLY surfaces for source scenarios, the preparation policy, source
candidates, first-sale records and the executable-profit capture. No route here arms, orders, writes or calls a model.

NOTE: no `from __future__ import annotations` - see api/app.py.
"""
import datetime as dt
import re
from zoneinfo import ZoneInfo

from fastapi import HTTPException

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _day(date):
    if not date:
        return dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    if not _DATE.match(str(date)):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    return str(date)


def build_em_review_routes(app, eng, auth) -> None:
    def svc():
        if eng.technique is None:
            raise HTTPException(status_code=503, detail="technique layer not attached")
        return eng.technique

    @app.get("/api/technique/em/manifest", dependencies=[auth])
    async def em_manifest():
        from ..technique import em_review_service as rs
        return rs.manifest(svc())

    @app.get("/api/technique/em/source-table", dependencies=[auth])
    async def em_source_table(date: str = ""):
        from ..technique import em_review_service as rs
        return await rs.source_table(svc(), _day(date))

    @app.get("/api/technique/em/candidates", dependencies=[auth])
    async def em_candidates(date: str = ""):
        from ..technique import em_review_service as rs
        return await rs.candidates(svc(), _day(date))

    @app.get("/api/technique/em/first-sale", dependencies=[auth])
    async def em_first_sale(date: str = ""):
        from ..technique import em_review_service as rs
        return await rs.first_sale_rows(svc(), _day(date))

    @app.get("/api/technique/em/profit-capture", dependencies=[auth])
    async def em_profit_capture(date: str = ""):
        from ..technique import em_review_service as rs
        return await rs.profit_capture(svc(), _day(date))

    @app.get("/api/technique/em/experiment", dependencies=[auth])
    async def em_experiment_status():
        from ..technique import em_experiment as xp
        return await xp.status(svc())

    @app.post("/api/technique/em/experiment/prepare", dependencies=[auth])
    async def em_experiment_prepare(planFor: str = "", limit: int = 0):
        """Deterministic preparation of ONE session for the experimental Practice book (zero model calls; idempotent). It arms
        ONLY in the experimental sim book and refuses when the experiment is not enabled."""
        import time as _t
        from ..technique import em_experiment as xp
        from ..marketstructure.sessions import next_session_date
        day = _day(planFor) if planFor else next_session_date(int(_t.time() * 1000))
        return await xp.prepare(svc(), day, limit=(limit or None))

    @app.get("/api/technique/em/model-cost", dependencies=[auth])
    async def em_model_cost(date: str = ""):
        from ..technique import em_review_service as rs
        return await rs.model_cost(svc(), _day(date))

    @app.get("/api/technique/em/runs/{run_id}/prep-decision", dependencies=[auth])
    async def em_prep_decision(run_id: str):
        try:
            return await svc().prep_decide(run_id, persist=False)      # a preview: never written, never journaled
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
