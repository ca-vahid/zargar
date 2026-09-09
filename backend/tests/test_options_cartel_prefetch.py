import asyncio
import time
from itertools import pairwise

import pytest

from zargar.marketstructure.history import HistoryError
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.preparation_io import PreparationHistory


async def report(**kwargs):
    pass


def reader(**kwargs):
    return PreparationHistory(None, None, report, PreparationPolicy(**kwargs), lambda: 1000)


async def test_prefetch_overlaps_fetches_but_yields_in_discovery_order():
    history = reader(history_concurrency=3, history_batch_size=4)
    released = asyncio.Event()
    full = asyncio.Event()
    active = peak = 0
    finished = []
    async def daily(symbol, at, client):
        nonlocal active, peak
        active += 1; peak = max(peak, active)
        if active == 3:
            full.set()
        try:
            await released.wait()
            if symbol == '0':
                await asyncio.sleep(.02)
            finished.append(symbol)
            return symbol
        finally:
            active -= 1
    history.daily = daily
    async def consume():
        async with history.prefetch([{'symbol': str(i)} for i in range(8)], 1000, None, skip=lambda _: False) as rows:
            return [value async for _, value in rows]
    task = asyncio.create_task(consume())
    await asyncio.wait_for(full.wait(), 1)
    assert peak == active == 3
    released.set()
    assert await task == [str(i) for i in range(8)]
    assert finished.index('1') < finished.index('0')
    assert peak == 3 and active == 0


async def test_window_is_bounded_and_early_exit_cancels_all_owned_tasks():
    history = reader(history_concurrency=3, history_batch_size=4)
    started = set(); cancelled = set()
    async def daily(symbol, *args):
        started.add(symbol)
        if symbol == '0':
            return symbol
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.add(symbol)
    history.daily = daily
    async with history.prefetch([{'symbol':str(i)} for i in range(100)], 1000, None, skip=lambda _: False) as rows:
        async for _, value in rows:
            assert value == '0'
            await asyncio.sleep(0)
            break
    assert started <= {'0','1','2','3'}
    assert cancelled == started-{'0'}


async def test_cancelled_coordinator_awaits_workers_and_skips_do_not_fetch():
    history = reader(history_concurrency=2, history_batch_size=3)
    started = asyncio.Event(); stopped = asyncio.Event()
    async def daily(symbol, *args):
        assert symbol != 'skip'
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    history.daily = daily
    async def consume():
        async with history.prefetch([{'symbol':'skip'},{'symbol':'work'}], 1000, None, skip=lambda r:r['symbol']=='skip') as rows:
            async for _ in rows:
                pass
    task = asyncio.create_task(consume())
    await started.wait(); task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()


async def test_parallel_requests_share_pacing_and_stop_after_rate_limit():
    history = reader(request_interval_seconds=.02)
    starts = []
    async def fetch(symbol, *args, **kwargs):
        starts.append(time.monotonic())
        await asyncio.sleep(.05)
        return []
    history.fetch = fetch
    await asyncio.gather(*(history.window(str(i), '1d', 0, 1, None) for i in range(4)))
    assert all(b-a >= .018 for a,b in pairwise(starts))
    assert history.requests == 4 and history.active_requests == 0
    async def limited(*args, **kwargs):
        raise HistoryError('HTTP 429 rate limited')
    history.fetch = limited
    with pytest.raises(HistoryError):
        await history.window('bad','1d',0,1,None)
    requested = history.requests
    with pytest.raises(HistoryError):
        await history.window('later','1d',0,1,None)
    assert history.requests == requested and history.active_requests == 0
