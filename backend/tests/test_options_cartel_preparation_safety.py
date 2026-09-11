import datetime as dt

import pytest

from zargar.marketstructure.sessions import session_bounds
from zargar.options.occ import Occ
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.preparation import activate_pending, arm_with_capacity, run_preparation
from zargar.techniques.options_cartel.preparation_io import PreparationHistory
from zargar.techniques.options_cartel.preparation_scope import SETTING
from zargar.techniques.options_cartel.runtime import CartelRuntime

from .test_options_cartel_preparation import inputs
from .test_options_cartel_preparation_coverage import providers_for


@pytest.mark.parametrize('recovers', [True, False])
async def test_benchmark_retry_reports_actual_completed_session(engine, recovers):
    at, providers = inputs()
    calls = 0

    async def fetch(*args, **kwargs):
        nonlocal calls
        calls += 1
        bars = await providers['fetch'](*args, **kwargs)
        return bars if recovers and calls == 2 else bars[:-1]

    async def report(**kwargs):
        pass

    reader = PreparationHistory(engine, fetch, report, PreparationPolicy(request_interval_seconds=0), lambda: at)
    bars, provenance = await reader.daily('SPY', at, None)
    assert calls == 2
    assert provenance['historyThrough'] == bars[-1].session.isoformat()
    assert provenance['historyFresh'] is recovers
    assert (provenance['historyThrough'] == provenance['historyExpectedThrough']) is recovers


async def test_pending_top_candidate_does_not_hide_executable_reserve(engine):
    at, providers, _ = providers_for(['AAA', 'BBB', 'CCC'])
    checked = []

    async def choose(engine, plan, policy):
        checked.append(plan.symbol)
        selected = None if plan.symbol == 'AAA' else {'symbol': Occ(plan.symbol, plan.first_session+dt.timedelta(days=45), 'C', 150).symbol}
        return {'selected': selected, 'planningOnly': True}

    providers['choose'] = choose
    policy = PreparationPolicy(enabled=True, focus_count=1, request_interval_seconds=0)
    await engine.settings.set(SETTING, policy.model_dump(mode='json'))
    runtime = engine.cartel_observer = CartelRuntime(engine)
    runtime.clock = lambda: at
    try:
        result = (await run_preparation(engine, policy, clock=lambda: at, **providers))['result']
        assert checked == ['AAA', 'BBB']
        assert [r['status'] for r in result['shortlist']] == ['awaiting_contract', 'armed']
        assert result['armed'] == 1
        with pytest.raises(ValueError, match='capacity'):
            await arm_with_capacity(engine, runtime, policy, 'pending-reserve', {'portfolioId': runtime.rows[result['shortlist'][1]['planId']]['portfolioId']})
        # The older pending candidate must not issue provider work or a new arm
        # when the book already has the configured number of campaigns.
        async def forbidden(*args, **kwargs):
            pytest.fail('full-capacity pending activation requested a contract')
        opens, _ = session_bounds(runtime.plans[result['shortlist'][1]['planId']].first_session.isoformat())
        await activate_pending(engine, clock=lambda: opens, choose=forbidden)
        assert sum(r['status'] == 'armed' for r in runtime.rows.values()) == 1
        assert 'capacity' in next(iter(engine._cartel_preparation_activations['practice']['plans'].values()))
        again = (await run_preparation(engine, policy, clock=lambda: at+1, **providers))['result']
        assert len(again['retainedPlans']) == 1
        assert checked == ['AAA', 'BBB']  # Existing capacity is never displaced.
        assert again['armed'] == 0
    finally:
        await runtime.stop()


async def test_failed_refresh_preserves_existing_arm(engine):
    at, providers = inputs()
    policy = PreparationPolicy(enabled=True, risk_pct=1, request_interval_seconds=0)
    await engine.settings.set(SETTING, policy.model_dump(mode='json'))
    runtime = engine.cartel_observer = CartelRuntime(engine)
    runtime.clock = lambda: at
    try:
        first = await run_preparation(engine, policy, clock=lambda: at, **providers)
        plan_id = first['result']['shortlist'][0]['planId']

        async def fail(*args, **kwargs):
            raise OSError('provider unavailable')

        providers['discover'] = fail
        with pytest.raises(OSError):
            await run_preparation(engine, policy, clock=lambda: at+1, **providers)
        assert runtime.rows[plan_id]['status'] == 'armed'
    finally:
        await runtime.stop()


async def test_history_refresh_bypasses_response_cache(monkeypatch):
    import time

    from zargar.marketstructure import history

    key = ('SPY', '1d', 1, 2, 'rth')
    sentinel = object()
    monkeypatch.setattr(history, '_cache', {key: (time.time(), [sentinel])})
    monkeypatch.setattr(history, 'clip_request_window', lambda *args, **kwargs: (0, 0))
    assert await history.fetch_window('SPY', '1d', 60_000, 120_000) == [sentinel]
    assert await history.fetch_window('SPY', '1d', 60_000, 120_000, refresh=True) == []
