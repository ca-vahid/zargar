"""Read-only, restart-safe Cartel entry gating from persisted execution evidence."""
from __future__ import annotations

from sqlalchemy import select

from ...models import ManagedPositionRow, Order, TechniqueArmed

TERMINAL = {"FILLED", "CANCELLED", "EXPIRED", "REJECTED", "REJECTED_RISK"}
WORKING = {"NEW", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED", "WORKING"}


async def execution_readiness(engine, portfolio_id, symbol, *, ignore_attempt_run_id=None):
    """Block new exposure only; never mutate state or obstruct protective exits."""
    symbol = symbol.upper()
    async with engine.sf() as session:
        positions = (await session.scalars(select(ManagedPositionRow).where(
            ManagedPositionRow.technique == "options_cartel", ManagedPositionRow.portfolio_id == portfolio_id,
            ManagedPositionRow.symbol == symbol))).all()
        armed = (await session.scalars(select(TechniqueArmed).where(
            TechniqueArmed.technique == "options_cartel", TechniqueArmed.portfolio_id == portfolio_id,
            TechniqueArmed.symbol == symbol))).all()
        orders = (await session.scalars(select(Order).where(Order.technique == "options_cartel",
                                                          Order.portfolio_id == portfolio_id))).all()
    blockers = []

    def block(code, reason, *, position_id=None, run_id=None, order_id=None):
        blockers.append({"code": code, "reason": reason, "positionId": position_id,
                         "runId": run_id, "orderId": order_id})

    def matching(tag, oid):
        return [o for o in orders if tag in (o.tags or [])] if tag else [o for o in orders if o.id == oid]

    for p in positions:
        if p.status != "closed" and engine.position_manager.get(p.id) is None:
            block("position_not_restored", "Restore the existing position before adding exposure.", position_id=p.id)
        if p.status != "closed" and p.state.get("haltEntries"):
            block("position_reconciliation_halt", "Existing position requires reconciliation.", position_id=p.id)
        context = p.config.get("policy", {}).get("cartel", {})
        if p.status == "closing" or context.get("closeRequest") and p.status != "closed":
            block("close_in_progress", "An existing Cartel close is still in progress.", position_id=p.id)
        exits = list(p.state.get("exits") or [])
        stop_id = p.state.get("venueStopOrderId")
        if stop_id and not any(r.get("orderId") == stop_id for r in exits):
            block("stop_not_reconciled", "Existing venue-stop identity is not reconciled in the exit ledger.",
                  position_id=p.id, order_id=stop_id)
        for rec in exits:
            matches = matching(rec.get("attemptTag"), rec.get("orderId"))
            if len(matches) != 1:
                block("exit_outcome_unknown", "Exit attempt has no unique persisted owned order.", position_id=p.id,
                      order_id=rec.get("orderId"))
                continue
            order = matches[0]
            expected = rec.get("intent")
            if order.side != "SELL" or order.symbol != rec.get("leg") or order.qty != rec.get("qty") \
                    or (expected and any(getattr(order, key) != expected.get(key) for key in
                                         ("sec_type", "order_type", "limit_price", "stop_price", "tif"))):
                block("exit_identity_mismatch", "Exit order differs from its persisted intent.",
                      position_id=p.id, order_id=order.id)
                continue
            if rec.get("orderId") != order.id or rec.get("status") != order.status:
                block("exit_not_reconciled", "Exit status/identity must be reconciled before another entry.",
                      position_id=p.id, order_id=order.id)
            if float(rec.get("filledQty") or 0) != order.filled_qty:
                block("exit_fills_unreconciled", "Exit fills have not been applied to the managed position.",
                      position_id=p.id, order_id=order.id)
            if order.filled_qty > 0 and rec.get("price") != order.avg_fill_price:
                block("exit_price_unreconciled", "Exit fill price correction has not been reconciled.",
                      position_id=p.id, order_id=order.id)
            if order.status not in TERMINAL | WORKING:
                block("exit_outcome_unknown", "Exit order outcome remains unknown.", position_id=p.id, order_id=order.id)
            if order.status not in TERMINAL and (rec.get("cancelAttempts") or p.status == "closed"):
                block("exit_cancellation_pending", "A cancelled/closed campaign still has a working exit.",
                      position_id=p.id, order_id=order.id)
    position_ids = {p.id for p in positions}
    for row in armed:
        state = row.state
        if row.run_id == ignore_attempt_run_id or row.mode == "alert" or state.get("submissionAborted") \
                or not state.get("attemptTag"):
            continue
        # Exit tags retain entry lineage; only bought entry orders own this reservation.
        matches = [o for o in matching(state["attemptTag"], state.get("orderId")) if o.side == "BUY"]
        if len(matches) != 1:
            block("entry_outcome_unknown", "An earlier entry submission has no unique owned order.", run_id=row.run_id)
            continue
        order = matches[0]
        if state.get("orderId") != order.id:
            block("entry_not_reconciled", "Earlier entry order identity has not been reconciled.", run_id=row.run_id)
        expected = state.get("intent") or {}
        if any(getattr(order, key) != expected.get(key) for key in
               ("symbol", "side", "sec_type", "qty", "order_type", "limit_price")):
            block("entry_identity_mismatch", "Earlier entry order differs from its reserved intent.", run_id=row.run_id)
        if order.status not in TERMINAL:
            block("entry_not_settled", "An earlier entry order is still working or unresolved.", run_id=row.run_id)
        if order.filled_qty != float(state.get("adoptedEntryQty") or 0) or order.filled_qty > 0 \
                and state.get("managedPositionId") not in position_ids:
            block("entry_fills_unmanaged", "Earlier entry fills require managed-position reconciliation.", run_id=row.run_id)
    return {"passed": not blockers, "portfolioId": portfolio_id, "symbol": symbol, "blockers": blockers}
