"""Paced, observable history reads and bounded reuse of saved research bars."""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from sqlalchemy import BigInteger, cast, select

from ...marketstructure.history import HistoryError, fetch_daily_batch, fetch_window, native_daily_available
from ...marketstructure.sessions import session_bounds
from ...models import TechniqueRun
from .collect import normalize_daily
from .data import DailyBar, completed_daily
from .history_cache import cached_bars, read_cache, write_cache
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
        self.native_batch = policy.native_daily_batch and fetch is fetch_window and native_daily_available()
        self.batch_values = {}
        self.provider_key = 'alpaca:sip:raw:daily:v1' if self.native_batch else f'{getattr(fetch, "__module__", "injected")}.{getattr(fetch, "__qualname__", "provider")}:daily-yahoo-rth'

    @asynccontextmanager
    async def prefetch(self, listings, at, client, *, skip):
        """Bounded sliding window; fetch concurrently, consume in discovery order.

        Every task is owned by this context and awaited on every exit. Failures
        reach the coordinator in order so successful prior analyses remain resumable.
        """
        if self.native_batch:
            async def batched():
                size = self.policy.history_batch_size
                for offset in range(0, len(listings), size):
                    group = listings[offset:offset+size]
                    need = []
                    starts = []
                    for item in group:
                        if skip(item):
                            continue
                        cached = await read_cache(self.engine, item['symbol'], '1d', self.provider_key, at)
                        if not cached or not cached['bars'] or normalize_daily(cached_bars(cached, item['symbol'], '1d'), item['symbol'], at)[-1].session.isoformat() != _latest_session(at).isoformat():
                            need.append(item['symbol'])
                            starts.append(max(at-550*86400000, cached['bars'][-1][0]-86400000) if cached and cached['bars'] else at-550*86400000)
                    if need:
                        self.requests += 1
                        self.active_requests += 1
                        try:
                            self.batch_values = await observed_work(fetch_daily_batch(need, min(starts), at, client=client), self.report, message=f'Loading daily history batch ({len(need)} symbols)')
                        finally:
                            self.active_requests -= 1
                    for item in group:
                        try:
                            value = None if skip(item) else await self.daily(item['symbol'], at, client)
                            self.prefetched += value is not None
                        except Exception as exc:  # noqa: BLE001 - ordered coordinator handles individual errors
                            value = exc
                        yield item, value
                    self.batch_values = {}
                    await asyncio.sleep(self.policy.request_interval_seconds)
            iterator = batched()
            try:
                yield iterator
            finally:
                await iterator.aclose()
                self.batch_values = {}
            return
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
        raw_cache = await read_cache(self.engine, symbol, '1d', self.provider_key, at)
        prior_bars = cached_bars(raw_cache, symbol, '1d') if raw_cache else []
        if prior_bars:
            previous = normalize_daily(prior_bars, symbol, at)
            if previous and previous[-1].session.isoformat() == expected:
                self.cache_hits += 1
                return previous, {'historyCacheVersion': 1, 'historyThrough': expected,
                    'historyExpectedThrough': expected, 'historyFresh': True,
                    'historyObservedAt': raw_cache['observedAt'], 'historyReusedFrom': 'durable_cache',
                    'historySource': self.provider_key, 'inputHash': raw_cache['inputHash']}

        async with self.engine.sf() as session:
            cached = await session.scalar(select(TechniqueRun).where(
                TechniqueRun.technique == 'options_cartel', TechniqueRun.mode == 'analysis',
                TechniqueRun.symbol == symbol, TechniqueRun.status == 'done',
                TechniqueRun.result['collection']['historyCacheVersion'].as_integer() == 1,
                TechniqueRun.result['collection']['historyThrough'].as_string() == expected,
                cast(TechniqueRun.result['collection']['historyObservedAt'].as_string(), BigInteger) <= at,
                cast(TechniqueRun.result['collection']['historyObservedAt'].as_string(), BigInteger) >= at-5*86_400_000,
            ).order_by(TechniqueRun.created_at.desc()).limit(1))
        if cached and (not self.native_batch or cached.result.get('collection', {}).get('historySource') == self.provider_key):
            bars = completed_daily([DailyBar.model_validate(b) for b in cached.config['inputs']['history']], at)
            if bars and bars[-1].session.isoformat() == expected and all(b.symbol == symbol for b in bars):
                self.cache_hits += 1
                return bars, {**cached.result['collection'], 'historyReusedFrom': cached.id}
        start = at-550*86_400_000
        # Overlap the prior session to detect a revision; never reuse a incompatible prefix.
        fetch_start = max(start, prior_bars[-1].ts-86_400_000) if prior_bars else start
        provider_before = self.provider_key
        fetched = await self.window(symbol, '1d', fetch_start, at, client)
        if provider_before != self.provider_key:
            prior_bars = []
            fetched = await self.window(symbol, '1d', start, at, client)
        merged = {b.ts:b for b in prior_bars if b.ts >= start}
        # A revised overlap may indicate a split/adjustment change. Reload full history.
        if any(b.ts in merged and merged[b.ts].close != b.close for b in fetched):
            fetched = await self.window(symbol, '1d', start, at, client, refresh=True)
            merged = {}
        merged.update({b.ts:b for b in fetched})
        raw = sorted(merged.values(), key=lambda b:b.ts)
        bars = normalize_daily(raw, symbol, at)
        actual = bars[-1].session.isoformat() if bars else None
        if symbol in ('SPY', 'QQQ') and actual != expected:
            await self.report(symbol=symbol, message=f'{symbol} history ends {actual or "without bars"}; retrying for {expected}')
            bars = normalize_daily(await self.window(symbol, '1d', at-550*86_400_000, at, client, refresh=True), symbol, at)
            actual = bars[-1].session.isoformat() if bars else None
        if actual == expected:
            # Re-normalize to exchange-open timestamps for a stable completed-session cache.
            from ...domain import Bar
            sources = {r.ts:r.source for r in raw}
            raw = [Bar(symbol, '1d', session_bounds(b.session.isoformat())[0], b.open, b.high, b.low, b.close, b.volume, source=sources.get(session_bounds(b.session.isoformat())[0], 'unknown')) for b in bars]
            await write_cache(self.engine, symbol, '1d', self.provider_key, start, at, self.clock(), raw)
        return bars, {'historyCacheVersion': 1, 'historyThrough': actual,
                      'historyExpectedThrough': expected, 'historyFresh': actual == expected,
                      'historyObservedAt': self.clock(), 'historyReusedFrom': None,
                      'historySource': 'Shared historical provider; completed daily bars only'}

    async def baseline(self, symbol, at, client):
        from ...marketstructure.market_calendar import previous_trading_day
        day = _latest_session(at)
        required_minutes = (session_bounds(day.isoformat())[1]-session_bounds(day.isoformat())[0])//60000
        end = session_bounds(day.isoformat())[1]
        for _ in range(19):
            day = previous_trading_day(day)
            required_minutes += (session_bounds(day.isoformat())[1]-session_bounds(day.isoformat())[0])//60000
        start = session_bounds(day.isoformat())[0]
        provider = self.provider_key+':intraday'
        cached = await read_cache(self.engine, symbol, '1m', provider, at)
        old = cached_bars(cached, symbol, '1m') if cached else []
        full = len({b.ts for b in old if start <= b.ts and b.ts+60000 <= end and b.source == 'exchange'}) == required_minutes
        if cached and cached['start'] <= start and cached['end'] >= end and (full or at-cached['observedAt'] < 300000):
            self.cache_hits += 1
            return [b for b in old if start <= b.ts and b.ts+60000 <= end]
        fetch_start = max(start, cached['end']-2*86400000) if cached and full else start
        bars = await self.window(symbol, '1m', fetch_start, end, client)
        merged = {b.ts:b for b in old if start <= b.ts and b.ts+60000 <= end}
        merged.update({b.ts:b for b in bars if start <= b.ts and b.ts+60000 <= end})
        result = sorted(merged.values(), key=lambda b:b.ts)
        await write_cache(self.engine, symbol, '1m', provider, start, end, self.clock(), result)
        return result

    async def window(self, symbol, timeframe, start, end, client, *, refresh=False):
        if self.native_batch and timeframe == '1d':
            if symbol in self.batch_values and not refresh:
                return self.batch_values[symbol]
            self.requests += 1
            try:
                result = await observed_work(fetch_daily_batch([symbol], start, end, client=client), self.report, message=f'Loading {symbol} native daily history')
                return result[symbol]
            except HistoryError as exc:
                if not any(code in str(exc) for code in ('HTTP 401', 'HTTP 403')):
                    raise
                self.native_batch = False
                self.provider_key = f'{self.fetch.__module__}.{self.fetch.__qualname__}:daily-yahoo-rth'
                await self.report(message='Native daily access unavailable; using the existing history provider with a separate cache')

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
            kwargs = {'refresh': True} if refresh and self.fetch is fetch_window else {}
            return await observed_work(self.fetch(symbol, timeframe, start, end, client=client, **kwargs), self.report,
                                       message=f'Loading {symbol} {timeframe} history')
        except Exception as exc:
            if rate_limited(exc):
                self.provider_error = exc
            raise
        finally:
            self.active_requests -= 1


DATA_ERRORS = (ValueError, OSError, HistoryError)
