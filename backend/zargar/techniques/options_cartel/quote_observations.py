"""Persist existing cache observations; never subscribe, fetch, arm or submit."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ...domain import now_ms
from ...models import CartelOptionQuote
from ...options.occ import parse

RECORD_SETTING = 'techniques.options_cartel.record_option_quotes'


class QuoteRecorder:
    """One background sample batch at a time; no unbounded queue of quote ticks."""
    def __init__(self, service, clock=now_ms):
        self.service, self.clock = service, clock
        self.task = None
        self.stopping = False
        self.last_attempt = None
        self.result = {'captured': 0, 'errors': {}}

    def status(self):
        return {'enabled': bool(self.service.engine.settings.get(RECORD_SETTING, False)),
                'running': self.task is not None and not self.task.done(),
                'lastAttemptAt': self.last_attempt, 'sampleIntervalMs': 5000, **self.result}

    def observe(self, rows):
        if self.stopping or not self.service.engine.settings.get(RECORD_SETTING, False) \
                or self.task is not None and not self.task.done():
            return
        at = self.clock()
        if self.last_attempt is not None and at-self.last_attempt < 5000:
            return
        targets = set()
        for row in rows:
            spec = row.get('config', {}).get('execution', {})
            if row.get('mode') in ('proposal', 'auto') and row.get('status') in ('armed', 'paused', 'closing') \
                    and spec.get('instrument') == 'options' and spec.get('contract_symbol'):
                targets.add((row['runId'], spec['contract_symbol']))
        if not targets:
            return
        self.last_attempt = at
        self.task = asyncio.create_task(self._capture(sorted(targets)), name='cartel-quote-recorder')

    async def _capture(self, targets):
        result = {'captured': 0, 'errors': {}}
        for run_id, contract in targets:
            if self.stopping or not self.service.engine.settings.get(RECORD_SETTING, False):
                break
            try:
                await capture_cached_quote(self.service, run_id, contract, clock=self.clock)
                result['captured'] += 1
            except (KeyError, ValueError) as exc:
                result['errors'][run_id] = str(exc)
            except Exception as exc:  # noqa: BLE001 - research failures must not interrupt order handling
                result['errors'][run_id] = f'{type(exc).__name__}: quote recording failed'
        self.result = result

    async def stop(self):
        self.stopping = True
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


async def capture_cached_quote(service, run_id, contract, *, clock=now_ms):
    plan = await service._load(run_id)
    option = parse(contract)
    if plan.mode != 'plan' or option is None or option.underlying != plan.symbol:
        raise ValueError('quote capture requires an owned plan and a matching underlying contract')
    quote = service.engine.quotes.get(option.symbol)
    if quote is None:
        raise ValueError('No cached quote exists; capture does not request a feed subscription')
    observed = clock()
    if quote.ts > observed or quote.source_ts > observed:
        raise ValueError('Future-dated quote cannot be recorded as currently available')
    if not all(math.isfinite(v) and v >= 0 for v in (quote.bid, quote.ask, quote.bid_size, quote.ask_size)):
        raise ValueError('Quote prices and sizes must be finite and nonnegative')
    data = {'run_id': run_id, 'contract': option.symbol, 'source_at': quote.source_ts or None,
        'available_at': observed, 'confirmed_at': quote.ts, 'bid': quote.bid, 'ask': quote.ask,
        'bid_size': quote.bid_size, 'ask_size': quote.ask_size, 'source': quote.source,
        'feed_mode': service.engine.config.quote_source, 'delayed': quote.delayed, 'halted': quote.halted}
    data['id'] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    async with service.engine.sf() as session, session.begin():
        await session.execute(insert(CartelOptionQuote).values(**data).on_conflict_do_nothing(index_elements=['id']))
    return {**data, 'placesOrders': False,
            'warning': 'Observation time does not establish provider freshness. Missing source time remains unknown.'}


async def quote_observations(service, run_id, contract, *, limit=1000):
    plan = await service._load(run_id)
    option = parse(contract)
    if plan.mode != 'plan' or option is None or option.underlying != plan.symbol or not 1 <= limit <= 40000:
        raise ValueError('invalid owned plan, contract or observation limit')
    async with service.engine.sf() as session:
        rows = (await session.scalars(select(CartelOptionQuote).where(
            CartelOptionQuote.run_id == run_id, CartelOptionQuote.contract == option.symbol)
            .order_by(CartelOptionQuote.available_at.desc(), CartelOptionQuote.id).limit(limit))).all()
    return {'runId': run_id, 'contractSymbol': option.symbol, 'placesOrders': False,
            'limit': limit, 'rows': [{column.name: getattr(row, column.name) for column in CartelOptionQuote.__table__.columns}
                                    for row in reversed(rows)]}
