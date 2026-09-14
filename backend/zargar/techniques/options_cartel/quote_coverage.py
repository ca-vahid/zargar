"""Stream durable source observations; worker counters are not daily coverage."""
from sqlalchemy import select

from ...marketstructure.sessions import session_bounds
from ...models import CartelOptionQuote, TechniqueArmed, TechniqueRun
from .quote_observations import unusable_reason


async def coverage_report(engine, portfolio_id, day):
    lo, hi = session_bounds(day)
    async with engine.sf() as session:
        ids = select(TechniqueArmed.run_id).where(TechniqueArmed.technique == 'options_cartel', TechniqueArmed.portfolio_id == portfolio_id).union(
            select(TechniqueRun.id).where(TechniqueRun.technique == 'options_cartel', TechniqueRun.mode == 'plan',
                TechniqueRun.config['preparation']['portfolioId'].as_string() == portfolio_id))
        stream = await session.stream_scalars(select(CartelOptionQuote).where(CartelOptionQuote.run_id.in_(ids),
            CartelOptionQuote.available_at >= lo, CartelOptionQuote.available_at <= hi)
            .order_by(CartelOptionQuote.run_id, CartelOptionQuote.contract, CartelOptionQuote.available_at, CartelOptionQuote.id)
            .execution_options(yield_per=1000))
        groups = {}
        async for q in stream:
            key = (q.run_id, q.contract)
            row = groups.setdefault(key, {'planId': q.run_id, 'contract': q.contract, 'observations': 0,
                'eligible': 0, 'sources': {}, 'gapCount': 0, 'maxGapMs': 0, 'firstAt': q.available_at,
                'lastAt': q.available_at, 'lastEligibleAt': None})
            row['observations'] += 1
            row['lastAt'] = q.available_at
            row['sources'][q.source] = row['sources'].get(q.source, 0)+1
            data = {c.name: getattr(q, c.name) for c in CartelOptionQuote.__table__.columns}
            if not unusable_reason(data, q.available_at):
                last = row['lastEligibleAt']
                if last is not None and q.available_at-last > 15_000:
                    row['gapCount'] += 1
                    row['maxGapMs'] = max(row['maxGapMs'], q.available_at-last)
                row['lastEligibleAt'] = q.available_at
                row['eligible'] += 1
    return {'session': day, 'portfolioId': portfolio_id, 'rows': list(groups.values()),
        'note': 'Archive sampling gaps are not proof of feed outages. Closed plans need no later liquidation mark.'}
