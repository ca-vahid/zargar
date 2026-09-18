from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from zargar.techniques.options_cartel.entry import read_entry
from zargar.techniques.options_cartel.nonemission import VERSION, RULES_VERSION, SETTING, evidence_hash, effective, minute_set, verify
from .test_options_cartel_entry import OPEN, MIN, plan, tape
from .test_options_cartel_state import repo as repo_fixture

repo = repo_fixture


def proof(minute, *, observed=None):
    p={'version':VERSION,'rulesVersion':RULES_VERSION,'symbol':'HOOD','minute':minute,'observedAt':observed or minute+3*MIN,
       'barsComplete':True,'tradesComplete':True,'barPresent':False,'tradeCount':4,
       'priceEligibleTrades':0,'unknownConditions':0,'suppressedEligibleShares':40,
       'conditionGroups':[{'tape':'C','conditions':['I'],'trades':4,'shares':40}],
       'responseHashes':['a'*64,'b'*64]}
    p['evidenceHash']=evidence_hash(p)
    return p


def test_verified_interval_is_not_a_candle_and_sampled_prices_are_not_used():
    p=plan(entry=plan().entry.model_copy(update={'require_exchange_bars':True}))
    bars=[replace(b,source='exchange') for b in tape()]
    bars[6]=replace(bars[6],source='sampled',high=1000,low=1,volume=999999)
    evidence={str(bars[6].ts):proof(bars[6].ts)}
    before=deepcopy(bars)
    assert read_entry(p,bars,OPEN+10*MIN)['signal'] is None
    result=read_entry(p,bars,OPEN+10*MIN,verified_intervals=evidence)
    assert result['status']=='triggered'
    assert result['signal']['volume']==2000 and result['signal']['stop']==48.4
    assert bars==before  # no synthetic candle and no mutation of observed evidence
    assert read_entry(p,bars[1:],OPEN+10*MIN,verified_intervals=evidence)['signal'] is None


def test_incomplete_unknown_future_and_modified_proofs_do_not_bypass_data_gates():
    base=proof(OPEN)
    for field,value in [('barsComplete',False),('tradesComplete',False),('barPresent',True),
                        ('priceEligibleTrades',1),('unknownConditions',1),('symbol','OTHER'),
                        ('observedAt',OPEN+100*MIN)]:
        bad={**base,field:value};bad['evidenceHash']=evidence_hash(bad)
        assert minute_set({'x':bad},'HOOD',OPEN+10*MIN)==set()
    bad={**base,'tradeCount':999}
    assert minute_set({'x':bad},'HOOD',OPEN+10*MIN)==set()
    bad=deepcopy(base);bad['conditionGroups'][0]['conditions']=['@'];bad['evidenceHash']=evidence_hash(bad)
    assert minute_set({'x':bad},'HOOD',OPEN+10*MIN)==set()


def test_all_suppressed_bucket_has_no_crossing_and_repair_cannot_replay_old_signal():
    bars=[replace(b,source='exchange') for b in tape()]
    proofs={str(OPEN+i*MIN):proof(OPEN+i*MIN) for i in range(5,10)}
    suppressed=bars[:5]+[replace(b,source='sampled') for b in bars[5:]]
    result=read_entry(plan(),suppressed,OPEN+13*MIN,verified_intervals=proofs)
    assert result['signal'] is None
    assert any(t['decision']=='no_price_observations' for t in result['trace'])
    bars[6]=replace(bars[6],source='sampled')
    result=read_entry(plan(),bars,OPEN+13*MIN,entry_after=OPEN+11*MIN,verified_intervals=proofs)
    assert result['signal'] is None


def test_feature_is_off_by_default_and_never_applies_to_live_books():
    row={'portfolioId':'p','state':{'verifiedIntervals':{'x':proof(OPEN)}}}
    for switch,kind,expected in [(False,'sim',False),(True,'live',False),(True,'paper',False),(True,'sim',True)]:
        engine=SimpleNamespace(settings={SETTING:switch},positions=SimpleNamespace(portfolio=lambda _: {'kind':kind}))
        assert bool(effective(engine,row))==expected


@pytest.mark.asyncio
@pytest.mark.parametrize('case',['odd','boundary','eligible','unknown','partial','bar'])
async def test_verifier_requires_complete_same_interval_provider_evidence(monkeypatch,case):
    from zargar.techniques.options_cartel import nonemission
    real_client=httpx.AsyncClient
    async def serve(request):
        if request.url.path.endswith('/bars'):
            bars=[{'t':'2026-05-05T13:30:00Z'}] if case=='bar' else []
            return httpx.Response(200,json={'bars':bars,'symbol':'HOOD','next_page_token':None})
        trade={'t':'2026-05-05T13:30:00.000000001Z','p':10,'s':10,'z':'C','c':['I']}
        if case=='eligible':trade['c']=['@']
        if case=='unknown':trade['c']=['?']
        if case=='boundary':trade['t']='2026-05-05T13:31:00Z'
        return httpx.Response(200,json={'trades':[trade],'symbol':'HOOD','next_page_token':'more' if case=='partial' else None})
    monkeypatch.setattr(nonemission.httpx,'AsyncClient',lambda **kwargs:real_client(transport=httpx.MockTransport(serve),**kwargs))
    config=SimpleNamespace(alpaca_key_id='test',alpaca_secret='test')
    result=await verify(config,'HOOD',[OPEN],lambda:OPEN+10*MIN)
    assert bool(result)==(case == 'odd')
    if result:
        p=result[str(OPEN)]
        assert p['tradeCount']==(0 if case=='boundary' else 1)
        assert minute_set(result,'HOOD',OPEN+10*MIN)=={OPEN}


async def test_gap_verification_advances_cutoff_and_preserves_no_signal(repo,monkeypatch):
    from zargar.techniques.options_cartel.observation_health import repair_gaps, plan_coverage
    from zargar.techniques.options_cartel.data_quality import pack
    from .test_options_cartel_review_quality import make_runtime
    runtime=await make_runtime(repo)
    await repo.engine.positions.load()
    await repo.engine.settings.set(SETTING,True)
    bars=[replace(b,source='exchange') for b in tape()]
    bars[2]=replace(bars[2],source='sampled')
    async with repo.engine.sf() as s,s.begin():
        row=await repo._locked(s,'r1');row.state={**row.state,'minutes':{str(b.ts):pack(b) for b in bars}}
    runtime.rows['r1']=await repo.load('r1')
    runtime.plans['r1']=runtime.plans['r1'].model_copy(update={'entry':plan().entry.model_copy(update={'require_exchange_bars':True})})
    async def load(*args):return []
    async def verified(*args):return {str(OPEN+2*MIN):proof(OPEN+2*MIN)}
    monkeypatch.setattr('zargar.techniques.options_cartel.nonemission.verify',verified)
    await repair_gaps(runtime,load=load)
    state=(await repo.load('r1'))['state']
    assert state['observeAfter']==OPEN+10*MIN and state['signal'] is None
    assert state['minutes'][str(OPEN+2*MIN)][6]=='sampled'
    assert plan_coverage(runtime.plans['r1'],state,OPEN+10*MIN,use_verified=True)['untrustedMinutes']==0
    assert plan_coverage(runtime.plans['r1'],state,OPEN+10*MIN)['untrustedMinutes']==1
    assert read_entry(runtime.plans['r1'],bars,OPEN+10*MIN,entry_after=state['observeAfter'],verified_intervals=state['verifiedIntervals'])['signal'] is None


async def test_controller_uses_proofs_only_when_enabled_and_preserves_real_risk_path(repo,monkeypatch):
    from zargar.models import TechniqueRun
    from zargar.techniques.options_cartel.plans import CartelPlan
    from zargar.techniques.options_cartel.data_quality import pack
    from zargar.techniques.options_cartel.execution import ExecutionInput
    from .test_options_cartel_controller import setup
    controller,_=await setup(repo,monkeypatch)
    bars=[replace(b,source='exchange') for b in tape()]
    bars[6]=replace(bars[6],source='sampled')
    proofs={str(OPEN+6*MIN):proof(OPEN+6*MIN)}
    async with repo.engine.sf() as s,s.begin():
        run=await s.get(TechniqueRun,'r1')
        p=CartelPlan.model_validate(run.result['plan']['plan'])
        p=p.model_copy(update={'entry':p.entry.model_copy(update={'require_exchange_bars':True})})
        run.result={**run.result,'plan':{**run.result['plan'],'plan':p.model_dump(mode='json')}}
        row=await repo._locked(s,'r1')
        row.state={**row.state,'minutes':{str(b.ts):pack(b) for b in bars},'verifiedIntervals':proofs,
                   'signal':read_entry(p,bars,controller.clock(),verified_intervals=proofs)['signal']}
    row=await repo.load('r1');spec=ExecutionInput.model_validate(row['config']['execution'])
    with pytest.raises(ValueError,match='untrusted'):
        controller._entry_conditions(row,p,spec)
    await repo.engine.settings.set(SETTING,True)
    result=await controller.submit('r1')
    assert result.get('orderId') and result['submissionAttempted']
    await repo.engine.position_manager.stop()


async def test_verifier_timeout_keeps_successful_ordinary_repair(repo,monkeypatch):
    from .test_options_cartel_review_quality import make_runtime
    from zargar.techniques.options_cartel.observation_health import repair_gaps
    runtime=await make_runtime(repo)
    await repo.engine.positions.load();await repo.engine.settings.set(SETTING,True)
    async def load(*args):return [replace(tape()[2],source='exchange')]
    async def timeout(*args):raise TimeoutError('provider timeout')
    monkeypatch.setattr('zargar.techniques.options_cartel.nonemission.verify',timeout)
    await repair_gaps(runtime,load=load)
    state=(await repo.load('r1'))['state']
    assert state['minutes'][str(OPEN+2*MIN)][6]=='exchange'
    assert state['observeAfter']==OPEN+10*MIN
    assert not state.get('verifiedIntervals') and 'TimeoutError' in state['gapRepairError']


async def test_uncertifiable_early_intervals_do_not_starve_later_candidates(repo,monkeypatch):
    from .test_options_cartel_review_quality import make_runtime
    from zargar.techniques.options_cartel.observation_health import repair_gaps
    runtime=await make_runtime(repo)
    await repo.engine.positions.load();await repo.engine.settings.set(SETTING,True)
    runtime.clock=lambda:OPEN+40*MIN
    selected=[]
    async def load(*args):return []
    async def no_proof(config,symbol,minutes,clock):selected.append(minutes);return {}
    monkeypatch.setattr('zargar.techniques.options_cartel.nonemission.verify',no_proof)
    await repair_gaps(runtime,load=load)
    runtime.clock=lambda:OPEN+46*MIN
    await repair_gaps(runtime,load=load)
    assert len(selected)==2 and all(len(batch)==8 for batch in selected)
    assert set(selected[0]).isdisjoint(selected[1])
