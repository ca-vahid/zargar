"""Resume persisted catch-up requirements through the existing exit router."""
from __future__ import annotations

import datetime as dt
import math

from ...execution.serialization import position_guard
from ...marketstructure.market_calendar import is_trading_day
from ...marketstructure.sessions import ET, session_bounds
from .exit_router import TERMINAL


def current_execution_ready(manager, p):
    if not p.open_legs:
        return False
    now = manager.now_ms()
    day = dt.datetime.fromtimestamp(now/1000, ET).date()
    if not is_trading_day(day) or not session_bounds(day.isoformat())[0] <= now < session_bounds(day.isoformat())[1]:
        return False
    quote = manager.engine.quotes.get(p.open_legs[0].symbol)
    source_at = (quote.source_ts or quote.ts) if quote else 0
    return bool(quote and not quote.delayed and not quote.halted and 0 <= now-source_at <= 15_000
                and math.isfinite(quote.bid) and quote.bid > 0)


async def drain_catchup(adapter, manager, p):
    async with position_guard(manager, p.id):
        context = dict(p.policy['cartel'])
        batch = context.get('catchupReview')
        if not batch or batch['status'] not in ('reviewed', 'executing') or context.get('entryPending'):
            return
        if context.get('closeRequest') or any(r.get('status') not in TERMINAL
                and not (r['kind'] == 'venue_stop' and r.get('status') in ('ACCEPTED', 'SUBMITTED')) for r in p.exits):
            return
        _, state = adapter._sync(p, observed_at=manager.now_ms())
        context = dict(p.policy['cartel'])
        batch = dict(context['catchupReview'])
        if batch['status'] == 'reviewed':
            if state.model_dump(mode='json') != batch['review']['state']:
                batch.update(status='needs_review', reason='Position state changed after catch-up review.')
                context['catchupReview'] = batch
                p.policy = {**p.policy, 'cartel': context}
                await manager._persist(p)
                return
            target = state.remaining_qty
            actions = []
            for requirement in batch['review']['requirements']:
                target -= requirement['qty']
                actions.append({**requirement, 'remainingTarget': target})
            batch.update(status='executing', actions=actions, cursor=0)
        held = sum(abs(leg.qty) for leg in p.open_legs)
        while batch['cursor'] < len(batch['actions']) and held <= batch['actions'][batch['cursor']]['remainingTarget']:
            batch['cursor'] += 1
        if batch['cursor'] == len(batch['actions']):
            batch.update(status='complete', completedAt=manager.now_ms())
            context['missedCloses'] = sorted(set(context.get('missedCloses', []))-set(batch['review']['missedCloses']))
        context['catchupReview'] = batch
        p.policy = {**p.policy, 'cartel': context}
        await manager._persist(p)  # fixed remaining targets precede all routing I/O
        if batch['status'] == 'complete' or not p.open_legs:
            return
        if not current_execution_ready(manager, p):
            return  # never substitute the historical close for a current execution quote
        action = batch['actions'][batch['cursor']]
        await manager.close(p.id, fraction=(held-action['remainingTarget'])/held,
                            kind=f"cartel:{action['rung']}", force_market=action['rung'] == 'stop',
                            reason=f"Catch-up {batch['id']} at {action['observedAt']}: {action['reason']}")
