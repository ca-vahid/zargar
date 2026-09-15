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
        self.last_ids = {}
        self.result = {'captured': 0, 'duplicates': 0, 'gaps': {}, 'errors': {}}

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
        manager = getattr(self.service.engine, 'position_manager', None)
        for position in manager.positions() if manager is not None else []:
            if position.get('technique') != 'options_cartel' or position.get('status') in ('closed', 'archived') or not position.get('runId'):
                continue
            for leg in position.get('legs', []):
                if leg.get('secType') == 'OPT' and abs(leg.get('qty', 0)) > 0:
                    targets.add((position['runId'], leg['symbol']))
        if not targets:
            self.last_ids.clear()
            return
        self.last_ids = {key: value for key, value in self.last_ids.items() if key in targets}
        self.last_attempt = at
        self.task = asyncio.create_task(self._capture(sorted(targets)), name='cartel-quote-recorder')

    async def _capture(self, targets):
        result = {'captured': 0, 'duplicates': 0, 'gaps': {}, 'errors': {}}
        for run_id, contract in targets:
            if self.stopping or not self.service.engine.settings.get(RECORD_SETTING, False):
                break
            try:
                observation = await capture_cached_quote(self.service, run_id, contract, clock=self.clock)
                key = (run_id, contract)
                duplicate = self.last_ids.get(key) == observation['id']
                result['duplicates' if duplicate else 'captured'] += 1
                self.last_ids[key] = observation['id']
                reason = unusable_reason(observation, self.clock())
                if reason:
                    result['gaps'][run_id] = reason
            except (KeyError, ValueError) as exc:
                result['errors'][run_id] = str(exc)
                result['gaps'][run_id] = str(exc)
                try:
                    await capture_quote_gap(self.service, run_id, contract, clock=self.clock)
                except Exception as gap_error:  # noqa: BLE001 - research availability never interrupts execution
                    result['errors'][run_id] += f'; gap record unavailable ({type(gap_error).__name__})'
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
    # Source evidence owns identity; a cache re-read is not a new observation.
    identity = {k: v for k, v in data.items() if k not in ('available_at', 'confirmed_at')}
    data['id'] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    async with service.engine.sf() as session, session.begin():
        inserted = await session.scalar(insert(CartelOptionQuote).values(**data)
            .on_conflict_do_nothing(index_elements=['id']).returning(CartelOptionQuote.id))
        if inserted is None:
            existing = await session.get(CartelOptionQuote, data['id'])
            data = {column.name: getattr(existing, column.name) for column in CartelOptionQuote.__table__.columns}
    return {**data, 'placesOrders': False,
            'warning': 'Observation time does not establish provider freshness. Missing source time remains unknown.'}


def unusable_reason(observation, at, *, maximum_age_ms=15_000):
    if str(observation.get('source', '')).startswith('gap:'):
        return 'Missing usable cached quote'
    source_at = observation.get('source_at')
    if source_at is None:
        return 'Source observation time is unknown'
    if not 0 <= at-source_at <= maximum_age_ms:
        return 'No fresh source observation'
    if observation.get('delayed') or observation.get('halted'):
        return 'Delayed or halted observation'
    if not 0 < observation['bid'] <= observation['ask']:
        return 'Missing or crossed two-sided quote'
    return None


async def capture_quote_gap(service, run_id, contract, *, clock=now_ms):
    """One durable unavailable marker per contiguous gap; never a market quote."""
    plan = await service._load(run_id)
    option = parse(contract)
    if plan.mode != 'plan' or option is None or option.underlying != plan.symbol:
        raise ValueError('gap capture requires an owned plan and matching contract')
    observed = clock()
    async with service.engine.sf() as session, session.begin():
        prior = await session.scalar(select(CartelOptionQuote).where(CartelOptionQuote.run_id == run_id,
            CartelOptionQuote.contract == option.symbol).order_by(CartelOptionQuote.available_at.desc(),
            CartelOptionQuote.id.desc()).limit(1))
        if prior is not None and prior.source == 'gap:unavailable':
            return prior.id
        data = {'run_id': run_id, 'contract': option.symbol, 'source_at': None,
            'available_at': observed, 'confirmed_at': observed, 'bid': 0., 'ask': 0.,
            'bid_size': 0, 'ask_size': 0, 'source': 'gap:unavailable',
            'feed_mode': service.engine.config.quote_source, 'delayed': True, 'halted': False}
        data['id'] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        await session.execute(insert(CartelOptionQuote).values(**data).on_conflict_do_nothing(index_elements=['id']))
    return data['id']


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
