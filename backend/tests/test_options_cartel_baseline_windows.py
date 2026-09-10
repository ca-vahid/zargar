from dataclasses import replace
from types import SimpleNamespace

import pytest

from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.entry import read_entry
from zargar.techniques.options_cartel.plans import EntryPolicy
from zargar.techniques.options_cartel.preparation_readiness import baseline_coverage, entry_readiness
from zargar.techniques.options_cartel.prepare import build_volume_baseline

from .test_options_cartel_entry import MIN, OPEN, plan, tape
from .test_options_cartel_prepare import input_data


def test_missing_minutes_are_not_zero_filled_and_five_samples_still_required():
    data = input_data()
    minutes=[]
    for day in data['history'][-5:]:
        opens,_=session_bounds(day.session.isoformat())
        minutes += [Bar('TEST','1m',opens+i*MIN,100,101,99,100,100) for i in range(30) if i != 3]
    result=build_volume_baseline(minutes,'TEST',15,data['as_of_ms'])
    assert 0 not in result['baselines'] and result['baselines'][1] == 1500
    assert result['sampleCounts'][1] == result['minSamples'] == 5
    assert all(r['present'] == 29 for r in result['minuteCoverage'].values())
    result=build_volume_baseline(minutes[:-29],'TEST',15,data['as_of_ms'])
    assert not result['baselines']


def test_partial_baselines_enable_only_supported_windows_and_legacy_stays_strict():
    p=plan(volume_baseline={1:1000.},entry=EntryPolicy(timeframe_minutes=5,baseline_policy='covered_periods'))
    coverage=baseline_coverage(p)
    assert coverage['ready'] and coverage['limited'] and coverage['usableEntryPeriods'] == [1]
    assert coverage['entryWindows'] == [{'slot':1,'startET':'09:35','confirmationET':'09:40'}]
    assert read_entry(p,tape(),OPEN+10*MIN)['signal']
    unsupported=p.model_copy(update={'volume_baseline':{0:1000.}})
    result=read_entry(unsupported,tape(),OPEN+10*MIN)
    assert result['signal'] is None
    assert any(r['decision']=='unsupported_volume_period' for r in result['trace'])
    strict=p.model_copy(update={'entry':EntryPolicy(timeframe_minutes=5)})
    assert not baseline_coverage(strict)['ready']


def test_a_crossing_in_an_unsupported_period_cannot_be_replayed_in_a_supported_one():
    p=plan(volume_baseline={1:1000.},entry=EntryPolicy(timeframe_minutes=5,baseline_policy='covered_periods'))
    bars=[replace(b,open=48.7,high=49.,close=48.92) for b in tape()]
    assert read_entry(p,bars,OPEN+10*MIN)['signal'] is None


def test_closing_period_alone_does_not_make_a_plan_ready():
    p=plan(volume_baseline={77:1000.},entry=EntryPolicy(timeframe_minutes=5,baseline_policy='covered_periods'))
    assert not baseline_coverage(p)['ready']
    assert not entry_readiness(p,[],OPEN-MIN)['ready']
    p=p.model_copy(update={'volume_baseline':{1:1000.}})
    result=entry_readiness(p,tape(),OPEN+10*MIN)
    assert not result['ready'] and any('No supported confirmation period remains' in r for r in result['reasons'])


def test_new_practice_defaults_to_covered_periods_but_live_and_legacy_do_not():
    assert PreparationPolicy().baseline_readiness == 'covered_periods'
    assert PreparationPolicy(workspace='live').baseline_readiness == 'full_session'
    assert EntryPolicy.model_validate({}).baseline_policy == 'full_session'


def test_controller_rejects_an_unsupported_period_even_if_a_signal_is_supplied():
    from zargar.techniques.options_cartel.controller import CartelEntryController
    from zargar.techniques.options_cartel.execution import ExecutionInput
    p=plan(entry=EntryPolicy(timeframe_minutes=5,baseline_policy='covered_periods'))
    signal=read_entry(p,tape(),OPEN+10*MIN)['signal']
    p=p.model_copy(update={'volume_baseline':{0:1000.}})
    controller=CartelEntryController(SimpleNamespace(positions=SimpleNamespace(portfolio=lambda _:None)))
    controller.clock=lambda:OPEN+10*MIN
    row={'config':{},'mode':'auto','portfolioId':'pf','status':'armed','state':{
        'phase':'signalled','signal':signal,'opensAt':OPEN,'expiresAt':OPEN+390*MIN}}
    with pytest.raises(ValueError,match='supported volume-baseline periods'):
        controller._entry_conditions(row,p,ExecutionInput(portfolio_id='pf',mode='auto',instrument='shares',budget=500))


async def test_new_preparation_can_arm_a_partial_baseline_without_reducing_samples(engine):
    from zargar.marketstructure.sessions import session_date
    from zargar.techniques.options_cartel.preparation import SETTING, run_preparation
    from zargar.techniques.options_cartel.runtime import CartelRuntime

    from .test_options_cartel_preparation import inputs
    at,providers=inputs()
    original=providers['fetch']
    async def fetch(symbol,tf,start,end,*,client):
        bars=await original(symbol,tf,start,end,client=client)
        if tf=='1m':
            bars=[b for b in bars if b.ts-session_bounds(session_date(b.ts))[0] < 15*MIN]
        return bars
    policy=PreparationPolicy(enabled=True,risk_pct=1,request_interval_seconds=0)
    await engine.settings.set(SETTING,policy.model_dump(mode='json'))
    runtime=engine.cartel_observer=CartelRuntime(engine);runtime.clock=lambda:at
    try:
        result=(await run_preparation(engine,policy,clock=lambda:at,**{**providers,'fetch':fetch}))['result']
        assert result['armed']==1,result
        coverage=result['shortlist'][0]['volumeCoverage']
        assert coverage['available']==1 and coverage['expected']==26
        assert coverage['minSamples']==5 and coverage['historicalSessions']==5
        assert coverage['policy']=='covered_periods' and coverage['limited']
    finally:
        await runtime.stop()
