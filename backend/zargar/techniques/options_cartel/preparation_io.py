"""Paced, observable history reads and bounded reuse of saved research bars."""
from __future__ import annotations

import asyncio
import time

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
        delay = max(0, self.policy.request_interval_seconds-(time.monotonic()-self.last_request))
        if delay:
            await asyncio.sleep(delay)
        self.last_request = time.monotonic()
        self.requests += 1
        await self.report(symbol=symbol, message=f'Loading {symbol} {timeframe} history')
        return await observed_work(self.fetch(symbol, timeframe, start, end, client=client), self.report,
                                   message=f'Loading {symbol} {timeframe} history')


DATA_ERRORS = (ValueError, OSError, HistoryError)
