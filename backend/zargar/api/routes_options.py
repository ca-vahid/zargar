"""Options routes: chain browsing, contract quotes, broker preview, capability.

NOTE: no `from __future__ import annotations` — see api/app.py.
"""
from fastapi import HTTPException, Query
from pydantic import BaseModel

from ..options import occ
from ..options.chain import OptionsError


def _svc(eng):
    if eng.options is None:
        raise HTTPException(status_code=503, detail="options layer not attached")
    return eng.options


def build_options_routes(app, eng, auth, config) -> None:

    @app.get("/api/options/capabilities", dependencies=[auth])
    async def options_capabilities():
        return {"accounts": list(_svc(eng).capabilities().values())}

    @app.get("/api/options/expiring", dependencies=[auth])
    async def options_expiring(days: int = Query(default=2, ge=0, le=60)):
        return _svc(eng).expiring(days)

    @app.get("/api/options/quote/{symbol}", dependencies=[auth])
    async def options_quote(symbol: str):
        if not occ.is_occ(symbol):
            raise HTTPException(status_code=400, detail=f"{symbol!r} is not an OCC option symbol")
        svc = _svc(eng)
        await eng.ensure_symbol(occ.normalize(symbol))
        try:
            return await svc.contract(symbol)
        except OptionsError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/options/{underlying}/expiries", dependencies=[auth])
    async def options_expiries(underlying: str):
        try:
            return await _svc(eng).expiries(underlying)
        except OptionsError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/options/{underlying}/chain", dependencies=[auth])
    async def options_chain(underlying: str, expiry: str = Query(min_length=10, max_length=10)):
        try:
            return await _svc(eng).chain(underlying, expiry)
        except OptionsError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    class ImpactBody(BaseModel):
        portfolio_id: str
        symbol: str
        side: str
        qty: float
        order_type: str = "LMT"
        limit_price: float | None = None

    @app.post("/api/options/impact", dependencies=[auth])
    async def options_impact(body: ImpactBody):
        """Broker-side preview of an option order (SnapTrade impact) — read-only.

        Also the live capability probe: code 1156 marks the account unsupported.
        """
        if not occ.is_occ(body.symbol):
            raise HTTPException(status_code=400, detail=f"{body.symbol!r} is not an OCC option symbol")
        if eng.snaptrade_sync is None or eng.snaptrade is None:
            raise HTTPException(status_code=503, detail="SnapTrade is not configured")
        action = None
        if eng.orders is not None:
            action = eng.orders.option_action(body.portfolio_id, occ.normalize(body.symbol), body.side, body.qty)
        return await _svc(eng).impact(
            body.portfolio_id, symbol=occ.normalize(body.symbol), side=body.side, qty=body.qty,
            order_type=body.order_type, limit_price=body.limit_price, action=action)
