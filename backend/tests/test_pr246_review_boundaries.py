"""Independent acceptance probes for PR246; expected behavior, not implementation mirrors."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

from zargar.domain import Bar
from zargar.models import TechniqueArmed
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.cadence import control_config, read_control
from zargar.techniques.options_cartel.contracts import SelectionRequest, select_contract
from zargar.techniques.options_cartel.review_attribution import price_touch, actual_outcome, attribute
from .test_options_cartel_contracts import policy
from .test_options_cartel_entry import OPEN, MIN, plan, tape
from .test_options_cartel_state import repo
from .test_options_cartel_observer import observer


def test_existing_live_5m_policy_is_not_reinterpreted_as_new_experiment():
    saved={'workspace':'live','entry':{'timeframe_minutes':5}}
    parsed=PreparationPolicy.model_validate(saved)
    assert parsed.entry.timeframe_minutes==5


def test_long_only_cadence_pilot_does_not_change_short_execution():
    from zargar.techniques.options_cartel.automatic_plans import automatic_review
    from .test_options_cartel_prepare import input_data
    data={**input_data(),'direction':'short'}
    candidate={'setup':'base','trigger':150.,'invalidation':160.,'targets':[140.,130.],'contextPassed':True}
    configured=PreparationPolicy(entry={'timeframe_minutes':5},entry_cadence='breakout_5m_v1',min_target_distance_pct=0)
    reviewed=automatic_review(data,{'candidates':[candidate]},configured)
    assert reviewed is None or reviewed.entry_policy.timeframe_minutes==15, 'Long-only pilot must not silently produce 5m executable short plans'


async def test_expiration_discovery_consuming_deadline_prevents_further_requests():
    now=[OPEN]
    async def expirations(symbol):
        now[0]=OPEN+2000
        return ['2026-05-29']
    chain=AsyncMock(return_value=[])
    provider=SimpleNamespace(expirations=expirations,chain=chain)
    engine=SimpleNamespace(options=SimpleNamespace(provider=lambda:provider),quotes=SimpleNamespace(get=lambda _:None))
    result=await select_contract(engine,plan(),policy(selection_version='diverse_liquidity_v1'),
        SelectionRequest(deadline_ms=OPEN+1000,clock=lambda:now[0]))
    assert chain.await_count==0, 'No chain request may begin after the signal deadline'
    assert result['searchComplete'] is False


def test_incomplete_bucket_cannot_be_reported_as_completed_close():
    p=plan()
    partial={str(OPEN):[OPEN,48.7,49,48.5,48.9,100,'exchange']}
    result=price_touch(p,{'minutes':partial},p.first_session.isoformat(),OPEN+5*MIN)
    assert result['closedBucketsBeyond']==[], 'Four missing minutes make the 5m close unknown'
    assert result['wickOnly'] is None, 'Neither a confirmed close nor a wick-only conclusion is proved'


async def test_matched_control_keeps_observing_after_executing_signal(repo,monkeypatch):
    instance=await observer(repo,monkeypatch)
    block=control_config('breakout_5m_v1',{'timeframeMinutes':15,'baselines':{i:1000 for i in range(26)}},OPEN-MIN)
    async with repo.engine.sf() as s,s.begin():
        row=await s.get(TechniqueArmed,'r1');row.config={**row.config,'cadence':block}
    bars=[replace(b,source='exchange') for b in tape()]
    bars.extend(Bar('HOOD','1m',OPEN+i*MIN,48.7,48.94,48.6,48.92,500,source='exchange') for i in range(10,15))
    try:
        for b in bars:
            instance.clock=lambda b=b:b.ts+MIN
            await instance.on_minute_bar('HOOD',b)
        expected=read_control(plan(id='r1'),block,bars,OPEN+15*MIN,entry_after=OPEN)
        assert len(expected['signals'])==1
        actual=await repo.load('r1')
        assert len(actual['state']['control']['signals'])==1, 'Executing at 09:40 must not censor the 09:45 control'
    finally:
        await instance.stop()


def test_partial_fill_classification_consumes_the_real_ledger_shape():
    from zargar.techniques.options_cartel.review_ledger import summarize_fills
    order=SimpleNamespace(id='o',symbol='HOOD',sec_type='STK',portfolio_id='pf',side='BUY',qty=3)
    fill=SimpleNamespace(id='f',symbol='HOOD',portfolio_id='pf',side='BUY',qty=2,price=49,
                         commission=0,ts=OPEN+MIN)
    assets,issues=summarize_fills([(fill,order)],OPEN,OPEN+2*MIN,{'o':'r1'})
    assert not issues
    assert actual_outcome({'orderId':'o','requestedQty':3},assets,OPEN+2*MIN)=='partially_filled'


def test_later_refusal_is_not_proved_independent_of_first_entry_refusal():
    trace=[{'at':OPEN+5*MIN,'decision':'watch_only','rule':'M3',
            'reason':'volume below threshold','measurements':{'volumeRatio':1,'requiredVolumeMultiple':1.5}},
           {'at':OPEN+10*MIN,'decision':'invalidated','rule':'M4','reason':'price invalidated the unentered plan'}]
    result=attribute(plan(),{'minutes':{},'decisionHistory':trace},plan().first_session.isoformat(),OPEN+15*MIN)
    later=result['otherIndependentBlockers'][0]
    assert later['remainsIfFirstRemoved'] is not True, 'An earlier entry changes the lifecycle; later entry refusal is not an independent veto'
