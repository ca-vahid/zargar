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
from .fx import FxService, currency_for_symbol
from .marketdata import QuoteCache
from .models import BrokerageAccount, EquityPoint, Portfolio, Position
from .options import occ

ET = ZoneInfo("America/New_York")


def _mult(sec_type: str) -> float:
    return 100.0 if sec_type == "OPT" else 1.0


def _decimate(points: list[list], budget: int) -> list[list]:
    """Thin a series to ~`budget` samples WITHOUT losing its range.

    Keeping every Nth sample drops the highs and lows, so the same window came
    back with a different high depending on where the buckets happened to fall
    (a real 11,335 spike on one read, gone on the next — 2026-09-14). Min/max
    decimation keeps each bucket's extremes in time order instead, so the shape
    and the range survive at any budget.
    """
    if not budget or len(points) <= budget:
        return points
    buckets = max(1, budget // 2)
    step = len(points) / buckets
    keep: set[int] = {0, len(points) - 1}          # never drop the live point
    for b in range(buckets):
        lo_i = int(b * step)
        hi_i = min(len(points), int((b + 1) * step))
        if hi_i <= lo_i:
            continue
        window = range(lo_i, hi_i)
        keep.add(min(window, key=lambda i: points[i][1]))
        keep.add(max(window, key=lambda i: points[i][1]))
    return [p for i, p in enumerate(points) if i in keep]


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
        self.fx = FxService(quotes)
        self._portfolios: dict[str, dict] = {}
        self._positions: dict[tuple[str, str, str], dict] = {}
        self._day_start_equity: dict[tuple[str, str], float] = {}  # (pid, ET date) -> equity

    # --- loading ------------------------------------------------------------
    async def load(self) -> None:
        async with self._sf() as session:
            venues = {
                acct.portfolio_id: acct.venue
                for acct in (await session.execute(select(BrokerageAccount))).scalars()
            }
            for p in (await session.execute(select(Portfolio))).scalars():
                self._portfolios[p.id] = {
                    "id": p.id, "name": p.name, "kind": p.kind, "cash": p.cash,
                    "startingCash": p.starting_cash, "baseCurrency": p.base_currency,
                    "sourceName": p.source_name, "isDefault": p.is_default,
                    "book": getattr(p, "book", None), "archived": bool(getattr(p, "archived", False)),
                    "venue": venues.get(p.id, "ibkr"),
                }
            for pos in (await session.execute(select(Position))).scalars():
                self._positions[(pos.portfolio_id, pos.symbol, pos.sec_type)] = {
                    "portfolioId": pos.portfolio_id, "symbol": pos.symbol,
                    "secType": pos.sec_type, "qty": pos.qty, "avgCost": pos.avg_cost,
                    "realizedPnl": pos.realized_pnl,
                    "currency": currency_for_symbol(pos.symbol),
                }

    def register_portfolio(self, p: Portfolio, *, venue: str = "ibkr") -> None:
        self._portfolios[p.id] = {
            "id": p.id, "name": p.name, "kind": p.kind, "cash": p.cash,
            "startingCash": p.starting_cash, "baseCurrency": p.base_currency,
            "sourceName": p.source_name, "isDefault": p.is_default,
            "book": getattr(p, "book", None), "archived": bool(getattr(p, "archived", False)),
            "venue": venue,
        }

    async def remove_shadow(self, pid: str) -> dict:
        """Delete a SHADOW research book (demo/test cleanup, user 2026-08-30).
        Shadow-kind ONLY — sim/paper/live portfolios are never deletable. The
        book's simulated orders/executions/positions/equity points go with it;
        the JOURNAL (append-only) keeps the audit trail. A future tip from the
        same source simply re-creates a fresh book."""
        from sqlalchemy import delete as _delete

        from .models import Execution, Order
        info = self._portfolios.get(pid)
        if info is None:
            raise ValueError("unknown portfolio")
        if info.get("kind") != "shadow":
            raise ValueError("only shadow research books can be removed")
        async with self._sf() as session:
            order_ids = list((await session.execute(
                select(Order.id).where(Order.portfolio_id == pid))).scalars())
            if order_ids:
                await session.execute(
                    _delete(Execution).where(Execution.order_id.in_(order_ids)))
                await session.execute(_delete(Order).where(Order.id.in_(order_ids)))
            await session.execute(_delete(Position).where(Position.portfolio_id == pid))
            await session.execute(_delete(EquityPoint).where(EquityPoint.portfolio_id == pid))
            row = await session.get(Portfolio, pid)
            if row is not None:
                await session.delete(row)
            await session.commit()
        self._portfolios.pop(pid, None)
        for key in [k for k in self._positions if k[0] == pid]:
            self._positions.pop(key, None)
        await self._journal.append(
            ev.PORTFOLIO_REMOVED,
            {"id": pid, "name": info.get("name"), "kind": "shadow",
             "source": info.get("sourceName"), "orders": len(order_ids)},
            aggregate_type="portfolio", aggregate_id=pid)
        return info

    # --- queries ------------------------------------------------------------
    def portfolios(self, *, include_archived: bool = False) -> list[dict]:
        """Live books. Archived books (a retired Practice book) stay addressable by
        id for history and orders but never appear in lists or totals."""
        return [p for p in self._portfolios.values() if include_archived or not p.get("archived")]

    async def set_archived(self, pid: str, archived: bool) -> dict:
        p = self._portfolios.get(pid)
        if p is None:
            raise ValueError("unknown portfolio")
        if p.get("kind") not in ("sim", "shadow"):
            raise ValueError("only practice/research books can be archived")
        async with self._sf() as session:
            row = await session.get(Portfolio, pid)
            row.archived = bool(archived)
            await session.commit()
        p["archived"] = bool(archived)
        return dict(p)

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
            if not pid and (self._portfolios.get(p) or {}).get("archived"):
                continue            # an archived book's holdings are history, not exposure
            if abs(pos["qty"]) < 1e-9 and abs(pos["realizedPnl"]) < 1e-9:
                continue
            out.append(self._enrich(pos))
        return out

    def _pos_currency(self, pos: dict) -> str:
        return (pos.get("currency") or currency_for_symbol(pos["symbol"])).upper()

    def _mark(self, pos: dict) -> float:
        """What one unit of this position is worth right now.

        Options mark at the MID of a two-sided market. A thin contract's last
        print is not a valuation: on 2026-09-14 one print marked two INTC 0DTE
        calls bought at $1.00 near $7, which put a +$1,406 spike into the
        book's equity history permanently and set the dashboard chart's whole
        vertical range. The same figure feeds `daily_loss_pct`, so a bad print
        the other way would halt a book that had not lost anything.

        Falls back exactly as before: the last print, then the broker's own
        mark from the last sync, then avg cost (which reads as flat P&L).
        """
        q = self._quotes.get(pos["symbol"])
        # An option marks on its BOOK, at the mid — including a 0 bid, where
        # half the ask is the honest read on a contract going worthless. Only
        # with no ask at all does a print get used: a lone print on a thin
        # contract is what put +$1,406 into a book for one sample.
        if pos["secType"] == "OPT" and q is not None and q.ask > 0 and q.ask >= q.bid:
            return (max(q.bid, 0.0) + q.ask) / 2
        if q is not None and q.last > 0:
            return q.last
        return pos.get("mark") or pos["avgCost"]

    def mark_price(self, symbol: str, sec_type: str = "STK") -> float | None:
        """The valuation `equity()` uses for one unit of `symbol` — for callers
        that hold a LOT rather than a position (the ledger's FIFO lots).

        Same rule as `_mark` (PLATFORM-RULES invariant 22). The ledger used to
        take the last print here while the book marked options at the mid, so
        the day the mid rule shipped the ledger grew a "+4.00 unexplained" gap
        that was nothing but (mid − last) × qty across three open lots
        (2026-09-14). None when there is nothing to mark against.
        """
        held = next((p for (_pid, s, st), p in self._positions.items()
                     if s == symbol and st == sec_type and p.get("mark")), None)
        probe = {"symbol": symbol, "secType": sec_type, "avgCost": 0.0,
                 **({"mark": held["mark"]} if held else {})}
        return self._mark(probe) or None

    def _pos_value(self, pos: dict, target_ccy: str) -> float:
        """Position market value converted into target_ccy (signed)."""
        native = pos["qty"] * self._mark(pos) * _mult(pos["secType"])
        return self.fx.convert(native, self._pos_currency(pos), target_ccy)

    def _enrich(self, pos: dict) -> dict:
        # one definition of the mark, so the displayed P&L and the equity that
        # the risk halt reads can never disagree
        last = self._mark(pos)
        mult = _mult(pos["secType"])
        unreal = (last - pos["avgCost"]) * pos["qty"] * mult
        option = None
        if pos["secType"] == "OPT":
            o = occ.parse(pos["symbol"])
            option = o.to_dict() if o else None
        return {
            **pos,
            "option": option,
            "currency": self._pos_currency(pos),
            "last": round(last, 4),
            "marketValue": round(pos["qty"] * last * mult, 2),  # native currency
            "unrealizedPnl": round(unreal, 2),
            "unrealizedPnlPct": round(
                (last / pos["avgCost"] - 1) * 100 * (1 if pos["qty"] >= 0 else -1), 2)
            if pos["avgCost"] > 0 else 0.0,
        }

    async def equity(self, pid: str) -> float:
        """Cash + positions, each converted into the portfolio's base currency."""
        p = self._portfolios.get(pid)
        if p is None:
            return 0.0
        base = (p.get("baseCurrency") or "USD").upper()
        total = p["cash"]
        for (ppid, _sym, _st), pos in self._positions.items():
            if ppid != pid or abs(pos["qty"]) < 1e-9:
                continue
            total += self._pos_value(pos, base)
        return total

    async def gross_exposure(self, pid: str) -> float:
        p = self._portfolios.get(pid)
        base = ((p or {}).get("baseCurrency") or "USD").upper()
        total = 0.0
        for (ppid, _sym, _st), pos in self._positions.items():
            if ppid != pid or abs(pos["qty"]) < 1e-9:
                continue
            total += abs(self._pos_value(pos, base))
        return total

    def _quotes_ready(self, pid: str) -> bool:
        """True when every open position in the portfolio has a live quote.

        Anchoring the day-start equity on avgCost fallbacks produces false
        baselines (and false daily-loss triggers) — wait for real prices.
        """
        for (ppid, sym, _st), pos in self._positions.items():
            if ppid != pid or abs(pos["qty"]) < 1e-9:
                continue
            q = self._quotes.get(sym)
            if q is None or q.last <= 0:
                return False
        return True

    async def day_start_equity(self, pid: str) -> float | None:
        """This ET day's opening equity — the number every "today" figure measures from.

        Read from the PERSISTED equity points, not from whatever the process
        happened to see first: the last sample before today's 04:00 ET (i.e.
        the previous session's close, which is how every broker quotes a day
        change — see the day-change rule in CLAUDE.md), else the first sample
        of today for a book with no history, else its starting cash.

        Durability is the point. The old in-memory anchor was seeded with
        "equity the first time we looked today", so a mid-day restart re-based
        the day at the restart price: a book down 4% came back reading flat and
        the daily-loss halt forgot it (found 2026-09-14 while fixing the
        dashboard's red/green flip).
        """
        today = dt.datetime.now(tz=ET).date().isoformat()
        key = (pid, today)
        if key in self._day_start_equity:
            return self._day_start_equity[key] or None
        day0 = int(dt.datetime.now(tz=ET).replace(
            hour=4, minute=0, second=0, microsecond=0).timestamp() * 1000)
        async with self._sf() as session:
            prev = (await session.execute(
                select(EquityPoint).where(EquityPoint.portfolio_id == pid)
                .where(EquityPoint.ts < day0)
                .order_by(EquityPoint.ts.desc()).limit(1))).scalars().first()
            first = None if prev is not None else (await session.execute(
                select(EquityPoint).where(EquityPoint.portfolio_id == pid)
                .where(EquityPoint.ts >= day0)
                .order_by(EquityPoint.ts).limit(1))).scalars().first()
        row = prev or first
        if row is not None:
            self._day_start_equity[key] = row.equity
            return row.equity or None
        # a book with no samples at all: anchor on live equity once prices are
        # real, exactly as the old path did — but never on avgCost fallbacks
        if not self._quotes_ready(pid):
            return None
        eq = await self.equity(pid)
        self._day_start_equity[key] = eq
        return eq or None

    async def daily_loss_pct(self, pid: str) -> float | None:
        """Percent change of equity vs this ET day's opening equity."""
        start = await self.day_start_equity(pid)
        if not start or start <= 0:
            return None
        eq = await self.equity(pid)
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
            "currency": currency_for_symbol(symbol),
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

    async def sync_portfolio_state(
        self,
        pid: str,
        *,
        cash: float,
        positions: list[dict],  # [{symbol, secType, qty, avgCost}]
        source: str = "snaptrade",
    ) -> dict:
        """Authoritative broker-state overwrite (used by brokerage sync).

        Preserves accumulated realizedPnl on surviving keys, zeroes symbols the
        broker no longer reports, and adjusts the day-start-equity memo so a
        sync delta never shows up as intraday P&L.
        """
        pf = self._portfolios.get(pid)
        if pf is None:
            return {}
        eq_before = await self.equity(pid)
        # Resolve the day anchor while the book still looks the way it did
        # BEFORE this level-set. Resolving it afterwards anchors on the new
        # equity and the shift below then counts the same delta twice — a book
        # going 0 -> 10,000 read as -50% and tripped the daily-loss halt.
        await self.day_start_equity(pid)
        incoming = {(p["symbol"].upper(), p.get("secType", "STK")): p for p in positions}
        changes: list[dict] = []

        for (ppid, sym, st), pos in list(self._positions.items()):
            if ppid != pid:
                continue
            new = incoming.pop((sym, st), None)
            new_qty = float(new["qty"]) if new else 0.0
            new_avg = float(new["avgCost"]) if new else 0.0
            if abs(pos["qty"] - new_qty) > 1e-9 or abs(pos["avgCost"] - new_avg) > 1e-6:
                changes.append({"symbol": sym, "secType": st,
                                "qtyBefore": pos["qty"], "qtyAfter": new_qty})
                pos["qty"], pos["avgCost"] = new_qty, new_avg  # realizedPnl preserved
            if new and new.get("currency"):
                pos["currency"] = str(new["currency"]).upper()
            if new and new.get("price"):
                pos["mark"] = float(new["price"])   # broker's own mark — the no-quote fallback
        for (sym, st), new in incoming.items():
            self._positions[(pid, sym, st)] = {
                "portfolioId": pid, "symbol": sym, "secType": st,
                "qty": float(new["qty"]), "avgCost": float(new["avgCost"]),
                "realizedPnl": 0.0,
                "currency": str(new.get("currency") or currency_for_symbol(sym)).upper(),
                **({"mark": float(new["price"])} if new.get("price") else {}),
            }
            changes.append({"symbol": sym, "secType": st,
                            "qtyBefore": 0.0, "qtyAfter": float(new["qty"])})

        cash_before = pf["cash"]
        pf["cash"] = float(cash)

        async with self._sf() as session:
            for (ppid, sym, st), pos in self._positions.items():
                if ppid != pid:
                    continue
                row = (await session.execute(
                    select(Position).where(
                        Position.portfolio_id == pid,
                        Position.symbol == sym,
                        Position.sec_type == st,
                    ))).scalar_one_or_none()
                if row is None:
                    row = Position(portfolio_id=pid, symbol=sym, sec_type=st)
                    session.add(row)
                row.qty = pos["qty"]
                row.avg_cost = pos["avgCost"]
                row.realized_pnl = pos["realizedPnl"]
            pf_row = await session.get(Portfolio, pid)
            if pf_row is not None:
                pf_row.cash = pf["cash"]
            await session.commit()

        eq_after = await self.equity(pid)
        # A broker sync is a level-set, not trading P&L — shift the day anchor
        # (resolved above, against the pre-sync book).
        day_key = (pid, dt.datetime.now(tz=ET).date().isoformat())
        if day_key in self._day_start_equity:
            self._day_start_equity[day_key] += eq_after - eq_before

        diff = {
            "source": source,
            "cashBefore": round(cash_before, 2),
            "cashAfter": round(pf["cash"], 2),
            "positionsChanged": changes,
        }
        # Quiet cycles (no cash delta, no position change) are not decisions —
        # journaling them every sync would drown the audit trail.
        if changes or abs(pf["cash"] - cash_before) > 0.005:
            await self._journal.append(
                ev.BROKER_SYNC, diff, aggregate_type="portfolio",
                aggregate_id=pid, portfolio_id=pid)
        for change in changes:
            pos = self._positions.get((pid, change["symbol"], change["secType"]))
            if pos is not None:
                await self._journal.append(
                    ev.POSITION_RECONCILED, change,
                    aggregate_type="position",
                    aggregate_id=f"{pid}:{change['symbol']}", portfolio_id=pid)
                self._bus.publish(topics.POSITIONS, self._enrich(pos))
        self._bus.publish(topics.PORTFOLIO, {
            "portfolioId": pid, "cash": round(pf["cash"], 2), "ts": now_ms()})
        return diff

    async def snapshot_equity(self) -> list[dict]:
        """Persist an equity point per portfolio (called periodically by the engine)."""
        out = []
        async with self._sf() as session:
            for pid in self._portfolios:
                eq = await self.equity(pid)
                cash = self._portfolios[pid]["cash"]
                session.add(EquityPoint(portfolio_id=pid, ts=now_ms(), equity=eq, cash=cash))
                today = await self.daily_loss_pct(pid)
                start = await self.day_start_equity(pid)
                point = {"portfolioId": pid, "equity": round(eq, 2),
                         "cash": round(cash, 2), "ts": now_ms(),
                         "dayStart": round(start, 2) if start is not None else None,
                         "todayPct": round(today, 2) if today is not None else None}
                out.append(point)
                self._bus.publish(topics.PORTFOLIO, point)
            await session.commit()
        return out

    async def equity_series(self, pid: str, limit: int = 2000, *,
                            since: int | None = None, points: int = 0) -> list[list]:
        """Equity samples, newest last. `since` (epoch ms) bounds the window and
        `points` caps how many come back — a month of 30-second samples is 86k
        rows, so the caller asks for a budget and gets one value per bucket
        (the LAST in each, so the final point is always the live one)."""
        async with self._sf() as session:
            q = select(EquityPoint).where(EquityPoint.portfolio_id == pid)
            if since is not None:
                q = q.where(EquityPoint.ts >= since)
            rows = (await session.execute(
                q.order_by(EquityPoint.ts.desc()).limit(limit))).scalars().all()
        out = [[r.ts, round(r.equity, 2)] for r in reversed(rows)]
        return _decimate(out, points)
