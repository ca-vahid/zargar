"""In-process async pub/sub bus.

Topics are plain strings. Subscribers get their own bounded queue; a slow
subscriber drops oldest messages rather than blocking publishers (the UI fan-out
must never stall the trading path).
"""
from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from typing import Any, AsyncIterator


class Bus:
    def __init__(self, maxsize: int = 2000) -> None:
        self._topics: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._maxsize = maxsize

    def publish(self, topic: str, message: Any) -> None:
        for q in list(self._topics.get(topic, ())):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()  # drop oldest
                with contextlib.suppress(asyncio.QueueFull):
                    q.put_nowait(message)

    def subscribe(self, *topics: str) -> tuple[asyncio.Queue, "callable"]:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        for t in topics:
            self._topics[t].add(q)

        def unsubscribe() -> None:
            for t in topics:
                self._topics[t].discard(q)

        return q, unsubscribe

    @contextlib.asynccontextmanager
    async def subscription(self, *topics: str) -> AsyncIterator[asyncio.Queue]:
        q, unsub = self.subscribe(*topics)
        try:
            yield q
        finally:
            unsub()


# Well-known topics
QUOTES = "quotes"          # Quote objects, unconflated (engine consumers)
EVENTS = "events"          # journaled event dicts (audit/UI)
ORDERS = "orders"          # order projection dicts after every change
EXECUTIONS = "executions"  # execution dicts
POSITIONS = "positions"    # position projection dicts
PORTFOLIO = "portfolio"    # equity / cash snapshots
PROPOSALS = "proposals"    # proposal lifecycle dicts
SIGNALS = "signals"        # extracted signal dicts
SYSTEM = "system"          # halt state, broker connectivity, notices
BARS = "bars"              # closed bars {symbol, tf, bar}
TECHNIQUE = "technique"
CHAT = "chat"
