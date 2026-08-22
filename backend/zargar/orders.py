"""OrderManager: intent → risk gate → routing → lifecycle → projections.

Write-ahead discipline: the intent is journaled and persisted before anything
is routed, every risk verdict is journaled, and executor reports drive all
state transitions.
"""
from __future__ import annotations

import asyncio
from typing import Callable

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from . import bus as topics
from . import events as ev
from .brokers.base import BrokerOrder, ExecReport, Executor
from .bus import Bus
from .domain import OrderSide, OrderStatus, OrderType, TimeInForce, new_id
from .events import Journal
from .marketdata import QuoteCache
from .models import Execution, Order
from .options import occ
from .portfolio import PositionKeeper
from .risk import RiskGate


class BracketSpec(BaseModel):
    take_profit: float | None = None      # absolute price
    stop_loss: float | None = None        # absolute price
    take_profit_pct: float | None = None  # % offset from fill
    stop_loss_pct: float | None = None    # % offset from fill

    @property
    def empty(self) -> bool:
        return not any([self.take_profit, self.stop_loss, self.take_profit_pct, self.stop_loss_pct])


class OrderIntent(BaseModel):
    portfolio_id: str
    symbol: str
    sec_type: str = "STK"
    side: str
    qty: float = Field(gt=0)
    order_type: str = "LMT"
    limit_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    tif: str = "DAY"
    bracket: BracketSpec | None = None
    source: str = "manual"
    signal_id: str | None = None
    proposal_id: str | None = None
    dry_run: bool = False
    reduce_only: bool = False   # an exit that only reduces exposure — RiskGate runs the
    #                             reduced (safety-only) check list so a stop/flatten is never
    #                             blocked by an entry cap, the rate/duplicate window, or the
    #                             daily-loss halt (see RiskGate.evaluate)

    @field_validator("symbol")
    @classmethod
    def _sym(cls, v: str) -> str:
        return occ.normalize(v)

    @field_validator("sec_type")
    @classmethod
    def _st(cls, v: str) -> str:
        v = (v or "STK").strip().upper()
        if v not in ("STK", "ETF", "OPT", "CASH"):
            raise ValueError(f"unsupported sec_type {v!r}")
        return v

    @field_validator("side")
    @classmethod
    def _side(cls, v: str) -> str:
        return OrderSide(v.upper()).value

    @field_validator("order_type")
    @classmethod
    def _ot(cls, v: str) -> str:
        return OrderType(v.upper()).value

    @field_validator("tif")
    @classmethod
    def _tif(cls, v: str) -> str:
        return TimeInForce(v.upper()).value


def order_dict(o: Order) -> dict:
    return {
        "id": o.id,
        "portfolioId": o.portfolio_id,
        "symbol": o.symbol,
        "secType": o.sec_type,
        "side": o.side,
        "qty": o.qty,
        "orderType": o.order_type,
        "limitPrice": o.limit_price,
        "stopPrice": o.stop_price,
        "tif": o.tif,
        "status": o.status,
        "filledQty": o.filled_qty,
        "avgFillPrice": o.avg_fill_price,
        "source": o.source,
        "parentId": o.parent_id,
        "ocaGroup": o.oca_group,
        "signalId": o.signal_id,
        "proposalId": o.proposal_id,
        "rejectReason": o.reject_reason,
        "bracket": o.bracket,
        "option": _option_block(o.symbol) if o.sec_type == "OPT" else None,
        "createdAt": o.created_at.isoformat() if o.created_at else None,
        "updatedAt": o.updated_at.isoformat() if o.updated_at else None,
    }


def _option_block(symbol: str) -> dict | None:
    o = occ.parse(symbol)
    return o.to_dict() if o else None


def derive_option_action(side: str, position_qty: float, qty: float) -> str:
    """BUY/SELL + current contract position -> the broker's open/close action.

    A BUY against a short position closes (never flips in one order); a SELL
    against a long position closes; anything else opens.
    """
    if side == "BUY":
        return "BUY_TO_CLOSE" if position_qty < -1e-9 else "BUY_TO_OPEN"
    return "SELL_TO_CLOSE" if position_qty > 1e-9 else "SELL_TO_OPEN"


OPEN_STATUSES = (
    OrderStatus.SUBMITTED.value,
    OrderStatus.ACCEPTED.value,
    OrderStatus.PARTIALLY_FILLED.value,
)


class OrderManager:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        bus: Bus,
        journal: Journal,
        risk: RiskGate,
        settings,
        positions: PositionKeeper,
        quotes: QuoteCache,
        executor_for: Callable[[dict | None], Executor | None],
        ensure_symbol,  # async Callable[[str], None] — make sure quotes flow
    ) -> None:
        self._sf = session_factory
        self._bus = bus
        self._journal = journal
        self._risk = risk
        self._settings = settings
        self._positions = positions
        self._quotes = quotes
        self._executor_for = executor_for
        self._ensure_symbol = ensure_symbol
        self._report_lock = asyncio.Lock()
        # venue capability gate for option orders: portfolio_id -> (ok, reason);
        # the engine points this at OptionsService.allows_options
        self.option_gate: Callable[[str], tuple[bool, str]] | None = None

    def option_action(self, portfolio_id: str, symbol: str, side: str, qty: float) -> str:
        pos = self._positions.position_qty(portfolio_id, occ.normalize(symbol), "OPT")
        return derive_option_action(side.upper(), pos, qty)

    # ------------------------------------------------------------------ place
    async def place(self, intent: OrderIntent) -> dict:
        await self._ensure_symbol(intent.symbol)
        portfolio = self._positions.portfolio(intent.portfolio_id)
        if portfolio is None:
            raise ValueError(f"unknown portfolio: {intent.portfolio_id}")

        is_option = intent.sec_type == "OPT"
        if is_option and not occ.is_occ(intent.symbol):
            raise ValueError(f"{intent.symbol!r} is not an OCC option symbol")
        option_action = (
            self.option_action(intent.portfolio_id, intent.symbol, intent.side, intent.qty)
            if is_option else None)
        if is_option and option_action.endswith("_TO_CLOSE"):
            held = abs(self._positions.position_qty(intent.portfolio_id, intent.symbol, "OPT"))
            if intent.qty > held + 1e-9:
                raise ValueError(
                    f"closing {intent.qty:g} contracts but only {held:g} held - "
                    "split into a close and a separate open")
        order = Order(
            id=new_id(),
            portfolio_id=intent.portfolio_id,
            symbol=intent.symbol,
            sec_type=intent.sec_type,
            side=intent.side,
            qty=intent.qty,
            order_type=intent.order_type,
            limit_price=intent.limit_price,
            stop_price=intent.stop_price,
            tif=intent.tif,
            status=OrderStatus.NEW.value,
            source=intent.source,
            signal_id=intent.signal_id,
            proposal_id=intent.proposal_id,
            bracket=intent.bracket.model_dump() if intent.bracket and not intent.bracket.empty else None,
        )
        async with self._sf() as session:
            session.add(order)
            await session.commit()
        await self._journal.append(
            ev.ORDER_INTENT_CREATED, {**order_dict(order), "optionAction": option_action},
            aggregate_type="order", aggregate_id=order.id, portfolio_id=order.portfolio_id)
        extra_out = {"optionAction": option_action} if option_action else {}

        # ---- risk gate -----------------------------------------------------
        class _P:  # RiskGate expects .kind
            kind = portfolio["kind"]
        verdict = await self._risk.evaluate(intent, _P)
        await self._journal.append(
            ev.RISK_CHECK_PASSED if verdict.passed else ev.RISK_CHECK_FAILED,
            verdict.to_dict(),
            aggregate_type="order", aggregate_id=order.id, portfolio_id=order.portfolio_id)
        if not verdict.passed:
            reason = "; ".join(c.detail or c.name for c in verdict.failures)
            return await self._transition(
                order.id, OrderStatus.REJECTED_RISK, ev.ORDER_REJECTED,
                reject_reason=reason, extra={"risk": verdict.to_dict(), **extra_out})

        # Venue capability: only brokerages verified to accept option orders via
        # SnapTrade get them (Wealthsimple returns code 1156 - never discover
        # that with a real order). Checked before the dry-run short-circuit so
        # the confirm dialog's pre-flight shows it.
        if (is_option and portfolio.get("venue") == "snaptrade"
                and portfolio["kind"] in ("live", "paper") and self.option_gate is not None):
            ok, why = self.option_gate(intent.portfolio_id)
            if not ok:
                return await self._transition(
                    order.id, OrderStatus.REJECTED_RISK, ev.ORDER_REJECTED,
                    reject_reason=f"options unavailable on this account: {why}",
                    extra={"risk": verdict.to_dict(), **extra_out})

        # Venue capability check before the dry-run short-circuit so a
        # pre-flight dry run surfaces it in the confirm dialog too.
        if (order.bracket and portfolio.get("venue") == "snaptrade"
                and not bool(self._settings.get("snaptrade.allow_brackets", False))):
            return await self._transition(
                order.id, OrderStatus.REJECTED_RISK, ev.ORDER_REJECTED,
                reject_reason="bracket orders are not supported on SnapTrade venues")

        # ---- routing gate ----------------------------------------------------
        mode = str(self._settings.get("trading.mode", "practice"))
        kind = portfolio["kind"]
        if intent.dry_run:
            est = self._estimate_price(intent)
            return await self._transition(
                order.id, OrderStatus.DRY_RUN, ev.ORDER_DRY_RUN,
                extra={"estimatedPrice": est, "risk": verdict.to_dict(), **extra_out})
        # Dry runs never consume rate/duplicate budget (a confirm-dialog
        # pre-flight would otherwise block the real submit that follows).
        # Reduce-only exits are also exempt: a stop/flatten must never be
        # throttled by the very budget that protects entries.
        if not intent.reduce_only:
            self._risk.note_submission(intent.symbol, intent.side, intent.qty, intent.order_type)
        # practice: simulated venues only; live: everything (sim/shadow still
        # fill on the simulator — live/paper route to their real venue)
        allowed = {
            "practice": {"sim", "shadow"},
            "live": {"sim", "shadow", "paper", "live"},
        }.get(mode, set())
        if kind not in allowed:
            return await self._transition(
                order.id, OrderStatus.REJECTED_RISK, ev.ORDER_REJECTED,
                reject_reason=f"trading.mode={mode} blocks orders on a '{kind}' portfolio")
        executor = self._executor_for(portfolio)
        if executor is None or not executor.connected:
            return await self._transition(
                order.id, OrderStatus.REJECTED, ev.ORDER_REJECTED,
                reject_reason=f"no connected execution venue for '{kind}' portfolio")

        result = await self._transition(order.id, OrderStatus.SUBMITTED, ev.ORDER_SUBMITTED,
                                        extra=extra_out or None)
        await executor.submit(BrokerOrder(
            id=order.id, symbol=order.symbol, sec_type=order.sec_type,
            side=OrderSide(order.side), qty=order.qty,
            order_type=OrderType(order.order_type),
            limit_price=order.limit_price, stop_price=order.stop_price,
            tif=TimeInForce(order.tif), portfolio_id=order.portfolio_id,
            option_action=option_action,
        ))
        return result

    def _estimate_price(self, intent: OrderIntent) -> float | None:
        q = self._quotes.get(intent.symbol)
        if q is None:
            return intent.limit_price
        if intent.order_type == "MKT":
            return q.ask if intent.side == "BUY" else q.bid
        return intent.limit_price

    # ------------------------------------------------------------------ cancel
    async def cancel(self, order_id: str) -> dict:
        async with self._sf() as session:
            order = await session.get(Order, order_id)
        if order is None:
            raise ValueError(f"unknown order: {order_id}")
        if order.status in OPEN_STATUSES:
            portfolio = self._positions.portfolio(order.portfolio_id) or {}
            executor = self._executor_for(portfolio)
            if executor is not None:
                await executor.cancel(order_id)
                return order_dict(order)  # final state arrives via report
        if order.status == OrderStatus.NEW.value:
            return await self._transition(order_id, OrderStatus.CANCELLED, ev.ORDER_CANCELLED)
        return order_dict(order)

    # ------------------------------------------------------------- reports
    async def on_report(self, report: ExecReport) -> None:
        async with self._report_lock:
            if report.kind == "accepted":
                await self._transition(report.order_id, OrderStatus.ACCEPTED, ev.ORDER_ACCEPTED)
            elif report.kind == "fill":
                await self._apply_fill(report)
            elif report.kind == "cancelled":
                await self._transition(report.order_id, OrderStatus.CANCELLED, ev.ORDER_CANCELLED,
                                       extra={"reason": report.reason})
            elif report.kind == "rejected":
                await self._transition(report.order_id, OrderStatus.REJECTED, ev.ORDER_REJECTED,
                                       reject_reason=report.reason)
            elif report.kind == "expired":
                await self._transition(report.order_id, OrderStatus.EXPIRED, ev.ORDER_EXPIRED)

    async def _apply_fill(self, report: ExecReport) -> None:
        async with self._sf() as session:
            order = await session.get(Order, report.order_id)
            if order is None:
                return
            exec_row = Execution(
                id=report.exec_id, order_id=order.id, portfolio_id=order.portfolio_id,
                symbol=order.symbol, side=order.side, qty=report.fill_qty,
                price=report.fill_price, commission=report.commission,
            )
            session.add(exec_row)
            prev_filled = order.filled_qty or 0.0
            prev_avg = order.avg_fill_price or 0.0
            new_filled = prev_filled + report.fill_qty
            order.avg_fill_price = (
                (prev_filled * prev_avg + report.fill_qty * report.fill_price) / new_filled
                if new_filled > 0 else None)
            order.filled_qty = new_filled
            fully = new_filled >= order.qty - 1e-9
            order.status = OrderStatus.FILLED.value if fully else OrderStatus.PARTIALLY_FILLED.value
            # Positions must be current before the order becomes observable as
            # (PARTIALLY_)FILLED — readers treat FILLED as "effects applied".
            await self._positions.apply_fill(
                order.portfolio_id, order.symbol, order.sec_type, order.side,
                report.fill_qty, report.fill_price, report.commission)
            await session.commit()
            odict = order_dict(order)

        await self._journal.append(
            ev.ORDER_FILL,
            {"qty": report.fill_qty, "price": report.fill_price, "commission": report.commission},
            aggregate_type="order", aggregate_id=order.id, portfolio_id=order.portfolio_id)
        if fully:
            await self._journal.append(
                ev.ORDER_FILLED, {"avgFillPrice": order.avg_fill_price, "qty": order.filled_qty},
                aggregate_type="order", aggregate_id=order.id, portfolio_id=order.portfolio_id)

        self._bus.publish(topics.EXECUTIONS, {
            "id": report.exec_id, "orderId": order.id, "portfolioId": order.portfolio_id,
            "symbol": order.symbol, "side": order.side, "qty": report.fill_qty,
            "price": report.fill_price, "commission": report.commission, "ts": report.ts,
        })
        self._bus.publish(topics.ORDERS, odict)

        if fully and order.bracket and not order.parent_id:
            await self._spawn_bracket_children(order)

    async def _spawn_bracket_children(self, parent: Order) -> None:
        spec = BracketSpec(**parent.bracket)
        fill = parent.avg_fill_price or parent.limit_price or 0.0
        if fill <= 0:
            return
        long = parent.side == "BUY"
        sign = 1 if long else -1
        tp = spec.take_profit or (
            round(fill * (1 + sign * spec.take_profit_pct / 100), 2) if spec.take_profit_pct else None)
        sl = spec.stop_loss or (
            round(fill * (1 - sign * spec.stop_loss_pct / 100), 2) if spec.stop_loss_pct else None)
        child_side = "SELL" if long else "BUY"
        oca = f"oca-{parent.id[:12]}"
        portfolio = self._positions.portfolio(parent.portfolio_id) or {}
        executor = self._executor_for(portfolio)
        children: list[Order] = []
        if tp:
            children.append(Order(
                id=new_id(), portfolio_id=parent.portfolio_id, symbol=parent.symbol,
                sec_type=parent.sec_type, side=child_side, qty=parent.filled_qty,
                order_type="LMT", limit_price=tp, tif="GTC",
                status=OrderStatus.SUBMITTED.value, source="bracket",
                parent_id=parent.id, oca_group=oca))
        child_action = None
        if parent.sec_type == "OPT":
            child_action = "SELL_TO_CLOSE" if long else "BUY_TO_CLOSE"
        if sl:
            children.append(Order(
                id=new_id(), portfolio_id=parent.portfolio_id, symbol=parent.symbol,
                sec_type=parent.sec_type, side=child_side, qty=parent.filled_qty,
                order_type="STP", stop_price=sl, tif="GTC",
                status=OrderStatus.SUBMITTED.value, source="bracket",
                parent_id=parent.id, oca_group=oca))
        if not children:
            return
        async with self._sf() as session:
            session.add_all(children)
            await session.commit()
        for child in children:
            await self._journal.append(
                ev.ORDER_INTENT_CREATED, order_dict(child),
                aggregate_type="order", aggregate_id=child.id, portfolio_id=child.portfolio_id)
            self._bus.publish(topics.ORDERS, order_dict(child))
            if executor is not None and executor.connected:
                await executor.submit(BrokerOrder(
                    id=child.id, symbol=child.symbol, sec_type=child.sec_type,
                    side=OrderSide(child.side), qty=child.qty,
                    order_type=OrderType(child.order_type),
                    limit_price=child.limit_price, stop_price=child.stop_price,
                    tif=TimeInForce(child.tif), oca_group=oca, parent_id=parent.id,
                    portfolio_id=child.portfolio_id, option_action=child_action,
                ))

    # ------------------------------------------------------------------ util
    async def _transition(
        self,
        order_id: str,
        status: OrderStatus,
        event_type: str,
        *,
        reject_reason: str | None = None,
        extra: dict | None = None,
    ) -> dict:
        async with self._sf() as session:
            order = await session.get(Order, order_id)
            if order is None:
                return {}
            if OrderStatus(order.status).is_terminal and status != OrderStatus(order.status):
                return order_dict(order)  # never regress a terminal order
            order.status = status.value
            if reject_reason:
                order.reject_reason = reject_reason
            await session.commit()
            odict = order_dict(order)
        payload = {"status": status.value}
        if reject_reason:
            payload["reason"] = reject_reason
        if extra:
            payload.update(extra)
        await self._journal.append(
            event_type, payload,
            aggregate_type="order", aggregate_id=order_id, portfolio_id=odict.get("portfolioId"))
        self._bus.publish(topics.ORDERS, odict)
        # extra (risk verdict, estimated price) rides the API response only —
        # the UI shows failed checks and the confirm dialog's pre-flight result.
        return {**odict, **(extra or {})}

    # ------------------------------------------------------------------ queries
    async def list_orders(
        self, portfolio_id: str | None = None, open_only: bool = False, limit: int = 200
    ) -> list[dict]:
        async with self._sf() as session:
            stmt = select(Order).order_by(Order.created_at.desc()).limit(limit)
            if portfolio_id:
                stmt = stmt.where(Order.portfolio_id == portfolio_id)
            if open_only:
                stmt = stmt.where(Order.status.in_(OPEN_STATUSES))
            rows = (await session.execute(stmt)).scalars().all()
        return [order_dict(o) for o in rows]

    async def list_executions(self, portfolio_id: str | None = None, limit: int = 200) -> list[dict]:
        async with self._sf() as session:
            stmt = select(Execution).order_by(Execution.ts.desc()).limit(limit)
            if portfolio_id:
                stmt = stmt.where(Execution.portfolio_id == portfolio_id)
            rows = (await session.execute(stmt)).scalars().all()
        return [{
            "id": e.id, "orderId": e.order_id, "portfolioId": e.portfolio_id,
            "symbol": e.symbol, "side": e.side, "qty": e.qty, "price": e.price,
            "commission": e.commission, "ts": e.ts.isoformat(),
        } for e in rows]
