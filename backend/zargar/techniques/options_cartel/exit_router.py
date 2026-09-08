"""Verified cancellation and quantity accounting for Cartel's primary exits."""
from __future__ import annotations

import math

from sqlalchemy import select

from ...events import MANAGED_EXIT_CANCEL_REQUESTED
from ...execution.serialization import position_guard
from ...models import Order
from ...orders import OrderIntent, order_dict

TERMINAL = {"FILLED", "CANCELLED", "EXPIRED", "REJECTED", "REJECTED_RISK"}


class CartelExitRouter:
    def __init__(self):
        self.busy = set()

    @staticmethod
    def pending_qty(p, symbol):
        return sum(max(0., float(r["qty"])-float(r.get("filledQty") or 0)) for r in p.exits
                   if r["leg"] == symbol and r.get("status") not in TERMINAL)

    async def attention(self, manager, p, message):
        if message not in p.attention:
            p.attention.append(message)
            await manager._alert(p, message, stage="cartel_exit_reconciliation")

    async def refresh(self, manager, p):
        """Apply cumulative fills before using terminal status as cancellation proof."""
        async with manager.engine.sf() as session:
            orders = (await session.scalars(select(Order).where(Order.portfolio_id == p.portfolio_id,
                                                                 Order.technique == p.technique))).all()
        if p.venue_stop_order_id and not any(r.get("orderId") == p.venue_stop_order_id for r in p.exits):
            old = next((o for o in orders if o.id == p.venue_stop_order_id), None)
            if old is None or old.side != "SELL" or old.symbol != p.legs[0].symbol or old.order_type != "STP":
                await self.attention(manager, p, "Existing Cartel venue stop cannot be verified; reconcile before replacement.")
                return False
            p.exits.append({"kind": "venue_stop", "leg": old.symbol, "qty": old.qty,
                            "orderId": old.id, "filledQty": 0, "status": None, "ts": manager.now_ms()})
        for rec in list(p.exits):
            # Filled records already applied by the manager never become new exposure.
            if rec.get("status") == "FILLED" and float(rec.get("filledQty") or 0) >= float(rec["qty"]):
                continue
            matches = [o for o in orders if (rec.get("attemptTag") in (o.tags or []) if rec.get("attemptTag")
                                            else o.id == rec.get("orderId"))]
            expected = rec.get("intent")
            if len(matches) != 1 or matches[0].side != "SELL" or matches[0].symbol != rec["leg"] \
                    or matches[0].qty != rec["qty"] or (expected and any(getattr(matches[0], k) != expected.get(k)
                        for k in ("sec_type", "order_type", "limit_price", "stop_price", "tif"))):
                await self.attention(manager, p, "Cartel exit outcome is unresolved; no replacement is allowed until reconciled.")
                return False
            order = matches[0]
            if rec.get("orderId") not in (None, order.id):
                await self.attention(manager, p, "Cartel exit identity changed; manual reconciliation required.")
                return False
            rec["orderId"] = order.id
            manager._register_exit_order(p, order.id)
            if rec["kind"] == "venue_stop" and order.status not in TERMINAL:
                p.venue_stop_order_id, p.venue_stop_at = order.id, order.stop_price
            previous = float(rec.get("filledQty") or 0)
            if order.filled_qty < previous or order.filled_qty > rec["qty"] or not float(order.filled_qty).is_integer():
                await self.attention(manager, p, "Cartel exit cumulative fills are inconsistent; reconciliation required.")
                return False
            if order.filled_qty > previous:
                if not order.avg_fill_price or not math.isfinite(order.avg_fill_price):
                    await self.attention(manager, p, "Cartel exit fill price is missing; reconciliation required.")
                    return False
                await manager.on_order_update({**order_dict(order), "status": "PARTIALLY_FILLED"})
            await manager.on_order_update(order_dict(order))
            rec["status"] = order.status
            if p.status == "closed":
                return True
        p.attention = [m for m in p.attention if not m.startswith(("Cartel exit outcome", "Cartel exit identity",
                       "Cartel exit cumulative", "Cartel exit fill price", "Existing Cartel venue stop"))]
        await manager._persist(p)
        return True

    async def cancel(self, manager, p, records):
        for rec in records:
            if rec.get("status") in TERMINAL:
                continue
            if not rec.get("orderId"):
                return False
            attempts = int(rec.get("cancelAttempts", 0))
            if attempts < 5 and manager.now_ms()-rec.get("cancelRequestedAt", -10**15) >= 30_000:
                rec.update(cancelAttempts=attempts+1, cancelRequestedAt=manager.now_ms())
                await manager._journal(MANAGED_EXIT_CANCEL_REQUESTED, p,
                                       {"orderId": rec["orderId"], "attempt": attempts+1})
                try:
                    await manager.engine.orders.cancel(rec["orderId"])
                except Exception as exc:  # noqa: BLE001 - cancellation outcome stays unresolved
                    await self.attention(manager, p, f"Cartel exit cancellation failed: {exc}")
            if attempts >= 5:
                await self.attention(manager, p, "Cartel exit cancellation exhausted five attempts; broker review required.")
        if not await self.refresh(manager, p):
            return False
        ready = all(r.get("status") in TERMINAL for r in records)
        if not ready:
            await self.attention(manager, p, "Cartel exit cancellation is pending; existing fills/orders still count.")
        elif not any(r.get("cancelAttempts") and r.get("status") not in TERMINAL for r in p.exits):
            p.attention = [m for m in p.attention if not m.startswith("Cartel exit cancellation")]
            await manager._persist(p)
        return ready

    async def ensure_stop(self, manager, p):
        async with position_guard(manager, p.id):
            if p.id in self.busy:
                return
            self.busy.add(p.id)
            try:
                if await self.refresh(manager, p):
                    await self._ensure_stop(manager, p)
            finally:
                self.busy.remove(p.id)

    async def _ensure_stop(self, manager, p):
        if p.overnight != "venue_stop" or p.status != "open" or not p.open_legs:
            return
        request = p.policy["cartel"].get("closeRequest")
        if request and (request["remaining"] == 0 or not request.get("submittedTag")):
            return
        leg = p.open_legs[0]
        pending_other = sum(max(0., r["qty"]-float(r.get("filledQty") or 0)) for r in p.exits
                            if r["kind"] != "venue_stop" and r.get("status") not in TERMINAL)
        qty = max(0., leg.qty-pending_other)
        stops = [r for r in p.exits if r["kind"] == "venue_stop" and r.get("status") not in TERMINAL]
        history = [r for r in p.exits if r["kind"] == "venue_stop"]
        failures = []
        for record in reversed(history):
            if record.get("status") not in ("REJECTED", "REJECTED_RISK", "EXPIRED"):
                break
            failures.append(record)
        if not stops and failures:
            if len(failures) >= 5:
                await self.attention(manager, p, "Cartel venue stop exhausted five confirmed attempts; broker review required.")
                return
            if manager.now_ms()-failures[0]["ts"] < 30_000:
                return
        if len(stops) == 1 and stops[0]["qty"]-float(stops[0].get("filledQty") or 0) == qty \
                and p.venue_stop_at == p.state.stop:
            return
        if not await self.cancel(manager, p, stops) or p.status != "open" or not p.open_legs:
            return
        p.venue_stop_order_id = p.venue_stop_at = None
        qty = max(0., p.open_legs[0].qty-pending_other)
        if qty <= 0:
            await manager._persist(p)
            return
        await manager._submit_exit(p, OrderIntent(portfolio_id=p.portfolio_id, technique_id=p.technique,
            symbol=leg.symbol, sec_type="STK", side="SELL", qty=qty, order_type="STP",
            stop_price=p.state.stop, tif="GTC", source="technique", tags=list(p.tags), reduce_only=True),
            kind="venue_stop", reason="Protect confirmed Cartel holdings after verified cancellation.")

    async def close(self, manager, p, *, fraction, reason, kind, force_market):
        async with position_guard(manager, p.id):
            if not p.open_legs or p.status == "closed":
                return
            context = dict(p.policy["cartel"])
            old = context.get("closeRequest")
            if old and p.open_legs[0].qty <= old["remaining"]:
                context.pop("closeRequest")
                old = None
            if not old or force_market and not old["forceMarket"]:
                qty = min(p.open_legs[0].qty, max(0, round(p.open_legs[0].qty*min(1., max(0., fraction)))))
                if qty <= 0:
                    return
                context["closeRequest"] = {"remaining": p.open_legs[0].qty-qty, "reason": reason,
                                           "kind": kind, "forceMarket": force_market}
                p.policy = {**p.policy, "cartel": context}
                if fraction >= 1:
                    p.status = "closing"
                await manager._persist(p)
            await self.poll(manager, p)

    async def poll(self, manager, p):
        async with position_guard(manager, p.id):
            if p.id in self.busy:
                return
            self.busy.add(p.id)
            try:
                if not await self.refresh(manager, p) or not p.open_legs or p.status == "closed":
                    return
                request = p.policy["cartel"].get("closeRequest")
                if not request:
                    await self._ensure_stop(manager, p)
                    return
                if request.get("submittedTag"):
                    previous = next(r for r in p.exits if r.get("attemptTag") == request["submittedTag"])
                    if previous.get("status") not in TERMINAL:
                        await self._ensure_stop(manager, p)
                        return
                    if p.open_legs[0].qty <= request["remaining"]:
                        context = dict(p.policy["cartel"])
                        context.pop("closeRequest", None)
                        p.policy = {**p.policy, "cartel": context}
                        await manager._persist(p)
                        await self._ensure_stop(manager, p)
                        return
                    if request.get("attempts", 0) >= 5:
                        await self.attention(manager, p, "Cartel close exhausted five confirmed attempts; broker review required.")
                        return
                    if manager.now_ms()-previous["ts"] < 30_000:
                        return
                pending = [r for r in p.exits if r.get("status") not in TERMINAL]
                if not await self.cancel(manager, p, pending) or not p.open_legs:
                    return
                p.venue_stop_order_id = p.venue_stop_at = None
                qty = max(0., p.open_legs[0].qty-request["remaining"])
                if request.get('reason', '').startswith('Catch-up '):
                    from .catchup_runtime import current_execution_ready
                    if not current_execution_ready(manager, p):
                        return
                if qty:
                    await manager._close_leg(p, p.open_legs[0], qty, force_market=request["forceMarket"],
                                            kind=request["kind"], reason=request["reason"])
                context = dict(p.policy["cartel"])
                if qty and p.open_legs and p.open_legs[0].qty > request["remaining"]:
                    context["closeRequest"] = {**request, "submittedTag": p.exits[-1]["attemptTag"],
                                               "attempts": request.get("attempts", 0)+1}
                else:
                    context.pop("closeRequest", None)
                p.policy = {**p.policy, "cartel": context}
                await manager._persist(p)
                await self._ensure_stop(manager, p)
            finally:
                self.busy.remove(p.id)
