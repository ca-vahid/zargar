import asyncio
import datetime as dt

import pytest
from sqlalchemy import func, select

from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.models import Order, Portfolio, TechniqueArmed, TechniqueRun
from zargar.options.occ import Occ
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.industry import IndustrySnapshot, read_industry
from zargar.techniques.options_cartel.preparation import (
    SETTING,
    practice_portfolio,
    run_preparation,
    stop_preparation,
    submit_preparation,
)
from zargar.techniques.options_cartel.runtime import CartelRuntime

from .test_options_cartel_prepare import input_data


def inputs():
    data = input_data()
    data['history'] = [b.model_copy(update={'high': b.close+3, 'low': b.close-3}) for b in data['history']]
    at = data['as_of_ms']+1000
    universe = {'rows': [{'symbol': 'TEST', 'observedAt': at, 'source': 'synthetic publisher fixture',
        'marketCap': 1e9, 'sourceBarOpenAt': session_bounds(data['history'][-1].session.isoformat())[0],
        'industry': 'Semiconductors', 'dailyVolume': 1_000_000}], 'providerTotal': 1, 'received': 1,
        'complete': True, 'excluded': [], 'observedAt': at, 'inputSha256': 'fixture'}
    async def discover(rules, *, clock):
        return universe
    async def industries(*, clock):
        return IndustrySnapshot(source='synthetic publisher fixture', observed_at=at,
            freshness_basis='publisher_observation', expected_count=1,
            week_definition='fixture 1W', month_definition='fixture 1M',
            rows=[{'industry': 'Semiconductors', 'weekPct': 5, 'monthPct': 5}]), {'synthetic': True}
    async def fetch(symbol, tf, start, end, *, client):
        if tf == '1d':
            rows = data['history'] if symbol == 'TEST' else data['indices'][symbol]
            return [Bar(symbol, tf, session_bounds(b.session.isoformat())[0], b.open, b.high, b.low, b.close, b.volume) for b in rows]
        return [Bar(symbol, '1m', session_bounds(b.session.isoformat())[0]+i*60_000, 145, 146, 144, 145, 100)
                for b in data['history'][-5:] for i in range(15)]
    async def choose(engine, plan, policy):
        assert policy.max_ask <= 1  # 1% of the fixture's 10K equity, full-debit risk
        return {'selected': {'symbol': Occ('TEST', plan.first_session+dt.timedelta(days=45), 'C', 150).symbol},
                'planningOnly': True}
    return at, {'discover': discover, 'industries': industries, 'fetch': fetch, 'choose': choose}


async def test_full_preparation_builds_and_arms_automatic_practice_plan_without_entry_order(engine):
    at, providers = inputs()
    runtime = CartelRuntime(engine); runtime.clock = lambda: at
    engine.cartel_observer = runtime
    policy = PreparationPolicy(enabled=True, history_limit=10)
    await engine.settings.set(SETTING, policy.model_dump(mode='json'))
    try:
        result = await run_preparation(engine, policy, clock=lambda: at, **providers)
        assert result['status'] == 'done', result
        assert result['result']['armed'] == 1, result['result']
        row = result['result']['shortlist'][0]
        assert row['status'] == 'armed' and row['targets'][0] > row['trigger'] > row['invalidation']
        async with engine.sf() as session:
            armed = await session.get(TechniqueArmed, row['planId'])
            assert armed.mode == 'auto' and armed.config['execution']['allow_live'] is False
            assert (await session.get(Portfolio, armed.portfolio_id)).kind == 'sim'
            assert await session.scalar(select(func.count()).select_from(Order)) == 0
        runtime.clock = lambda: at+1
        refreshed = await run_preparation(engine, policy, clock=lambda: at+1, **providers)
        assert refreshed['result']['armed'] == 1, refreshed
        assert refreshed['result']['replacedPlans'] == [row['planId']]
        assert runtime.rows[row['planId']]['status'] == 'disarmed'
        new_id = refreshed['result']['shortlist'][0]['planId']
        await runtime.pause(new_id)
        runtime.clock = lambda: at+2
        paused = await run_preparation(engine, policy, clock=lambda: at+2, **providers)
        assert paused['result']['replacedPlans'] == []
        assert paused['result']['shortlist'][0]['status'] == 'already_managed'
        assert runtime.rows[new_id]['status'] == 'paused'
        runtime.clock = lambda: at+86_400_010
        await runtime.on_heartbeat()
        assert runtime.rows[new_id]['status'] == 'expired'
    finally:
        await runtime.stop()


async def test_preparation_refuses_non_practice_portfolio_before_any_discovery(engine):
    async with engine.sf() as session, session.begin():
        session.add(Portfolio(id='real-book', name='Not Practice', kind='live', base_currency='USD', cash=10000))
    with pytest.raises(ValueError, match='Practice'):
        await practice_portfolio(engine, 'real-book')


async def test_concurrent_requests_share_preparation_and_shutdown_cancels_research(engine):
    at, providers = inputs()
    runtime = CartelRuntime(engine); runtime.clock = lambda: at
    engine.cartel_observer = runtime
    await engine.settings.set(SETTING, PreparationPolicy(enabled=True).model_dump(mode='json'))
    entered = asyncio.Event()
    async def blocked(*args, **kwargs):
        entered.set(); await asyncio.Event().wait()
    providers['discover'] = blocked
    try:
        first, second = await asyncio.gather(*[submit_preparation(engine, clock=lambda: at, **providers) for _ in range(2)])
        assert first['runId'] == second['runId']
        await entered.wait()
        await stop_preparation(engine)
        assert engine._cartel_preparation_task.cancelled()
        async with engine.sf() as session:
            record = await session.get(TechniqueRun, first['runId'])
            assert record.status == 'failed' and record.result['phase'] == 'interrupted'
    finally:
        await runtime.stop()


def test_publisher_snapshot_uses_observation_age_without_fabricating_provider_time():
    snapshot = IndustrySnapshot(source='publisher fixture', observed_at=2000, freshness_basis='publisher_observation',
        expected_count=1, week_definition='1W', month_definition='1M', rows=[{'industry':'A','weekPct':1,'monthPct':1}])
    assert snapshot.data_as_of_ms is None
    assert read_industry(snapshot, 'A', at=2000)['status'] == 'pass'
    assert read_industry(snapshot, 'A', at=1999)['status'] == 'unknown'
    assert read_industry(snapshot, 'A', at=2000+86_400_001)['status'] == 'unknown'
