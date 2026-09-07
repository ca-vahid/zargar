"""Confirmed-fill adoption and provisional protection; never submit an entry.

The strict terminal API stays available. Settlement uses reconcile_entry_fills
to manage confirmed partials before waiting on cancellation. Closing-position
late fills still require a residual-exposure path before live entry activation.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import math
from weakref import WeakKeyDictionary

from sqlalchemy import select

from ...execution.positions import POSITION_SCALED
from ...execution.serialization import position_guard
from ...models import ManagedPositionRow, Order, TechniqueArmed, TechniqueRun
from .data import DailyBar
from .exits import ExitCampaign
from .plans import CartelPlan
from .position_adapter import register_cartel_policy
from .residuals import reconcile_residuals

_locks = WeakKeyDictionary()


async def adopt_confirmed_entry(engine, run_id: str):
    # One engine owns a runtime DB. Serialize local holdings allocation across
    # different runs as well as the per-run database lock below.
    async with _locks.setdefault(engine.position_manager, asyncio.Lock()):
        return await _adopt_confirmed_entry(engine, run_id)


async def reconcile_entry_fills(engine, run_id: str):
    """Protect confirmed working fills; reconcile growth before terminal handoff."""
    async with _locks.setdefault(engine.position_manager, asyncio.Lock()):
        return await _adopt_confirmed_entry(engine, run_id, allow_working=True)


async def _adopt_confirmed_entry(engine, run_id: str, *, allow_working=False):
    register_cartel_policy(engine)
    manager = engine.position_manager
    async with engine.sf() as session, session.begin():
        armed = await session.scalar(select(TechniqueArmed).where(TechniqueArmed.run_id == run_id,
                                                                 TechniqueArmed.technique == "options_cartel").with_for_update())
        if armed is None:
            raise KeyError("Cartel armed state not found")
        if armed.mode == "alert":
            raise ValueError("an alert-only plan cannot own an entry adoption")
        run = await session.scalar(select(TechniqueRun).where(TechniqueRun.id == run_id,
                                                             TechniqueRun.technique == "options_cartel"))
        if run is None:
            raise ValueError("owned plan is missing")
        oid = armed.state.get("orderId")
        order = await session.get(Order, oid) if oid else None
        if order is None or order.technique != "options_cartel" or order.portfolio_id != armed.portfolio_id \
                or armed.state.get("attemptTag") not in (order.tags or []):
            raise ValueError("entry order is not associated with this attempt")
        reserved = armed.state.get("intent") or {}
        if any(getattr(order, key) != reserved.get(key) for key in ("symbol", "sec_type", "side", "qty", "portfolio_id")):
            raise ValueError("entry order differs from the reserved intent; reconcile before adoption")
        terminal = order.status in ("FILLED", "CANCELLED", "EXPIRED", "REJECTED")
        if not terminal and not allow_working:
            raise ValueError("entry is still working; cancel/reconcile and protect partial exposure first")
        qty, price = float(order.filled_qty), float(order.avg_fill_price or 0)
        if order.side != "BUY" or not qty.is_integer() or qty <= 0 or not math.isfinite(price) or price <= 0:
            raise ValueError("adoption requires confirmed bought whole units and an actual fill price")
        if qty > order.qty:
            raise ValueError("entry cumulative fills exceed the submitted quantity")
        position_id = "cartel-" + hashlib.sha256(oid.encode()).hexdigest()[:40]
        existing = await session.get(ManagedPositionRow, position_id)
        if existing is not None:
            if existing.technique != "options_cartel" or existing.portfolio_id != order.portfolio_id \
                    or existing.config.get("runId") != run_id:
                raise ValueError("adoption identity ownership mismatch")
            if float(existing.config["policy"]["cartel"]["initialQty"]) != qty and not allow_working:
                raise ValueError("late additional entry fill requires dedicated reconciliation")
            if existing.status != "closed" and manager.get(position_id) is None:
                raise RuntimeError("restore the persisted position manager before rebinding adoption")
            async with position_guard(manager, position_id):
                managed = manager.get(position_id)
                status = managed.status if managed is not None else existing.status
                if allow_working and status in ("closing", "closed"):
                    return await reconcile_residuals(engine, session, armed, existing, order, terminal=terminal)
                if existing.status != "closed":
                    if allow_working:
                        await _reconcile_quantity(engine, managed, order, terminal=terminal)
                    manager.start()
                    if engine.started:
                        for symbol in {managed.symbol, *(leg.symbol for leg in managed.open_legs)}:
                            await engine.ensure_symbol(symbol)
                    await manager._ensure_venue_stop(managed)
                elif float(existing.config["policy"]["cartel"]["initialQty"]) != qty:
                    raise ValueError("late fill after closed protection requires residual exposure reconciliation")
            armed.state = {**armed.state, "phase": "closed" if existing.status == "closed" else "managed",
                           "managedPositionId": position_id, "adoptedEntryQty": qty, "adoptedEntryPrice": price}
            if not terminal and existing.status != "closed":
                armed.state = {**armed.state, "phase": "entry_protected"}
            if existing.status == "closed":
                armed.status = armed.state.get("retireTo") or "disarmed"
            return {"positionId": position_id, "reused": True, "status": existing.status}
        plan = CartelPlan.model_validate(run.result["plan"]["plan"])
        held = engine.positions.position_qty(order.portfolio_id, order.symbol, order.sec_type)
        allocated = sum(abs(leg["qty"]) for managed in manager.positions()
                        if managed["portfolioId"] == order.portfolio_id and managed["status"] != "closed"
                        for leg in managed["legs"] if leg["symbol"] == order.symbol and leg["secType"] == order.sec_type)
        if held-allocated < qty-1e-8:
            raise ValueError("confirmed order no longer has sufficient unallocated portfolio holdings; reconcile first")
        signal = armed.state.get("signal") or {}
        reference, stop = float(signal.get("referencePrice", 0)), float(signal.get("stop", 0))
        if reference <= 0 or stop <= 0 or (reference-stop)*(1 if plan.direction == "long" else -1) <= 0:
            raise ValueError("confirmed signal stop geometry is missing or invalid")
        campaign = ExitCampaign.model_validate(run.result["exitCampaign"])
        history = [DailyBar.model_validate(b).model_dump(mode="json") for b in run.config["inputs"]["history"]]
        options = order.sec_type == "OPT"
        execution_config = armed.config.get("execution", armed.config)
        acknowledged = execution_config.get("overnightAck", execution_config.get("overnight_ack", False)) is True
        if options and not acknowledged:
            raise ValueError("option overnight protection was not acknowledged")
        spec = {"positionId": position_id, "portfolioId": order.portfolio_id, "symbol": plan.symbol,
                "direction": plan.direction, "techniqueId": "options_cartel", "runId": run_id,
                "entry": reference, "risk": abs(reference-stop), "tags": list(order.tags or []),
                "overnight": "app_managed" if options else "venue_stop", "overnightAck": acknowledged,
                "legs": [{"symbol": order.symbol, "secType": order.sec_type, "qty": int(qty),
                          "avgFill": price, "multiplier": 100 if options else 1, "entryOrderId": oid}],
                "policy": {"adapter": "options_cartel", "timeframe": "1d", "stop": {"kind": "fixed", "price": stop},
                           "cartel": {"campaign": campaign.model_dump(mode="json"), "daily": history,
                                      "initialQty": int(qty), "entryPending": not terminal,
                                      "entryFilledNotional": qty*price}}}
        # Armed-row lock spans adoption; competing callbacks cannot create a
        # second manager. Deterministic identity survives a crash before binding.
        adopted = await manager.adopt(spec)
        stored = await session.get(ManagedPositionRow, position_id)
        if stored is None:
            raise RuntimeError("managed adoption did not persist")
        armed.state = {**armed.state, "phase": "managed" if terminal else "entry_protected", "managedPositionId": position_id,
                       "adoptedEntryQty": qty, "adoptedEntryPrice": price}
        return {"positionId": position_id, "reused": False, "status": adopted["status"]}


async def _reconcile_quantity(engine, p, order, *, terminal):
    manager = engine.position_manager
    async with position_guard(manager, p.id):
        adapter = manager._policy_adapter(p)
        context = p.policy["cartel"]
        old_qty = int(context["initialQty"])
        qty = int(order.filled_qty)
        delta = qty-old_qty
        if delta < 0:
            raise ValueError("entry cumulative fill quantity regressed")
        if delta and p.status != "open":
            raise ValueError("late fill while protection is closing requires residual exposure reconciliation")
        held = engine.positions.position_qty(order.portfolio_id, order.symbol, order.sec_type)
        allocated = sum(abs(leg.qty) for position in manager._pos.values() if position.status != "closed"
                        and position.portfolio_id == order.portfolio_id for leg in position.open_legs
                        if leg.symbol == order.symbol and leg.sec_type == order.sec_type)
        if held-allocated < delta-1e-8:
            raise ValueError("new entry fills lack unallocated portfolio holdings")
        saved = copy.deepcopy(p.__dict__)
        try:
            _, state = adapter._sync(p)
            context = dict(p.policy["cartel"])
            notional = qty*float(order.avg_fill_price)
            previous_notional = float(context.get("entryFilledNotional", old_qty*p.legs[0].avg_fill))
            if delta:
                added_price = (notional-previous_notional)/delta
                if not math.isfinite(added_price) or added_price <= 0:
                    raise ValueError("invalid incremental entry fill price")
                leg = p.legs[0]
                leg.avg_fill = (leg.qty*leg.avg_fill+delta*added_price)/(leg.qty+delta)
                leg.qty += delta
                state = state.model_copy(update={"initial_qty": qty, "remaining_qty": state.remaining_qty+delta})
                request = context.get("closeRequest")
                if request and request["remaining"] > 0:
                    context["closeRequest"] = {**request, "remaining": request["remaining"]+delta}
                p.venue_stop_at = None  # quantity changed, even when the stop price did not
            elif abs(notional-previous_notional) > 1e-7:
                raise ValueError("entry fill-price correction requires accounting reconciliation")
            context.update(initialQty=qty, entryPending=not terminal, entryFilledNotional=notional,
                           state=state.model_dump(mode="json"))
            p.policy = {**p.policy, "cartel": context}
            p.entry_mark = manager._entry_mark(p)
            await manager._persist(p)
        except Exception:
            p.__dict__.clear()
            p.__dict__.update(saved)
            raise
        if delta:
            await manager._journal(POSITION_SCALED, p, {"entryOrderId": order.id,
                                   "confirmedEntryQty": qty, "addedQty": delta,
                                   "addedFillPrice": added_price, "entryPending": not terminal})
