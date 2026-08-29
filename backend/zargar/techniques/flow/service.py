"""FlowService — the daily scan and the read store.

Orchestration only; the math lives in `scan.py` (pure, tested on fixtures).
Aligned with the engine's Phase 3 batch (BUILDING-A-TECHNIQUE.md):

- the scan runs on **`engine.scheduler`** (no self-spawned timing loop), after
  the `chain_snapshots` research feed (16:30 ET) has written the day's rows;
- chain data comes from **`option_chain_snapshots`** (single writer: the
  research feed). When today's rows are missing for a symbol (feed failure,
  on-demand scan before 16:30), the scan falls back to a live provider fetch
  for scoring only — it never writes the snapshot table.

Flow persists only its own verdicts (`flow_reads`). Places no orders, holds
no positions: Flow v1 is context.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging

from sqlalchemy import delete, func, select

from ... import events as ev
from ...domain import new_id
from ...marketstructure import ET
from ...models import FlowRead as FlowReadRow, OptionChainSnapshot
from ...technique.universe import is_us_optionable_symbol
from .scan import (
    FlowThresholds,
    aggregate_symbol,
    build_read,
    confirm_oi,
    context_line,
    flag_contracts,
    last_weekday,
    repeat_counts,
    spot_from_chain,
)

log = logging.getLogger("zargar.flow")


def _read_dict(row: FlowReadRow) -> dict:
    return {"id": row.id, "day": row.day, "symbol": row.symbol, "score": row.score,
            "lean": row.lean, **(row.read or {}),
            "createdAt": row.created_at.isoformat() if row.created_at else None}


def _snapshot_to_row(s: OptionChainSnapshot) -> dict:
    """option_chain_snapshots row -> the provider-normalized shape scan.py eats."""
    return {
        "symbol": s.occ, "underlying": s.underlying, "expiry": s.expiry,
        "option_type": s.option_type, "strike": s.strike,
        "bid": s.bid or 0.0, "ask": s.ask or 0.0, "last": s.last or 0.0,
        "volume": int(s.volume or 0), "open_interest": int(s.open_interest or 0),
        "greeks": {"mid_iv": s.iv},
    }


class FlowService:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.last_scan: dict | None = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """Register the daily scan on the engine scheduler (runs after the
        chain-snapshots research feed so the day's rows are already stored),
        and check the last scan for the degraded spot-less signature."""
        at = str(self.engine.settings.get("techniques.flow.scan_at", "16:45"))
        self.engine.scheduler.register("flow_scan", at, lambda: self.scan())
        try:
            asyncio.get_running_loop().create_task(
                self._repair_last_scan(), name="flow-scan-repair")
        except RuntimeError:                     # no loop (unit rigs) — skip
            pass

    async def stop(self) -> None:
        self.engine.scheduler.unregister("flow_scan")

    # ------------------------------------------------------------------ scanning
    def _universe(self, cap: int) -> list[str]:
        svc = getattr(self.engine, "technique", None)
        symbols: list[str] = []
        if svc is not None:
            try:
                cached = svc.universe_cached() or {}
                symbols = list(cached.get("symbols") or [])
            except Exception:  # pragma: no cover - universe cache not warm
                symbols = []
        if not symbols:
            from ...technique.universe import CORE_UNIVERSE
            symbols = list(CORE_UNIVERSE)
        return [s for s in symbols if is_us_optionable_symbol(s)][:cap]

    async def _rows_for(self, sym: str, day: str) -> tuple[list[dict], str]:
        """Today's chain rows: the snapshot store first, live provider as the
        scoring-only fallback. Returns (rows, source)."""
        async with self.engine.sf() as session:
            snaps = (await session.execute(
                select(OptionChainSnapshot).where(OptionChainSnapshot.date == day,
                                                  OptionChainSnapshot.underlying == sym)
            )).scalars().all()
        if snaps:
            return [_snapshot_to_row(s) for s in snaps], "snapshots"
        opts = getattr(self.engine, "options", None)
        if opts is None:
            raise RuntimeError("no snapshots for the day and no options provider")
        return await opts.provider().all_rows(sym), "live"

    async def _spot_for(self, sym: str, rows: list[dict]) -> float:
        quote = self.engine.quotes.get(sym)
        if quote is not None and quote.last > 0:
            return float(quote.last)
        # no live quote (cold boot, late scan): the chain itself knows the spot
        # via put-call parity — never score a chain against spot 0 (2026-08-28)
        parity = spot_from_chain(rows)
        if parity > 0:
            return parity
        opts = getattr(self.engine, "options", None)
        if opts is not None:
            try:
                return float(await opts.provider().spot(sym) or 0.0)
            except Exception:  # pragma: no cover - provider hiccup
                pass
        return 0.0

    async def scan(self, *, day: str | None = None, symbols: list[str] | None = None) -> dict:
        """Scan the universe, persist reads, journal a summary. Idempotent per
        (day, symbol): a re-run replaces that day's read."""
        eng = self.engine
        t = FlowThresholds.from_settings(eng.settings)
        # weekend default rolls back to Friday: a Saturday "Scan now" re-reads
        # Friday's tape instead of minting a junk day
        day = day or last_weekday(dt.datetime.now(ET).date()).strftime("%Y-%m-%d")
        cap = int(eng.settings.get("techniques.flow.scan_top", 60))
        syms = [s.upper() for s in (symbols or self._universe(cap))]

        scanned, flagged, errors, live_fallbacks, no_spot, kept = 0, 0, 0, 0, 0, 0
        reads: list[dict] = []
        for sym in syms:
            try:
                rows, source = await self._rows_for(sym, day)
                spot = await self._spot_for(sym, rows)
            except Exception as exc:
                errors += 1
                log.warning("flow scan: %s failed (%s)", sym, exc)
                continue
            if source == "live":
                live_fallbacks += 1
            scanned += 1
            read = await self._score_symbol(sym, day, rows, spot, t)
            if spot <= 0:
                # a spot-less score is DEGRADED (every flag filter needs spot):
                # never overwrite a real read with it (the 2026-08-28 wipe)
                no_spot += 1
                if await self._read_row_for(sym, day) is not None:
                    kept += 1
                    continue
            await self._persist_read(read)
            if read["score"] > 0:
                flagged += 1
                reads.append({"symbol": sym, "score": read["score"], "lean": read["lean"]})
        summary = {"day": day, "scanned": scanned, "flagged": flagged, "errors": errors,
                   "liveFallbacks": live_fallbacks, "noSpot": no_spot, "keptExisting": kept,
                   "top": sorted(reads, key=lambda r: -r["score"])[:10]}
        self.last_scan = summary
        await eng.journal.append(ev.FLOW_SCAN_COMPLETED, {**summary, "technique": "flow"},
                                 aggregate_type="flow", aggregate_id=day)
        return summary

    async def _score_symbol(self, sym: str, day: str, rows: list[dict], spot: float,
                            t: FlowThresholds) -> dict:
        flags = flag_contracts(rows, spot=spot, day=day, t=t)
        prev = await self._latest_read_before(sym, day)
        today_oi = {r.get("symbol"): int(r.get("open_interest") or 0) for r in rows}
        confirmed = confirm_oi(list((prev or {}).get("flags") or []), today_oi)
        history = await self._flag_history(sym, day, window=t.repeat_window)
        for f in flags:                                   # today's flags join the history
            history.setdefault(f["contract"], []).append(day)
        window_days = await self._recent_days(sym, day, t.repeat_window)
        repeats = repeat_counts(history, window_days=window_days + [day])
        quote = self.engine.quotes.get(sym)
        stock_volume = getattr(quote, "day_volume", None) or getattr(quote, "volume", None)
        agg = aggregate_symbol(rows, stock_volume=int(stock_volume) if stock_volume else None)
        return build_read(sym, day, flags=flags, confirmed=confirmed, repeats=repeats,
                          agg=agg, t=t, spot=spot or None)

    async def _repair_last_scan(self, *, delay: float = 15.0) -> None:
        """Self-healing for the 2026-08-28 failure: if the latest scanned day
        carries the degraded signature — scores from OI confirmations but ZERO
        flags anywhere, spot never persisted — while its chain snapshots hold
        real volume, re-scan that day (the guard above keeps the result from
        ever regressing again)."""
        try:
            await asyncio.sleep(delay)          # let the feed warm; parity works anyway
            async with self.engine.sf() as session:
                latest = (await session.execute(
                    select(FlowReadRow.day).order_by(FlowReadRow.day.desc()).limit(1)
                )).scalars().first()
                if not latest:
                    return
                rows = (await session.execute(
                    select(FlowReadRow).where(FlowReadRow.day == latest))).scalars().all()
                degraded = (any(r.score > 0 for r in rows)
                            and all(not ((r.read or {}).get("flags")) for r in rows)
                            and all((r.read or {}).get("spot") in (None, 0) for r in rows))
                if not degraded:
                    return
                vol = (await session.execute(
                    select(func.coalesce(func.sum(OptionChainSnapshot.volume), 0))
                    .where(OptionChainSnapshot.date == latest))).scalar_one()
            if not vol:
                return                           # nothing better to score from
            log.warning("flow: %s reads look degraded (no flags, no spot) but "
                        "snapshots hold volume — re-scanning", latest)
            # only the symbols that day actually read — never a fresh full sweep
            summary = await self.scan(day=latest,
                                      symbols=sorted({r.symbol for r in rows}))
            await self.engine.journal.append(
                ev.FLOW_SCAN_COMPLETED,
                {**summary, "technique": "flow", "repair": True},
                aggregate_type="flow", aggregate_id=latest)
        except Exception:                        # self-healing never breaks boot
            log.exception("flow scan repair failed")

    # ------------------------------------------------------------------ persistence
    async def _read_row_for(self, sym: str, day: str) -> FlowReadRow | None:
        async with self.engine.sf() as session:
            return (await session.execute(
                select(FlowReadRow).where(FlowReadRow.day == day,
                                          FlowReadRow.symbol == sym).limit(1)
            )).scalars().first()

    async def _persist_read(self, read: dict) -> None:
        async with self.engine.sf() as session:
            await session.execute(delete(FlowReadRow).where(
                FlowReadRow.day == read["day"], FlowReadRow.symbol == read["symbol"]))
            session.add(FlowReadRow(id=new_id(), day=read["day"], symbol=read["symbol"],
                                    score=float(read["score"]), lean=read["lean"],
                                    read={k: v for k, v in read.items()
                                          if k not in ("day", "symbol", "score", "lean")}))
            await session.commit()

    # ------------------------------------------------------------------ queries
    async def _latest_read_before(self, sym: str, day: str) -> dict | None:
        async with self.engine.sf() as session:
            row = (await session.execute(
                select(FlowReadRow).where(FlowReadRow.symbol == sym, FlowReadRow.day < day)
                .order_by(FlowReadRow.day.desc()).limit(1))).scalars().first()
        return _read_dict(row) if row else None

    async def _recent_days(self, sym: str, before_day: str, n: int) -> list[str]:
        async with self.engine.sf() as session:
            days = (await session.execute(
                select(FlowReadRow.day).where(FlowReadRow.symbol == sym,
                                              FlowReadRow.day < before_day)
                .order_by(FlowReadRow.day.desc()).limit(n))).scalars().all()
        return sorted(days)

    async def _flag_history(self, sym: str, before_day: str, *, window: int) -> dict[str, list[str]]:
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(FlowReadRow).where(FlowReadRow.symbol == sym,
                                          FlowReadRow.day < before_day)
                .order_by(FlowReadRow.day.desc()).limit(window))).scalars().all()
        hist: dict[str, list[str]] = {}
        for row in rows:
            for f in (row.read or {}).get("flags") or []:
                if f.get("contract"):
                    hist.setdefault(f["contract"], []).append(row.day)
        return hist

    async def reads(self, day: str | None = None, limit: int = 100) -> list[dict]:
        async with self.engine.sf() as session:
            q = select(FlowReadRow).order_by(FlowReadRow.day.desc(), FlowReadRow.score.desc())
            if day:
                q = q.where(FlowReadRow.day == day)
            rows = (await session.execute(q.limit(limit))).scalars().all()
        return [_read_dict(r) for r in rows]

    async def context_for(self, symbol: str, *, max_age_days: int = 3,
                          consumer: str | None = None, ref_id: str | None = None) -> str | None:
        """The plain-language flow context line for another technique, or None.

        When `consumer` is given (tip / em), the delivery is JOURNALED
        (`FlowContextServed`, aggregate_id = the symbol) — this is what makes
        the Symbol Story's "where this read went" panel real (UI-PLAN F1)."""
        async with self.engine.sf() as session:
            row = (await session.execute(
                select(FlowReadRow).where(FlowReadRow.symbol == symbol.upper())
                .order_by(FlowReadRow.day.desc()).limit(1))).scalars().first()
        if row is None:
            return None
        try:
            age = (dt.date.today() - dt.date.fromisoformat(row.day)).days
        except ValueError:
            return None
        if age > max_age_days:
            return None
        line = context_line(_read_dict(row))
        if line and consumer:
            await self.engine.journal.append(
                ev.FLOW_CONTEXT_SERVED,
                {"symbol": row.symbol, "day": row.day, "score": row.score, "lean": row.lean,
                 "line": line, "consumer": consumer, "refId": ref_id},
                aggregate_type="flow_context", aggregate_id=row.symbol)
        return line

    # ------------------------------------------------------------------ UI queries (UI-PLAN F1)
    async def days(self, limit: int = 10) -> list[dict]:
        """Trailing scan days with per-day aggregates for the day picker + strip."""
        async with self.engine.sf() as session:
            day_rows = (await session.execute(
                select(FlowReadRow.day).distinct().order_by(FlowReadRow.day.desc())
                .limit(limit + 1))).scalars().all()
        out: list[dict] = []
        for i, day in enumerate(day_rows[:limit]):
            prev_day = day_rows[i + 1] if i + 1 < len(day_rows) else None
            reads = await self.reads(day=day, limit=500)
            prev = await self.reads(day=prev_day, limit=500) if prev_day else []
            out.append(self._day_summary(day, reads, prev))
        return out

    def _day_summary(self, day: str, reads: list[dict], prev: list[dict]) -> dict:
        call_prem = put_prem = 0.0
        confirmed = 0
        streaks: list[dict] = []
        for r in reads:
            for f in r.get("flags") or []:
                if f.get("optionType") == "put":
                    put_prem += float(f.get("premium") or 0)
                else:
                    call_prem += float(f.get("premium") or 0)
            confirmed += len(r.get("confirmed") or [])
            for contract, n in (r.get("repeatHits") or {}).items():
                streaks.append({"symbol": r["symbol"], "contract": contract, "days": int(n)})
        prev_flagged = {f.get("contract") for r in prev for f in (r.get("flags") or [])}
        confirmed_contracts = {c.get("contract") for r in reads for c in (r.get("confirmed") or [])}
        churn = len([c for c in prev_flagged if c and c not in confirmed_contracts])
        streaks.sort(key=lambda s: -s["days"])
        return {"day": day, "scanned": len(reads),
                "flagged": len([r for r in reads if (r.get("score") or 0) > 0]),
                "callPremium": round(call_prem, 0), "putPremium": round(put_prem, 0),
                "confirmed": confirmed, "churn": churn, "repeatStreaks": streaks[:6]}

    async def story(self, symbol: str, *, days: int = 6) -> dict:
        """One symbol's flow story: reads oldest-to-newest, every journaled
        context delivery, and whether the universe currently holds it."""
        sym = symbol.upper()
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(FlowReadRow).where(FlowReadRow.symbol == sym)
                .order_by(FlowReadRow.day.desc()).limit(days))).scalars().all()
        reads = [_read_dict(r) for r in reversed(rows)]
        from ...models import Event
        async with self.engine.sf() as session:
            evrows = (await session.execute(
                select(Event).where(Event.type == ev.FLOW_CONTEXT_SERVED,
                                    Event.aggregate_id == sym)
                .order_by(Event.ts.desc()).limit(20))).scalars().all()
        deliveries = [{"consumer": (e.payload or {}).get("consumer"),
                       "refId": (e.payload or {}).get("refId"),
                       "day": (e.payload or {}).get("day"),
                       "score": (e.payload or {}).get("score"),
                       "line": (e.payload or {}).get("line"),
                       "ts": e.ts.isoformat() if e.ts else None} for e in evrows]
        universe = {"inUniverse": False, "provenance": None}
        svc = getattr(self.engine, "technique", None)
        if svc is not None:
            with contextlib.suppress(Exception):
                cached = svc.universe_cached() or {}
                prov = (cached.get("provenance") or {}).get(sym)
                universe = {"inUniverse": prov is not None, "provenance": prov}
        return {"symbol": sym, "reads": reads, "deliveries": deliveries, "universe": universe}

    async def to_tip(self, symbol: str) -> dict:
        """Turn the latest read into a TIP — the user judged the flow worth
        acting on, so it enters the normal tip pipeline (grounding, dedupe,
        both shadow books, arming, scorecards) under the source "flow-scan".
        Flow itself still never places an order; the Tip machinery does, with
        every gate it already has. Sending the same read twice dedupes into
        a seen-again bump like any repeated tip."""
        svc = getattr(self.engine, "signals_service", None)
        if svc is None:
            raise RuntimeError("signals layer not attached")
        sym = symbol.upper()
        async with self.engine.sf() as session:
            row = (await session.execute(
                select(FlowReadRow).where(FlowReadRow.symbol == sym)
                .order_by(FlowReadRow.day.desc()).limit(1))).scalars().first()
        if row is None or (row.score or 0) <= 0:
            raise ValueError(f"no flagged flow read for {sym}")
        read = _read_dict(row)
        lean = read.get("lean")
        if lean not in ("bull", "bear"):
            raise ValueError(f"{sym}'s flow is {lean or 'quiet'} — two-sided or directionless "
                             "flow gives no side to trade; nothing to send")
        want = "call" if lean == "bull" else "put"
        flag = next((f for f in (read.get("flags") or [])
                     if f.get("optionType") == want and (f.get("dte") or 0) >= 2), None)
        if flag is None:
            raise ValueError(f"{sym}'s flagged {want}s all expire within a day — "
                             "expiry-board noise, not a tradeable thesis")
        from ...models import RawContent
        from ...signals.schemas import ExtractionResult, TradeSignal
        direction = "long" if lean == "bull" else "short"
        strike = float(flag.get("strike") or 0)
        expiry = str(flag.get("expiry") or "")
        spot = read.get("spot")
        reason = (read.get("reasons") or ["unusual options activity"])[0]
        text = (f"Flow scan {read['day']}: {sym} {lean} — {reason}. "
                f"Contract {want} strike {strike:g} expiry {expiry}, "
                f"premium ${flag.get('premium', 0):,.0f} at Vol/OI {flag.get('volOi')}. "
                f"Direction {direction}.")
        content = RawContent(id=new_id(), source_type="flow", source_name="flow-scan",
                             subject=f"{sym} flow read {read['day']}", body_text=text,
                             meta={"flowDay": read["day"], "flowScore": read["score"]})
        async with self.engine.sf() as session:
            session.add(content)
            await session.commit()
        extraction = ExtractionResult(signals=[TradeSignal(
            ticker=sym, direction=direction, action="open",
            instrument=want, strike=strike, expiry=expiry or None,
            timeframe="swing",
            thesis_summary=f"Options flow: {reason}",
            evidence_quotes=[f"{sym} {lean}", f"{want} strike {strike:g} expiry {expiry}",
                             f"Direction {direction}"],
            confidence="implied", is_actionable=True)], source_type="trade_alert")
        out = await svc.handle_extraction(content, extraction, source_text=text)
        result = out[0] if out else {}
        await self.engine.journal.append(
            ev.FLOW_CONTEXT_SERVED,
            {"symbol": sym, "day": read["day"], "score": read["score"], "lean": lean,
             "line": f"sent to Tips as a {want} tip", "consumer": "tip",
             "refId": (result.get("signal") or {}).get("id")},
            aggregate_type="flow_context", aggregate_id=sym)
        return {**result, "spot": spot}

    async def universe_layer(self) -> list[str]:
        """Symbols the scanner is actively tracking: score >= the threshold on
        >= 2 of the last 3 scan days. They join the working universe with
        provenance "flow" and drop out when the chain goes quiet (UI-PLAN F5)."""
        floor = float(self.engine.settings.get("techniques.flow.universe_score_min", 5))
        async with self.engine.sf() as session:
            day_rows = (await session.execute(
                select(FlowReadRow.day).distinct().order_by(FlowReadRow.day.desc())
                .limit(3))).scalars().all()
            if not day_rows:
                return []
            rows = (await session.execute(
                select(FlowReadRow.symbol, FlowReadRow.day, FlowReadRow.score)
                .where(FlowReadRow.day.in_(day_rows), FlowReadRow.score >= floor))).all()
        hits: dict[str, set[str]] = {}
        for sym, d, _score in rows:
            hits.setdefault(sym, set()).add(d)
        return sorted(s for s, ds in hits.items() if len(ds) >= 2)

    async def brief(self, day: str | None = None) -> dict:
        """The Morning Brief, composed server-side (UI-PLAN F4 reads this)."""
        async with self.engine.sf() as session:
            day_rows = (await session.execute(
                select(FlowReadRow.day).distinct().order_by(FlowReadRow.day.desc())
                .limit(8))).scalars().all()
        if not day_rows:
            return {"day": day, "sections": {}, "empty": True}
        if day is None or day not in day_rows:
            day = day if day in day_rows else day_rows[0]
        idx = day_rows.index(day)
        prev_day = day_rows[idx + 1] if idx + 1 < len(day_rows) else None
        reads = await self.reads(day=day, limit=500)
        prev = await self.reads(day=prev_day, limit=500) if prev_day else []
        flagged = [r for r in reads if (r.get("score") or 0) > 0]
        flagged.sort(key=lambda r: -(r.get("score") or 0))

        confirmed_rows: list[dict] = []
        confirmed_contracts: set[str] = set()
        for r in flagged:
            for c in (r.get("confirmed") or []):
                confirmed_contracts.add(str(c.get("contract")))
                confirmed_rows.append({"symbol": r["symbol"], "contract": c.get("contract"),
                                       "expiry": c.get("expiry"), "optionType": c.get("optionType"),
                                       "strike": c.get("strike"), "oiDelta": c.get("oiDelta"),
                                       "volume": c.get("volume"), "score": r.get("score")})
        churn_rows = []
        for r in prev:
            for f in (r.get("flags") or []):
                if str(f.get("contract")) not in confirmed_contracts:
                    churn_rows.append({"symbol": r["symbol"], "contract": f.get("contract"),
                                       "premium": f.get("premium")})
        prev_contracts = {str(f.get("contract"))
                         for r in prev for f in (r.get("flags") or [])}
        prev_hot = {str(c) for r in prev for c in (r.get("repeatHits") or {})}

        accumulation = []
        new_today = []
        dying = []
        for r in flagged:
            for contract, n in (r.get("repeatHits") or {}).items():
                flag = next((f for f in (r.get("flags") or []) if f.get("contract") == contract), {})
                accumulation.append({"symbol": r["symbol"], "contract": contract, "days": int(n),
                                     "dte": flag.get("dte"), "premium": flag.get("premium")})
            for f in (r.get("flags") or []):
                if str(f.get("contract")) not in prev_contracts:
                    new_today.append({"symbol": r["symbol"], "contract": f.get("contract"),
                                      "premium": f.get("premium"), "volOi": f.get("volOi"),
                                      "lean": r.get("lean"), "strong": f.get("strong")})
                if (f.get("dte") or 99) <= 1:
                    dying.append({"symbol": r["symbol"], "contract": f.get("contract"),
                                  "dte": f.get("dte"), "reason": "expires tomorrow — the OI verdict never arrives"})
        today_hot = {str(c) for r in flagged for c in (r.get("repeatHits") or {})}
        for c in prev_hot - today_hot:
            sym = next((r["symbol"] for r in prev if c in (r.get("repeatHits") or {})), None)
            dying.append({"symbol": sym, "contract": c, "dte": None, "reason": "repeat streak broke"})

        context_lines = [{"symbol": r["symbol"], "line": context_line(r)}
                         for r in flagged if (r.get("score") or 0) >= 3 and context_line(r)]
        summary = self._day_summary(day, reads, prev)
        return {"day": day, "prevDay": prev_day, "summary": summary, "empty": False,
                "sections": {"confirmedOvernight": confirmed_rows[:8], "churn": churn_rows[:6],
                             "accumulation": sorted(accumulation, key=lambda a: -a["days"])[:6],
                             "newToday": sorted(new_today, key=lambda n: -(n.get("premium") or 0))[:8],
                             "dying": dying[:6], "contextLines": context_lines[:6]}}


def attach_flow_layer(engine) -> None:
    """Called from the FastAPI lifespan after the engine starts."""
    if getattr(engine, "flow_service", None) is not None:
        return
    engine.flow_service = FlowService(engine)
    engine.flow_service.start()
