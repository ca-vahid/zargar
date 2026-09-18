"""Immutable decision inputs committed atomically with arm state and journal reference.

Inputs preserve what the observer had, not later provider corrections. The context contains
the full session tape (bounded by a session), plan/baseline and observation cutoff. This is
enough to reconstruct preceding crossing state and session-extreme stops using read_entry.
Exact repeated occurrences dedupe; subsequent observations never overwrite earlier evidence.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy.dialects.postgresql import insert

from ...models import CartelDecisionBundle, CartelDecisionContext, Event

VERSION = 'cartel-decision-inputs-v2'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


async def capture(session, row, plan, minutes, previous, observation, now):
    seen = {digest(d) for d in previous.get('decisionHistory', [])}
    decisions = [d for d in observation.get('trace', []) if digest(d) not in seen]
    if not decisions:
        return []
    context = {'version': VERSION, 'plan': plan.model_dump(mode='json'),
               'minutes': sorted(minutes.values(), key=lambda b: b[0]),
               'entryAfter': previous.get('observeAfter', previous.get('armedAt')),
               'previousPhase': previous.get('phase'), 'previousSignal': previous.get('signal'),
               'verifiedIntervals': observation.get('verifiedIntervals', {}),
               'asOfMs': now, 'availability': 'Present in the observer at this cutoff; individual receipt times were not recorded.'}
    context_id = digest(context)
    await session.execute(insert(CartelDecisionContext).values(id=context_id,payload=context).on_conflict_do_nothing())
    events = []
    for decision in decisions:
        payload = {'version': VERSION, 'runId': row.run_id, 'portfolioId': row.portfolio_id,
                   'contextId': context_id, 'observedAt': now, 'decision': decision}
        identity = digest(payload)
        added = await session.scalar(insert(CartelDecisionBundle).values(
            id=identity, run_id=row.run_id, portfolio_id=row.portfolio_id,
            bucket_end=decision['at'], observed_at=now, context_id=context_id, payload=payload
        ).on_conflict_do_nothing().returning(CartelDecisionBundle.id))
        if added:
            event = Event(type='TechniqueCartelDecisionCaptured', aggregate_type='technique_run',
                          aggregate_id=row.run_id, portfolio_id=row.portfolio_id,
                          payload={'runId': row.run_id, 'symbol': plan.symbol, 'bundleId': identity,
                                   'sha256': identity, 'contextId': context_id, 'bucketEnd': decision['at'],
                                   'observedAt': now, 'decision': decision['decision']})
            session.add(event)
            events.append(event)
    await session.flush()
    return [{'id': e.id, 'ts': e.ts.isoformat(), 'type': e.type, 'aggregateType': e.aggregate_type,
             'aggregateId': e.aggregate_id, 'portfolioId': e.portfolio_id, 'payload': e.payload} for e in events]
