"""Read-only Cartel session attribution; no estimated option profits."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from ...marketstructure.sessions import session_bounds
from ...models import Order, TechniqueArmed
from .data_quality import evidence


async def report(engine, portfolio_id, day):
    opens, closes = session_bounds(day)
    lo, hi = dt.datetime.fromtimestamp(opens/1000, dt.UTC), dt.datetime.fromtimestamp(closes/1000, dt.UTC)
    async with engine.sf() as session:
        arms = (await session.scalars(select(TechniqueArmed).where(TechniqueArmed.technique=='options_cartel',
            TechniqueArmed.portfolio_id==portfolio_id, TechniqueArmed.state['day'].as_string()==day))).all()
        orders = (await session.scalars(select(Order).where(Order.portfolio_id==portfolio_id,
            Order.technique=='options_cartel', Order.created_at>=lo, Order.created_at<=hi))).all()
    rows = []
    for arm in arms:
        state = arm.state
        trace = state.get('decisionHistory', [])
        kinds = {d.get('decision') for d in trace}
        category = ('signalled' if state.get('signal') else 'invalidated' if 'invalidated' in kinds else
                    'data_limited' if kinds & {'unsupported_volume_period','untrusted_confirmation'} else
                    'strategy_rejected' if 'watch_only' in kinds else 'no_trigger')
        rows.append({'planId':arm.run_id,'symbol':arm.symbol,'status':arm.status,'category':category,
            'decisions':trace, 'dataEvidence':evidence(state.get('minutes',{})),
            'lastObservedMinute':state.get('lastMinute')})
    return {'session':day,'portfolioId':portfolio_id,'rows':rows,'orderCount':len(orders),
        'filledOrders':sum(o.filled_qty>0 for o in orders), 'placesOrders':False,
        'note':'As-observed decisions. Source corrections may differ; this report does not estimate option P&L.'}
