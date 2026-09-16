"""Research denominator, causal observations and non-execution boundaries."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from zargar.db import make_engine
from zargar.domain import Quote
from zargar.models import BarRow, Order, TechniqueArmed, TechniqueRun
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.profitability_research import (
    SETTING, _premium_evidence, _warm_baselines, capture_quotes, collect,
    directional_market, freeze_preparation, identity, status,
    weak_environment,
)
from zargar.techniques.options_cartel.preparation_io import PreparationHistory

from .conftest import make_test_config
from .test_options_cartel_intraday_research import DAY, OPEN, STEP, bars, market


def candidate(index=0):
    return {'id': f'candidate-{index}', 'analysisId': f'analysis-{index}', 'symbol': f'TEST{index}',
        'direction': 'long', 'cohort': 'primary', 'setup': 'base', 'trigger': 101., 'invalidation': 99.,
        'targets': [110.], 'sourceAt': OPEN-3600000, 'ranking': {'structuralTargetR': 10-index*.01,
            'directionalRelativeStrength': 10-index*.01, 'dailyVolume': 1000000-index},
        'leaderEvidence': {'industry': 'fixture', 'directionalRelativeStrength': 10-index*.01,
            'dailyDollarVolume': 100000000-index, 'volumeVsPrior20': 2},
        'rules': {}, 'entryPolicy': {'timeframe_minutes': 15, 'require_exchange_bars': True},
        'exitCampaign': {'profile': 'may_2026', 'source_refs': ['fixture'], 'allocation_note': 'fixture',
            'rungs': [{'id': 'target1', 'kind': 'target', 'fraction': .25, 'target': 110},
                {'id': 'ema8', 'kind': 'ema', 'fraction': .75, 'ema_period': 8}]},
        'daily': [], 'baselineStatus': 'ready', 'baseline': {'baselines': {i: 100 for i in range(26)}},
        'baselineReadyAt': OPEN-60000}


@pytest.fixture
async def research(fresh_db):
    db = make_engine(make_test_config().database_url)
    sf = async_sessionmaker(db, expire_on_commit=False)
    policy = PreparationPolicy(enabled=True, portfolio_id='research-book')
    settings = {'techniques.options_cartel.preparation': policy.model_dump(mode='json'),
        SETTING: True, SETTING+'.candidate_cap': 50, SETTING+'.bearish_enabled': False, 'trading.mode': 'practice'}
    engine = SimpleNamespace(sf=sf, settings=settings, feed=SimpleNamespace(watch=AsyncMock()),
        config=SimpleNamespace(quote_source='sim'), options=None)
    prep = TechniqueRun(id='profit-prep', technique='options_cartel', symbol='MULTI', mode='preparation',
        status='done', as_of=OPEN-3600000, config={'workspace': 'practice', 'portfolioId': 'research-book',
            'session': DAY, 'policy': policy.model_dump(mode='json')}, result={})
    async with sf() as session, session.begin():
        session.add(prep)
    rig = SimpleNamespace(db=db, sf=sf, engine=engine, policy=policy, prep=prep)
    try:
        yield rig
    finally:
        await db.dispose()


async def seed_context(rig, rows=None):
    rows = rows or [candidate()]
    context = TechniqueRun(id=identity(rig.prep.id, 'context'), technique='options_cartel', symbol='MULTI',
        mode='profit_context', status='done', parent_run_id=rig.prep.id, as_of=OPEN-60000,
        config={'workspace': 'practice', 'portfolioId': 'research-book', 'session': DAY,
            'policy': rig.policy.model_dump(mode='json')}, result={'phase': 'collecting', 'frozenAt': OPEN-60000,
            'candidates': rows, 'market': market(), 'rankings': {}, 'protocol': {'version': 'fixture'},
            'denominator': {'discovered': len(rows), 'evaluated': len(rows), 'eligible': len(rows),
                'boundedLimit': 50, 'omitted': 0, 'primaryEligible': len(rows), 'bearishEligible': 0}})
    async with rig.sf() as session, session.begin():
        session.add(context)
    return context


def test_bearish_alignment_is_strict_sustained_and_cannot_use_stale_bars():
    first_at = OPEN+STEP
    first = directional_market(market(), bars('SPY', first_at, 97)+bars('QQQ', first_at, 97),
        first_at, first_at+60000, 'short')
    assert first['aligned'] and not first['sustained']
    second_at = first_at+STEP
    second = directional_market(market(), bars('SPY', second_at, 97)+bars('QQQ', second_at, 97),
        second_at, second_at+60000, 'short', first)
    assert second['sustained'] and second['improvedSince']==second_at+60000
    mixed = directional_market(market(), bars('SPY', second_at, 99)+bars('QQQ', second_at, 97),
        second_at, second_at+60000, 'short', first)
    assert not mixed['aligned']
    late = directional_market(market(), bars('SPY', second_at, 97)+bars('QQQ', second_at, 97),
        second_at, second_at+120001, 'short', first)
    assert late['status']=='unavailable' and not late['sustained']


def test_weak_environment_keeps_moderate_mixed_distinct_from_unknown():
    saved = market()
    saved['indices']['SPY']['direction'] = 'long'
    saved['indices']['QQQ']['direction'] = 'mixed'
    assert weak_environment(saved, 'long') is True
    saved['indices']['QQQ']['direction'] = 'long'
    assert weak_environment(saved, 'long') is False
    saved['indices']['QQQ']['emas'] = {}
    assert weak_environment(saved, 'long') is None


async def test_freezes_all_nine_when_both_rankings_have_identical_top_five(research, monkeypatch):
    rig = research
    async with rig.sf() as session, session.begin():
        for i in range(9):
            session.add(TechniqueRun(id=f'analysis-{i}', technique='options_cartel', symbol=f'TEST{i}', mode='analysis',
                status='done', as_of=rig.prep.as_of, config={'inputs': {'direction': 'long'}}, result={}))
    monkeypatch.setattr('zargar.techniques.options_cartel.profitability_research.candidate_from_analysis',
        lambda saved, policy, cohort, short=False: candidate(int(saved['runId'].split('-')[-1])))
    result = {'rows': [{'analysisId': f'analysis-{i}'} for i in range(9)], 'market': market(),
        'discovered': 100, 'evaluated': 99, 'leaderContext': {'groups': []}}
    frozen = await freeze_preparation(rig.engine, rig.prep.id, rig.policy, result, clock=lambda: OPEN-60000)
    assert frozen['eligible']==9 and frozen['observedLimit']==9
    async with rig.sf() as session:
        context = await session.get(TechniqueRun, frozen['contextId'])
        assert len(context.result['candidates'])==9
        assert len(context.result['rankings']['primary']['baselineIds'])==5
        assert await session.scalar(select(func.count()).select_from(TechniqueArmed))==0
        assert await session.scalar(select(func.count()).select_from(Order))==0
        assert await session.scalar(select(func.count()).select_from(TechniqueRun).where(TechniqueRun.mode=='plan'))==0


async def test_no_context_is_adopted_retroactively_after_open(research):
    result = await freeze_preparation(research.engine, research.prep.id, research.policy,
        {'rows': []}, clock=lambda: OPEN+60000)
    assert result['status']=='pre_session_required'
    async with research.sf() as session:
        assert await session.get(TechniqueRun, identity(research.prep.id, 'context')) is None


async def test_baseline_progress_survives_later_failure_and_retries_only_unready(research, monkeypatch):
    rows = [candidate(i) for i in range(3)]
    for row in rows:
        row.update(baselineStatus='pending', baselineAttempts=0, nextBaselineAt=0)
    context = await seed_context(research, rows)
    now = [OPEN-60000]
    runtime = SimpleNamespace(engine=research.engine, clock=lambda: now[0], stopping=False)
    calls = []

    async def baseline(self, symbol, at, client):
        calls.append(symbol)
        if symbol=='TEST1':
            raise OSError('fixture unavailable')
        return []

    monkeypatch.setattr(PreparationHistory, 'baseline', baseline)
    monkeypatch.setattr('zargar.techniques.options_cartel.profitability_research.build_volume_baseline',
        lambda *a, **kw: {'baselines': {i: 100 for i in range(26)}})
    async def provider(*args, **kwargs):
        return []
    context = await _warm_baselines(runtime, context, research.policy, fetch=provider)
    assert [c['baselineStatus'] for c in context.result['candidates']]==['ready','data_unavailable','pending']
    context = await _warm_baselines(runtime, context, research.policy, fetch=provider)
    assert calls==['TEST0','TEST1','TEST2']
    now[0] += 300001
    context = await _warm_baselines(runtime, context, research.policy, fetch=provider)
    assert calls==['TEST0','TEST1','TEST2','TEST1']


async def test_signal_observation_and_funding_do_not_backdate_a_modeled_entry(research):
    context = await seed_context(research)
    now = [OPEN+STEP+60000]
    runtime = SimpleNamespace(engine=research.engine, clock=lambda: now[0], stopping=False,
        _profitability_started=None, _intraday_research_watched=set())
    quotes = []

    async def observe(engine, plan, policy, clock):
        quotes.append(clock())
        return {'status': 'awaiting_contract', 'observedAt': clock(), 'selected': None,
            'funding': {'quantity': None}, 'affordabilityOnly': False}

    for bucket in range(1, 6):
        boundary = OPEN+bucket*STEP; now[0] = boundary+60000
        async with research.sf() as session, session.begin():
            for bar in bars('SPY', boundary)+bars('QQQ', boundary)+bars('TEST0', boundary, 101.2 if bucket>=4 else 100):
                session.add(BarRow(symbol=bar.symbol, tf=bar.tf, ts=bar.ts, open=bar.open, high=bar.high,
                    low=bar.low, close=bar.close, volume=bar.volume, source=bar.source))
        await collect(runtime, quote_observer=observe)
    await collect(runtime, quote_observer=observe)
    async with research.sf() as session:
        saved = await session.get(TechniqueRun, context.id)
        assert saved.result['candidates'][0]['researchEntry']['at']==OPEN+4*STEP
        assert saved.result['candidates'][0]['entryObservedAt']==OPEN+4*STEP+60000
        latest = await session.get(TechniqueRun, saved.result['latestObservationId'])
        entry = latest.result['candidates'][0]['experiments']['entry']
        assert entry['at'] >= OPEN+4*STEP+60000
        assert latest.result['candidates'][0]['experiments']['status']=='quantity_unknown'
        assert len(quotes)==1
        assert await session.scalar(select(func.count()).select_from(Order))==0
        assert await session.scalar(select(func.count()).select_from(TechniqueArmed))==0
    # Viewing Live does not confer permission and does not stop this Practice experiment.
    research.engine.settings['trading.mode']='live'
    assert (await status(research.engine, DAY, 'research-book'))['researchOnly'] is True
    assert (await status(research.engine, DAY, None))['candidates']==[]


async def test_slow_candidate_evaluation_cannot_backdate_confirmation(research, monkeypatch):
    from zargar.techniques.options_cartel import research_economics
    context = await seed_context(research)
    now = [OPEN+STEP+60000]
    runtime = SimpleNamespace(engine=research.engine, clock=lambda: now[0], stopping=False,
        _profitability_started=None, _intraday_research_watched=set())
    original = research_economics.compare_entry_variants

    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        if result['baseline'].get('signal'):
            now[0] += 61000  # source was timely when queried, but decision completed too late
        return result

    monkeypatch.setattr(research_economics, 'compare_entry_variants', delayed)
    observe = AsyncMock()
    for bucket in range(1, 5):
        boundary = OPEN+bucket*STEP; now[0] = boundary+60000
        async with research.sf() as session, session.begin():
            for bar in bars('SPY', boundary)+bars('QQQ', boundary)+bars('TEST0', boundary, 101.2 if bucket==4 else 100):
                session.add(BarRow(symbol=bar.symbol, tf=bar.tf, ts=bar.ts, open=bar.open, high=bar.high,
                    low=bar.low, close=bar.close, volume=bar.volume, source=bar.source))
        await collect(runtime, quote_observer=observe)
    async with research.sf() as session:
        saved = await session.get(TechniqueRun, context.id)
        assert saved.result['candidates'][0].get('researchEntry') is None
        last = await session.get(TechniqueRun, saved.result['latestObservationId'])
        row = last.result['candidates'][0]
        assert row['status']=='stale_confirmation'
        assert row['observedAt']==OPEN+4*STEP+121000
    observe.assert_not_awaited()


async def test_new_quote_gap_blocks_reuse_of_an_older_favorable_quote(research):
    row = candidate()
    contract = 'TEST0261016C00100000'
    at = OPEN+60000
    good = {'contract': contract, 'observedAt': at, 'sourceAt': at, 'status': 'observed',
        'bid': 2., 'ask': 2.1, 'delayed': False, 'halted': False}
    row['optionObservation'] = {'selected': {'symbol': contract}, 'timely': True,
        'quote': good, 'funding': {'optionFeePerContractUsd': 1.04}}
    context = await seed_context(research, [row])
    now = [at]
    cached = [Quote(contract, bid=2, ask=2.1, bid_size=10, ask_size=10, source='opra', source_ts=at, ts=at)]
    research.engine.quotes = SimpleNamespace(get=lambda _: cached[0])
    runtime = SimpleNamespace(engine=research.engine, clock=lambda: now[0], stopping=False,
        _profitability_targets={'one': {'contextId': context.id, 'candidateId': row['id'],
            'contract': contract, 'preparationId': research.prep.id, 'day': DAY}})
    await capture_quotes(runtime)
    now[0] += 11000  # quote crossed research freshness bound but is still within replay's 15 seconds
    await capture_quotes(runtime)
    body = await _premium_evidence(research.engine, context, row, now[0])
    assert len(body['quotes'])==2
    latest = max(body['quotes'], key=lambda q: q['available_at'])
    assert latest['source_at'] is None and latest['delayed'] is True and latest['bid']==0
    await capture_quotes(runtime)
    async with research.sf() as session:
        assert await session.scalar(select(func.count()).select_from(TechniqueRun).where(TechniqueRun.mode=='profit_quote'))==2


async def test_baseline_queue_first_attempts_precede_retries_across_reload(research, monkeypatch):
    rows = [candidate(i) for i in range(7)]
    now = [OPEN-60000]
    for i, row in enumerate(rows):
        row.update(baselineStatus='pending', baselineAttempts=0, nextBaselineAt=0)
    rows[0].update(baselineStatus='data_unavailable', baselineAttempts=19)
    rows[1].update(baselineStatus='data_unavailable', baselineAttempts=18)
    rows[2].update(baselineStatus='ready')
    rows[6].update(nextBaselineAt=now[0]+3600000)
    context = await seed_context(research, rows)
    runtime = SimpleNamespace(engine=research.engine, clock=lambda: now[0], stopping=False)
    calls = []

    async def baseline(self, symbol, at, client):
        calls.append(symbol)
        raise OSError('persistent provider gap')

    async def provider(*args, **kwargs):
        return []

    monkeypatch.setattr(PreparationHistory, 'baseline', baseline)
    await _warm_baselines(runtime, context, research.policy, fetch=provider)
    assert calls == ['TEST3', 'TEST4']  # fixed per-pass budget, not the first ranked failures
    async with research.sf() as session:
        context = await session.get(TechniqueRun, context.id)
    context = await _warm_baselines(runtime, context, research.policy, fetch=provider)
    assert calls == ['TEST3', 'TEST4', 'TEST5', 'TEST1']
    now[0] += 300001
    context = await _warm_baselines(runtime, context, research.policy, fetch=provider)
    assert calls[-2:] == ['TEST3', 'TEST4']  # least-attempted due retries get their turn
    assert [c['id'] for c in context.result['candidates']] == [r['id'] for r in rows]
    assert context.result['candidates'][0]['baselineAttempts'] == 19
    assert 'TEST2' not in calls and 'TEST6' not in calls  # ready and cooldown stay untouched


async def test_baseline_retry_ties_use_oldest_due_time(research, monkeypatch):
    rows = [candidate(i) for i in range(3)]
    now = OPEN-60000
    for i, row in enumerate(rows):
        row.update(baselineStatus='data_unavailable', baselineAttempts=2,
                   nextBaselineAt=now-(i+1)*60000)
    context = await seed_context(research, rows)
    runtime = SimpleNamespace(engine=research.engine, clock=lambda: now, stopping=False)
    calls = []

    async def baseline(self, symbol, at, client):
        calls.append(symbol)
        raise OSError('provider gap')

    async def provider(*args, **kwargs):
        return []

    monkeypatch.setattr(PreparationHistory, 'baseline', baseline)
    await _warm_baselines(runtime, context, research.policy, fetch=provider)
    assert calls == ['TEST2', 'TEST1']
