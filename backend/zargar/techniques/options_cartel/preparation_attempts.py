"""Durable candidate observations; never order authority."""
import json

from sqlalchemy import and_, func, or_, select

from ...domain import new_id
from ...marketstructure.sessions import session_bounds
from ...models import CartelPreparationAttempt, TechniqueRun


async def record_attempt(engine, preparation_id, portfolio_id, item, at, *, policy=None):
    evidence = json.loads(json.dumps(item))
    if policy is not None:
        evidence['workspace'] = policy.workspace
        evidence['policy'] = policy.model_dump(mode='json')
    async with engine.sf() as session, session.begin():
        session.add(CartelPreparationAttempt(id=new_id(), preparation_id=preparation_id,
            portfolio_id=portfolio_id, plan_id=item.get('planId'), at=at, evidence=evidence))


def held_identity(position):
    config = position.config if isinstance(position.config, dict) else {}
    identity = config.get('runId')
    return identity if isinstance(identity, str) and identity.strip() else f'managed:{position.id}'


def recovery_due(row, now):
    recovery = row.result.get('recovery', {})
    target = getattr(row, 'config', {}).get('session')
    if target and recovery.get('window') != recovery_window(now, target):
        return not row.result.get('userCancelled')
    return (not row.result.get('userCancelled') and recovery.get('attempt', 0) < 3
            and now >= (recovery.get('nextRetryAt') or 0))


def recovery_window(now, target_session):
    phase = 'preopen' if now >= session_bounds(target_session)[0]-45*60_000 else 'evening'
    return f'{target_session}:{phase}'


async def attempt_page(engine, portfolio_id, day, cutoff, cursor=None):
    table = CartelPreparationAttempt
    filters = [table.portfolio_id == portfolio_id, table.at <= cutoff,
        table.preparation_id.in_(select(TechniqueRun.id).where(TechniqueRun.technique == 'options_cartel',
            TechniqueRun.config['session'].as_string() == day))]
    async with engine.sf() as session:
        total = await session.scalar(select(func.count()).select_from(table).where(*filters))
        if cursor:
            before, identity = cursor.split(':', 1)
            filters.append(or_(table.at < int(before), and_(table.at == int(before), table.id < identity)))
        rows = (await session.scalars(select(table).where(*filters).order_by(table.at.desc(), table.id.desc()).limit(201))).all()
    page = rows[:200]
    return {'rows': [{'id': a.id, 'at': a.at, 'planId': a.plan_id, **a.evidence} for a in page],
        'total': total, 'nextCursor': f'{page[-1].at}:{page[-1].id}' if len(rows) > 200 else None}
