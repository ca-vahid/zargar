"""Cyclic-GC pauses (2026-11-09).

The engine's heap is mostly long-lived state (bars, plans, positions, caches) and grows to ~1.5 GB over a week.
CPython's full (gen-2) collection walks every tracked object, so each one stalled the event loop 2.4-2.7 s in the
session (loopwatch top frame `_weakrefset._remove`, 11:02 and 11:35 ET on 11-09) - the app's 2 s quote stop watch
can act up to that much late (venue GTC stops are unaffected).

`compact()` runs a full collection and then FREEZES every survivor into the permanent generation, so collections
during the session only walk objects created since. It runs once after startup and nightly off-hours; each run
UNFREEZES first, so cycles that died since the last freeze are still collected (nothing leaks for longer than a day).
Refcount-freed objects are unaffected by freezing. Rollback: `ops.gc_freeze` false.
"""
from __future__ import annotations

import gc
import logging
import time

log = logging.getLogger(__name__)


def compact() -> dict:
    """Full collection off the hot path, then freeze the survivors."""
    t0 = time.perf_counter()
    gc.unfreeze()
    collected = gc.collect()
    gc.freeze()
    out = {"collected": collected, "frozen": gc.get_freeze_count(),
           "seconds": round(time.perf_counter() - t0, 3)}
    log.info("gc compact: %s", out)
    return out


def attach(engine) -> None:
    """Compact now (after startup) and nightly at `ops.gc_compact_at` ET, every day."""
    s = engine.settings
    if not bool(s.get("ops.gc_freeze", True)):
        return
    compact()

    async def _nightly() -> dict:
        if not bool(engine.settings.get("ops.gc_freeze", True)):
            return {"skipped": "ops.gc_freeze off"}
        return compact()

    engine.scheduler.register("gc_compact", str(s.get("ops.gc_compact_at", "20:00")), _nightly,
                              weekdays_only=False)
