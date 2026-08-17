"""PositionKeeper: positions, cash, realized/unrealized P&L, equity, daily loss.

Keeps an in-memory mirror for the hot path (risk checks on every order) and
persists projections to the DB. Average-cost method; options use a 100x
multiplier.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from . import bus as topics
from . import events as ev
from .bus import Bus
from .domain import now_ms
from .events import Journal
from .marketdata import QuoteCache
from .models import EquityPoint, Portfolio, Position

ET = ZoneInfo("America/New_York")


def _mult(sec_type: str) -> float:
    return 100.0 if sec_type == "OPT" else 1.0


class PositionKeeper:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        bus: Bus,
        journal: Journal,
        quotes: QuoteCache,
    ) -> None:
        self._sf = session_factory
        self._bus = bus
        self._journal = journal
        self._quotes = quotes
        self._portfolios: dict[str, dict] = {}
        self._positions: dict[tuple[str, str, str], dict] = {}
        self._day_start_equity: dict[tuple[str, str], float] = {}  # (pid, ET date) -> equity

    # --- loading ------------------------------------------------------------
    async def load(self) -> None:
        async with self._sf() as session:
            for p in (await session.execute(select(Portfolio))).scalars():
                self._portfolios[p.id] = {
                    "id": p.id, "name": p.name, "kind": p.kind, "cash": p.cash,
                    "startingCash": p.starting_cash, "baseCurrency": p.base_currency,
                    "sourceName": p.source_name, "isDefault": p.is_default,
                }
            for pos in (await session.execute(select(Position))).scalars():
                self._positions[(pos.portfolio_id, pos.symbol, pos.sec_type)] = {
                    "portfolioId": pos.portfolio_id, "symbol": pos.symbol,
                    "secType": pos.sec_type, "qty": pos.qty, "avgCost": pos.avg_cost,
                    "realizedPnl": pos.realized_pnl,
                }

    def register_portfolio(self, p: Portfolio) -> None:
        self._portfolios[p.id] = {
            "id": p.id, "name": p.name, "kind": p.kind, "cash": p.cash,
            "startingCash": p.starting_cash, "baseCurrency": p.base_currency,
            "sourceName": p.source_name, "isDefault": p.is_default,
        }

    # --- queries ------------------------------------------------------------
    def portfolios(self) -> list[dict]:
        return list(self._portfolios.values())

    def portfolio(self, pid: str) -> dict | None:
        return self._portfolios.get(pid)

    def position_qty(self, pid: str, symbol: str, sec_type: str = "STK") -> float:
        pos = self._positions.get((pid, symbol, sec_type))
        return pos["qty"] if pos else 0.0

    def positions_list(self, pid: str | None = None) -> list[dict]:
        out = []
        for (p, _sym, _st), pos in self._positions.items():
            if pid and p != pid:
                continue
            if abs(pos["qty"]) < 1e-9 and abs(pos["realizedPnl"]) < 1e-9:
                continue
            out.append(self._enrich(pos))
        return out

    def _enrich(self, pos: dict) -> dict:
        q = self._quotes.get(pos["symbol"])
        last = q.last if q and q.last > 0 else pos["avgCost"]
        mult = _mult(pos["secType"])
        unreal = (last - pos["avgCost"]) * pos["qty"] * mult
        return {
            **pos,
            "last": round(last, 4),
            "marketValue": round(pos["qty"] * last * mult, 2),
            "unrealizedPnl": round(unreal, 2),
            "unrealizedPnlPct": round(
                (last / pos["avgCost"] - 1) * 100 * (1 if pos["qty"] >= 0 else -1), 2)
            if pos["avgCost"] > 0 else 0.0,
        }

    async def equity(self, pid: str) -> float:
        p = self._portfolios.get(pid)
        if p is None:
            return 0.0
        total = p["cash"]
        for (ppid, sym, st), pos in self._positions.items():
            if ppid != pid or abs(pos["qty"]) < 1e-9:
                continue
            q = self._quotes.get(sym)
            last = q.last if q and q.last > 0 else pos["avgCost"]
            total += pos["qty"] * last * _mult(st)
        return total

    async def gross_exposure(self, pid: str) -> float:
        total = 0.0
        for (ppid, sym, st), pos in self._positions.items():
            if ppid != pid or abs(pos["qty"]) < 1e-9:
                continue
            q = self._quotes.get(sym)
            last = q.last if q and q.last > 0 else pos["avgCost"]
            total += abs(pos["qty"]) * last * _mult(st)
        return total

    async def daily_loss_pct(self, pid: str) -> float | None:
        """Percent change of equity vs the first observation of the ET trading day."""
        today = dt.datetime.now(tz=ET).date().isoformat()
        key = (pid, today)
        eq = await self.equity(pid)
        if key not in self._day_start_equity:
            self._day_start_equity[key] = eq
            return 0.0
        start = self._day_start_equity[key]
        if start <= 0:
            return None
        return (eq - start) / start * 100

    # --- mutations -----------------------------------------------------------
    async def apply_fill(
        self,
        portfolio_id: str,
        symbol: str,
        sec_type: str,
        side: str,
        qty: float,
        price: float,
        commission: float,
    ) -> dict:
        mult = _mult(sec_type)
        signed = qty if side == "BUY" else -qty
        key = (portfolio_id, symbol, sec_type)
        pos = self._positions.get(key) or {
            "portfolioId": portfolio_id, "symbol": symbol, "secType": sec_type,
            "qty": 0.0, "avgCost": 0.0, "realizedPnl": 0.0,
        }
        old_qty, avg = pos["qty"], pos["avgCost"]
        realized_delta = 0.0

        if old_qty == 0 or old_qty * signed > 0:
            total = abs(old_qty) + abs(signed)
            pos["avgCost"] = (abs(old_qty) * avg + abs(signed) * price) / total if total else 0.0
            pos["qty"] = old_qty + signed
        else:
            closed = min(abs(old_qty), abs(signed))
            direction = 1.0 if old_qty > 0 else -1.0
            realized_delta = (price - avg) * closed * direction * mult
            pos["realizedPnl"] += realized_delta
            new_qty = old_qty + signed
            if abs(new_qty) < 1e-9:
                pos["qty"], pos["avgCost"] = 0.0, 0.0
            elif old_qty * new_qty > 0:
                pos["qty"] = new_qty  # partial close keeps avg cost
            else:
                pos["qty"], pos["avgCost"] = new_qty, price  # crossed through flat
        self._positions[key] = pos

        pf = self._portfolios.get(portfolio_id)
        if pf is not None:
            pf["cash"] -= signed * price * mult
            pf["cash"] -= commission

        async with self._sf() as session:
            row = (await session.execute(
                select(Position).where(
                    Position.portfolio_id == portfolio_id,
                    Position.symbol == symbol,
                    Position.sec_type == sec_type,
                ))).scalar_one_or_none()
            if row is None:
                row = Position(portfolio_id=portfolio_id, symbol=symbol, sec_type=sec_type)
                session.add(row)
            row.qty = pos["qty"]
            row.avg_cost = pos["avgCost"]
            row.realized_pnl = pos["realizedPnl"]
            pf_row = await session.get(Portfolio, portfolio_id)
            if pf_row is not None and pf is not None:
                pf_row.cash = pf["cash"]
            await session.commit()

        enriched = self._enrich(pos)
        await self._journal.append(
            ev.POSITION_UPDATED,
            {"symbol": symbol, "qty": pos["qty"], "avgCost": round(pos["avgCost"], 4),
             "realizedDelta": round(realized_delta, 2), "commission": commission},
            aggregate_type="position", aggregate_id=f"{portfolio_id}:{symbol}",
            portfolio_id=portfolio_id,
        )
        self._bus.publish(topics.POSITIONS, enriched)
        if pf is not None:
            self._bus.publish(topics.PORTFOLIO, {
                "portfolioId": portfolio_id, "cash": round(pf["cash"], 2), "ts": now_ms()})
        return enriched

    async def snapshot_equity(self) -> list[dict]:
        """Persist an equity point per portfolio (called periodically by the engine)."""
        out = []
        async with self._sf() as session:
            for pid in self._portfolios:
                eq = await self.equity(pid)
                cash = self._portfolios[pid]["cash"]
                session.add(EquityPoint(portfolio_id=pid, ts=now_ms(), equity=eq, cash=cash))
                point = {"portfolioId": pid, "equity": round(eq, 2),
                         "cash": round(cash, 2), "ts": now_ms()}
                out.append(point)
                self._bus.publish(topics.PORTFOLIO, point)
            await session.commit()
        return out

    async def equity_series(self, pid: str, limit: int = 2000) -> list[list]:
        async with self._sf() as session:
            rows = (await session.execute(
                select(EquityPoint)
                .where(EquityPoint.portfolio_id == pid)
                .order_by(EquityPoint.ts.desc())
                .limit(limit))).scalars().all()
        return [[r.ts, round(r.equity, 2)] for r in reversed(rows)]
