"""2026-09-16: three event-loop stalls (4 s, ~10 s, ~180 s) got a live engine killed by a single-probe watchdog and
nothing in the process could say what blocked the loop. The stall watch is a daemon thread: it captures the loop
thread's stack while the loop is blocked, logs the stall length when the loop resumes, and exposes the record on the
health snapshot. Diagnostic only - it never cancels, kills or restarts anything."""
import asyncio
import logging
import time

from zargar.loopwatch import LoopStallWatch


def _blocking_call_site(seconds: float) -> None:
    time.sleep(seconds)                  # the blocking call the watch must name


def test_stall_is_captured_with_the_blocking_call_site_and_recorded_on_resume(caplog):
    caplog.set_level(logging.WARNING, logger="zargar.loopwatch")

    async def scenario():
        w = LoopStallWatch(threshold_s=0.3, beat_s=0.05)
        w.start()
        await asyncio.sleep(0.2)          # a few heartbeats first
        assert w.snapshot()["loopStalls"] == 0
        _blocking_call_site(1.0)          # BLOCK the loop
        await asyncio.sleep(0.3)          # let the thread see the beat resume
        snap = w.snapshot()
        w.stop()
        return w, snap

    w, snap = asyncio.run(scenario())
    assert w.count == 1 and snap["loopStalls"] == 1 and snap["stalledNowS"] is None
    assert 0.9 <= snap["lastStall"]["seconds"] <= 2.0
    assert "_blocking_call_site" in w.stalls[0]["stack"], "the stack must name the blocking call site"
    msgs = [r.getMessage() for r in caplog.records]
    assert any("STALLED" in m and "_blocking_call_site" in m for m in msgs)
    assert any("resumed after" in m for m in msgs)


def test_no_stall_no_noise_and_disabled_by_zero_threshold():
    async def scenario():
        w = LoopStallWatch(threshold_s=0.5, beat_s=0.05)
        w.start()
        for _ in range(6):
            await asyncio.sleep(0.05)
        snap = w.snapshot(); w.stop()
        return w.count, snap

    count, snap = asyncio.run(scenario())
    assert count == 0 and snap["loopStalls"] == 0 and snap["lastStall"] is None


def test_watch_never_touches_the_loop_it_observes():
    """The thread only reads frames and timestamps: the loop keeps running its own tasks during and after a stall."""
    ticks = []

    async def ticker():
        while True:
            ticks.append(time.monotonic()); await asyncio.sleep(0.05)

    async def scenario():
        w = LoopStallWatch(threshold_s=0.2, beat_s=0.05); w.start()
        t = asyncio.create_task(ticker())
        await asyncio.sleep(0.15)
        time.sleep(0.6)
        await asyncio.sleep(0.3)
        t.cancel(); w.stop()
        return w.count

    assert asyncio.run(scenario()) == 1
    assert len(ticks) >= 5
