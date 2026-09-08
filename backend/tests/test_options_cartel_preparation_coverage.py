import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import select

from zargar.marketstructure.history import HistoryError
from zargar.models import Event, TechniqueRun
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.industry import IndustrySnapshot
from zargar.techniques.options_cartel.preparation import evaluation_row, resumable, run_preparation
from zargar.techniques.options_cartel.preparation_io import observed_work
from zargar.techniques.options_cartel.preparation_scope import setting_key
from zargar.techniques.options_cartel.runtime import CartelRuntime

from .test_options_cartel_preparation import inputs


def providers_for(symbols):
    at, providers = inputs()
    original_discover, original_fetch = providers['discover'], providers['fetch']
    calls = []
    async def discover(rules, *, clock):
        result = await original_discover(rules, clock=clock)
        result['rows'] = [{**result['rows'][0], 'symbol': symbol} for symbol in symbols]
        result['received'] = result['providerTotal'] = len(symbols)
        return result
    async def fetch(symbol, tf, start, end, *, client):
        calls.append((symbol, tf))
        bars = await original_fetch(symbol if symbol in ('SPY', 'QQQ') else 'TEST', tf, start, end, client=client)
        return [replace(b, symbol=symbol) for b in bars]
    async def choose(*args):
        return {'selected': None, 'planningOnly': True}
    return at, {**providers, 'discover': discover, 'fetch': fetch, 'choose': choose}, calls


def test_filtered_reason_includes_named_structure_checks():
    row = evaluation_row({'symbol':'TEST', 'runId':'analysis', 'result': {
        'screen': {'gates':[{'label':'Listing', 'status':'pass'}]},
        'analysis': {'checks':[{'name':'Weekly base range', 'status':'fail'}]}}}, None)
    assert row['reasons'] == ['Weekly base range'] and row['status'] == 'filtered'


@pytest.mark.parametrize('all_stocks, expected', [(True, 201), (False, 2)])
async def test_full_coverage_is_independent_of_optional_cap_and_shortlist(engine, all_stocks, expected):
    at, providers, calls = providers_for([f'T{i}' for i in range(201)])
    policy = PreparationPolicy(enabled=True, scan_all=all_stocks, history_limit=2, focus_count=1, request_interval_seconds=0)
    await engine.settings.set(setting_key('practice'), policy.model_dump(mode='json'))
    runtime = engine.cartel_observer = CartelRuntime(engine); runtime.clock = lambda: at
    try:
        result = (await run_preparation(engine, policy, clock=lambda: at, **providers))['result']
        assert result['evaluated'] == result['processed'] == expected
        assert len(result['shortlist']) == 1
        assert result['coverageComplete'] is all_stocks
        assert result['notEvaluated'] == 201-expected
        assert result['phase'] == ('complete' if all_stocks else 'partial')
        assert len([c for c in calls if c[1] == '1d' and c[0] not in ('SPY', 'QQQ')]) == expected
        async with engine.sf() as session:
            events = (await session.scalars(select(Event).where(Event.type.in_(('TechniqueRunStarted', 'TechniqueRunCompleted'))))).all()
            preparation_events = [e for e in events if e.payload.get('mode') == 'preparation']
            assert len(preparation_events) == 2 and all(e.payload['symbol'] == 'MULTI' for e in preparation_events)
    finally:
        await runtime.stop()


async def test_rate_limit_stops_batch_and_resume_reuses_completed_analyses(engine):
    at, providers, calls = providers_for(['TEST', 'ALT'])
    policy = PreparationPolicy(enabled=True, request_interval_seconds=0)
    await engine.settings.set(setting_key('practice'), policy.model_dump(mode='json'))
    runtime = engine.cartel_observer = CartelRuntime(engine); runtime.clock = lambda: at
    fetch = providers['fetch']
    async def limited(symbol, *args, **kwargs):
        if symbol == 'ALT':
            raise HistoryError('HTTP 429 rate limited')
        return await fetch(symbol, *args, **kwargs)
    try:
        with pytest.raises(HistoryError):
            await run_preparation(engine, policy, clock=lambda: at, **{**providers, 'fetch': limited})
        async with engine.sf() as session:
            failed = await session.scalar(select(TechniqueRun).where(TechniqueRun.mode == 'preparation'))
            previous_rows = list(failed.result['rows'])
        calls.clear()
        runtime.clock = lambda: at+1
        resumed = await run_preparation(engine, policy, clock=lambda: at+1, resume_run_id=failed.id, **providers)
        assert resumed['result']['coverageComplete'] and resumed['result']['resumedAnalyses'] == 1
        assert ('TEST', '1d') not in calls and ('ALT', '1d') in calls
        assert resumed['parentRunId'] == failed.id
        async with engine.sf() as session:
            original = await session.get(TechniqueRun, failed.id)
            assert original.status == 'failed' and original.result['rows'] == previous_rows
    finally:
        await runtime.stop()


async def test_completed_history_cache_keeps_original_observation(engine):
    at, providers, calls = providers_for(['TEST'])
    policy = PreparationPolicy(enabled=True, request_interval_seconds=0)
    await engine.settings.set(setting_key('practice'), policy.model_dump(mode='json'))
    runtime = engine.cartel_observer = CartelRuntime(engine); runtime.clock = lambda: at
    try:
        await run_preparation(engine, policy, clock=lambda: at, **providers)
        calls.clear(); runtime.clock = lambda: at+1
        second = await run_preparation(engine, policy, clock=lambda: at+1, **providers)
        assert second['result']['cacheHits'] == 1 and ('TEST', '1d') not in calls
        async with engine.sf() as session:
            row = await session.get(TechniqueRun, second['result']['rows'][0]['analysisId'])
            assert row.result['collection']['historyObservedAt'] == at
            assert row.result['collection']['historyReusedFrom']
    finally:
        await runtime.stop()


async def test_provider_timeout_cancels_and_awaits_owned_request():
    stopped = asyncio.Event()
    async def blocked():
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    async def report(**kwargs):
        pass
    with pytest.raises(TimeoutError):
        await observed_work(blocked(), report, message='fixture', timeout=.01)
    assert stopped.is_set()


async def test_definite_industry_failure_is_counted_without_history_requests(engine):
    at, providers, calls = providers_for(['TEST'])
    async def industries(*, clock):
        return IndustrySnapshot(source='fixture', observed_at=at, freshness_basis='publisher_observation',
            expected_count=12, week_definition='fixture', month_definition='fixture',
            rows=[{'industry': f'Group{i}', 'weekPct': i+1, 'monthPct': i+1} for i in range(11)] +
                 [{'industry':'Semiconductors', 'weekPct':-1, 'monthPct':-1}]), {}
    policy = PreparationPolicy(enabled=True, request_interval_seconds=0)
    await engine.settings.set(setting_key('practice'), policy.model_dump(mode='json'))
    runtime = engine.cartel_observer = CartelRuntime(engine); runtime.clock = lambda: at
    try:
        result = (await run_preparation(engine, policy, clock=lambda: at, **{**providers, 'industries': industries}))['result']
        assert result['coverageComplete'] and result['prefiltered'] == 1
        assert result['processed'] == 1 and result['evaluated'] == 0
        assert ('TEST', '1d') not in calls and result['rows'][0]['status'] == 'prefiltered'
    finally:
        await runtime.stop()


async def test_resume_recovers_child_committed_before_progress_row(engine, monkeypatch):
    from zargar.techniques.options_cartel import preparation
    at, providers, calls = providers_for(['TEST', 'ALT'])
    policy = PreparationPolicy(enabled=True, request_interval_seconds=0)
    await engine.settings.set(setting_key('practice'), policy.model_dump(mode='json'))
    runtime = engine.cartel_observer = CartelRuntime(engine); runtime.clock = lambda: at
    review = preparation.automatic_review
    def interrupt_after_analysis(research, analysis, policy):
        if research['facts']['symbol'] == 'ALT':
            raise RuntimeError('fixture interruption after analysis commit')
        return review(research, analysis, policy)
    monkeypatch.setattr(preparation, 'automatic_review', interrupt_after_analysis)
    try:
        with pytest.raises(RuntimeError, match='fixture interruption'):
            await run_preparation(engine, policy, clock=lambda: at, **providers)
        async with engine.sf() as session:
            failed = await session.scalar(select(TechniqueRun).where(TechniqueRun.mode == 'preparation'))
        assert len(failed.result['rows']) == 1
        monkeypatch.setattr(preparation, 'automatic_review', review)
        calls.clear(); runtime.clock = lambda: at+1
        resumed = await run_preparation(engine, policy, clock=lambda: at+1, resume_run_id=failed.id, **providers)
        assert resumed['result']['resumedAnalyses'] == 2 and resumed['result']['coverageComplete']
        assert not any(tf == '1d' and symbol in ('TEST', 'ALT') for symbol, tf in calls)
    finally:
        await runtime.stop()


async def test_plan_data_failure_is_partial_and_resumable(engine):
    at, providers, _ = providers_for(['TEST'])
    policy = PreparationPolicy(enabled=True, request_interval_seconds=0)
    await engine.settings.set(setting_key('practice'), policy.model_dump(mode='json'))
    runtime = engine.cartel_observer = CartelRuntime(engine); runtime.clock = lambda: at
    fetch = providers['fetch']
    async def missing_minutes(symbol, timeframe, *args, **kwargs):
        if timeframe == '1m':
            raise HistoryError('fixture minute history unavailable')
        return await fetch(symbol, timeframe, *args, **kwargs)
    try:
        result = await run_preparation(engine, policy, clock=lambda: at, **{**providers, 'fetch': missing_minutes})
        assert result['result']['coverageComplete'] and result['result']['phase'] == 'partial'
        assert result['result']['planErrors'] == 1 and result['result']['dataErrors'] == 0
        async with engine.sf() as session:
            record = await session.get(TechniqueRun, result['runId'])
            assert resumable(record, policy, at+1)
    finally:
        await runtime.stop()
