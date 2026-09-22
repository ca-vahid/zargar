"""R3 (2026-09-21 review): a real short-regime preparation through arming under both policy states.

The 5-minute pilot (`breakout_5m_v1`) is scoped to LONG Practice plans. A bearish market regime is an
actionable direction in this pipeline, so its executable short plan must keep the incumbent 15-minute
cadence with no matched control, under the pilot exactly as under the incumbent policy.
"""
import datetime as dt

from sqlalchemy import func, select

from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.models import Order, TechniqueArmed, TechniqueRun
from zargar.options.occ import Occ
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.industry import IndustrySnapshot
from zargar.techniques.options_cartel.plans import CartelPlan, EntryPolicy
from zargar.techniques.options_cartel.preparation import SETTING, run_preparation
from zargar.techniques.options_cartel.runtime import CartelRuntime

from .test_options_cartel_prepare import input_data


def regime_inputs(direction):
    """The long fixture, or its price mirror with falling indices for a bearish regime."""
    data = input_data()
    data['history'] = [b.model_copy(update={'high': b.close+3, 'low': b.close-3}) for b in data['history']]
    if direction == 'short':
        data['history'] = [b.model_copy(update={'open': 300-b.open, 'close': 300-b.close, 'high': 300-b.low, 'low': 300-b.high})
                           for b in data['history']]
        for symbol, bars in data['indices'].items():
            data['indices'][symbol] = [b.model_copy(update={'open': 100-i*.01, 'close': 100-i*.01, 'high': 101-i*.01, 'low': 99-i*.01})
                                       for i, b in enumerate(bars)]
    at = data['as_of_ms']+1000
    universe = {'rows': [{'symbol': 'TEST', 'observedAt': at, 'source': 'synthetic publisher fixture',
        'marketCap': 1e9, 'sourceBarOpenAt': session_bounds(data['history'][-1].session.isoformat())[0],
        'industry': 'Semiconductors', 'dailyVolume': 1_000_000}], 'providerTotal': 1, 'received': 1,
        'complete': True, 'excluded': [], 'observedAt': at, 'inputSha256': 'fixture'}

    async def discover(rules, *, clock):
        return universe

    async def industries(*, clock):
        return IndustrySnapshot(source='synthetic publisher fixture', observed_at=at, freshness_basis='publisher_observation',
            expected_count=1, week_definition='fixture 1W', month_definition='fixture 1M',
            rows=[{'industry': 'Semiconductors', 'weekPct': 5 if direction == 'long' else -5, 'monthPct': 5 if direction == 'long' else -5}]), {'synthetic': True}

    async def fetch(symbol, tf, start, end, *, client):
        if tf == '1d':
            rows = data['history'] if symbol == 'TEST' else data['indices'][symbol]
            return [Bar(symbol, tf, session_bounds(b.session.isoformat())[0], b.open, b.high, b.low, b.close, b.volume, source="exchange") for b in rows]
        price = data['history'][-1].close
        return [Bar(symbol, '1m', session_bounds(b.session.isoformat())[0]+i*60_000, price, price+1, price-1, price, 100, source="exchange")
                for b in data['history'][-5:] for i in range(390)]

    async def choose(engine, plan, policy):
        right = 'C' if plan.direction == 'long' else 'P'
        return {'selected': {'symbol': Occ('TEST', plan.first_session+dt.timedelta(days=45), right, round(plan.trigger)).symbol}, 'planningOnly': True}
    return at, {'discover': discover, 'industries': industries, 'fetch': fetch, 'choose': choose}


async def prepared_arm(engine, policy, direction):
    at, providers = regime_inputs(direction)
    runtime = CartelRuntime(engine); runtime.clock = lambda: at
    engine.cartel_observer = runtime
    await engine.settings.set(SETTING, policy.model_dump(mode='json'))
    try:
        result = await run_preparation(engine, policy, clock=lambda: at, **providers)
        assert result['status'] == 'done', result
        assert result['result']['market']['direction'] == direction, result['result']['market']
        assert result['result']['armed'] == 1, result['result']
        row = result['result']['shortlist'][0]
        async with engine.sf() as session:
            armed = await session.get(TechniqueArmed, row['planId'])
            run = await session.get(TechniqueRun, row['planId'])
            assert await session.scalar(select(func.count()).select_from(Order)) == 0
        plan = CartelPlan.model_validate(run.result['plan']['plan'])
        assert plan.direction == direction
        return armed, plan
    finally:
        await runtime.stop()


SHORT_EXPECTED = (15, 'breakout_15m_v1', None, 26)   # timeframe, label, control block, baseline slots


async def test_short_regime_arms_a_15m_plan_under_the_pilot(engine):
    pilot = PreparationPolicy(risk_pct=1, enabled=True, history_limit=10, entry=EntryPolicy(timeframe_minutes=5, allow_gap_retest=True),
                              entry_cadence='breakout_5m_v1')
    armed, plan = await prepared_arm(engine, pilot, 'short')
    assert (plan.entry.timeframe_minutes, plan.cadence_version, armed.config.get('cadence'), len(plan.volume_baseline)) == SHORT_EXPECTED
    assert armed.config['execution']['contract_symbol'][-9] == 'P'   # a put, the plan's vehicle


async def test_short_regime_arms_the_same_15m_plan_under_the_incumbent(engine):
    incumbent = PreparationPolicy(risk_pct=1, enabled=True, history_limit=10)
    armed, plan = await prepared_arm(engine, incumbent, 'short')
    assert (plan.entry.timeframe_minutes, plan.cadence_version, armed.config.get('cadence'), len(plan.volume_baseline)) == SHORT_EXPECTED


async def test_long_regime_arms_a_5m_plan_with_its_matched_control_under_the_pilot(engine):
    pilot = PreparationPolicy(risk_pct=1, enabled=True, history_limit=10, entry=EntryPolicy(timeframe_minutes=5, allow_gap_retest=True),
                              entry_cadence='breakout_5m_v1')
    armed, plan = await prepared_arm(engine, pilot, 'long')
    assert plan.entry.timeframe_minutes == 5 and plan.cadence_version == 'breakout_5m_v1' and len(plan.volume_baseline) == 78
    control = armed.config['cadence']
    assert control['control'] == 'breakout_15m_v1' and control['controlTimeframeMinutes'] == 15 and control['placesOrders'] is False
    assert len(control['controlBaseline']) == 26 and control['controlBaseline']['0'] == 1500.   # 15 minutes x 100 shares, independent of the 5m 500
    assert plan.volume_baseline[0] == 500.
