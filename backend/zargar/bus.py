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
        # subscriber drops (KFIN-03, 2026-09-14): counted per topic and per live queue so a
        # consumer can report how many of ITS messages were shed; bounded by the subscriptions
        self._topic_drops: dict[str, int] = defaultdict(int)
        self._queue_drops: dict[asyncio.Queue, int] = {}

    def publish(self, topic: str, message: Any) -> None:
        for q in list(self._topics.get(topic, ())):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()  # drop oldest
                self._topic_drops[topic] += 1
                if q in self._queue_drops:
                    self._queue_drops[q] += 1
                with contextlib.suppress(asyncio.QueueFull):
                    q.put_nowait(message)

    def drops(self, q: asyncio.Queue | None = None) -> int:
        """Messages shed from one subscriber's queue (or from every queue when `q` is None)."""
        if q is not None:
            return self._queue_drops.get(q, 0)
        return sum(self._topic_drops.values())

    def drop_counts(self) -> dict[str, int]:
        return {**{t: n for t, n in self._topic_drops.items() if n}, "total": self.drops()}

    def subscribe(self, *topics: str) -> tuple[asyncio.Queue, "callable"]:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        for t in topics:
            self._topics[t].add(q)
        self._queue_drops[q] = 0

        def unsubscribe() -> None:
            for t in topics:
                self._topics[t].discard(q)
            self._queue_drops.pop(q, None)

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
TIP_ANALYST = "tip_analyst"   # tips analyst run steps (live play-by-play)
