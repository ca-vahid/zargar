from unittest.mock import AsyncMock

import pytest

from zargar.models import ManagedPositionRow, Portfolio, TechniqueArmed, TechniqueRun
from zargar.techniques.options_cartel.accounts import DEFAULT_BOOK
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.execution_review import review_execution_limits
from zargar.techniques.options_cartel.preparation import run_preparation
from zargar.techniques.options_cartel.preparation_scope import SETTING
from zargar.techniques.options_cartel.runtime import CartelRuntime

from .test_options_cartel_preparation import inputs


@pytest.fixture(autouse=True)
async def isolated_review_runtime(engine, monkeypatch):
    # These tests explicitly drive preparation/review at a historical clock.
    # An inherited listener or scheduler must not run an independent real-time
    # recovery against the same fixture lease while that work is in progress.
    inherited = getattr(engine, 'cartel_observer', None)
    if inherited is not None:
        await inherited.stop()
    await engine.scheduler.stop()
    monkeypatch.setattr(CartelRuntime, 'start', lambda self: None)
    # Market selection is injected below; quote-provider I/O is not under test.
    monkeypatch.setattr(engine.options, 'track', AsyncMock())
    try:
        yield
    finally:
        runtime = getattr(engine, 'cartel_observer', None)
        if runtime is not None:
            await runtime.stop()  # also owns cleanup when legacy_arm itself fails


async def legacy_arm(engine):
    at, providers = inputs()
    portfolio_id = 'cartel-execution-review-fixture'
    async with engine.sf() as session, session.begin():
        session.add(Portfolio(id=portfolio_id, name='Cartel execution review fixture', kind='sim',
                              base_currency='USD', starting_cash=10_000, cash=10_000))
    await engine.positions.load()
    await engine.settings.set(DEFAULT_BOOK, portfolio_id)
    runtime = engine.cartel_observer = CartelRuntime(engine)
    runtime.clock = lambda: at
    policy = PreparationPolicy(enabled=True, portfolio_id=portfolio_id, risk_pct=1, request_interval_seconds=0)
    await engine.settings.set(SETTING, policy.model_dump(mode='json'))
    result = await run_preparation(engine, policy, clock=runtime.clock, **providers)
    run_id = result['result']['shortlist'][0]['planId']
    async with engine.sf() as session, session.begin():
        arm = await session.get(TechniqueArmed, run_id)
        config = {**arm.config, 'execution': {**arm.config['execution'], 'contract_policy': None, 'max_premium': None}}
        arm.config = config
    await runtime._remember(await runtime.repository.load(run_id))
    return runtime, run_id


async def test_review_saves_limits_without_changing_contract_targets_or_exits(engine):
    runtime, run_id = await legacy_arm(engine)
    try:
        before = await runtime.repository.load(run_id)
        async with engine.sf() as session:
            plan = await session.get(TechniqueRun, run_id)
            original_plan = plan.result
        await review_execution_limits(engine, run_id, clock=runtime.clock)
        after = await runtime.repository.load(run_id)
        assert after['config']['execution']['contract_policy']['max_ask'] == 1
        assert after['config']['execution']['contract_symbol'] == before['config']['execution']['contract_symbol']
        assert after['state']['configHistory'][-1]['config'] == before['config']
        assert after['state'].get('attemptTag') is None
        async with engine.sf() as session:
            assert (await session.get(TechniqueRun, run_id)).result == original_plan
    finally:
        await runtime.stop()


async def test_review_cannot_unpause_a_concurrently_paused_arm(engine, monkeypatch):
    runtime, run_id = await legacy_arm(engine)
    arm = runtime.arm

    async def concurrent_pause(*args, **kwargs):
        await runtime.pause(run_id)
        return await arm(*args, **kwargs)

    monkeypatch.setattr(runtime, 'arm', concurrent_pause)
    try:
        with pytest.raises(ValueError, match='paused and edited'):
            await review_execution_limits(engine, run_id, clock=runtime.clock)
        row = await runtime.repository.load(run_id)
        assert row['status'] == 'paused'
        assert row['config']['execution']['contract_policy'] is None
    finally:
        await runtime.stop()


@pytest.mark.parametrize('status,phase', [('paused', 'waiting'), ('armed', 'signalled'), ('closing', 'submitting')])
async def test_review_rejects_used_or_nonwaiting_arms(engine, status, phase):
    runtime, run_id = await legacy_arm(engine)
    try:
        async with engine.sf() as session, session.begin():
            arm = await session.get(TechniqueArmed, run_id)
            arm.status = status
            arm.state = {**arm.state, 'phase': phase}
        with pytest.raises(ValueError, match='unused waiting'):
            await review_execution_limits(engine, run_id, clock=runtime.clock)
    finally:
        await runtime.stop()


@pytest.mark.parametrize('scope', ['owned', 'other_account', 'other_technique', 'closed'])
async def test_review_held_campaign_guard_uses_stored_plan_and_account(engine, scope):
    runtime, run_id = await legacy_arm(engine)
    before = await runtime.repository.load(run_id)
    async with engine.sf() as session, session.begin():
        session.add(ManagedPositionRow(id='held-review-fixture', symbol=before['symbol'],
            portfolio_id='another-account' if scope == 'other_account' else before['portfolioId'],
            technique='tip' if scope == 'other_technique' else 'options_cartel',
            status='closed' if scope == 'closed' else 'open', config={'runId': run_id}))
    if scope == 'owned':
        with pytest.raises(ValueError, match='Held campaigns keep their original'):
            await review_execution_limits(engine, run_id, clock=runtime.clock)
        assert (await runtime.repository.load(run_id))['config'] == before['config']
    else:
        await review_execution_limits(engine, run_id, clock=runtime.clock)
        assert (await runtime.repository.load(run_id))['config']['execution']['contract_policy'] is not None
