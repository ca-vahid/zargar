"""SessionListener — the shared live loop for any technique that watches
1-minute bars and manages orders.

It subscribes once to BARS (1-minute closed bars) and ORDERS (every order state
change), plus a 60-second heartbeat, and dispatches to three hooks the subclass
fills in. It owns the order-id → owner index so an order update always finds the
trade that raised it — and rebuilding that index on restart is a one-liner
(`register_order`). Cancel/stop plumbing and the task lifecycle live here so a
new technique inherits the safe parts instead of copying them.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from .. import bus as topics

log = logging.getLogger("zargar.execution.listener")


class SessionListener:
    def __init__(self, engine, *, name: str = "session") -> None:
        self.engine = engine
        self._name = name
        self._bar_task: asyncio.Task | None = None
        self._orders_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._quote_watch_task: asyncio.Task | None = None
        # order id -> whatever token the subclass needs to find its trade
        self._order_index: dict[str, Any] = {}

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        if self._bar_task is None:
            self._bar_task = asyncio.create_task(self._bar_loop(), name=f"{self._name}-bars")
        if self._orders_task is None:
            self._orders_task = asyncio.create_task(self._orders_loop(), name=f"{self._name}-orders")
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name=f"{self._name}-heartbeat")
        if self._quote_watch_task is None:
            self._quote_watch_task = asyncio.create_task(self._quote_watch_loop(), name=f"{self._name}-quote-watch")

    async def stop(self) -> None:
        for attr in ("_bar_task", "_orders_task", "_heartbeat_task", "_quote_watch_task"):
            t = getattr(self, attr)
            if t is not None:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
                setattr(self, attr, None)

    # -- order index (rebuilt on restart) ------------------------------------
    def register_order(self, order_id: str, owner: Any) -> None:
        if order_id:
            self._order_index[order_id] = owner

    def owner_of(self, order_id: str) -> Any:
        return self._order_index.get(order_id)

    def forget_order(self, order_id: str) -> None:
        self._order_index.pop(order_id, None)

    # -- hooks (subclass fills these) ----------------------------------------
    async def on_minute_bar(self, symbol: str, bar) -> None:  # pragma: no cover - overridden
        ...

    async def on_order(self, order: dict) -> None:            # pragma: no cover - overridden
        ...

    async def on_heartbeat(self) -> None:                     # pragma: no cover - overridden
        ...

    async def on_quote_watch(self) -> None:                   # pragma: no cover - overridden
        """Fast intra-minute check (safety only — earlier exits, never entries).
        Runs every `quote_watch_seconds()`; return without doing anything when
        the subclass has nothing open."""
        ...

    def quote_watch_seconds(self) -> float:
        """Cadence of on_quote_watch; the live quote feed itself polls ~3 s, so
        going much faster only re-reads the same quote."""
        return 2.0

    def heartbeat_seconds(self) -> float:
        return 60.0

    def heartbeat_warmup_seconds(self) -> float:
        return 20.0

    # -- loops ---------------------------------------------------------------
    async def _bar_loop(self) -> None:
        async with self.engine.bus.subscription(topics.BARS) as q:
            while True:
                msg = await q.get()
                try:
                    if msg.get("tf") != "1m":
                        continue
                    await self.on_minute_bar(msg.get("symbol"), msg.get("bar"))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("%s bar handling failed", self._name)

    async def _orders_loop(self) -> None:
        async with self.engine.bus.subscription(topics.ORDERS) as q:
            while True:
                msg = await q.get()
                try:
                    if msg.get("id") in self._order_index:
                        await self.on_order(msg)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("%s order handling failed", self._name)

    async def _quote_watch_loop(self) -> None:
        await asyncio.sleep(1.0)
        while True:
            try:
                await self.on_quote_watch()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("%s quote watch failed", self._name)
            await asyncio.sleep(max(0.05, float(self.quote_watch_seconds())))

    async def _heartbeat_loop(self) -> None:
        await asyncio.sleep(self.heartbeat_warmup_seconds())
        while True:
            try:
                await self.on_heartbeat()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("%s heartbeat failed", self._name)
            await asyncio.sleep(self.heartbeat_seconds())
