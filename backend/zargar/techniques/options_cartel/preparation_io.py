"""Paced, observable history reads and bounded reuse of saved research bars."""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from sqlalchemy import BigInteger, cast, select

from ...marketstructure.history import HistoryError
from ...models import TechniqueRun
from .collect import normalize_daily
from .data import DailyBar, completed_daily
from .screen import _latest_session


async def observed_work(awaitable, report, *, message, timeout=180):
    """Keep a visible heartbeat during provider waits; cancellation owns the child."""
    task = asyncio.create_task(awaitable)
    started = time.monotonic()
    try:
        async with asyncio.timeout(timeout):
            while not task.done():
                done, _ = await asyncio.wait({task}, timeout=10)
                if not done:
                    await report(message=f'{message} · waiting {int(time.monotonic()-started)}s')
            return await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def rate_limited(error):
    return any(text in str(error).lower() for text in ('429', 'rate limit', 'too many requests'))


class PreparationHistory:
    def __init__(self, engine, fetch, report, policy, clock):
        self.engine, self.fetch, self.report, self.policy, self.clock = engine, fetch, report, policy, clock
        self.cache_hits = 0
        self.requests = 0
        self.last_request = 0.
        self.request_lock = asyncio.Lock()
        self.provider_error = None
        self.active_requests = 0
        self.prefetched = 0

    @asynccontextmanager
    async def prefetch(self, listings, at, client, *, skip):
        """Bounded sliding window; fetch concurrently, consume in discovery order.

        Every task is owned by this context and awaited on every exit. Failures
        reach the coordinator in order so successful prior analyses remain resumable.
        """
        concurrency = self.policy.history_concurrency
        window = self.policy.history_batch_size
        semaphore = asyncio.Semaphore(concurrency)
        tasks = {}

        async def load(listing):
            if skip(listing):
                return None
            async with semaphore:
                try:
                    if self.provider_error:
                        raise self.provider_error
                    value = await self.daily(listing['symbol'], at, client)
                    self.prefetched += 1
                    return value
                except Exception as exc:  # noqa: BLE001 - coordinator owns ordered failure handling
                    if rate_limited(exc):
                        self.provider_error = exc
                    return exc

        async def ordered():
            launched = 0
            for index, listing in enumerate(listings):
                while launched < min(len(listings), index+window):
                    tasks[launched] = asyncio.create_task(load(listings[launched]), name=f"cartel-history-{launched}")
                    launched += 1
                outcome = await tasks[index]
                del tasks[index]
                yield listing, outcome

        iterator = ordered()
        try:
            yield iterator
        finally:
            await iterator.aclose()
            for task in tasks.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)

    async def daily(self, symbol, at, client):
        await self.report(symbol=symbol, message=f'Checking saved {symbol} daily history')
        expected = _latest_session(at).isoformat()
        async with self.engine.sf() as session:
            cached = await session.scalar(select(TechniqueRun).where(
                TechniqueRun.technique == 'options_cartel', TechniqueRun.mode == 'analysis',
                TechniqueRun.symbol == symbol, TechniqueRun.status == 'done',
                TechniqueRun.result['collection']['historyCacheVersion'].as_integer() == 1,
                TechniqueRun.result['collection']['historyThrough'].as_string() == expected,
                cast(TechniqueRun.result['collection']['historyObservedAt'].as_string(), BigInteger) <= at,
                cast(TechniqueRun.result['collection']['historyObservedAt'].as_string(), BigInteger) >= at-12*3_600_000,
            ).order_by(TechniqueRun.created_at.desc()).limit(1))
        if cached:
            bars = completed_daily([DailyBar.model_validate(b) for b in cached.config['inputs']['history']], at)
            if bars and bars[-1].session.isoformat() == expected and all(b.symbol == symbol for b in bars):
                self.cache_hits += 1
                return bars, {**cached.result['collection'], 'historyReusedFrom': cached.id}
        bars = normalize_daily(await self.window(symbol, '1d', at-550*86_400_000, at, client), symbol, at)
        return bars, {'historyCacheVersion': 1, 'historyThrough': expected,
                      'historyObservedAt': self.clock(), 'historyReusedFrom': None,
                      'historySource': 'Shared historical provider; completed daily bars only'}

    async def window(self, symbol, timeframe, start, end, client):
        await self.report(symbol=symbol, message=f'Loading {symbol} {timeframe} history')
        async with self.request_lock:
            delay = max(0, self.policy.request_interval_seconds-(time.monotonic()-self.last_request))
            if delay:
                await asyncio.sleep(delay)
            if self.provider_error:
                raise self.provider_error
            self.last_request = time.monotonic()
            self.requests += 1
        self.active_requests += 1
        try:
            return await observed_work(self.fetch(symbol, timeframe, start, end, client=client), self.report,
                                       message=f'Loading {symbol} {timeframe} history')
        except Exception as exc:
            if rate_limited(exc):
                self.provider_error = exc
            raise
        finally:
            self.active_requests -= 1


DATA_ERRORS = (ValueError, OSError, HistoryError)
