from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from zargar.models import Order, Portfolio, TechniqueArmed, TechniqueRun
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.execution import ExecutionInput
from zargar.techniques.options_cartel.preparation import (
    preparation_portfolio,
    preparation_status,
    run_preparation,
)
from zargar.techniques.options_cartel.preparation_scope import (
    read_policy,
    require_execution_scope,
    setting_key,
)
from zargar.techniques.options_cartel.runtime import CartelRuntime
from zargar.techniques.options_cartel.service import CartelService

from .test_options_cartel_preparation import inputs


def test_live_requires_separate_explicit_acknowledgements():
    with pytest.raises(ValueError, match='acknowledgements'):
        PreparationPolicy(workspace='live', enabled=True)
    engine = SimpleNamespace(settings={setting_key('practice'): {'enabled': True, 'budget': 321}})
    assert read_policy(engine, 'practice').budget == 321
    assert not read_policy(engine, 'live').enabled
    assert not read_policy(engine, 'live').allow_live


async def test_live_and_practice_prepare_independently_without_cross_account_orders(engine, monkeypatch):
    at, providers = inputs()
    runtime = CartelRuntime(engine); runtime.clock = lambda: at
    engine.cartel_observer = runtime
    practice = PreparationPolicy(risk_pct=1, enabled=True)
    await engine.settings.set(setting_key('practice'), practice.model_dump(mode='json'))
    try:
        first = await run_preparation(engine, practice, clock=lambda: at, **providers)
        assert first['result']['armed'] == 1
        # Legacy records have no workspace marker; they must remain Practice-owned.
        async with engine.sf() as session, session.begin():
            saved = await session.get(TechniqueRun, first['runId'])
            saved.config = {k: v for k, v in saved.config.items() if k != 'workspace'}
            saved_plan = await session.get(TechniqueRun, first['result']['shortlist'][0]['planId'])
            saved_plan.config = {**saved_plan.config, 'preparation': {k:v for k,v in saved_plan.config['preparation'].items() if k != 'workspace'}}
        async with engine.sf() as session, session.begin():
            session.add(Portfolio(id='cartel-live', name='Live fixture', kind='live', base_currency='USD', cash=10000))
        await engine.positions.load()
        monkeypatch.setattr(engine, 'executor_for', lambda _: SimpleNamespace(connected=True))
        live = PreparationPolicy(risk_pct=1, enabled=True, workspace='live', portfolio_id='cartel-live',
                                 allow_live=True, overnight_ack=True)
        await engine.settings.set(setting_key('live'), live.model_dump(mode='json'))
        await engine.settings.set('trading.mode', 'live')
        with pytest.raises(ValueError, match='permission'):
            await run_preparation(engine, live, clock=lambda: at, **providers)
        await engine.settings.set('techniques.options_cartel.allow_live_auto', True)
        second = await run_preparation(engine, live, clock=lambda: at, **providers)
        assert second['result']['armed'] == 1, second['result']
        assert second['result']['replacedPlans'] == []
        assert (await preparation_status(engine, 'practice'))['latest']['runId'] == first['runId']
        assert (await preparation_status(engine, 'live'))['latest']['runId'] == second['runId']
        practice_plans = await CartelService(engine).runs(mode='plan', workspace='practice')
        live_plans = await CartelService(engine).runs(mode='plan', workspace='live')
        assert [p['runId'] for p in practice_plans] == [first['result']['shortlist'][0]['planId']]
        assert [p['runId'] for p in live_plans] == [second['result']['shortlist'][0]['planId']]
        async with engine.sf() as session:
            arm = await session.get(TechniqueArmed, second['result']['shortlist'][0]['planId'])
            assert arm.portfolio_id == 'cartel-live' and arm.config['execution']['allow_live']
            assert arm.config['preparation']['workspace'] == 'live'
            assert await session.scalar(select(func.count()).select_from(Order)) == 0
        await engine.settings.set('trading.mode', 'practice')
        runtime.controller.clock = lambda: at
        with pytest.raises(ValueError, match='workspace changed'):
            runtime.controller._entry_conditions(runtime.rows[arm.run_id], runtime.plans[arm.run_id], ExecutionInput.model_validate(arm.config['execution']))
        with pytest.raises(ValueError, match='workspace changed'):
            require_execution_scope(engine, live)
        with pytest.raises(ValueError, match='Practice account'):
            await preparation_portfolio(engine, 'cartel-live', 'practice')
        with pytest.raises(ValueError, match='explicitly'):
            await preparation_portfolio(engine, None, 'live')
    finally:
        await runtime.stop()


async def test_mode_switch_during_collection_prevents_arming(engine):
    at, providers = inputs()
    runtime = CartelRuntime(engine); runtime.clock = lambda: at
    engine.cartel_observer = runtime
    policy = PreparationPolicy(risk_pct=1, enabled=True)
    await engine.settings.set(setting_key('practice'), policy.model_dump(mode='json'))
    choose = providers['choose']
    async def switch_before_arm(*args):
        result = await choose(*args)
        await engine.settings.set('trading.mode', 'live')
        return result
    providers['choose'] = switch_before_arm
    try:
        result = await run_preparation(engine, policy, clock=lambda: at, **providers)
        assert result['result']['armed'] == 0
        assert any('workspace changed' in r.get('reason', '') for r in result['result']['rows'])
        async with engine.sf() as session:
            assert await session.scalar(select(func.count()).select_from(TechniqueArmed)) == 0
    finally:
        await runtime.stop()
