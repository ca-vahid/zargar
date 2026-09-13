"""Durable incremental research cache. Never writes the runtime bars projection."""
from __future__ import annotations

import hashlib
import json

from sqlalchemy.dialects.postgresql import insert

from ...domain import Bar
from ...models import CartelHistoryCache


def cache_key(symbol, timeframe, provider):
    return hashlib.sha256(f'{provider}:{symbol}:{timeframe}:rth:v1'.encode()).hexdigest()


async def read_cache(engine, symbol, timeframe, provider, at):
    async with engine.sf() as session:
        row = await session.get(CartelHistoryCache, cache_key(symbol, timeframe, provider))
        if row is None or row.observed_at > at:
            return None
        return {'start': row.start_ms, 'end': row.end_ms, 'observedAt': row.observed_at, **row.payload}


async def write_cache(engine, symbol, timeframe, provider, start, end, observed_at, bars):
    # Bar revisions are retained in each analysis/decision, not certified by this cache.
    values = [[b.ts, b.open, b.high, b.low, b.close, b.volume, b.source] for b in bars]
    payload = {'bars': values, 'provider': provider, 'sessionPolicy': 'provider_daily' if 'alpaca' in provider and timeframe == '1d' else 'rth',
               'inputHash': hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()}
    args = {'id': cache_key(symbol, timeframe, provider), 'symbol': symbol, 'timeframe': timeframe,
            'start_ms': start, 'end_ms': end, 'observed_at': observed_at, 'payload': payload}
    async with engine.sf() as session, session.begin():
        stmt = insert(CartelHistoryCache).values(**args)
        await session.execute(stmt.on_conflict_do_update(index_elements=['id'],
            set_={k:v for k,v in args.items() if k != 'id'},
            where=CartelHistoryCache.observed_at <= observed_at))
    return payload


def cached_bars(cache, symbol, timeframe):
    return [Bar(symbol, timeframe, *b[:6], source=b[6] or 'unknown') for b in cache['bars']]
