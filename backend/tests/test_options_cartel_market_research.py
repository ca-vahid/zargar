from dataclasses import replace

import pytest
from sqlalchemy import func, select

from zargar.models import Order, TechniqueArmed, TechniqueRun
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.preparation import SETTING, activate_pending, run_preparation
from zargar.techniques.options_cartel.runtime import CartelRuntime
from zargar.techniques.options_cartel.service import CartelService

from .test_options_cartel_preparation import inputs


@pytest.mark.parametrize('market_case', ['mixed', 'unknown'])
async def test_blocked_market_saves_research_but_never_plans_contracts_or_arms(engine, monkeypatch, market_case):
    from zargar.techniques.options_cartel import preparation, screen
    at, providers = inputs()
    original_fetch = providers['fetch']
    async def fetch(symbol, tf, start, end, *, client):
        bars = await original_fetch(symbol, tf, start, end, client=client)
        if symbol == 'QQQ' and tf == '1d':
            bars[-1] = replace(bars[-1], close=bars[-1].close-3, low=bars[-1].low-3)
        return bars
    if market_case == 'unknown':
        original_regime = screen.market_regime
        def unknown(*args):
            result = original_regime(*args)
            return {**result, 'direction': 'unknown'}
        monkeypatch.setattr(screen, 'market_regime', unknown)
        monkeypatch.setattr(preparation, 'market_regime', unknown)
    async def forbidden(*args, **kwargs):
        raise AssertionError('Blocked research must never select a contract or arm')
    runtime = engine.cartel_observer = CartelRuntime(engine)
    runtime.clock = lambda: at
    monkeypatch.setattr(runtime, 'arm', forbidden)
    policy = PreparationPolicy(enabled=True, risk_pct=1, request_interval_seconds=0)
    await engine.settings.set(SETTING, policy.model_dump(mode='json'))
    try:
        result = (await run_preparation(engine, policy, clock=lambda: at,
            **{**providers, 'fetch': fetch, 'choose': forbidden}))['result']
        assert result['market']['direction'] == market_case
        assert result['armingBlocked'] and result['coverageComplete']
        assert result['evaluated'] == 1 and result['dataErrors'] == 0 and result['notEvaluated'] == 0
        assert result['researchCandidates'] == 1 and result['qualifying'] == result['armed'] == 0
        candidate = result['shortlist'][0]
        assert candidate['status'] == 'market_blocked' and candidate.get('planId') is None
        async with engine.sf() as session:
            analysis = await session.get(TechniqueRun, candidate['analysisId'])
            assert not analysis.result['screen']['screenPassed']
            assert analysis.result['screen']['researchPassed']
            assert any(c['researchContextPassed'] for c in analysis.result['analysis']['candidates'])
            assert not any(c['contextPassed'] for c in analysis.result['analysis']['candidates'])
            assert await session.scalar(select(func.count()).select_from(TechniqueRun).where(TechniqueRun.mode == 'plan')) == 0
            assert await session.scalar(select(func.count()).select_from(TechniqueArmed)) == 0
            assert await session.scalar(select(func.count()).select_from(Order)) == 0
        # Even if the next activation poll runs during the entry window, this snapshot cannot auto-arm.
        from zargar.marketstructure.sessions import session_bounds
        opens, _ = session_bounds(result['session'])
        await activate_pending(engine, clock=lambda: opens, choose=forbidden)
        from zargar.techniques.options_cartel.automatic_plans import automatic_review
        research = CartelService(engine)._view(analysis, detail=True)
        assert automatic_review(research['config']['inputs'], research['result']['analysis'], policy) is None
        research_review = automatic_review(research['config']['inputs'], research['result']['analysis'], policy, research_only=True)
        with pytest.raises(ValueError, match='context did not pass'):
            await CartelService(engine).prepare(analysis.id, research_review)
    finally:
        await runtime.stop()
