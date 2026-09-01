"""The test-pinnable clock (POST-SOAK 5.1).

Production: real time, always. Tests set ZARGAR_TEST_NOW (ISO-8601 with offset,
or epoch milliseconds) to pin the moment PLAN-BUILDING decisions are made —
which session a tip plan targets, and therefore whether the armer's seed replay
finds any real bars to consume. The tip_runner test rig pins a past pre-open
moment so the flaky trio (gap judgement on the synthetic opening bar) behaves
identically at any wall-clock hour; live code paths that must use real time
(scheduler, heartbeats, journals) deliberately do NOT read this.
"""
from __future__ import annotations

import datetime as dt
import os


def now_ms() -> int:
    v = os.environ.get("ZARGAR_TEST_NOW")
    if v:
        try:
            return int(v)
        except ValueError:
            return int(dt.datetime.fromisoformat(v).timestamp() * 1000)
    return int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
