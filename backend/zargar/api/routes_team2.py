"""Team2 technique routes — plans, the live read, replay and the walk-forward sweep.

NOTE: no `from __future__ import annotations` — see api/app.py.
"""
from fastapi import HTTPException
from pydantic import BaseModel


def _svc(eng):
    svc = getattr(eng, "team2", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="team2 layer not attached")
    return svc


def build_team2_routes(app, eng, auth, config) -> None:

    @app.get("/api/team2/status", dependencies=[auth])
    async def team2_status():
        s = eng.settings
        runner = getattr(eng, "team2_runner", None)
        armed = runner.armed(slim=True) if runner is not None else []
        macro = eng.macro.describe() if getattr(eng, "macro", None) is not None else None
        from ..techniques.team2.rules import rules_from_settings
        return {"enabled": bool(s.get("techniques.team2.enabled", True)), "mode": s.get("techniques.team2.mode"),
                "symbols": s.get("techniques.team2.symbols"), "planAt": s.get("techniques.team2.plan_at"),
                "preopenAt": s.get("techniques.team2.preopen_at"), "zeroDte": s.get("techniques.team2.zero_dte"),
                "armed": armed, "macro": macro, "thresholds": rules_from_settings(s).to_dict()}

    @app.get("/api/team2/runs", dependencies=[auth])
    async def team2_runs(limit: int = 50, symbol: str | None = None):
        return await _svc(eng).runs(limit=min(200, max(1, limit)), symbol=symbol)

    @app.get("/api/team2/runs/{run_id}/read", dependencies=[auth])
    async def team2_read(run_id: str):
        runner = getattr(eng, "team2_runner", None)
        live = runner.last_read(run_id) if runner is not None else None
        if live is not None:
            return {"runId": run_id, "source": "live", "result": live}
        rep = await _svc(eng).replay(run_id)
        if rep is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {"runId": run_id, "source": "replay", **rep}

    class PlanBody(BaseModel):
        date: str | None = None
        arm: bool = True

    @app.post("/api/team2/plan-now", dependencies=[auth])
    async def team2_plan_now(body: PlanBody):
        return await _svc(eng).nightly_plans(body.date, arm=body.arm)

    @app.post("/api/team2/preopen-now", dependencies=[auth])
    async def team2_preopen_now():
        return await _svc(eng).preopen_complete()

    class ReplayBody(BaseModel):
        overrides: dict | None = None

    @app.post("/api/team2/runs/{run_id}/replay", dependencies=[auth])
    async def team2_replay(run_id: str, body: ReplayBody):
        rep = await _svc(eng).replay(run_id, overrides=body.overrides)
        if rep is None:
            raise HTTPException(status_code=404, detail="run not found")
        return rep

    class SweepBody(BaseModel):
        start: str
        end: str
        symbols: list[str] | None = None
        overrides: dict | None = None
        sigma: float | None = None

    @app.post("/api/team2/sweep", dependencies=[auth])
    async def team2_sweep(body: SweepBody):
        return await _svc(eng).sweep(body.start, body.end, symbols=body.symbols, overrides=body.overrides,
                                     sigma=body.sigma)
