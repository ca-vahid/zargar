"""Pending selection must not erase a closed-bar invalidation while it waits."""
import datetime as dt
from dataclasses import replace

from sqlalchemy import select

from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds, session_date
from zargar.models import Order, TechniqueArmed, TechniqueRun
from zargar.options.occ import Occ
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.data_quality import pack
from zargar.techniques.options_cartel.observer import CartelObserver
from zargar.techniques.options_cartel.preparation import activate_pending, run_preparation
from zargar.techniques.options_cartel.preparation_scope import SETTING
from zargar.techniques.options_cartel.runtime import CartelRuntime

from .test_options_cartel_entry import MIN, OPEN, tape
from .test_options_cartel_preparation import inputs
from .test_options_cartel_state import repo as repo  # noqa: PLC0414


async def test_invalidation_during_contract_selection_is_terminal_and_never_arms(engine, monkeypatch):
    at, providers = inputs()
    policy = PreparationPolicy(enabled=True, risk_pct=1, request_interval_seconds=0)
    await engine.settings.set(SETTING, policy.model_dump(mode='json'))
    now = [at]
    runtime = engine.cartel_observer = CartelRuntime(engine)
    runtime.clock = lambda: now[0]

    async def pending(*args):
        return {'selected': None, 'planningOnly': True}

    providers['choose'] = pending
    try:
        saved = await run_preparation(engine, policy, clock=runtime.clock, **providers)
        pid = saved['result']['shortlist'][0]['planId']
        async with engine.sf() as session:
            record = await session.get(TechniqueRun, pid)
        from zargar.techniques.options_cartel.plans import CartelPlan
        plan = CartelPlan.model_validate(record.result['plan']['plan'])
        opens, _ = session_bounds(plan.first_session.isoformat())
        step = plan.entry.timeframe_minutes
        now[0] = opens+step*MIN-10000
        price = (plan.trigger+plan.invalidation)/2
        candles = [Bar(plan.symbol, '1m', opens+i*MIN, price, price+.01, price-.01,
            price, 100, source='exchange') for i in range(step)]
        candles[-1] = replace(candles[-1], low=plan.invalidation-1, close=plan.invalidation-1)

        async def context(_engine, _plan, at):
            return [b for b in candles if b.ts+MIN <= at]

        monkeypatch.setattr('zargar.techniques.options_cartel.preparation.load_session_context', context)
        choices = []

        async def choose(_engine, _plan, _policy):
            choices.append(now[0])
            now[0] += 20000  # crosses the invalidating confirmation close
            return {'selected': {'symbol': Occ(plan.symbol, plan.first_session+dt.timedelta(days=45), 'C', 150).symbol}}

        await activate_pending(engine, clock=runtime.clock, choose=choose)
        async with engine.sf() as session:
            result = await session.get(TechniqueRun, saved['runId'])
            assert result.result['shortlist'][0]['status'] == 'invalidated'
            assert await session.get(TechniqueArmed, pid) is None
            assert not (await session.scalars(select(Order))).all()
        now[0] += 60000
        candles[-1] = replace(candles[-1], low=price-.01, close=price)  # rebound cannot revive persisted terminal status
        await activate_pending(engine, clock=runtime.clock, choose=choose)
        assert len(choices) == 1
    finally:
        await runtime.stop()


async def test_late_arm_observer_preserves_original_invalidation_lifetime(repo, monkeypatch):
    bars = [replace(b, source='exchange') for b in tape()]
    bars[:5] = [replace(b, low=48.1, close=48.2) for b in bars[:5]]
    armed_at = OPEN+11*MIN
    row = await repo.arm('r1', 'pf', 'alert', {}, now_ms=armed_at)
    async with repo.engine.sf() as session, session.begin():
        stored = await session.get(TechniqueArmed, 'r1')
        stored.state = {**stored.state, 'day': session_date(OPEN),
            'minutes': {str(b.ts): pack(b) for b in bars}, 'observeAfter': armed_at}
    observer = CartelObserver(repo.engine)
    observer.clock = lambda: OPEN+16*MIN
    monkeypatch.setattr(observer, '_publish', lambda _: None)
    await observer._remember(await repo.load(row['runId']))
    await observer.on_minute_bar('HOOD', replace(bars[-1], ts=OPEN+15*MIN))
    retired = await repo.load('r1')
    assert retired['status'] == 'disarmed'
    assert retired['state']['observation']['status'] == 'invalidated'
    assert retired['state']['signal'] is None
    restored = CartelObserver(repo.engine)
    assert await restored.repository.active() == []
    async with repo.engine.sf() as session:
        assert not (await session.scalars(select(Order))).all()
