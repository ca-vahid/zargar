"""Recorded-quote valuation of a saved campaign schedule, not broker-fill replay."""
from __future__ import annotations

import hashlib
import json
from bisect import bisect_right

from pydantic import Field, model_validator
from sqlalchemy import select

from ...marketstructure.sessions import session_bounds
from ...models import CartelOptionQuote
from ...options.occ import parse
from .service import WireModel


class PremiumQuote(WireModel):
    source_at: int | None = Field(default=None, ge=0)
    available_at: int = Field(ge=0)
    bid: float = Field(ge=0)
    ask: float = Field(ge=0)
    delayed: bool = False
    halted: bool = False

    @model_validator(mode='after')
    def coherent(self):
        if self.source_at is not None and self.available_at < self.source_at:
            raise ValueError('quote availability cannot precede source time')
        return self


class StoredPremiumReplayInput(WireModel):
    contract_symbol: str = Field(min_length=1, max_length=32)
    max_quote_age_ms: int = Field(default=15_000, ge=0, le=60_000)
    fee_per_contract: float = Field(default=0, ge=0, le=100)


class PremiumReplayInput(StoredPremiumReplayInput):
    source: str = Field(min_length=1, max_length=2000)
    quotes: list[PremiumQuote] = Field(default_factory=list, max_length=40_000)


def value_campaign(replay, body: PremiumReplayInput, *, symbol, direction, as_of_ms):
    contract = parse(body.contract_symbol)
    if contract is None or contract.underlying != symbol or contract.right != ('C' if direction == 'long' else 'P'):
        raise ValueError('option contract must match the replay underlying and direction')
    expiry_close = session_bounds(contract.expiry.isoformat())[1]
    seen = {}
    for q in body.quotes:
        key = q.available_at
        if key in seen and seen[key] != q:
            raise ValueError('conflicting recorded quotes')
        seen[key] = q
    latest = sorted(seen.values(), key=lambda q: q.available_at)
    available = [q.available_at for q in latest]

    def quote_at(at):
        index = bisect_right(available, at)-1
        q = latest[index] if index >= 0 else None
        return q if q is not None and q.source_at is not None and not q.delayed and not q.halted \
            and q.ask >= q.bid > 0 and at < expiry_close \
            and 0 <= at-q.source_at <= body.max_quote_age_ms else None

    output = {'model': 'Recorded ask entry and bid exits on the underlying replay fill schedule',
        'contractSymbol': contract.symbol, 'source': body.source, 'placesOrders': False,
        'simulation': True, 'status': 'incomplete', 'fills': [], 'realizedPnl': None,
        'openPnl': None, 'totalPnl': None, 'returnOnDebitPct': None, 'fees': None,
        'warnings': ['Quote sizes, resting fills, expiry settlement and premium-triggered exits are not simulated.']}
    fills = replay.get('fills', [])
    if not replay.get('dataComplete') or not fills or fills[0]['kind'] != 'entry':
        output['warnings'].append('A complete underlying replay with a modeled entry is required.')
        return output
    initial = fills[0]['qty']
    if not isinstance(initial, int) or isinstance(initial, bool) or initial <= 0:
        raise ValueError('invalid replay quantity')
    remaining, entry_price, realized, fees = initial, None, 0., 0.
    previous_at = -1
    for index, fill in enumerate(fills):
        at, qty = fill['at'], fill['qty']
        if at < previous_at or at > as_of_ms or not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            raise ValueError('invalid replay fill sequence')
        previous_at = at
        q = quote_at(at)
        if q is None:
            output['warnings'].append(f'No eligible recorded quote at modeled fill time {at}; no return inferred.')
            return output
        if index:
            if fill['kind'] == 'entry' or qty > remaining:
                raise ValueError('invalid replay exit quantity')
            remaining -= qty
            realized += (q.bid-entry_price)*qty*100 - 2*body.fee_per_contract*qty
        else:
            entry_price = q.ask
        price = q.ask if index == 0 else q.bid
        fees += body.fee_per_contract*qty
        output['fills'].append({'kind': fill['kind'], 'at': at, 'qty': qty, 'premium': price,
            'quoteSourceAt': q.source_at, 'quoteAvailableAt': q.available_at,
            'fee': body.fee_per_contract*qty})
    if remaining:
        mark = quote_at(as_of_ms)
        if mark is None:
            output['warnings'].append('No eligible remaining-position mark; no total return inferred.')
            return output
        open_pnl = (mark.bid-entry_price)*remaining*100 - body.fee_per_contract*remaining
    else:
        open_pnl = 0.
    total = realized+open_pnl
    return {**output, 'status': 'closed' if not remaining else 'open', 'remainingQty': remaining,
        'realizedPnl': realized, 'openPnl': open_pnl, 'totalPnl': total, 'fees': fees,
        'returnOnDebitPct': total/(entry_price*initial*100+body.fee_per_contract*initial)*100}


async def save_premium_replay(service, run_id, body: PremiumReplayInput, *, observation_ids=None):
    parent = await service._load(run_id)
    if parent.mode != 'replay':
        raise ValueError('premium valuation requires a saved underlying campaign replay')
    plan = parent.config['planSnapshot']['plan']
    result = value_campaign(parent.result, body, symbol=parent.symbol,
                            direction=plan['direction'], as_of_ms=parent.as_of)
    inputs = body.model_dump(mode='json')
    return await service._store(mode='premium_replay', symbol=parent.symbol, at=parent.as_of,
        verdict=result['status'], parent=run_id, result=result,
        config={'inputs': inputs, 'underlyingReplay': parent.result, 'quoteObservationIds': observation_ids,
                'inputSha256': hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
                'dataSource': body.source, 'codeVersion': 'cartel-premium-valuation-2'})


async def value_stored_quotes(service, run_id, body: StoredPremiumReplayInput):
    replay = await service._load(run_id)
    if replay.mode != 'replay' or not replay.parent_run_id:
        raise ValueError('stored quote valuation requires a replay linked to its owned plan')
    plan = await service._load(replay.parent_run_id)
    contract = parse(body.contract_symbol)
    if plan.mode != 'plan' or contract is None or contract.underlying != replay.symbol or plan.symbol != replay.symbol:
        raise ValueError('stored quote contract and replay must match the owned plan')
    start = min((f['at'] for f in replay.result.get('fills', [])), default=replay.as_of)-body.max_quote_age_ms
    async with service.engine.sf() as session:
        rows = (await session.scalars(select(CartelOptionQuote).where(
            CartelOptionQuote.run_id == plan.id, CartelOptionQuote.contract == contract.symbol,
            CartelOptionQuote.available_at >= start, CartelOptionQuote.available_at <= replay.as_of)
            .order_by(CartelOptionQuote.available_at, CartelOptionQuote.id).limit(40001))).all()
    if len(rows) > 40000:
        raise ValueError('quote window exceeds 40,000 observations; choose a shorter replay')
    sources = sorted({f'{r.source or "unspecified"} (feed mode {r.feed_mode})' for r in rows})
    request = PremiumReplayInput(**body.model_dump(),
        source='Stored Cartel observations: '+(', '.join(sources) or 'none in this plan/contract window'),
        quotes=[PremiumQuote(source_at=r.source_at, available_at=r.available_at, bid=r.bid, ask=r.ask,
                             delayed=r.delayed, halted=r.halted) for r in rows])
    return await save_premium_replay(service, run_id, request, observation_ids=[r.id for r in rows])
