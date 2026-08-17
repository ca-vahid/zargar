"""Pending-proposal queue: verified signal → sized order proposal → approve/reject/expire."""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import math

from sqlalchemy import select

from .. import bus as topics
from .. import events as ev
from ..domain import new_id
from ..models import Proposal, Signal
from ..orders import BracketSpec, OrderIntent
from ..signals.schemas import TradeSignal

log = logging.getLogger("zargar.proposals")


def proposal_dict(p: Proposal) -> dict:
    return {
        "id": p.id,
        "signalId": p.signal_id,
        "portfolioId": p.portfolio_id,
        "symbol": p.symbol,
        "secType": p.sec_type,
        "side": p.side,
        "qty": p.qty,
        "orderType": p.order_type,
        "limitPrice": p.limit_price,
        "bracket": p.bracket,
        "rationale": p.rationale,
        "context": p.context,
        "status": p.status,
        "expiresAt": p.expires_at.isoformat() if p.expires_at else None,
        "decidedAt": p.decided_at.isoformat() if p.decided_at else None,
        "decidedVia": p.decided_via,
        "orderId": p.order_id,
        "createdAt": p.created_at.isoformat() if p.created_at else None,
    }


class ProposalService:
    def __init__(self, engine) -> None:
        self.engine = engine
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------- create
    async def create_from_signal(self, signal_row: Signal, sig: TradeSignal,
                                 verification: dict) -> dict | None:
        eng = self.engine
        pid = str(eng.settings.get("trading.default_portfolio", ""))
        if not pid or eng.positions.portfolio(pid) is None:
            portfolios = [p for p in eng.positions.portfolios() if p["kind"] == "sim"]
            if not portfolios:
                log.warning("no portfolio available for proposal")
                return None
            pid = portfolios[0]["id"]

        symbol = sig.ticker.upper()
        await eng.ensure_symbol(symbol)
        quote = eng.quotes.get(symbol)
        ref_price = (quote.ask if quote and quote.ask > 0 else None) or sig.entry_price
        if not ref_price or ref_price <= 0:
            return None

        equity = await eng.positions.equity(pid)
        sizing_pct = float(eng.settings.get("signals.default_sizing_pct", 5.0))
        budget = equity * sizing_pct / 100
        qty = max(1, math.floor(budget / ref_price))
        limit = round(ref_price, 2)

        bracket = None
        if sig.target_price or sig.stop_price:
            bracket = {"take_profit": sig.target_price, "stop_loss": sig.stop_price,
                       "take_profit_pct": None, "stop_loss_pct": None}

        ttl_min = int(eng.settings.get("signals.default_ttl_minutes", 30))
        side = "BUY" if sig.direction == "long" else "SELL"
        row = Proposal(
            id=new_id(),
            signal_id=signal_row.id,
            portfolio_id=pid,
            symbol=symbol,
            side=side,
            qty=float(qty),
            order_type="LMT",
            limit_price=limit,
            bracket=bracket,
            rationale=sig.thesis_summary,
            context={
                "sourceName": signal_row.source_name,
                "confidence": sig.confidence,
                "verification": verification,
                "sizing": {"equity": round(equity, 2), "pct": sizing_pct,
                           "budget": round(budget, 2), "refPrice": limit},
                "signalPrices": {"entry": sig.entry_price, "target": sig.target_price,
                                 "stop": sig.stop_price},
            },
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=ttl_min),
        )
        async with eng.sf() as session:
            session.add(row)
            sig_db = await session.get(Signal, signal_row.id)
            if sig_db is not None:
                sig_db.status = "proposed"
            await session.commit()
        pdict = proposal_dict(row)
        await eng.journal.append(ev.PROPOSAL_CREATED, pdict,
                                 aggregate_type="proposal", aggregate_id=row.id,
                                 portfolio_id=pid)
        eng.bus.publish(topics.PROPOSALS, pdict)
        return pdict

    # ------------------------------------------------------------- decide
    async def approve(self, proposal_id: str, *, via: str = "app",
                      half: bool = False) -> dict:
        eng = self.engine
        async with eng.sf() as session:
            row = await session.get(Proposal, proposal_id)
            if row is None:
                raise ValueError("unknown proposal")
            if row.status != "pending":
                raise ValueError(f"proposal is {row.status}, not pending")
            if row.expires_at and row.expires_at < dt.datetime.now(dt.timezone.utc):
                row.status = "expired"
                await session.commit()
                raise ValueError("proposal has expired")
            qty = max(1.0, row.qty / 2 if half else row.qty)
            row.status = "approved"
            row.decided_at = dt.datetime.now(dt.timezone.utc)
            row.decided_via = via
            await session.commit()
            pdict = proposal_dict(row)

        await eng.journal.append(
            ev.PROPOSAL_APPROVED, {"via": via, "half": half, "qty": qty},
            aggregate_type="proposal", aggregate_id=proposal_id,
            portfolio_id=pdict["portfolioId"])

        bracket = None
        if pdict["bracket"]:
            bracket = BracketSpec(**{k: v for k, v in {
                "take_profit": pdict["bracket"].get("take_profit"),
                "stop_loss": pdict["bracket"].get("stop_loss"),
                "take_profit_pct": pdict["bracket"].get("take_profit_pct"),
                "stop_loss_pct": pdict["bracket"].get("stop_loss_pct"),
            }.items() if v is not None})
        intent = OrderIntent(
            portfolio_id=pdict["portfolioId"], symbol=pdict["symbol"],
            sec_type=pdict["secType"], side=pdict["side"], qty=qty,
            order_type=pdict["orderType"], limit_price=pdict["limitPrice"],
            bracket=bracket, source="signal",
            signal_id=pdict["signalId"], proposal_id=proposal_id)
        order = await eng.orders.place(intent)

        status = "executed" if order.get("status") not in ("REJECTED_RISK", "REJECTED") else "failed"
        async with eng.sf() as session:
            row = await session.get(Proposal, proposal_id)
            row.status = status
            row.order_id = order.get("id")
            await session.commit()
            pdict = proposal_dict(row)
        eng.bus.publish(topics.PROPOSALS, pdict)
        return {"proposal": pdict, "order": order}

    async def reject(self, proposal_id: str, *, via: str = "app") -> dict:
        eng = self.engine
        async with eng.sf() as session:
            row = await session.get(Proposal, proposal_id)
            if row is None:
                raise ValueError("unknown proposal")
            if row.status != "pending":
                raise ValueError(f"proposal is {row.status}, not pending")
            row.status = "rejected"
            row.decided_at = dt.datetime.now(dt.timezone.utc)
            row.decided_via = via
            await session.commit()
            pdict = proposal_dict(row)
        await eng.journal.append(ev.PROPOSAL_REJECTED, {"via": via},
                                 aggregate_type="proposal", aggregate_id=proposal_id)
        eng.bus.publish(topics.PROPOSALS, pdict)
        return pdict

    # ------------------------------------------------------------- queries
    async def list_pending(self) -> list[dict]:
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(Proposal).where(Proposal.status == "pending")
                .order_by(Proposal.created_at.desc()))).scalars().all()
        return [proposal_dict(r) for r in rows]

    async def list_all(self, limit: int = 100) -> list[dict]:
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(Proposal).order_by(Proposal.created_at.desc()).limit(limit)
            )).scalars().all()
        return [proposal_dict(r) for r in rows]

    # ------------------------------------------------------------- expiry
    def start(self) -> None:
        self._task = asyncio.create_task(self._expiry_loop(), name="proposal-expiry")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def expire_due(self) -> int:
        eng = self.engine
        now = dt.datetime.now(dt.timezone.utc)
        expired: list[dict] = []
        async with eng.sf() as session:
            rows = (await session.execute(
                select(Proposal).where(Proposal.status == "pending",
                                       Proposal.expires_at < now))).scalars().all()
            for row in rows:
                row.status = "expired"
                row.decided_at = now
                expired.append(proposal_dict(row))
            await session.commit()
        for pdict in expired:
            await eng.journal.append(ev.PROPOSAL_EXPIRED, {},
                                     aggregate_type="proposal", aggregate_id=pdict["id"])
            eng.bus.publish(topics.PROPOSALS, pdict)
        return len(expired)

    async def _expiry_loop(self) -> None:
        while True:
            await asyncio.sleep(20)
            try:
                await self.expire_due()
            except Exception:  # pragma: no cover
                log.exception("proposal expiry failed")
