"""WebSocket hub: snapshot + delta protocol.

On connect the client receives {"t":"snapshot", ...full state...}, then deltas:
quote (conflated to ~10 Hz), order, execution, position, portfolio, proposal,
signal, system, event, bar. Client messages: {"t":"watch","symbol":...},
{"t":"ping"}.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

from .. import bus as topics
from ..engine import Engine

log = logging.getLogger("zargar.ws")

TOPIC_TO_TYPE = {
    topics.ORDERS: "order",
    topics.EXECUTIONS: "execution",
    topics.POSITIONS: "position",
    topics.PORTFOLIO: "portfolio",
    topics.PROPOSALS: "proposal",
    topics.SIGNALS: "signal",
    topics.SYSTEM: "system",
    topics.EVENTS: "event",
    topics.TECHNIQUE: "technique",
    topics.CHAT: "chat",
    topics.TIP_ANALYST: "tipAnalyst",
}


class WSHub:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._clients: set[WebSocket] = set()
        self._pending_quotes: dict[str, dict] = {}
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._topic_fanout(topic, mtype), name=f"ws-fanout-{mtype}")
            for topic, mtype in TOPIC_TO_TYPE.items()
        ] + [
            asyncio.create_task(self._quote_collector(), name="ws-quote-collector"),
            asyncio.create_task(self._quote_flusher(), name="ws-quote-flusher"),
            asyncio.create_task(self._bar_fanout(), name="ws-bar-fanout"),
        ]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self._tasks = []

    async def handle(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        try:
            snapshot = await self.engine.snapshot()
            try:
                await ws.send_text(json.dumps({"t": "snapshot", "d": snapshot}))
            except RuntimeError:
                return   # client closed while the snapshot was in flight (phone reconnect race)
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                t = msg.get("t")
                if t == "ping":
                    await ws.send_text('{"t":"pong"}')
                elif t == "watch" and msg.get("symbol"):
                    await self.engine.ensure_symbol(str(msg["symbol"]))
        except WebSocketDisconnect:
            pass
        except Exception:  # pragma: no cover
            log.exception("ws handler error")
        finally:
            self._clients.discard(ws)

    async def _broadcast(self, payload: dict) -> None:
        if not self._clients:
            return
        text = json.dumps(payload)
        dead = []
        for ws in self._clients:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def _topic_fanout(self, topic: str, mtype: str) -> None:
        async with self.engine.bus.subscription(topic) as q:
            while True:
                msg = await q.get()
                await self._broadcast({"t": mtype, "d": msg})

    async def _quote_collector(self) -> None:
        async with self.engine.bus.subscription(topics.QUOTES) as q:
            while True:
                quote = await q.get()
                self._pending_quotes[quote.symbol] = quote.to_dict()

    async def _quote_flusher(self) -> None:
        # conflate quotes to ~10 Hz for the UI
        while True:
            await asyncio.sleep(0.1)
            if self._pending_quotes and self._clients:
                batch, self._pending_quotes = self._pending_quotes, {}
                await self._broadcast({"t": "quotes", "d": list(batch.values())})
            elif self._pending_quotes:
                self._pending_quotes.clear()

    async def _bar_fanout(self) -> None:
        async with self.engine.bus.subscription(topics.BARS) as q:
            while True:
                msg = await q.get()
                bar = msg["bar"]
                await self._broadcast({
                    "t": "bar",
                    "d": {"symbol": msg["symbol"], "tf": msg["tf"], "bar": bar.to_row()},
                })
