from sqlalchemy import select
import httpx
import pytest
import time
from types import SimpleNamespace

from zargar.marketstructure import market_calendar, sessions
from zargar.models import TechniqueArmed
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.preparation import SETTING, run_preparation
from zargar.techniques.options_cartel.runtime import CartelRuntime
from zargar.techniques.options_cartel.preparation_io import PreparationHistory

from .test_options_cartel_preparation import inputs


def test_cached_session_arithmetic_keeps_early_close_and_calendar_changes(monkeypatch):
    day = '2026-11-27'
    opens, closes = sessions.session_bounds(day)
    assert (closes-opens)//60000 == 210
    monkeypatch.setattr(market_calendar, 'session_close_minutes', lambda _: 16*60)
    assert (sessions.session_bounds(day)[1]-opens)//60000 == 390
    assert sessions._session_bounds.cache_info().maxsize == 4096


def test_rate_limit_backoff_slows_only_this_preparation():
    policy = PreparationPolicy(request_interval_seconds=.05)
    reader = PreparationHistory(SimpleNamespace(), lambda: None, None, policy, lambda: 0)
    before = time.monotonic()
    reader.rate_limit_backoff(2)
    assert reader.effective_interval == .25 and reader.cooldown_until >= before+2
    reader.rate_limit_backoff(1)
    assert reader.effective_interval == .5 and reader.rate_limit_retries == 2
    assert policy.request_interval_seconds == .05


@pytest.mark.asyncio
async def test_shared_history_reports_throttle_and_keeps_its_existing_retry(monkeypatch):
    from zargar.marketstructure import history
    attempts, retries = [], []
    monkeypatch.setattr(history, '_ALPACA', {'key': '', 'secret': ''})
    monkeypatch.setattr(history, '_RETRY_PAUSES', (0,))
    monkeypatch.setattr(history, '_parse', lambda *args: [])
    async def provider(request):
        attempts.append(request)
        return httpx.Response(429 if len(attempts)==1 else 200, json={})
    end = int(time.time()*1000)
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        await history.fetch_window_ex('TEST','1d',end-86400000,end,client=client,refresh=True,on_rate_limit=retries.append)
    assert len(attempts) == 2 and retries == [0]


async def test_shortlist_is_armed_before_optional_research_and_failure_preserves_it(engine, monkeypatch):
    at, providers = inputs()
    runtime = CartelRuntime(engine); runtime.clock = lambda: at
    engine.cartel_observer = runtime
    policy = PreparationPolicy(risk_pct=1, enabled=True)
    await engine.settings.set(SETTING, policy.model_dump(mode='json'))
    saw_armed = []
    async def research(engine, prep_id, policy, result, **kwargs):
        assert result['shortlistReadyAt'] == at
        async with engine.sf() as session:
            arms = (await session.scalars(select(TechniqueArmed).where(TechniqueArmed.technique=='options_cartel'))).all()
        saw_armed.extend(a.run_id for a in arms if a.status=='armed')
        assert saw_armed
        raise ValueError('research unavailable')
    monkeypatch.setattr('zargar.techniques.options_cartel.profitability_research.freeze_preparation', research)
    try:
        result = await run_preparation(engine, policy, clock=lambda: at, **providers)
        assert result['result']['armed'] == 1
        assert result['result']['researchStatus'] == 'unavailable'
        assert result['result']['phaseDurationsMs']['research'] >= 0
        assert runtime.rows[saw_armed[0]]['status'] == 'armed'
    finally:
        await runtime.stop()
