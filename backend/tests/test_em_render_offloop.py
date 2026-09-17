"""2026-09-16: chart rendering ran synchronously on the event loop at every vision pass (service.py) and the legacy
fire critic (arming.py); under review load the loop went silent for seconds to minutes and the watchdog killed a
live engine. `render_chart_async` produces the same PNG off the loop on ONE worker thread (matplotlib is not
thread-safe), and the loop keeps serving while a render runs."""
import asyncio
import time

from zargar.domain import Bar
from zargar.technique.render import render_chart, render_chart_async

DAY = 1_789_479_000_000


def _bars(n=240):
    return [Bar(symbol="X", tf="1m", ts=DAY + i * 60_000, open=100 + i * 0.01, high=100.3 + i * 0.01, low=99.7 + i * 0.01,
                close=100.1 + i * 0.01, volume=1000 + i) for i in range(n)]


def test_async_render_returns_the_same_png_and_keeps_the_loop_serving():
    bars = _bars()
    sync_png = render_chart(bars, title="X 1m", tf="1m")
    ticks = []

    async def ticker():
        while True:
            ticks.append(time.monotonic()); await asyncio.sleep(0.02)

    async def scenario():
        t = asyncio.create_task(ticker())
        t0 = time.monotonic()
        png = await render_chart_async(bars, title="X 1m", tf="1m")
        elapsed = time.monotonic() - t0
        t.cancel()
        return png, elapsed

    png, elapsed = asyncio.run(scenario())
    assert png and len(png) > 1000 and png[:8] == sync_png[:8]           # a PNG, same header (bytes can differ by metadata timestamps)
    assert len(ticks) >= max(3, int(elapsed / 0.02) // 4), "the loop must keep running its own tasks while a chart renders off-loop"


def test_renders_are_serialised_on_one_worker():
    from zargar.technique import render as render_mod
    pool = render_mod._pool()
    assert pool._max_workers == 1
    bars = _bars(60)

    async def scenario():
        return await asyncio.gather(*(render_chart_async(bars, title=f"X {i}", tf="1m") for i in range(3)))

    pngs = asyncio.run(scenario())
    assert all(p and p[:8] == pngs[0][:8] for p in pngs)
