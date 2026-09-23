"""Event-loop stall watch (2026-09-16). The engine's loop stalled three times on 2026-09-16 (07:40 PT ~4 s,
08:56 PT ~10 s, 17:42-17:45 PT ~180 s) and the single-probe watchdog killed a LIVE engine on the first one. The
existing `_event_loop_monitor` measures lag from inside the loop, so it cannot see WHAT blocked it - a stalled loop
runs nothing. This watch is a daemon THREAD: the loop stamps a heartbeat every `beat_s`; when the heartbeat is older
than `threshold_s` the thread captures the main thread's current stack (`sys._current_frames`) - the blocking call
site - and logs it; when the beat resumes it logs the stall length. Diagnostic only: it never cancels, kills or
restarts anything, and the record it keeps is exposed on `/api/health` (`local.delivery.loopStalls`, `lastStall`) so
a probe can tell "alive but stalled" from "dead".
"""
from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
import traceback

log = logging.getLogger("zargar.loopwatch")


class LoopStallWatch:
    def __init__(self, *, threshold_s: float = 2.0, beat_s: float = 0.25, keep: int = 20, logger=log) -> None:
        self.threshold_s = float(threshold_s)
        self.beat_s = float(beat_s)
        self.keep = int(keep)
        self.log = logger
        self._beat = time.monotonic()
        self._loop_thread_ident: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._task: asyncio.Task | None = None
        self._in_stall: dict | None = None
        self.stalls: list[dict] = []          # newest last, bounded
        self.count = 0

    # ---------------------------------------------------------------- loop side
    async def _heartbeat(self) -> None:
        self._loop_thread_ident = threading.get_ident()
        try:
            while not self._stop.is_set():
                self._beat = time.monotonic()
                await asyncio.sleep(self.beat_s)
        except asyncio.CancelledError:
            raise

    def start(self) -> None:
        """Call from inside the running loop. Idempotent."""
        if self._task is not None:
            return
        self._task = asyncio.get_running_loop().create_task(self._heartbeat(), name="loop-stall-heartbeat")
        self._thread = threading.Thread(target=self._watch, name="loop-stall-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            self._task = None

    # ---------------------------------------------------------------- thread side
    def _stack(self) -> str:
        ident = self._loop_thread_ident
        if ident is None:
            return "(loop thread unknown)"
        frame = sys._current_frames().get(ident)
        if frame is None:
            return "(no frame)"
        return "".join(traceback.format_stack(frame)[-12:])

    def _watch(self) -> None:
        poll = max(0.05, min(self.beat_s, self.threshold_s / 4))
        while not self._stop.is_set():
            time.sleep(poll)
            age = time.monotonic() - self._beat
            if self._in_stall is None and age >= self.threshold_s:
                stack = self._stack()
                self._in_stall = {"startedAt": time.time() - age, "detectedAfterS": round(age, 2), "stack": stack}
                self.log.warning("event loop STALLED for %.1fs and counting - main thread is at:\n%s", age, stack)
            elif self._in_stall is not None and age < self.threshold_s:
                rec = self._in_stall; self._in_stall = None
                rec["seconds"] = round(time.time() - rec["startedAt"], 2)
                rec["endedAt"] = time.time()
                self.count += 1
                self.stalls.append(rec)
                del self.stalls[:-self.keep]
                self.log.warning("event loop resumed after a %.1fs stall (#%d)", rec["seconds"], self.count)

    # ---------------------------------------------------------------- read side
    def snapshot(self) -> dict:
        cur = self._in_stall
        last = self.stalls[-1] if self.stalls else None
        return {"loopStalls": self.count,
                "stalledNowS": (round(time.monotonic() - self._beat, 1) if cur is not None else None),
                "lastStall": ({"seconds": last["seconds"], "endedAt": last["endedAt"],
                               "top": last["stack"].strip().splitlines()[-2:]} if last else None)}
