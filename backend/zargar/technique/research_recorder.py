"""EM research plumbing shared by the first-sale record, the ED-04 book capture and the source candidates (IR-02 / IR-04).

`BoundedRecorder`  research persistence that can NEVER hold a trading path: `put()` is synchronous (`put_nowait`), the
                   queue is bounded, a full queue drops VISIBLY (counted), writes are retried a fixed number of times
                   with the record's original content and then dropped visibly. Nothing awaits it.
`quote_evidence`   the quote cache's row as plain evidence WITHOUT inventing anything: an absent source stays absent, the
                   venue time of a field is that field's own venue time (never the receipt time), and the symbol rides
                   along so a consumer can verify identity.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

log = logging.getLogger(__name__)


class BoundedRecorder:
    def __init__(self, write: Callable[[dict], Awaitable[None]], *, name: str, maxsize: int = 256, retries: int = 3,
                 retry_sleep_s: float = 0.5, write_timeout_s: float = 10.0):
        self._write, self._name = write, name
        self._maxsize, self._retries, self._sleep, self._timeout = int(maxsize), int(retries), float(retry_sleep_s), float(write_timeout_s)
        self._queue: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None
        self.stats = {"queued": 0, "written": 0, "droppedQueueFull": 0, "droppedWriteFailed": 0, "retries": 0}

    def put(self, rec: dict) -> bool:
        """Synchronous, never raises, never awaits. False = dropped (counted)."""
        try:
            if self._queue is None:
                self._queue = asyncio.Queue(maxsize=self._maxsize)
            self._queue.put_nowait(rec)
        except asyncio.QueueFull:
            self.stats["droppedQueueFull"] += 1
            log.warning("%s: research record dropped - recorder saturated (%d dropped so far)", self._name, self.stats["droppedQueueFull"])
            return False
        except Exception:                                  # noqa: BLE001 - e.g. no running loop in a sync test rig
            self.stats["droppedQueueFull"] += 1
            return False
        self.stats["queued"] += 1
        try:
            if self._task is None or self._task.done():
                self._task = asyncio.get_running_loop().create_task(self._drain(), name=f"{self._name}-recorder")
        except RuntimeError:
            pass
        return True

    async def _drain(self) -> None:
        q = self._queue
        while True:
            rec = await q.get()
            try:
                for attempt in range(self._retries):
                    try:
                        await asyncio.wait_for(self._write(rec), timeout=self._timeout)
                        self.stats["written"] += 1
                        break
                    except Exception as exc:               # noqa: BLE001 - research write: retried, then counted
                        if attempt == self._retries - 1:
                            self.stats["droppedWriteFailed"] += 1
                            log.warning("%s: research record not written after %d attempts (%s)", self._name, self._retries, type(exc).__name__)
                        else:
                            self.stats["retries"] += 1
                            await asyncio.sleep(self._sleep)
            finally:
                q.task_done()

    async def wait_idle(self) -> None:
        if self._queue is not None:
            await self._queue.join()


def feed_identity(engine) -> str | None:
    """The engine-level identity of the equity quote feed (`feed:<Class>`), or None when there is no feed object. A FACT
    about the process, labelled as such - not a per-quote venue attribution."""
    feed = getattr(engine, "feed", None)
    return f"feed:{type(feed).__name__}" if feed is not None else None


def quote_evidence(q, *, symbol: str, is_option: bool, feed: str | None) -> dict | None:
    """Plain evidence from a `Quote`. Source: the quote's own `source` when it has one; for an EQUITY quote with an empty
    source (= "the feed itself" by the Quote contract) the engine feed identity is used ONLY when the quote carries a real
    venue quote time - otherwise the source stays None (unknown). Times: `quoteTs` = venue time of the bid/ask (options:
    the NBBO `source_ts`; equities: `quote_ts`), `lastTs` = venue time of the print. The receipt time is kept apart."""
    if q is None:
        return None
    src = str(getattr(q, "source", "") or "").strip()
    quote_ts = int((getattr(q, "source_ts", 0) if is_option else getattr(q, "quote_ts", 0)) or 0)
    if not src and not is_option and feed and quote_ts > 0:
        src, basis = feed, "engine_feed"
    else:
        basis = "quote" if src else None
    return {"symbol": str(getattr(q, "symbol", "") or symbol), "bid": float(getattr(q, "bid", 0) or 0), "ask": float(getattr(q, "ask", 0) or 0),
            "last": float(getattr(q, "last", 0) or 0), "bidSize": (int(getattr(q, "bid_size", 0) or 0) or None),
            "askSize": (int(getattr(q, "ask_size", 0) or 0) or None), "sizeUnit": ("contracts" if is_option else "shares"),
            "source": (src or None), "sourceBasis": basis, "rawSource": (getattr(q, "raw_source", "") or None),
            "transform": (getattr(q, "transform", "") or None), "delayed": bool(getattr(q, "delayed", False)),
            "quoteTs": quote_ts, "lastTs": int(getattr(q, "last_ts", 0) or 0), "sourceTs": quote_ts,
            "receivedTs": int(getattr(q, "ts", 0) or 0), "session": (getattr(q, "session", "") or None), "halted": bool(getattr(q, "halted", False))}
