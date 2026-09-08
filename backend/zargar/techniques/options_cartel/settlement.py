"""Protect confirmed Cartel fills, then cancel/reconcile the remaining entry.

Never infer cancellation from a cancel() return value. Order reports persisted
by OrderManager are authoritative. Working partials use provisional stop/expiry
management. Terminal settlement enables the campaign's profit-taking rules.
"""
from __future__ import annotations

import asyncio
import logging
import time

from ...models import Order
from .adoption import reconcile_entry_fills
from .state import ArmRepository

TERMINAL = {"FILLED", "CANCELLED", "EXPIRED", "REJECTED", "REJECTED_RISK"}
log = logging.getLogger("zargar.options_cartel.settlement")


async def _order(engine, repository, run_id):
    state = await repository.load(run_id)
    if state is None:
        raise KeyError("Cartel armed record not found")
    oid = state["state"].get("orderId")
    async with engine.sf() as session:
        order = await session.get(Order, oid) if oid else None
    if order is None or order.technique != "options_cartel" or order.portfolio_id != state["portfolioId"] \
            or state["state"].get("attemptTag") not in (order.tags or []):
        raise ValueError("entry order ownership is unresolved")
    if order.filled_qty < state["state"].get("adoptedEntryQty", 0):
        raise ValueError("entry cumulative fill quantity regressed below managed exposure")
    return state, order


async def settle_entry(engine, run_id, *, request_cancel=False, wait_seconds=3.):
    if not 0 <= wait_seconds <= 10:
        raise ValueError("settlement wait must be between zero and ten seconds")
    repository = ArmRepository(engine)
    state, order = await _order(engine, repository, run_id)
    protection = None
    if order.filled_qty > 0:
        # Persist management before a cancel call/poll can block. Profit-taking
        # stays disabled while the entry is working; stop/expiry protection runs.
        protection = await reconcile_entry_fills(engine, run_id)
    should_cancel = request_cancel or order.filled_qty > 0 or state["status"] in ("paused", "closing", "disarmed", "expired")
    if order.status not in TERMINAL and should_cancel:
        reserved = False
        now = int(time.time()*1000)
        async with engine.sf() as session, session.begin():
            row = await repository._locked(session, run_id)
            attempts = int(row.state.get("cancelAttempts", 0))
            last = row.state.get("cancelRequestedAt")
            if attempts < 5 and (last is None or now-last >= 30_000):
                row.state = {**row.state, "cancelRequestedAt": now, "cancelAttempts": attempts+1,
                             "cancelOrderId": order.id}
                reserved = True
                snapshot = repository.view(row)
        if reserved:
            await repository._journal(snapshot, "entry_cancel_requested")
            try:
                await engine.orders.cancel(order.id)
            except Exception as exc:
                log.exception("Cartel entry cancellation failed for %s", order.id)
                async with engine.sf() as session, session.begin():
                    row = await repository._locked(session, run_id)
                    row.state = {**row.state, "phase": "needs_attention",
                                 "cancelError": f"{type(exc).__name__}: {exc}"}
                    snapshot = repository.view(row)
                await repository._journal(snapshot, "entry_cancel_failed")
        deadline = time.monotonic()+wait_seconds
        while True:
            state, order = await _order(engine, repository, run_id)
            if order.status in TERMINAL or time.monotonic() >= deadline:
                break
            await asyncio.sleep(min(.1, max(0, deadline-time.monotonic())))
    if order.status in TERMINAL:
        if order.filled_qty > 0:
            adoption = await reconcile_entry_fills(engine, run_id)
            return {"runId": run_id, "status": adoption["status"] if adoption["status"] in ("closed", "closing") else "managed",
                    "orderId": order.id, "filledQty": order.filled_qty, "adoption": adoption,
                    "needsProtection": False, "placesEntryOrders": False}
        async with engine.sf() as session, session.begin():
            row = await repository._locked(session, run_id)
            row.status = row.state.get("retireTo") or "disarmed"
            row.state = {**row.state, "phase": "closed", "orderStatus": order.status, "filledQty": 0}
            snapshot = repository.view(row)
        await repository._journal(snapshot, "entry_closed_unfilled")
        return {"runId": run_id, "status": "closed_unfilled", "orderId": order.id,
                "filledQty": 0, "needsProtection": False, "placesEntryOrders": False}
    if should_cancel:
        if order.filled_qty > 0:
            protection = await reconcile_entry_fills(engine, run_id)
        async with engine.sf() as session, session.begin():
            row = await repository._locked(session, run_id)
            # Another callback may have finished adoption while this callback
            # was polling. Do not overwrite that newer durable state.
            if row.state.get("phase") == "managed" and order.filled_qty <= row.state.get("adoptedEntryQty", 0):
                return {"runId": run_id, "status": "managed", "orderId": order.id,
                        "filledQty": order.filled_qty, "needsProtection": False, "placesEntryOrders": False}
            row.state = {**row.state, "phase": "needs_attention", "orderStatus": order.status,
                         "filledQty": order.filled_qty,
                         "recoveryReason": "Cancellation not confirmed; do not resubmit. Continue reconciling managed partial exposure."}
            snapshot = repository.view(row)
        await repository._journal(snapshot, "entry_cancel_unconfirmed")
    return {"runId": run_id, "status": "cancel_pending" if should_cancel else "working",
            "orderId": order.id, "filledQty": order.filled_qty,
            "needsProtection": order.filled_qty > 0 and protection is None, "protection": protection,
            "placesEntryOrders": False}
