"""Signal pipeline service: raw content → extraction → grounding → verification → proposal."""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select

from .. import bus as topics
from .. import events as ev
from ..domain import new_id
from ..models import RawContent, Signal
from .extraction import Extractor, ground_signal
from .schemas import ExtractionResult, TradeSignal
from .verification import verify_signal

log = logging.getLogger("zargar.signals")


def signal_dict(row: Signal) -> dict:
    return {
        "id": row.id,
        "rawContentId": row.raw_content_id,
        "sourceName": row.source_name,
        "ticker": row.ticker,
        "exchangeHint": row.exchange_hint,
        "direction": row.direction,
        "action": row.action,
        "entryPrice": row.entry_price,
        "entryType": row.entry_type,
        "targetPrice": row.target_price,
        "stopPrice": row.stop_price,
        "timeframe": row.timeframe,
        "thesisSummary": row.thesis_summary,
        "confidence": row.confidence,
        "isActionable": row.is_actionable,
        "extraction": row.extraction,
        "verification": row.verification,
        "status": row.status,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


class SignalService:
    def __init__(self, engine, extractor: Extractor) -> None:
        self.engine = engine
        self.extractor = extractor

    # ------------------------------------------------------------- intake
    async def ingest_email(self, payload: dict) -> dict:
        """Store an inbound email (Cloudflare Email Worker webhook shape) and process it."""
        eng = self.engine
        sender = payload.get("from", "")
        source_name = self._match_source(sender) or sender
        row = RawContent(
            id=new_id(),
            source_type="email",
            source_name=source_name,
            sender=sender,
            subject=payload.get("subject", ""),
            body_text=payload.get("text") or "",
            body_html=payload.get("html") or "",
            meta={
                "to": payload.get("to"),
                "headers": payload.get("headers", {}),
                "spf": payload.get("spf"),
                "dkim": payload.get("dkim"),
            },
        )
        async with eng.sf() as session:
            session.add(row)
            await session.commit()
        await eng.journal.append(
            ev.CONTENT_RECEIVED,
            {"id": row.id, "source": source_name, "subject": row.subject,
             "sourceType": "email"},
            aggregate_type="content", aggregate_id=row.id)
        return await self.process_content(row.id)

    async def ingest_manual(self, text: str, *, source_name: str = "manual",
                            subject: str = "") -> dict:
        """Paste-in path for testing the pipeline without email plumbing."""
        eng = self.engine
        row = RawContent(id=new_id(), source_type="manual", source_name=source_name,
                         subject=subject, body_text=text)
        async with eng.sf() as session:
            session.add(row)
            await session.commit()
        await eng.journal.append(
            ev.CONTENT_RECEIVED, {"id": row.id, "source": source_name, "sourceType": "manual"},
            aggregate_type="content", aggregate_id=row.id)
        return await self.process_content(row.id)

    def _match_source(self, sender: str) -> str | None:
        registry = self.engine.settings.get("sources.registry") or []
        sender_lower = sender.lower()
        for src in registry:
            for email in src.get("emails", []):
                if email.lower() in sender_lower:
                    return src.get("name")
        return None

    # ------------------------------------------------------------- pipeline
    async def process_content(self, content_id: str) -> dict:
        eng = self.engine
        async with eng.sf() as session:
            content = await session.get(RawContent, content_id)
        if content is None:
            raise ValueError("unknown content")
        text = content.body_text or content.body_html or ""
        if not text.strip():
            await self._set_content_status(content_id, "ignored")
            return {"contentId": content_id, "status": "ignored", "signals": []}
        if not self.extractor.available:
            return {"contentId": content_id, "status": "new", "signals": [],
                    "note": "extraction unavailable: ANTHROPIC_API_KEY not configured"}

        try:
            result = await self.extractor.extract(
                text,
                subject=content.subject or "",
                source_name=content.source_name or "",
                received_at=content.received_at.isoformat() if content.received_at else "")
        except Exception as exc:
            log.exception("extraction failed for %s", content_id)
            await self._set_content_status(content_id, "error")
            return {"contentId": content_id, "status": "error", "error": str(exc), "signals": []}

        out = await self.handle_extraction(content, result, source_text=text)
        await self._set_content_status(content_id, "extracted")
        return {"contentId": content_id, "status": "extracted",
                "sourceType": result.source_type, "signals": out}

    async def handle_extraction(self, content: RawContent, result: ExtractionResult,
                                *, source_text: str) -> list[dict]:
        """Grounding → persistence → verification → proposal, per signal.
        Split out so tests can drive it with a canned ExtractionResult (no API)."""
        eng = self.engine
        out: list[dict] = []
        for sig in result.signals:
            grounding = ground_signal(sig, source_text)
            row = Signal(
                id=new_id(),
                raw_content_id=content.id,
                source_name=content.source_name,
                ticker=sig.ticker.upper(),
                exchange_hint=sig.exchange_hint,
                direction=sig.direction,
                action=sig.action,
                entry_price=sig.entry_price,
                entry_type=sig.entry_type,
                target_price=sig.target_price,
                stop_price=sig.stop_price,
                timeframe=sig.timeframe,
                thesis_summary=sig.thesis_summary,
                confidence=sig.confidence,
                is_actionable=sig.is_actionable,
                extraction={"signal": sig.model_dump(), "grounding": grounding,
                            "sourceType": result.source_type},
            )
            async with eng.sf() as session:
                session.add(row)
                await session.commit()
            await eng.journal.append(
                ev.SIGNAL_EXTRACTED,
                {"ticker": row.ticker, "direction": row.direction,
                 "confidence": row.confidence, "grounded": grounding["passed"]},
                aggregate_type="signal", aggregate_id=row.id)

            await eng.ensure_symbol(row.ticker)
            verification = await verify_signal(sig, eng.quotes, eng.settings,
                                               grounding=grounding)
            status = "verified" if verification["passed"] else "verification_failed"
            async with eng.sf() as session:
                db_row = await session.get(Signal, row.id)
                db_row.verification = verification
                db_row.status = status
                await session.commit()
                row = db_row
            await eng.journal.append(
                ev.SIGNAL_VERIFIED if verification["passed"] else ev.SIGNAL_VERIFICATION_FAILED,
                verification, aggregate_type="signal", aggregate_id=row.id)
            eng.bus.publish(topics.SIGNALS, signal_dict(row))

            proposal = None
            shadow_order = None
            if verification["passed"]:
                if eng.proposals is not None:
                    proposal = await eng.proposals.create_from_signal(row, sig, verification)
                shadow_order = await self._shadow_execute(row, sig)
            out.append({"signal": signal_dict(row), "proposal": proposal,
                        "shadowOrder": shadow_order})
        return out

    async def _shadow_execute(self, signal_row: Signal, sig: TradeSignal) -> dict | None:
        """Every verified signal also trades in a per-source shadow portfolio, so the
        'what would have happened' record exists regardless of the human decision."""
        import math

        from ..models import Portfolio as PortfolioRow
        from ..orders import BracketSpec, OrderIntent

        eng = self.engine
        source = signal_row.source_name or "unknown"
        shadow = next((p for p in eng.positions.portfolios()
                       if p["kind"] == "shadow" and p.get("sourceName") == source), None)
        if shadow is None:
            row = PortfolioRow(id=new_id(), name=f"Shadow: {source}", kind="shadow",
                               starting_cash=10_000.0, cash=10_000.0, source_name=source)
            async with eng.sf() as session:
                session.add(row)
                await session.commit()
            eng.positions.register_portfolio(row)
            shadow = eng.positions.portfolio(row.id)

        symbol = sig.ticker.upper()
        quote = eng.quotes.get(symbol)
        ref = (quote.ask if quote and quote.ask > 0 else None) or sig.entry_price
        if not ref or ref <= 0:
            return None
        equity = await eng.positions.equity(shadow["id"])
        pct = float(eng.settings.get("signals.default_sizing_pct", 5.0))
        qty = max(1, math.floor(equity * pct / 100 / ref))
        bracket = None
        if sig.target_price or sig.stop_price:
            bracket = BracketSpec(take_profit=sig.target_price, stop_loss=sig.stop_price)
        try:
            return await eng.orders.place(OrderIntent(
                portfolio_id=shadow["id"], symbol=symbol,
                side="BUY" if sig.direction == "long" else "SELL",
                qty=qty, order_type="MKT", bracket=bracket,
                source="auto", signal_id=signal_row.id))
        except Exception:
            log.exception("shadow execution failed for signal %s", signal_row.id)
            return None

    async def _set_content_status(self, content_id: str, status: str) -> None:
        async with self.engine.sf() as session:
            row = await session.get(RawContent, content_id)
            if row is not None:
                row.status = status
                await session.commit()

    # ------------------------------------------------------------- queries
    async def list_signals(self, limit: int = 100) -> list[dict]:
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(Signal).order_by(Signal.created_at.desc()).limit(limit)
            )).scalars().all()
        return [signal_dict(r) for r in rows]

    async def list_content(self, limit: int = 50) -> list[dict]:
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(RawContent).order_by(RawContent.received_at.desc()).limit(limit)
            )).scalars().all()
        return [{
            "id": r.id, "sourceType": r.source_type, "sourceName": r.source_name,
            "sender": r.sender, "subject": r.subject, "status": r.status,
            "receivedAt": r.received_at.isoformat() if r.received_at else None,
            "preview": (r.body_text or "")[:280],
        } for r in rows]


async def attach_signal_layer(engine) -> None:
    """Called from the FastAPI lifespan after the engine starts."""
    from ..approvals.proposals import ProposalService

    if getattr(engine, "signals_service", None) is not None:
        return
    extractor = Extractor(engine.config.anthropic_api_key, engine.config.extraction_model)
    engine.signals_service = SignalService(engine, extractor)
    engine.proposals = ProposalService(engine)
    engine.proposals.start()
