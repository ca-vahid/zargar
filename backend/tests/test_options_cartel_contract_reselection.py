from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from zargar.models import Order
from zargar.techniques.options_cartel.contract_reselection import reselect_for_spread
from zargar.techniques.options_cartel.contracts import ContractSelectionInput
from zargar.techniques.options_cartel.execution import ExecutionInput
from tests import test_options_cartel_state as state_tests
from tests.test_options_cartel_entry import OPEN, plan

repo = state_tests.repo
OLD='HOOD260619C00050000'
NEW='HOOD260619C00049000'


async def rig(repo):
    await repo.engine.positions.load()
    now=[OPEN+301000]
    policy=ContractSelectionInput(dte_min=21,dte_max=90,target_dte=45,target_abs_delta=.5,max_ask=5,max_spread_pct=20,min_open_interest=100)
    spec=ExecutionInput(portfolio_id='pf',mode='auto',instrument='options',contract_symbol=OLD,
        budget=500,risk_pct=10,max_premium=5,contract_policy=policy)
    await repo.arm('r1','pf','auto',{'execution':spec.model_dump(),'preparation':{'workspace':'practice'}},now_ms=OPEN)
    await repo.consume_signal('r1',state_tests.signal(),now_ms=now[0])
    def guard(row,p,s):
        if row['status']!='armed' or row['state']['phase']!='signalled':raise ValueError('inactive')
        if now[0]-row['state']['signal']['at']>120000:raise ValueError('stale')
        if ExecutionInput.model_validate(row['config']['execution'])!=s:raise ValueError('changed policy')
        return p
    controller=SimpleNamespace(engine=repo.engine,repository=repo,clock=lambda:now[0],_entry_conditions=guard)
    row=await repo.load('r1')
    report={'passed':False,'checks':[{'name':'entry_contract_spread','passed':False}], 'risk':{'passed':True}}
    def result(ask=2):
        return {'selected':{'symbol':NEW,'bid':ask*.95,'ask':ask,'delta':.5,'openInterest':1000,
            'quoteAsOf':now[0],'deltaAsOf':now[0],'quoteSource':'opra'}}
    return controller,row,plan(id='r1'),spec,report,now,result


async def test_reselection_preserves_limits_is_durable_and_once_per_signal(repo):
    c,row,p,s,report,now,result=await rig(repo)
    choose=AsyncMock(return_value=result())
    new_row,new_spec=await reselect_for_spread(c,'r1',row,p,s,report,choose=choose)
    assert new_spec.contract_symbol==NEW
    assert new_spec.model_dump(exclude={'contract_symbol'})==s.model_dump(exclude={'contract_symbol'})
    assert new_row['state']['contractReselection']['status']=='selected'
    assert await reselect_for_spread(c,'r1',new_row,p,new_spec,report,choose=choose) is None
    choose.assert_awaited_once()
    async with repo.engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(Order))==0


@pytest.mark.parametrize('change',['pause','stale','policy'])
async def test_reselection_rechecks_authority_after_provider_io(repo,change):
    c,row,p,s,report,now,result=await rig(repo)
    async def choose(*args):
        if change=='pause':await repo.set_status('r1','paused')
        elif change=='stale':now[0]+=120001
        else:
            async with repo.engine.sf() as session,session.begin():
                locked=await repo._locked(session,'r1')
                locked.config={**locked.config,'execution':s.model_copy(update={'budget':200}).model_dump()}
        return result()
    with pytest.raises(ValueError):
        await reselect_for_spread(c,'r1',row,p,s,report,choose=choose)
    assert (await repo.load('r1'))['config']['execution']['contract_symbol']==OLD


@pytest.mark.parametrize('failure',['other_gate','proposal','live','disabled'])
async def test_reselection_does_not_expand_scope(repo,failure):
    c,row,p,s,report,now,result=await rig(repo)
    if failure=='other_gate':report['checks'].append({'name':'cash_available','passed':False})
    elif failure=='proposal':row={**row,'mode':'proposal'}
    elif failure=='live':row['config']['preparation']['workspace']='live'
    else:await repo.engine.settings.set('techniques.options_cartel.reselect_wide_contract',False)
    choose=AsyncMock(return_value=result())
    assert await reselect_for_spread(c,'r1',row,p,s,report,choose=choose) is None
    choose.assert_not_awaited()


async def test_reselection_does_not_accept_a_contract_above_saved_cap(repo):
    c,row,p,s,report,now,result=await rig(repo)
    choose=AsyncMock(return_value=result(ask=6))
    assert await reselect_for_spread(c,'r1',row,p,s,report,choose=choose) is None
    saved=await repo.load('r1')
    assert saved['config']['execution']['contract_symbol']==OLD
    assert saved['state']['contractReselection']['status']=='unavailable'


async def test_search_timeout_is_spent_once_and_keeps_original_contract(repo):
    c,row,p,s,report,now,result=await rig(repo)
    choose=AsyncMock(side_effect=TimeoutError('provider timeout'))
    assert await reselect_for_spread(c,'r1',row,p,s,report,choose=choose) is None
    current=await repo.load('r1')
    assert current['config']['execution']['contract_symbol']==OLD
    assert await reselect_for_spread(c,'r1',current,p,s,report,choose=choose) is None
    choose.assert_awaited_once()


# ---- 2026-09-21 brief F2: the saved contract gets first refresh consideration inside the signal deadline ----

async def test_reselection_passes_the_saved_contract_deadline_and_cash_basis_to_the_search(repo):
    from zargar.techniques.options_cartel.contracts import SelectionRequest
    c,row,p,s,report,now,result=await rig(repo)
    seen={}
    async def choose(engine,plan,policy,request):
        seen['request']=request
        return result()
    new_row,new_spec=await reselect_for_spread(c,'r1',row,p,s,report,choose=choose)
    request=seen['request']
    assert isinstance(request,SelectionRequest)
    assert request.preferred_contract==OLD and request.plan_id=='r1' and request.portfolio_id=='pf'
    assert request.deadline_ms==row['state']['signal']['at']+120000 and request.clock is c.clock
    assert request.economics is not None and request.economics.max_units==s.max_units
    assert request.economics.cash_cap_usd==pytest.approx(min(s.budget,10000*s.risk_pct/100)) or request.economics.cash_cap_usd<=s.budget
    claim=new_row['state']['contractReselection']
    assert claim['selectionVersion']=='legacy' and claim['rankingVersion']=='legacy'


async def test_reselection_snapshots_the_saved_selection_version(repo):
    c,row,p,s,report,now,result=await rig(repo)
    versioned=s.model_copy(update={'contract_policy':s.contract_policy.model_copy(update={'selection_version':'diverse_liquidity_v1','ranking_version':'executable_cost_v1'})})
    async with repo.engine.sf() as session,session.begin():
        locked=await repo._locked(session,'r1')
        locked.config={**locked.config,'execution':versioned.model_dump()}
    row=await repo.load('r1')
    seen={}
    async def choose(engine,plan,policy,request):
        seen['policy']=policy
        return result()
    new_row,new_spec=await reselect_for_spread(c,'r1',row,p,versioned,report,choose=choose)
    assert seen['policy'].selection_version=='diverse_liquidity_v1' and seen['policy'].ranking_version=='executable_cost_v1'
    assert new_row['state']['contractReselection']['selectionVersion']=='diverse_liquidity_v1'
    assert new_spec.contract_policy.selection_version=='diverse_liquidity_v1'
