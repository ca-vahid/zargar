"""Standing-order routes (2026-11-14). Drafts are created by Claude from the user's plan; ARMING is the user's
click in the UI (the confirm phrase travels with it). Real-money books also need
`execution.standing_orders.allow_live`, which only the user turns on (Settings).

NOTE: no `from __future__ import annotations` - see api/app.py.
"""
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel


class StandingOrderSpec(BaseModel):
    portfolioId: str
    symbol: str
    side: str
    qty: Optional[float] = None
    budget: Optional[float] = None
    trigger: str = "now"
    notBefore: Optional[str] = None
    expiresOn: Optional[str] = None
    maxPrice: Optional[float] = None
    minPrice: Optional[float] = None
    slippagePct: Optional[float] = None
    takeProfitPct: Optional[float] = None
    stopLossPct: Optional[float] = None
    note: Optional[str] = None


class PlanSpec(BaseModel):
    name: str
    orders: list[StandingOrderSpec]


class ArmBody(BaseModel):
    confirm: str


def _svc(eng):
    svc = getattr(eng, "standing_orders", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="standing orders not attached")
    return svc


def _spec(o: StandingOrderSpec) -> dict:
    return {k: v for k, v in o.model_dump().items() if v is not None}


def build_standing_routes(app, eng, auth, config) -> None:

    @app.get("/api/standing", dependencies=[auth])
    async def standing_list(open_only: bool = False):
        return {"orders": await _svc(eng).list(include_closed=not open_only),
                "allowLive": bool(eng.settings.get("execution.standing_orders.allow_live", False))}

    @app.post("/api/standing", dependencies=[auth])
    async def standing_create(body: StandingOrderSpec):
        try:
            return await _svc(eng).create(_spec(body))
        except (ValueError, AssertionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/standing/plan", dependencies=[auth])
    async def standing_plan(body: PlanSpec):
        try:
            return await _svc(eng).create_plan(body.name, [_spec(o) for o in body.orders])
        except (ValueError, AssertionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/standing/plan/{plan_id}/arm", dependencies=[auth])
    async def standing_plan_arm(plan_id: str, body: ArmBody):
        try:
            return await _svc(eng).arm_plan(plan_id, body.confirm)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/standing/{oid}/arm", dependencies=[auth])
    async def standing_arm(oid: str, body: ArmBody):
        try:
            return await _svc(eng).arm(oid, body.confirm)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/standing/{oid}/disarm", dependencies=[auth])
    async def standing_disarm(oid: str):
        try:
            return await _svc(eng).disarm(oid)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/standing/{oid}/cancel", dependencies=[auth])
    async def standing_cancel(oid: str):
        try:
            return await _svc(eng).cancel(oid)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/standing/{oid}/preflight", dependencies=[auth])
    async def standing_preflight(oid: str):
        try:
            return await _svc(eng).preflight(oid)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
