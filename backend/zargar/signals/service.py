"""Signal pipeline service: raw content → extraction → grounding → verification → proposal.

Rebuilt 2026-08-27 for the tip technique (docs/techniques/tip/PLAN.md §A):
extraction v2 carries the whole trade (instrument/strike/expiry/horizon),
screenshots of the user's own client are transcribed and extracted, duplicate
tips attach to the original as "seen again" instead of minting a second
proposal, price-position failures *park* a signal (the tip technique waits for
the level) instead of killing it, and every verified signal shadow-trades so
the per-source scorecard exists regardless of the human decision.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import logging

from sqlalchemy import select

from .. import bus as topics
from .. import events as ev
from ..domain import new_id
from ..models import ChatAsset, Portfolio as PortfolioRow, RawContent, Signal
from .extraction import Extractor, ground_signal
from .schemas import ExtractionResult, TradeSignal
from .sources import SourcePolicy, resolve_policy
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
        "instrument": row.instrument,
        "strike": row.strike,
        "premium": row.premium,
        "expiry": row.expiry,
        "dteHintDays": row.dte_hint_days,
        "horizonSessions": row.horizon_sessions,
        "catalyst": row.catalyst,
        "seenCount": row.seen_count,
        "lastSeenAt": row.last_seen_at.isoformat() if row.last_seen_at else None,
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


def dedupe_key_for(source: str | None, sig: TradeSignal) -> str:
    """Semantic identity of a tip: same source + same trade = the same tip,
    however it was worded. Repeat mentions bump `seen_count` on the original."""
    raw = "|".join([
        (source or "unknown").lower(), sig.ticker.upper(), sig.direction,
        sig.instrument, f"{sig.strike:g}" if sig.strike else "", sig.expiry or "",
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:40]


class SignalService:
    def __init__(self, engine, extractor: Extractor) -> None:
        self.engine = engine
        self.extractor = extractor
        self._replay_fetch = None      # tests inject a bars fetcher for replays
        self._analyst_client = None    # tests inject a fake Anthropic client

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
                            subject: str = "", image: bytes | None = None,
                            image_media_type: str = "image/png") -> dict:
        """Paste-in path — text, or a screenshot of the user's own client (the
        model transcribes it; the image is kept as evidence in chat_assets)."""
        eng = self.engine
        meta: dict = {}
        if image is not None:
            asset = ChatAsset(id=new_id(), thread_id=None, media_type=image_media_type,
                              data=image, meta={"kind": "tip_screenshot"})
            async with eng.sf() as session:
                session.add(asset)
                await session.commit()
            meta["imageAssetId"] = asset.id
        row = RawContent(id=new_id(), source_type="manual", source_name=source_name,
                         subject=subject, body_text=text, meta=meta)
        async with eng.sf() as session:
            session.add(row)
            await session.commit()
        await eng.journal.append(
            ev.CONTENT_RECEIVED, {"id": row.id, "source": source_name, "sourceType": "manual",
                                  "hasImage": image is not None},
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

    async def known_sources(self) -> list[str]:
        """Every source name the app has seen: the registry + prior signals.
        Feeds the compose box's suggestions and auto-detect matching."""
        names: list[str] = []
        for src in self.engine.settings.get("sources.registry") or []:
            if src.get("name"):
                names.append(str(src["name"]))
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(Signal.source_name).distinct())).scalars().all()
        for n in rows:
            if n and n not in names:
                names.append(n)
        return sorted(names, key=str.casefold)

    async def _resolve_source(self, hint: str) -> tuple[str, bool]:
        """A detected source hint -> a canonical source name. Exact casefold
        match on known sources first, then containment either way (a screenshot
        says '#alpha-alerts' and the source is 'Alpha Alerts'); a genuinely new
        hint becomes a new source under its own (cleaned) name. Returns
        (name, matched_existing)."""
        clean = " ".join(str(hint).split()).strip("#@ ")[:64] or "unknown"

        def key(s: str) -> str:
            # punctuation/case-insensitive: '#alpha-alerts' matches 'Alpha Alerts'
            return "".join(ch for ch in s.casefold() if ch.isalnum())

        cf = key(clean)
        known = await self.known_sources()
        if cf:
            for name in known:
                if key(name) == cf:
                    return name, True
            for name in known:
                nk = key(name)
                if nk and (cf in nk or nk in cf):
                    return name, True
        return clean, False

    # ------------------------------------------------------------- pipeline
    async def process_content(self, content_id: str) -> dict:
        eng = self.engine
        async with eng.sf() as session:
            content = await session.get(RawContent, content_id)
        if content is None:
            raise ValueError("unknown content")
        image: bytes | None = None
        asset_id = (content.meta or {}).get("imageAssetId")
        if asset_id:
            async with eng.sf() as session:
                asset = await session.get(ChatAsset, asset_id)
            image = asset.data if asset else None
        text = content.body_text or content.body_html or ""
        if not text.strip() and image is None:
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
                received_at=content.received_at.isoformat() if content.received_at else "",
                image=image)
        except Exception as exc:
            log.exception("extraction failed for %s", content_id)
            await self._set_content_status(content_id, "error")
            return {"contentId": content_id, "status": "error", "error": str(exc), "signals": []}

        source_text = text
        if image is not None and result.source_transcript:
            # the transcript IS the source for grounding + display; keep it
            source_text = result.source_transcript
            async with eng.sf() as session:
                db_content = await session.get(RawContent, content_id)
                if db_content is not None and not (db_content.body_text or "").strip():
                    db_content.body_text = result.source_transcript
                    await session.commit()

        out = await self.handle_extraction(content, result, source_text=source_text)
        await self._set_content_status(content_id, "extracted")
        async with eng.sf() as session:               # source may have been auto-detected
            refreshed = await session.get(RawContent, content_id)
        return {"contentId": content_id, "status": "extracted",
                "sourceType": result.source_type, "signals": out,
                "source": (refreshed.source_name if refreshed else content.source_name),
                "sourceDetected": bool((refreshed.meta or {}).get("sourceDetected")) if refreshed else False}

    async def _find_duplicate(self, key: str, window_hours: float) -> Signal | None:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=window_hours)
        async with self.engine.sf() as session:
            return (await session.execute(
                select(Signal).where(Signal.dedupe_key == key,
                                     Signal.created_at >= cutoff,
                                     Signal.status != "dismissed")
                .order_by(Signal.created_at.desc()).limit(1)
            )).scalars().first()

    async def handle_extraction(self, content: RawContent, result: ExtractionResult,
                                *, source_text: str) -> list[dict]:
        """Grounding → dedupe → persistence → verification → proposal, per signal.
        Split out so tests can drive it with a canned ExtractionResult (no API)."""
        eng = self.engine
        # auto-detect the source when the user didn't name one: the extractor
        # reads attribution out of the content itself (channel name, poster's
        # handle, newsletter masthead) and we match it to a known source
        if (content.source_name or "").strip().lower() in ("", "auto") :
            detected, matched = (await self._resolve_source(result.source_hint)
                                 if result.source_hint else ("unknown", False))
            async with eng.sf() as session:
                row = await session.get(RawContent, content.id)
                if row is not None:
                    row.source_name = detected
                    row.meta = {**(row.meta or {}),
                                "sourceDetected": bool(result.source_hint),
                                "sourceHint": result.source_hint,
                                "sourceMatchedExisting": matched}
                    await session.commit()
                    content = row
        # --- freshness: a tip whose content shows an old post date is REPLAYED
        # on history, never traded against today's price (decision 2026-08-28)
        max_age = float(eng.settings.get("techniques.tip.max_tip_age_hours", 72))
        stated_ms, age_hours = self._stated_age(result.stated_at, content.received_at)
        stale = age_hours is not None and age_hours > max_age

        out: list[dict] = []
        for sig in result.signals:
            policy = resolve_policy(eng.settings, content.source_name)
            grounding = ground_signal(sig, source_text)

            # --- dedupe: the same tip seen again attaches to the original ---
            key = dedupe_key_for(content.source_name, sig)
            window = float(eng.settings.get("techniques.tip.dedupe_window_hours", 24))
            dup = await self._find_duplicate(key, window)
            if dup is not None:
                async with eng.sf() as session:
                    db_dup = await session.get(Signal, dup.id)
                    db_dup.seen_count = int(db_dup.seen_count or 1) + 1
                    db_dup.last_seen_at = dt.datetime.now(dt.timezone.utc)
                    await session.commit()
                    dup = db_dup
                await eng.journal.append(
                    ev.SIGNAL_SEEN_AGAIN,
                    {"ticker": dup.ticker, "source": content.source_name,
                     "seenCount": dup.seen_count, "contentId": content.id},
                    aggregate_type="signal", aggregate_id=dup.id)
                eng.bus.publish(topics.SIGNALS, signal_dict(dup))
                out.append({"signal": signal_dict(dup), "duplicateOf": dup.id,
                            "proposal": None, "shadowOrder": None})
                continue

            row = Signal(
                id=new_id(),
                raw_content_id=content.id,
                source_name=content.source_name,
                ticker=sig.ticker.upper(),
                exchange_hint=sig.exchange_hint,
                direction=sig.direction,
                action=sig.action,
                instrument=sig.instrument,
                strike=sig.strike,
                premium=sig.premium,
                expiry=sig.expiry,
                dte_hint_days=sig.dte_hint_days,
                horizon_sessions=sig.horizon_sessions,
                catalyst=sig.catalyst,
                dedupe_key=key,
                entry_price=sig.entry_price,
                entry_type=sig.entry_type,
                target_price=sig.target_price or (sig.target_prices[0] if sig.target_prices else None),
                stop_price=sig.stop_price,
                timeframe=sig.timeframe,
                thesis_summary=sig.thesis_summary,
                confidence=sig.confidence,
                is_actionable=sig.is_actionable,
                extraction={"signal": sig.model_dump(), "grounding": grounding,
                            "sourceType": result.source_type,
                            "policy": policy.to_dict()},
            )
            async with eng.sf() as session:
                session.add(row)
                await session.commit()
            await eng.journal.append(
                ev.SIGNAL_EXTRACTED,
                {"ticker": row.ticker, "direction": row.direction,
                 "instrument": row.instrument, "confidence": row.confidence,
                 "grounded": grounding["passed"], "source": content.source_name},
                aggregate_type="signal", aggregate_id=row.id)

            await eng.ensure_symbol(row.ticker)
            verification = await verify_signal(sig, eng.quotes, eng.settings,
                                               grounding=grounding)
            # flow context rides along (informational, never a check): does the
            # options tape agree with the tip?
            flow = getattr(eng, "flow_service", None)
            if flow is not None:
                try:
                    line = await flow.context_for(row.ticker, consumer="tip", ref_id=row.id)
                    if line:
                        verification["flowContext"] = line
                except Exception:  # pragma: no cover - context is best-effort
                    log.debug("flow context lookup failed for %s", row.ticker)
            # calendar context (advisory — Yahoo dates are unconfirmed): a tip
            # riding into earnings should say so where the human decides
            cal = getattr(eng, "calendar", None)
            if cal is not None:
                try:
                    days = await cal.days_to_earnings(row.ticker)
                    horizon = row.horizon_sessions or 10
                    if days is not None and days <= horizon + 4:
                        verification["calendarContext"] = (
                            f"earnings in ~{days} calendar day(s) — inside this tip's horizon "
                            "(dates are advisory, not confirmed)")
                except Exception:  # pragma: no cover - context is best-effort
                    log.debug("calendar lookup failed for %s", row.ticker)
            replay = None
            if stale:
                # too old to trade — replay it on history so the paste still
                # teaches something (both books' counterfactuals, no orders)
                verification["checks"].append({
                    "name": "fresh", "passed": False, "fatal": True,
                    "detail": f"content is ~{age_hours:.0f}h old "
                              f"(max {max_age:.0f}h) — replayed on history, not traded"})
                verification["passed"] = False
                verification["park"] = False
                verification["shadow_only"] = False
                status = "replayed"
                replay = await self._replay_signal(row, sig, stated_ms)
            elif verification["passed"]:
                status = "verified"
            elif verification.get("park"):
                status = "parked"
            elif verification.get("shadow_only"):
                status = "shadow"
            else:
                status = "verification_failed"
            async with eng.sf() as session:
                db_row = await session.get(Signal, row.id)
                db_row.verification = verification
                db_row.status = status
                extra = {"statedAt": result.stated_at, "ageHours": age_hours}
                if replay is not None:
                    extra["replay"] = replay
                db_row.extraction = {**(db_row.extraction or {}), **extra}
                await session.commit()
                row = db_row
            kind = {"verified": ev.SIGNAL_VERIFIED, "shadow": ev.SIGNAL_VERIFIED,
                    "parked": ev.SIGNAL_PARKED, "replayed": ev.SIGNAL_REPLAYED,
                    }.get(status, ev.SIGNAL_VERIFICATION_FAILED)
            await eng.journal.append(kind, {**verification, "status": status},
                                     aggregate_type="signal", aggregate_id=row.id)
            eng.bus.publish(topics.SIGNALS, signal_dict(row))

            proposal = None
            shadow_order = None
            if status in ("verified", "shadow"):
                # the shadow books ALWAYS trade a verified/shadow signal — the
                # per-source track record exists regardless of the human decision
                shadow_order = await self._shadow_execute(row, sig)
                async with eng.sf() as session:   # pick up the recorded expression
                    row = await session.get(Signal, row.id) or row
            if status in ("verified", "shadow", "parked"):
                # the tips analyst appraises the tip with market tools —
                # strictly advisory, fail-open (POC 2026-08-28)
                try:
                    from ..techniques.tip.analyst import analyze_tip
                    opinion = await analyze_tip(eng, row, verification, policy,
                                                client=self._analyst_client)
                except Exception:                  # never block the pipeline
                    log.exception("tip analyst crashed for %s", row.id)
                    opinion = None
                if opinion is not None:
                    async with eng.sf() as session:
                        db_row = await session.get(Signal, row.id)
                        db_row.extraction = {**(db_row.extraction or {}),
                                             "analyst": opinion}
                        await session.commit()
                        row = db_row
                    await eng.journal.append(
                        ev.SIGNAL_ANALYZED,
                        {k: opinion.get(k) for k in ("verdict", "contract",
                                                     "contractLabel", "limit_price",
                                                     "quantity", "rationale")},
                        aggregate_type="signal", aggregate_id=row.id)
                    eng.bus.publish(topics.SIGNALS, signal_dict(row))
            if status == "verified":
                # proposals need an explicit call (status "shadow" never proposes)
                if (eng.proposals is not None and policy.mode in ("proposal", "auto")
                        and policy.meets_conviction(sig.confidence)):
                    proposal = await eng.proposals.create_from_signal(row, sig, verification)
            out.append({"signal": signal_dict(row), "proposal": proposal,
                        "shadowOrder": shadow_order})
        return out

    @staticmethod
    def _stated_age(stated_at: str | None,
                    received: dt.datetime | None) -> tuple[int | None, float | None]:
        """(stated_at as epoch ms, age in hours at receipt). (None, None) when the
        content shows no parseable date. Naive timestamps are assumed ET; a bare
        date is treated as noon ET — generous in the tip's favour."""
        if not stated_at:
            return None, None
        try:
            s = stated_at.strip()
            if len(s) == 10:                      # YYYY-MM-DD
                parsed = dt.datetime.fromisoformat(s + "T12:00")
            else:
                parsed = dt.datetime.fromisoformat(s)
        except ValueError:
            return None, None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone(dt.timedelta(hours=-4)))
        ref = received or dt.datetime.now(dt.timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=dt.timezone.utc)
        age = (ref - parsed).total_seconds() / 3600
        return int(parsed.timestamp() * 1000), age

    async def _replay_signal(self, row: Signal, sig: TradeSignal,
                             stated_ms: int | None) -> dict:
        """Run the stale tip's history replay (techniques/tip/replay.py)."""
        if stated_ms is None:
            return {"ok": False, "note": "no parseable tip time"}
        from ..techniques.tip.replay import replay_tip
        policy = resolve_policy(self.engine.settings, row.source_name)
        try:
            kwargs = {}
            if self._replay_fetch is not None:            # test injection
                kwargs["fetch"] = self._replay_fetch
            return await replay_tip(
                symbol=row.ticker, direction=row.direction, stated_at_ms=stated_ms,
                tip_entry=sig.entry_price, tip_stop=sig.stop_price,
                tip_targets=tuple(sig.target_prices or
                                  ([sig.target_price] if sig.target_price else [])),
                horizon_sessions=sig.horizon_sessions or policy.horizon_sessions,
                source=row.source_name, thesis=sig.thesis_summary, **kwargs)
        except Exception as exc:                          # replay is best-effort
            log.exception("replay failed for signal %s", row.id)
            return {"ok": False, "note": f"replay failed: {exc}"}

    async def shadow_portfolio(self, source: str, book: str) -> dict:
        """The per-source shadow account for one BOOK: 'immediate' (buy at tip
        time — the source's raw quality) or 'armed' (wait for the level, managed
        exits — what the app actually does). Two books per source so the
        scorecard can compare the strategies without blending their P&L
        (user decision 2026-08-27). Pre-split rows (book NULL) are immediate."""
        eng = self.engine

        def match(p: dict) -> bool:
            if p["kind"] != "shadow" or p.get("sourceName") != source:
                return False
            b = p.get("book")
            return b == book or (b is None and book == "immediate")

        shadow = next((p for p in eng.positions.portfolios() if match(p)), None)
        if shadow is None:
            name = f"Shadow: {source}" + (" (armed)" if book == "armed" else "")
            row = PortfolioRow(id=new_id(), name=name, kind="shadow",
                               starting_cash=10_000.0, cash=10_000.0,
                               source_name=source, book=book)
            async with eng.sf() as session:
                session.add(row)
                await session.commit()
            eng.positions.register_portfolio(row)
            shadow = eng.positions.portfolio(row.id)
        return shadow

    async def _shadow_execute(self, signal_row: Signal, sig: TradeSignal) -> dict | None:
        """Every verified signal also trades in the source's IMMEDIATE shadow
        book, so the 'what if we'd bought the moment they spoke' record exists
        regardless of the human decision (the armed book is the tip runner's).

        Phase B (BUILD-PLAN T1): the per-tip vehicle rule — a tip that names an
        option buys the CONTRACT (buy-and-hold counterfactual: no bracket,
        expiry settlement closes it); anything else buys shares with the tip's
        bracket as before. A failed pick falls back to shares, recorded on the
        signal — the book never silently skips a tip."""
        import math

        from ..orders import BracketSpec, OrderIntent
        from ..techniques.tip.express import pick_tip_contract, tip_is_option

        eng = self.engine
        source = signal_row.source_name or "unknown"
        shadow = await self.shadow_portfolio(source, "immediate")
        policy = resolve_policy(eng.settings, source)
        expression: dict = {"vehicle": "shares"}

        try:
            if tip_is_option(signal_row):
                targets = ((signal_row.extraction or {}).get("signal") or {}).get("target_prices") \
                    or ([sig.target_price] if sig.target_price else [])
                cap = float(targets[-1]) if targets else None
                pick = await pick_tip_contract(
                    eng, symbol=sig.ticker.upper(), direction=sig.direction,
                    dte_min=policy.dte_min, dte_max=policy.dte_max,
                    strike=signal_row.strike, expiry=signal_row.expiry,
                    max_strike=cap if sig.direction == "long" else None,
                    min_strike=cap if sig.direction == "short" else None)
                ask = float(pick.get("ask") or pick.get("mid") or 0) if pick.get("available") else 0.0
                if pick.get("available") and pick.get("symbol") and ask > 0:
                    from ..execution.sizing import size_by_budget
                    contracts = size_by_budget(policy.budget_per_tip, ask,
                                               max_units=1_000, multiplier=100.0)
                    if contracts < 1:
                        contracts = 1     # one contract slightly over budget beats skipping the tip
                        expression["note"] = (f"premium ${ask * 100:,.0f} exceeds the "
                                              f"${policy.budget_per_tip:,.0f} budget — 1 contract anyway")
                    occ_sym = str(pick["symbol"])
                    await eng.ensure_symbol(occ_sym)      # track + quotes so sim can fill
                    expression.update({"vehicle": "option", "contract": occ_sym,
                                       "display": pick.get("display"), "ask": ask,
                                       "contracts": contracts,
                                       "warnings": pick.get("warnings") or []})
                    await self._record_expression(signal_row.id, expression)
                    return await eng.orders.place(OrderIntent(
                        portfolio_id=shadow["id"], symbol=occ_sym, sec_type="OPT",
                        side="BUY", qty=contracts, order_type="MKT",
                        source="auto", signal_id=signal_row.id,
                        technique_id="tip", tags=[f"source:{source}"]))
                expression["fallback"] = pick.get("error") or "no usable contract"

            if sig.direction == "short":
                # shorts are puts only (never-listed share shorting) — a short tip
                # with no usable contract cannot be expressed; record that honestly
                expression["note"] = "short tip needs a put — " + str(
                    expression.get("fallback") or "no chain") + "; not expressed"
                await self._record_expression(signal_row.id, expression)
                return None

            symbol = sig.ticker.upper()
            quote = eng.quotes.get(symbol)
            ref = (quote.ask if quote and quote.ask > 0 else None) or sig.entry_price
            if not ref or ref <= 0:
                expression["note"] = "no reference price — nothing bought"
                await self._record_expression(signal_row.id, expression)
                return None
            # shares are sized by the SAME per-tip budget as options — the two
            # books/vehicles must be dollar-comparable on the scorecard
            # (decision 2026-08-28; was 5% of equity, which dwarfed option tips)
            qty = max(1, math.floor(policy.budget_per_tip / ref))
            bracket = None
            if sig.target_price or sig.stop_price:
                bracket = BracketSpec(take_profit=sig.target_price, stop_loss=sig.stop_price)
            # a bracket-less share position must still die: the morning loop
            # closes it once the tip's thesis window has passed
            from ..techniques.tip.horizon import add_sessions, hold_sessions_cap, tip_expiry
            today = dt.datetime.now(dt.timezone.utc).date()
            cap = hold_sessions_cap(
                expiry=tip_expiry(signal_row.expiry, signal_row.dte_hint_days, today),
                today=today, fallback=policy.horizon_sessions)
            expression.update({"qty": qty, "entryRef": round(float(ref), 4),
                               "closeAfter": add_sessions(today, cap).isoformat()})
            await self._record_expression(signal_row.id, expression)
            return await eng.orders.place(OrderIntent(
                portfolio_id=shadow["id"], symbol=symbol,
                side="BUY" if sig.direction == "long" else "SELL",
                qty=qty, order_type="MKT", bracket=bracket,
                source="auto", signal_id=signal_row.id,
                technique_id="tip", tags=[f"source:{source}"]))
        except Exception:
            log.exception("shadow execution failed for signal %s", signal_row.id)
            return None

    async def _record_expression(self, signal_id: str, expression: dict) -> None:
        """How the immediate book expressed this tip (vehicle, contract,
        fallback reason) — kept on the signal so the scorecard and the UI can
        show it; no new journal kind (the order path journals the money)."""
        async with self.engine.sf() as session:
            row = await session.get(Signal, signal_id)
            if row is not None:
                row.extraction = {**(row.extraction or {}), "shadowExpression": expression}
                await session.commit()

    async def _set_content_status(self, content_id: str, status: str) -> None:
        async with self.engine.sf() as session:
            row = await session.get(RawContent, content_id)
            if row is not None:
                row.status = status
                await session.commit()

    # ------------------------------------------------------------- tip plans
    async def build_tip_plan_for(self, signal_id: str) -> dict:
        """Signal → the tip SessionPlan the runner will arm (preview; no side
        effects). Verified and parked signals both plan — parked is exactly the
        case where the plan waits at the level."""
        import time as _time

        from ..marketstructure.history import fetch_window
        from ..techniques.tip import build_tip_plan

        eng = self.engine
        async with eng.sf() as session:
            row = await session.get(Signal, signal_id)
        if row is None:
            raise ValueError("unknown signal")
        if row.status not in ("verified", "parked", "proposed"):
            raise ValueError(f"signal is {row.status} — only verified/parked tips plan")
        policy = resolve_policy(eng.settings, row.source_name)
        # an options tip dies at its contract's expiry: the wait window is capped
        # by (expiry - entry_cutoff_dte), never just the policy horizon
        from ..techniques.tip.horizon import effective_wait_sessions, tip_expiry
        today = dt.datetime.now(dt.timezone.utc).date()
        expiry = tip_expiry(row.expiry, row.dte_hint_days,
                            (row.created_at.date() if row.created_at else today))
        wait = effective_wait_sessions(
            policy_horizon=policy.horizon_sessions, tip_horizon=row.horizon_sessions,
            expiry=expiry, today=today,
            entry_cutoff_dte=int(eng.settings.get("techniques.tip.entry_cutoff_dte", 2)))
        if wait <= 0:
            raise ValueError(
                f"too late — the tip's contract expires {expiry} and the entry cutoff "
                f"({eng.settings.get('techniques.tip.entry_cutoff_dte', 2)}d before expiry) has passed")
        now_ms = int(_time.time() * 1000)
        bars = await fetch_window(row.ticker, "5m", now_ms - 10 * 86_400_000, now_ms)
        quote = eng.quotes.get(row.ticker)
        ref = (quote.last if quote and quote.last > 0 else None) or (bars[-1].close if bars else None)
        if not ref:
            raise ValueError(f"no price for {row.ticker}")
        extraction_sig = (row.extraction or {}).get("signal") or {}
        plan = build_tip_plan(
            symbol=row.ticker,
            direction=row.direction,
            reference_price=float(ref),
            bars=bars,
            as_of_ms=now_ms,
            entry_mode=policy.entry,
            tip_entry=row.entry_price,
            tip_stop=row.stop_price,
            tip_targets=extraction_sig.get("target_prices")
            or ([row.target_price] if row.target_price else []),
            horizon_sessions=wait,
            stop_atr_mult=float(eng.settings.get("techniques.tip.stop_atr_mult", 1.0)),
            target_r=tuple(eng.settings.get("techniques.tip.target_r") or (1.5, 3.0)),
            signal_id=row.id,
            source=row.source_name,
            thesis=row.thesis_summary or "",
            instrument_hint=row.instrument,
        )
        return plan.to_dict()

    # ------------------------------------------------------------- queries
    async def list_signals(self, limit: int = 100) -> list[dict]:
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(Signal).order_by(Signal.created_at.desc()).limit(limit)
            )).scalars().all()
        return [signal_dict(r) for r in rows]

    async def content_bundle(self, content_id: str) -> dict:
        """Everything about one Extract & verify by its id — the raw content
        (text/transcript, source detection meta) plus every signal it produced
        with full extraction + verification. This is the record behind the
        UI's copyable #id: quote the id, pull this, discuss the run."""
        async with self.engine.sf() as session:
            row = await session.get(RawContent, content_id)
            if row is None:
                raise KeyError(f"content {content_id} not found")
            sigs = (await session.execute(
                select(Signal).where(Signal.raw_content_id == content_id)
                .order_by(Signal.created_at))).scalars().all()
        return {
            "id": row.id, "sourceType": row.source_type, "sourceName": row.source_name,
            "sender": row.sender, "subject": row.subject, "status": row.status,
            "receivedAt": row.received_at.isoformat() if row.received_at else None,
            "bodyText": row.body_text, "meta": row.meta or {},
            "hasImage": bool((row.meta or {}).get("imageAssetId")),
            "signals": [signal_dict(s) for s in sigs],
        }

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
            "hasImage": bool((r.meta or {}).get("imageAssetId")),
        } for r in rows]

    async def source_scorecards(self) -> list[dict]:
        """Per-source track record, TWO books side by side (user decision
        2026-08-27): 'immediate' = buy the moment the tip verified (the
        source's raw quality); 'armed' = wait for the level with managed exits
        (what the app actually does). The comparison is what decides whether a
        source has EARNED tip-time entry — if immediate beats armed for a
        source, their tips run away and waiting costs money."""
        eng = self.engine
        async with eng.sf() as session:
            rows = (await session.execute(select(Signal))).scalars().all()
        by_source: dict[str, dict] = {}

        def card_for(src: str) -> dict:
            return by_source.setdefault(src, {
                "source": src, "signals": 0, "verified": 0, "parked": 0,
                "failed": 0, "expiredUnfilled": 0, "seenAgain": 0, "lastSignalAt": None,
                "books": {"immediate": {}, "armed": {}}})

        for r in rows:
            card = card_for(r.source_name or "unknown")
            card["signals"] += 1
            card["seenAgain"] += max(0, int(r.seen_count or 1) - 1)
            if r.status in ("verified", "proposed", "shadow"):
                card["verified"] += 1      # shadow = verified for the books (implied call)
            elif r.status == "parked":
                card["parked"] += 1
            elif r.status == "verification_failed":
                card["failed"] += 1
            elif r.status == "expired":
                card["expiredUnfilled"] += 1      # the level never came before the tip died
            ts = r.created_at.isoformat() if r.created_at else None
            if ts and (card["lastSignalAt"] is None or ts > card["lastSignalAt"]):
                card["lastSignalAt"] = ts

        for p in eng.positions.portfolios():
            if p.get("kind") != "shadow" or not p.get("sourceName"):
                continue
            book = p.get("book") or "immediate"
            if book not in ("immediate", "armed"):
                continue
            card = card_for(p["sourceName"])
            try:
                equity = await eng.positions.equity(p["id"])
            except Exception:  # pragma: no cover - portfolio math hiccup
                equity = None
            start = p.get("startingCash") or 10_000.0
            card["books"][book] = {
                "portfolioId": p["id"], "equity": equity,
                "pnl": (equity - start) if equity is not None else None,
                "pnlPct": ((equity - start) / start * 100) if equity is not None and start else None,
            }

        # armed-book activity: managed positions opened by the tip runner, per source tag
        mgr = getattr(eng, "position_manager", None)
        if mgr is not None:
            with contextlib.suppress(Exception):
                for pos in mgr.positions():
                    if pos.get("technique") != "tip":
                        continue
                    src = next((t.split(":", 1)[1] for t in (pos.get("tags") or [])
                                if t.startswith("source:")), None)
                    if not src:
                        continue
                    book = card_for(src)["books"]["armed"]
                    book["positions"] = int(book.get("positions") or 0) + 1
                    if pos.get("status") == "closed":
                        book["closed"] = int(book.get("closed") or 0) + 1
                        book["realizedPnl"] = round(
                            float(book.get("realizedPnl") or 0) + float(pos.get("realizedPnl") or 0), 2)

        # R-based armed-book outcomes (BUILD-PLAN T3): every tip run's trigger
        # outcome, grouped by the run's source. Expectancy counts an unfilled
        # (never-triggered) tip as 0R — it measures the strategy per tip taken.
        from ..models import TechniqueOutcome, TechniqueRun
        async with eng.sf() as session:
            runs = (await session.execute(
                select(TechniqueRun.id, TechniqueRun.config)
                .where(TechniqueRun.technique == "tip"))).all()
        run_src = {r.id: ((r.config or {}).get("source") or "unknown") for r in runs}
        if run_src:
            async with eng.sf() as session:
                outs = (await session.execute(
                    select(TechniqueOutcome)
                    .where(TechniqueOutcome.run_id.in_(list(run_src))))).scalars().all()
            per: dict[str, dict] = {}
            for o in outs:
                if not (o.plan_source or "").startswith("trigger:") or o.status != "scored":
                    continue
                st = per.setdefault(run_src.get(o.run_id) or "unknown",
                                    {"n": 0, "fired": 0, "wins": 0, "sumR": 0.0, "never": 0})
                st["n"] += 1
                if o.r_multiple is not None:
                    st["fired"] += 1
                    st["sumR"] += float(o.r_multiple)
                    if o.r_multiple > 0:
                        st["wins"] += 1
                else:
                    st["never"] += 1
            for src, st in per.items():
                card_for(src)["books"]["armed"]["outcomes"] = {
                    "scored": st["n"], "fired": st["fired"], "neverTriggered": st["never"],
                    "winRate": round(st["wins"] / st["fired"], 3) if st["fired"] else None,
                    "avgR": round(st["sumR"] / st["fired"], 3) if st["fired"] else None,
                    "expectancyR": round(st["sumR"] / st["n"], 3) if st["n"] else None,
                }

        cards = list(by_source.values())
        min_n = int(eng.settings.get("techniques.tip.scorecard_min_n", 20))
        for c in cards:
            policy = resolve_policy(eng.settings, c["source"])
            c["policy"] = policy.to_dict()
            # back-compat fields (UI + older callers): the immediate book
            imm = c["books"]["immediate"]
            c["shadowPortfolioId"] = imm.get("portfolioId")
            c["shadowEquity"] = imm.get("equity")
            c["shadowPnl"] = imm.get("pnl")
            c["shadowPnlPct"] = imm.get("pnlPct")
            # the bar judges the ARMED book — real money would trade the armed
            # way. Once enough outcomes are SCORED the bar flips on expectancy
            # in R (the honest per-tip measure); until then, book P&L in $.
            oc = c["books"]["armed"].get("outcomes") or {}
            armed_pnl = c["books"]["armed"].get("pnl")
            if (oc.get("scored") or 0) >= min_n:
                c["barCleared"] = bool((oc.get("expectancyR") or 0) > 0)
                c["barBasis"] = "expectancyR"
            else:
                c["barCleared"] = bool(c["verified"] >= min_n and armed_pnl is not None and armed_pnl > 0)
                c["barBasis"] = "pnl"
            # tip-time entry is EARNED when immediate demonstrably beats armed
            imm_pnl = imm.get("pnl")
            c["tipTimeEarned"] = bool(
                c["verified"] >= min_n and imm_pnl is not None and armed_pnl is not None
                and imm_pnl > 0 and imm_pnl > armed_pnl)
        cards.sort(key=lambda c: -(c.get("signals") or 0))
        return cards


async def attach_signal_layer(engine) -> None:
    """Called from the FastAPI lifespan after the engine starts."""
    from ..approvals.proposals import ProposalService

    if getattr(engine, "signals_service", None) is not None:
        return
    extractor = Extractor(engine.config.anthropic_api_key, engine.config.extraction_model)
    engine.signals_service = SignalService(engine, extractor)
    engine.proposals = ProposalService(engine)
    engine.proposals.start()
