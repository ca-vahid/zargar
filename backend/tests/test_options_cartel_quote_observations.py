import asyncio

import pytest
from sqlalchemy import func, select

from zargar.domain import Quote
from zargar.models import CartelOptionQuote, Order
from zargar.techniques.options_cartel.quote_observations import capture_cached_quote, quote_observations
from zargar.techniques.options_cartel.service import CartelService

CONTRACT = 'HOOD260515C00050000'


async def saved_plan(engine):
    service = CartelService(engine)
    plan = await service._store(mode='plan', symbol='HOOD', at=500, verdict='plan', result={}, config={})
    return service, plan['runId']


@pytest.mark.parametrize('source,source_at', [('opra', 800), ('chain', 0)])
async def test_observation_preserves_source_time_and_idempotent_snapshot_without_orders(engine, source, source_at):
    service, run_id = await saved_plan(engine)
    engine.quotes.on_quote(Quote(CONTRACT, bid=1, ask=1.1, ts=900, source=source, source_ts=source_at))
    first = await capture_cached_quote(service, run_id, CONTRACT, clock=lambda: 1000)
    second = await capture_cached_quote(service, run_id, CONTRACT, clock=lambda: 1000)
    assert first == second and first['placesOrders'] is False
    assert first['source_at'] == (source_at or None)
    assert first['confirmed_at'] == 900 and first['available_at'] == 1000
    assert first['delayed'] == (source == 'chain')
    rows = await quote_observations(service, run_id, CONTRACT)
    assert len(rows['rows']) == 1 and rows['rows'][0]['source_at'] == (source_at or None)
    async with engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(Order)) == 0


async def test_missing_wrong_underlying_or_future_quote_does_not_write(engine):
    service, run_id = await saved_plan(engine)
    with pytest.raises(ValueError, match='cached quote'):
        await capture_cached_quote(service, run_id, CONTRACT, clock=lambda: 1000)
    with pytest.raises(ValueError, match='matching underlying'):
        await capture_cached_quote(service, run_id, 'MU260515C00050000', clock=lambda: 1000)
    engine.quotes.on_quote(Quote(CONTRACT, bid=1, ask=1.1, ts=900, source='opra', source_ts=1100))
    with pytest.raises(ValueError, match='Future-dated'):
        await capture_cached_quote(service, run_id, CONTRACT, clock=lambda: 1000)
    async with engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(CartelOptionQuote)) == 0


async def test_recorder_is_opt_in_bounded_and_cancelled_on_shutdown(engine, monkeypatch):
    from zargar.techniques.options_cartel import quote_observations as module
    service, run_id = await saved_plan(engine)
    entered = asyncio.Event()
    calls = []
    async def held(service, rid, contract, *, clock):
        calls.append((rid, contract)); entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(module, 'capture_cached_quote', held)
    recorder = module.QuoteRecorder(service, clock=lambda: 1000)
    row = {'runId': run_id, 'mode': 'auto', 'status': 'armed',
           'config': {'execution': {'instrument': 'options', 'contract_symbol': CONTRACT}}}
    recorder.observe([row])
    assert recorder.task is None
    await engine.settings.set(module.RECORD_SETTING, True)
    recorder.observe([row, {**row, 'mode': 'alert'}, {**row, 'status': 'disarmed'}])
    await asyncio.wait_for(entered.wait(), 2)
    task = recorder.task
    recorder.observe([row])
    assert recorder.task is task and calls == [(run_id, CONTRACT)]
    await recorder.stop()
    assert task.done() and task.cancelled()
    recorder.observe([row])
    assert recorder.task is task


async def test_recorder_persists_one_sample_per_interval_and_reports_missing_quote(engine):
    from zargar.techniques.options_cartel.quote_observations import RECORD_SETTING, QuoteRecorder
    service, run_id = await saved_plan(engine)
    now = [1000]
    recorder = QuoteRecorder(service, clock=lambda: now[0])
    row = {'runId': run_id, 'mode': 'proposal', 'status': 'paused',
           'config': {'execution': {'instrument': 'options', 'contract_symbol': CONTRACT}}}
    await engine.settings.set(RECORD_SETTING, True)
    recorder.observe([row]); await recorder.task
    assert recorder.status()['captured'] == 0 and run_id in recorder.status()['errors']
    engine.quotes.on_quote(Quote(CONTRACT, bid=1, ask=1.1, ts=900, source='opra', source_ts=800))
    first = recorder.task
    now[0] = 2000; recorder.observe([row])
    assert recorder.task is first
    now[0] = 6000; recorder.observe([row]); await recorder.task
    assert recorder.status()['captured'] == 1 and not recorder.status()['errors']
    assert len((await quote_observations(service, run_id, CONTRACT))['rows']) == 1
    await recorder.stop()
