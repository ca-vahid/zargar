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
        """Verified tip → the order the human is asked to approve. The proposal
        trades the SAME vehicle the shadow books do: a tip that names an option
        proposes that contract (BUY to open — a bearish tip buys the put, share
        shorting is never proposed); the analyst's pick, when it said "take",
        wins over the raw expression (the P6 handshake). Sized by the source's
        per-tip budget, like the books, so the scorecard stays comparable."""
        from ..signals.sources import resolve_policy

        eng = self.engine
        pid = str(eng.settings.get("trading.default_portfolio", ""))
        if not pid or eng.positions.portfolio(pid) is None:
            portfolios = [p for p in eng.positions.portfolios() if p["kind"] == "sim"]
            if not portfolios:
                log.warning("no portfolio available for proposal")
                return None
            pid = portfolios[0]["id"]
        pf = eng.positions.portfolio(pid) or {}
        policy = resolve_policy(eng.settings, signal_row.source_name)
        budget = float(policy.budget_per_tip)

        extraction = signal_row.extraction or {}
        analyst = extraction.get("analyst") or {}
        expr = extraction.get("shadowExpression") or {}

        # ---- vehicle: the analyst's contract beats the book's, both beat shares
        occ = label = None
        limit_hint = qty_hint = None
        if analyst.get("verdict") == "take" and analyst.get("contract") \
                and analyst.get("instrument", "option") == "option":
            occ = str(analyst["contract"]).upper()
            label = analyst.get("contract_label") or occ
            limit_hint = analyst.get("limit_price")
            qty_hint = analyst.get("quantity")
            picked_by = "analyst"
        elif expr.get("vehicle") == "option" and expr.get("contract"):
            occ = str(expr["contract"]).upper()
            label = expr.get("display") or occ
            limit_hint = expr.get("ask")
            qty_hint = expr.get("contracts")
            picked_by = "tip"

        bracket = None
        vehicle: dict = {}
        if occ:
            symbol, sec_type, side = occ, "OPT", "BUY"      # long the contract, both directions
            await eng.ensure_symbol(occ)
            quote = eng.quotes.get(occ)
            ref_price = ((quote.ask if quote and quote.ask > 0 else None)
                         or limit_hint or sig.premium)
            if not ref_price or ref_price <= 0:
                log.warning("no premium reference for %s — no proposal", occ)
                return None
            limit = round(float(ref_price), 2)
            qty = int(qty_hint or 0) or max(1, math.floor(budget / (limit * 100)))
            from ..options import occ as occ_mod
            parsed = occ_mod.parse(occ)
            opt_type = parsed.option_type if parsed else ("put" if sig.direction == "short" else "call")
            label = label or (occ_mod.display(occ) if parsed else occ)
            vehicle = {"kind": "option", "display": label, "underlying": sig.ticker.upper(),
                       "optionType": opt_type, "pickedBy": picked_by, "multiplier": 100}
            cost = limit * qty * 100
            explain = (f"Approve = buy {qty} contract{'s' if qty != 1 else ''} of "
                       f"{label} (a {opt_type} — {'bullish' if opt_type == 'call' else 'bearish'}) "
                       f"at a ${limit:.2f} limit ≈ ${cost:,.0f} in “{pf.get('name', pid)}” "
                       f"({pf.get('kind', '?')}). The order still passes the risk gate. "
                       f"Nothing manages the exit automatically yet — it shows in Portfolios.")
        else:
            if sig.direction == "short":
                # bearish with no usable put: share shorting is never proposed
                log.warning("short tip %s has no usable put — no proposal (shorts are puts only)",
                            signal_row.id)
                return None
            symbol, sec_type, side = sig.ticker.upper(), "STK", "BUY"
            await eng.ensure_symbol(symbol)
            quote = eng.quotes.get(symbol)
            ref_price = (quote.ask if quote and quote.ask > 0 else None) or sig.entry_price
            if not ref_price or ref_price <= 0:
                return None
            limit = round(float(ref_price), 2)
            qty = max(1, math.floor(budget / limit))
            vehicle = {"kind": "shares"}
            if sig.target_price or sig.stop_price:
                bracket = {"take_profit": sig.target_price, "stop_loss": sig.stop_price,
                           "take_profit_pct": None, "stop_loss_pct": None}
            explain = (f"Approve = buy {qty} share{'s' if qty != 1 else ''} of {symbol} at a "
                       f"${limit:.2f} limit ≈ ${limit * qty:,.0f} in “{pf.get('name', pid)}” "
                       f"({pf.get('kind', '?')})"
                       + (", with the tip's target/stop attached as a bracket"
                          if bracket else "")
                       + ". The order still passes the risk gate.")

        ttl_min = int(eng.settings.get("signals.default_ttl_minutes", 30))
        row = Proposal(
            id=new_id(),
            signal_id=signal_row.id,
            portfolio_id=pid,
            symbol=symbol,
            sec_type=sec_type,
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
                "sizing": {"budget": round(budget, 2), "refPrice": limit, "qty": qty},
                "signalPrices": {"entry": sig.entry_price, "target": sig.target_price,
                                 "stop": sig.stop_price},
                "vehicle": vehicle,
                "explain": explain,
                "analystRunId": analyst.get("runId"),
                "analyst": ({k: analyst.get(k) for k in
                             ("verdict", "rationale", "invalidation", "confidence")}
                            if analyst else None),
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
        # If this came from an armed technique plan, hand the position to the armer
        # so its exits (stop / ladder / flatten) are managed like an auto trade.
        tech = (pdict.get("context") or {}).get("technique") or {}
        run_id = tech.get("runId")
        if status == "executed" and run_id and getattr(eng, "technique", None) is not None:
            with contextlib.suppress(Exception):
                await eng.technique.armer.adopt_order(
                    run_id, key=f"proposal:{proposal_id[:8]}", underlying=tech.get("underlying") or {},
                    order=order, instrument=("options" if pdict.get("secType") == "OPT" else "shares"),
                    order_symbol=(pdict.get("symbol") if pdict.get("secType") == "OPT" else None),
                    multiplier=(100.0 if pdict.get("secType") == "OPT" else 1.0))
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
