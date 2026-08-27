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

import datetime as dt
import logging

from sqlalchemy import delete, select

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
    repeat_counts,
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
        chain-snapshots research feed so the day's rows are already stored)."""
        at = str(self.engine.settings.get("techniques.flow.scan_at", "16:45"))
        self.engine.scheduler.register("flow_scan", at, lambda: self.scan())

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
        day = day or dt.datetime.now(ET).strftime("%Y-%m-%d")
        cap = int(eng.settings.get("techniques.flow.scan_top", 60))
        syms = [s.upper() for s in (symbols or self._universe(cap))]

        scanned, flagged, errors, live_fallbacks = 0, 0, 0, 0
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
            await self._persist_read(read)
            if read["score"] > 0:
                flagged += 1
                reads.append({"symbol": sym, "score": read["score"], "lean": read["lean"]})
        summary = {"day": day, "scanned": scanned, "flagged": flagged, "errors": errors,
                   "liveFallbacks": live_fallbacks,
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
                          agg=agg, t=t)

    # ------------------------------------------------------------------ persistence
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

    async def context_for(self, symbol: str, *, max_age_days: int = 3) -> str | None:
        """The plain-language flow context line for another technique, or None."""
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
        return context_line(_read_dict(row))


def attach_flow_layer(engine) -> None:
    """Called from the FastAPI lifespan after the engine starts."""
    if getattr(engine, "flow_service", None) is not None:
        return
    engine.flow_service = FlowService(engine)
    engine.flow_service.start()
