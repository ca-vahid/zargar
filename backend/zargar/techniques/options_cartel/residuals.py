"""Late entry fills after campaign closure: separate, linked exposure to flatten.

Never reopen the original campaign or infer an exit from a cancellation response.
Persisted fill ranges identify residual adoptions after an interrupted binding.
"""
from __future__ import annotations

import copy
import hashlib
import math

from sqlalchemy import select

from ...execution.serialization import position_guard
from ...models import ManagedPositionRow, Order
from ...orders import order_dict

TERMINAL = {"FILLED", "CANCELLED", "EXPIRED", "REJECTED", "REJECTED_RISK"}


async def reconcile_residuals(engine, session, armed, original, order, *, terminal):
    """Caller holds the entry row and original-position guards."""
    manager = engine.position_manager
    base = original.config["policy"]["cartel"]
    covered = int(base["initialQty"])
    notional = float(base.get("entryFilledNotional", covered*original.legs[0]["avgFill"]))
    rows = (await session.scalars(select(ManagedPositionRow).where(
        ManagedPositionRow.technique == "options_cartel", ManagedPositionRow.portfolio_id == armed.portfolio_id))).all()
    residuals = [r for r in rows if r.config.get("runId") == armed.run_id
                 and r.config.get("policy", {}).get("cartel", {}).get("residualOf") == original.id]
    residuals.sort(key=lambda r: r.config["policy"]["cartel"]["fromQty"])
    for row in residuals:
        c = row.config["policy"]["cartel"]
        if row.status != "closed" and manager.get(row.id) is None:
            raise RuntimeError("restore residual position management before reconciliation")
        if c["fromQty"] != covered or c["toQty"]-covered != c["initialQty"] \
                or abs(c["fromNotional"]-notional) > 1e-7:
            raise ValueError("residual entry fill ranges overlap or have a gap")
        covered, notional = int(c["toQty"]), float(c["toNotional"])
    total, total_notional = int(order.filled_qty), float(order.filled_qty)*float(order.avg_fill_price)
    if total < covered:
        raise ValueError("entry cumulative fill quantity regressed below allocated residuals")
    if total == covered and abs(total_notional-notional) > 1e-7:
        raise ValueError("entry fill-price correction requires accounting reconciliation")
    if total > covered:
        qty = total-covered
        price = (total_notional-notional)/qty
        if not math.isfinite(price) or price <= 0:
            raise ValueError("invalid residual fill cost")
        allocated = sum(abs(leg.qty) for p in manager._pos.values() if p.status != "closed"
                        and p.portfolio_id == order.portfolio_id for leg in p.open_legs
                        if leg.symbol == order.symbol and leg.sec_type == order.sec_type)
        held = engine.positions.position_qty(order.portfolio_id, order.symbol, order.sec_type)
        if held-allocated < qty-1e-8:
            raise ValueError("residual fills lack unallocated portfolio holdings")
        identity = hashlib.sha256(f"{order.id}:{covered}:{total}".encode()).hexdigest()[:40]
        context = {"campaign": copy.deepcopy(base["campaign"]), "daily": copy.deepcopy(base["daily"]),
                   "initialQty": qty, "entryPending": True, "residualOf": original.id,
                   "fromQty": covered, "toQty": total, "fromNotional": notional, "toNotional": total_notional}
        spec = {"positionId": f"cartel-residual-{identity}", "portfolioId": order.portfolio_id,
                "symbol": original.symbol, "direction": original.config["direction"],
                "techniqueId": "options_cartel", "runId": armed.run_id,
                "entry": original.config["entry"], "risk": original.config["risk"],
                "overnight": "day_only", "tags": list(order.tags or []),
                "legs": [{"symbol": order.symbol, "secType": order.sec_type, "qty": qty,
                          "avgFill": price, "entryOrderId": order.id, "multiplier": 100 if order.sec_type == "OPT" else 1}],
                "policy": {"adapter": "options_cartel", "timeframe": "1d",
                           "stop": copy.deepcopy(original.config["policy"]["stop"]), "cartel": context}}
        result = await manager.adopt(spec)
        created = await session.get(ManagedPositionRow, result["id"])
        if created is None:
            raise RuntimeError("residual adoption did not persist")
        residuals.append(created)
    statuses = []
    for row in residuals:
        await session.refresh(row)
        p = manager.get(row.id)
        if row.status != "closed" and p is None:
            raise RuntimeError("restore residual position management before reconciliation")
        if p is not None and p.status != "closed":
            await drain_residual(manager, p)
        statuses.append(p.status if p is not None else row.status)
    primary = manager.get(original.id)
    primary_status = primary.status if primary is not None else original.status
    all_closed = primary_status == "closed" and all(s == "closed" for s in statuses)
    done = terminal and all_closed
    armed.status = (armed.state.get("retireTo") or "disarmed") if done else "closing"
    armed.state = {**armed.state, "phase": "closed" if done else "residual_closing",
                   "managedPositionId": original.id, "residualPositionIds": [r.id for r in residuals],
                   "adoptedEntryQty": total, "adoptedEntryPrice": float(order.avg_fill_price)}
    return {"positionId": original.id, "reused": True, "status": "closed" if done else "closing",
            "residualPositionIds": [r.id for r in residuals]}


async def _attention(manager, p, message):
    if message not in p.attention:
        p.attention.append(message)
        await manager._alert(p, message, stage="cartel_residual")


async def drain_residual(manager, p):
    """Retry only an authoritative terminal exit, never a timeout/unknown submit."""
    async with position_guard(manager, p.id):
        if p.status == "closed" or not p.open_legs:
            return
        p.status = "closing"
        for rec in p.exits:
            # Every residual exit uses the manager's write-ahead intent/tag.
            async with manager.engine.sf() as session:
                candidates = (await session.scalars(select(Order).where(
                    Order.portfolio_id == p.portfolio_id, Order.technique == p.technique))).all()
            matches = [o for o in candidates if rec.get("attemptTag") in (o.tags or [])]
            expected = rec.get("intent") or {}
            if len(matches) != 1 or any(getattr(matches[0], k) != expected.get(k)
                    for k in ("symbol", "sec_type", "side", "qty", "order_type", "limit_price", "portfolio_id")):
                await _attention(manager, p, "Residual exit outcome is unresolved; reconcile its persisted attempt before retry.")
                return
            order = matches[0]
            if rec.get("orderId") not in (None, order.id):
                await _attention(manager, p, "Residual exit order identity changed; manual reconciliation required.")
                return
            rec["orderId"] = order.id
            manager._register_exit_order(p, order.id)
            if order.filled_qty < float(rec.get("filledQty") or 0):
                await _attention(manager, p, "Residual exit fill quantity regressed; accounting reconciliation required.")
                return
            if order.filled_qty > float(rec.get("filledQty") or 0):
                if not order.avg_fill_price or not math.isfinite(order.avg_fill_price) \
                        or order.filled_qty > rec["qty"] or not float(order.filled_qty).is_integer():
                    await _attention(manager, p, "Residual exit has invalid fill accounting; reconciliation required.")
                    return
                await manager.on_order_update({**order_dict(order), "status": "PARTIALLY_FILLED"})
            await manager.on_order_update(order_dict(order))
            rec["status"] = order.status
            if p.status == "closed":
                return
            if order.status not in TERMINAL:
                await manager._persist(p)
                return
        if len(p.exits) >= 5:
            await _attention(manager, p, "Residual exit exhausted five confirmed attempts; close remaining exposure at the broker.")
            return
        if p.exits and manager.now_ms()-p.exits[-1]["ts"] < 30_000:
            return
        await manager._persist(p)
        await manager._close_leg(p, p.open_legs[0], abs(p.open_legs[0].qty), force_market=True,
                                 kind="residual", reason="Late entry fill after campaign closure; flatten residual exposure.")
