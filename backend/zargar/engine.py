"""Engine: wires config, DB, bus, journal, settings, market data, brokers,
risk, orders, and background tasks into one lifecycle."""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging

from sqlalchemy import func, select

from . import bus as topics
from . import events as ev
from .bus import Bus
from .config import AppConfig
from .db import create_all, make_engine, make_session_factory
from .domain import OrderStatus, new_id
from .events import Journal
from .marketdata import BarAggregator, BarPersister, QuoteCache, load_bars, persist_bars
from .models import BarRow, Order, Portfolio, Watchlist
from .orders import OrderManager
from .portfolio import ET, PositionKeeper
from .risk import HaltState, RiskGate
from .settings_service import SettingsService

log = logging.getLogger("zargar.engine")

DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD", "SPY", "SHOP.TO", "TD.TO"]


class Engine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db = make_engine(config.database_url, echo=config.db_echo)
        self.sf = make_session_factory(self.db)
        self.bus = Bus()
        self.journal = Journal(self.sf, self.bus)
        self.settings = SettingsService(self.sf, self.bus, self.journal)
        self.quotes = QuoteCache(self.bus)
        self.bars = BarAggregator(self.bus)
        self.halt = HaltState()
        self.positions = PositionKeeper(self.sf, self.bus, self.journal, self.quotes)
        self.risk = RiskGate(self.settings, self.quotes, self.positions, self.halt)

        # Executors / feeds are attached in start() (sim always; ibkr when configured)
        self.sim_executor = None
        self.ibkr = None            # IBKRBroker (feed+executor) when configured
        self.snaptrade = None       # SnapTradeBroker (executor) when configured
        self.snaptrade_sync = None  # SnapTradeSync (account/balance/position sync)
        self._snaptrade_client = None
        self.feed = None
        self.orders: OrderManager | None = None
        self.proposals = None        # attached by signal layer
        self.signals_service = None  # attached by signal layer
        self.technique = None        # TechniqueService (attached by technique layer)
        self.chat = None             # ChatService
        self.telegram = None
        self._tasks: list[asyncio.Task] = []
        self._history_seeded: set[str] = set()  # symbols whose day bars were loaded
        self._bar_persister: BarPersister | None = None
        self._drift_warned: set[tuple[str, str]] = set()  # (pid, ET date) warned once/day
        self.started = False

    # ------------------------------------------------------------------ start
    async def start(self) -> None:
        from .brokers.sim import SimExecutor, SimQuoteFeed  # local import keeps deps lazy

        await create_all(self.db)
        await self.settings.load()
        await self._seed()
        await self.positions.load()

        # restore kill switch state across restarts
        halt_state = self.settings.get("system.halt")
        if isinstance(halt_state, dict) and halt_state.get("engaged"):
            self.halt.engage(halt_state.get("reason", "restored after restart"))

        self.sim_executor = SimExecutor()
        if self.config.broker == "ibkr":
            try:
                from .brokers.ibkr import IBKRBroker
                self.ibkr = IBKRBroker(
                    host=self.config.ibkr_host, port=self.config.ibkr_port,
                    client_id=self.config.ibkr_client_id, on_quote=self.quotes.on_quote)
                await self.ibkr.start()
                self.feed = self.ibkr
                await self.journal.append(ev.BROKER_CONNECTED, {"broker": "ibkr"})
            except Exception as exc:  # pragma: no cover - depends on gateway
                log.error("IBKR connection failed (%s); falling back to sim feed", exc)
                await self.journal.append(ev.BROKER_DISCONNECTED, {"broker": "ibkr", "error": str(exc)})
        # SnapTrade venue (Wealthsimple / Webull through the aggregator)
        snaptrade_configured = bool(
            self.config.snaptrade_client_id and self.config.snaptrade_consumer_key
            and self.settings.get("snaptrade.enabled", False))
        if snaptrade_configured:
            from .brokers.snaptrade import SnapTradeBroker, SnapTradeClient, SnapTradeSync
            self._snaptrade_client = SnapTradeClient(
                self.config.snaptrade_client_id, self.config.snaptrade_consumer_key)
            symbol_ids: dict = {}  # sync fills from held positions; broker reads
            self.snaptrade_sync = SnapTradeSync(
                self._snaptrade_client, self.sf, self.positions, self.journal,
                self.settings, self.bus, self.ensure_symbol, symbol_ids=symbol_ids)
            await self.snaptrade_sync.load_links()
            self.snaptrade = SnapTradeBroker(
                self._snaptrade_client, self.sf, self.journal, self.settings,
                self.snaptrade_sync.account_for, symbol_ids=symbol_ids)
            await self.journal.append(ev.BROKER_CONNECTED, {"broker": "snaptrade"})

        if self.feed is None:
            use_yahoo = self.config.quote_source == "yahoo" or (
                self.config.quote_source == "auto" and snaptrade_configured)
            if use_yahoo:
                from .brokers.yahoo import YahooQuoteFeed
                self.feed = YahooQuoteFeed(
                    on_quote=self.quotes.on_quote,
                    poll_seconds=lambda: self.settings.get("quotes.yahoo_poll_seconds", 1.0))
            else:
                self.feed = SimQuoteFeed(
                    on_quote=self.quotes.on_quote,
                    tick_interval=self.config.sim_tick_interval,
                    seed=self.config.sim_seed)

        self.orders = OrderManager(
            self.sf, self.bus, self.journal, self.risk, self.settings,
            self.positions, self.quotes, self.executor_for, self.ensure_symbol)
        self.sim_executor.on_report = self.orders.on_report
        if self.ibkr is not None:
            self.ibkr.on_report = self.orders.on_report
        if self.snaptrade is not None:
            self.snaptrade.on_report = self.orders.on_report
            await self.snaptrade.start()

        for symbol in await self._startup_symbols():
            await self.ensure_symbol(symbol)
        from .brokers.yahoo import YahooQuoteFeed
        if isinstance(self.feed, YahooQuoteFeed):
            for pair in self.positions.fx.watch_symbols:  # live FX for CAD/USD math
                await self.feed.watch(pair)
        await self.feed.start()

        self._bar_persister = BarPersister(self.bus, self.sf)
        self._tasks = [
            asyncio.create_task(self._quote_consumer(), name="quote-consumer"),
            asyncio.create_task(self._bar_persister.run(), name="bar-persister"),
            asyncio.create_task(self._equity_snapshotter(), name="equity-snapshots"),
            asyncio.create_task(self._daily_loss_monitor(), name="daily-loss-monitor"),
        ]
        if self.snaptrade_sync is not None:
            self._tasks.append(
                asyncio.create_task(self.snaptrade_sync.run(), name="snaptrade-sync"))
        self.started = True
        log.info("engine started (feed=%s)", type(self.feed).__name__)

    async def stop(self) -> None:
        self.started = False
        if self.proposals is not None:
            await self.proposals.stop()
        if self.telegram is not None:
            await self.telegram.stop()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self._tasks = []
        if self._bar_persister:
            await self._bar_persister.flush()
        if self.feed:
            await self.feed.stop()
        if self.ibkr:
            await self.ibkr.stop()
        if self.snaptrade is not None:
            await self.snaptrade.stop()
        if getattr(self, "_snaptrade_client", None) is not None:
            await self._snaptrade_client.aclose()
        await self.db.dispose()

    # ------------------------------------------------------------- seeding
    async def _seed(self) -> None:
        async with self.sf() as session:
            count = (await session.execute(select(func.count(Portfolio.id)))).scalar_one()
            if count == 0:
                sim = Portfolio(id=new_id(), name="Practice", kind="sim",
                                starting_cash=10_000.0, cash=10_000.0, is_default=True)
                live = Portfolio(id=new_id(), name="Live (IBKR)", kind="live",
                                 starting_cash=0.0, cash=0.0)
                session.add_all([sim, live])
                await session.commit()
                await self.settings.set("trading.default_portfolio", sim.id, journal=False)
            else:
                # v0.3 rename: the sandbox is "Practice", not "Simulation"
                for row in (await session.execute(
                        select(Portfolio).where(Portfolio.kind == "sim",
                                                Portfolio.name == "Simulation"))).scalars():
                    row.name = "Practice"
                await session.commit()
            wl_count = (await session.execute(select(func.count(Watchlist.id)))).scalar_one()
            if wl_count == 0:
                session.add(Watchlist(id=new_id(), name="Main", sort=0, symbols=DEFAULT_WATCHLIST))
                await session.commit()

    async def _startup_symbols(self) -> list[str]:
        symbols: list[str] = []
        async with self.sf() as session:
            for wl in (await session.execute(select(Watchlist))).scalars():
                symbols.extend(wl.symbols or [])
        for pos in self.positions.positions_list():
            symbols.append(pos["symbol"])
        default_sym = str(self.settings.get("ui.default_symbol", "AAPL"))
        symbols.append(default_sym)
        seen, out = set(), []
        for s in symbols:
            s = s.upper()
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    # ------------------------------------------------------------- symbols
    async def ensure_symbol(self, symbol: str) -> None:
        """Make sure quotes flow and chart history exists for a symbol."""
        symbol = symbol.upper()
        from .brokers.sim import SimQuoteFeed
        from .brokers.yahoo import YahooQuoteFeed
        already = symbol in self._history_seeded or (
            isinstance(self.feed, SimQuoteFeed) and symbol in self.feed.symbols)
        await self.feed.watch(symbol)
        if already:
            return
        self._history_seeded.add(symbol)
        existing = await load_bars(self.sf, symbol, "1m", limit=3000)
        if not existing and isinstance(self.feed, SimQuoteFeed):
            history = self.feed.synthesize_history(symbol, minutes=self.config.sim_history_minutes)
            await persist_bars(self.sf, history)
            existing = history[-3000:]
        if isinstance(self.feed, YahooQuoteFeed):
            # real exchange bars for today beat our ticks-since-boot aggregation;
            # on overlapping minutes Yahoo's bar wins
            day = await self.feed.fetch_day_bars(symbol)
            if day:
                await persist_bars(self.sf, day)
                merged = {b.ts: b for b in existing}
                merged.update({b.ts: b for b in day})
                existing = [merged[k] for k in sorted(merged)][-3000:]
        self.bars.seed(symbol, existing)

    # ------------------------------------------------------------- routing
    def executor_for(self, portfolio: dict | None):
        kind = (portfolio or {}).get("kind", "sim")
        if kind in ("sim", "shadow"):
            return self.sim_executor
        if kind in ("paper", "live"):
            if (portfolio or {}).get("venue") == "snaptrade":
                return self.snaptrade
            return self.ibkr
        return None

    # ------------------------------------------------------------- kill switch
    async def engage_halt(self, reason: str, *, source: str = "app") -> dict:
        self.halt.engage(reason)
        await self.settings.set("system.halt", self.halt.to_dict(), journal=False)
        await self.journal.append(ev.KILL_SWITCH_ENGAGED, {"reason": reason, "source": source})
        state = {"kind": "halt", **self.halt.to_dict()}
        self.bus.publish(topics.SYSTEM, state)
        return self.halt.to_dict()

    async def release_halt(self, *, source: str = "app") -> dict:
        self.halt.release()
        await self.settings.set("system.halt", self.halt.to_dict(), journal=False)
        await self.journal.append(ev.KILL_SWITCH_RELEASED, {"source": source})
        self.bus.publish(topics.SYSTEM, {"kind": "halt", **self.halt.to_dict()})
        return self.halt.to_dict()

    # ------------------------------------------------------------- tasks
    async def _quote_consumer(self) -> None:
        async with self.bus.subscription(topics.QUOTES) as q:
            while True:
                quote = await q.get()
                if "=X" not in quote.symbol:  # FX pairs feed conversions, not charts
                    self.bars.on_quote(quote)
                if self.sim_executor is not None:
                    await self.sim_executor.on_quote(quote)

    async def _equity_snapshotter(self) -> None:
        while True:
            await asyncio.sleep(30)
            try:
                await self.positions.snapshot_equity()
            except Exception:  # pragma: no cover
                log.exception("equity snapshot failed")

    async def _daily_loss_monitor(self) -> None:
        while True:
            await asyncio.sleep(10)
            try:
                await self.check_daily_loss()
            except Exception:  # pragma: no cover
                log.exception("daily loss monitor failed")

    async def _traded_today(self) -> set[str]:
        """Portfolio ids with zargar-originated orders placed today (ET)."""
        start_et = dt.datetime.now(tz=ET).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.sf() as session:
            rows = (await session.execute(
                select(Order.portfolio_id).distinct().where(
                    Order.created_at >= start_et.astimezone(dt.timezone.utc),
                    Order.status != OrderStatus.DRY_RUN.value,
                ))).scalars().all()
        return set(rows)

    async def check_daily_loss(self) -> None:
        """One monitoring pass.

        The kill switch is for losses *zargar's trading* produced — only
        portfolios with orders placed today can auto-halt. Passive market
        drift on real accounts raises a once-a-day warning instead.
        """
        halt_pct = float(self.settings.get("risk.daily_loss_halt_pct", 3.0))
        traded = await self._traded_today()
        today = dt.datetime.now(tz=ET).date().isoformat()
        for p in self.positions.portfolios():
            if p["kind"] == "shadow":
                continue
            loss = await self.positions.daily_loss_pct(p["id"])
            if loss is None or loss > -abs(halt_pct):
                continue
            if p["id"] in traded:
                if self.halt.engaged:
                    continue
                reason = (f"daily loss limit: {p['name']} at {loss:.2f}% "
                          f"(halt at -{halt_pct:.1f}%)")
                await self.journal.append(
                    ev.DAILY_LOSS_HALT, {"portfolioId": p["id"], "lossPct": loss})
                await self.engage_halt(reason, source="auto")
            else:
                key = (p["id"], today)
                if key in self._drift_warned:
                    continue
                self._drift_warned.add(key)
                await self.journal.append(
                    ev.DAILY_DRIFT_WARNING,
                    {"portfolioId": p["id"], "name": p["name"], "lossPct": round(loss, 2),
                     "note": "market drift — no zargar trades today; trading not halted"},
                    portfolio_id=p["id"])
                self.bus.publish(topics.SYSTEM, {
                    "kind": "drift", "portfolioId": p["id"], "name": p["name"],
                    "lossPct": round(loss, 2), "ts": dt.datetime.now(
                        dt.timezone.utc).isoformat()})

    # ------------------------------------------------------------- snapshot
    async def snapshot(self) -> dict:
        portfolios = []
        for p in self.positions.portfolios():
            eq = await self.positions.equity(p["id"])
            today = await self.positions.daily_loss_pct(p["id"])
            portfolios.append({**p, "equity": round(eq, 2), "cash": round(p["cash"], 2),
                               "todayPct": round(today, 2) if today is not None else None})
        open_orders = await self.orders.list_orders(open_only=True) if self.orders else []
        async with self.sf() as session:
            watchlists = [
                {"id": w.id, "name": w.name, "sort": w.sort, "symbols": w.symbols or []}
                for w in (await session.execute(
                    select(Watchlist).order_by(Watchlist.sort))).scalars()
            ]
        pending = []
        if self.proposals is not None:
            pending = await self.proposals.list_pending()
        feed_name = type(self.feed).__name__ if self.feed else None
        quote_source = {"SimQuoteFeed": "sim", "YahooQuoteFeed": "yahoo",
                        "IBKRBroker": "ibkr"}.get(feed_name or "", "sim")
        return {
            "settings": self.settings.all(),
            "portfolios": portfolios,
            "positions": self.positions.positions_list(),
            "openOrders": open_orders,
            "quotes": {s: q.to_dict() for s, q in self.quotes.all().items()},
            "halt": self.halt.to_dict(),
            "watchlists": watchlists,
            "proposals": pending,
            "brokerages": self.snaptrade_sync.payload() if self.snaptrade_sync else None,
            "broker": {
                "feed": feed_name,
                "feedConnected": bool(self.feed and self.feed.connected),
                "ibkrConnected": bool(self.ibkr and self.ibkr.connected),
                "snaptradeConnected": bool(self.snaptrade and self.snaptrade.connected),
                "quoteSource": quote_source,
                "mode": self.settings.get("trading.mode"),
            },
        }
