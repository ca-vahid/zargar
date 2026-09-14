import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from zargar.models import (
    CartelPreparationAttempt,
    Execution,
    ManagedPositionRow,
    Order,
    Portfolio,
    TechniqueArmed,
)
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.preparation import run_preparation, submit_preparation
from zargar.techniques.options_cartel.preparation_attempts import held_identity, recovery_due
from zargar.techniques.options_cartel.preparation_scope import setting_key
from zargar.techniques.options_cartel.review_ledger import summarize_fills
from zargar.techniques.options_cartel.runtime import CartelRuntime
from zargar.techniques.options_cartel.session_review import report

from .test_options_cartel_preparation_coverage import providers_for

DAY = dt.datetime(2026, 9, 14, tzinfo=dt.UTC)

def pair(identity, side, qty, price, fee, when, symbol='APA261016C00045000'):
    return (SimpleNamespace(id=identity, order_id=identity, side=side, qty=qty, price=price,
        commission=fee, ts=when, symbol=symbol, portfolio_id='book'),
        SimpleNamespace(id=identity, side=side, sec_type='OPT', symbol=symbol, portfolio_id='book'))

def test_carried_partial_lots_allocate_entry_fees_and_ignore_future_fills():
    rows = [pair('buy','BUY',2,3.3,2.08,DAY-dt.timedelta(days=1)),
            pair('sell','SELL',1,2.7095,1.04,DAY+dt.timedelta(hours=17)),
            pair('future','SELL',1,9,1.04,DAY+dt.timedelta(days=1))]
    assets, issues = summarize_fills(rows, DAY, DAY+dt.timedelta(hours=20))
    assert not issues
    assert assets[0]['netRealized'] == pytest.approx(-61.13)
    assert assets[0]['remainingQty'] == 1
    assert assets[0]['openEntryFees'] == pytest.approx(1.04)

def test_same_contract_campaigns_are_not_double_counted():
    rows = [pair('a','BUY',1,3,1,DAY), pair('b','BUY',1,4,1,DAY), pair('c','SELL',1,5,1,DAY)]
    assets, issues = summarize_fills(rows,DAY,DAY,{'a':'plan1','b':'plan2','c':'plan2'})
    assert not issues
    assert {a['planId']:a['remainingQty'] for a in assets} == {'plan1':1,'plan2':0}
    assert sum(a['netRealized'] for a in assets) == 98

@pytest.mark.parametrize('config, expected',[({},'managed:held'),({'runId':[]},'managed:held'),({'runId':'r1'},'r1')])
def test_real_managed_model_identity(config, expected):
    assert held_identity(ManagedPositionRow(id='held',config=config)) == expected

def test_bounded_retry_survives_reload_and_cancellation():
    row = SimpleNamespace(result={'recovery':{'attempt':2,'nextRetryAt':100}})
    assert not recovery_due(row,99)
    assert recovery_due(row,100)
    row.result['recovery']['attempt']=3
    assert not recovery_due(row,9999)
    row.result={'userCancelled':True}
    assert not recovery_due(row,9999)

async def test_closed_apa_report_uses_fills_fees_and_preserves_unknown_evidence(engine):
    async with engine.sf() as session, session.begin():
        session.add(Portfolio(id='book',name='Cartel Test',kind='sim',base_currency='USD',cash=9938.87,starting_cash=10000))
        await session.flush()
        for identity,side,price,hour in [('buy','BUY',3.3,14),('sell','SELL',2.7095,17)]:
            session.add(Order(id=identity,portfolio_id='book',symbol='APA261016C00045000',sec_type='OPT',
                technique='options_cartel',side=side,qty=1,order_type='MKT',status='FILLED',filled_qty=1,
                avg_fill_price=price,created_at=DAY+dt.timedelta(hours=hour)))
        await session.flush()
        for identity,side,price,hour in [('buy','BUY',3.3,14),('sell','SELL',2.7095,17)]:
            session.add(Execution(id=identity,order_id=identity,portfolio_id='book',symbol='APA261016C00045000',
                side=side,qty=1,price=price,commission=1.04,ts=DAY+dt.timedelta(hours=hour)))
        session.add(TechniqueArmed(run_id='plan',symbol='APA',technique='options_cartel',portfolio_id='book',
            plan_for='2026-09-14',status='disarmed',state={'day':'2026-09-14','orderId':'buy','signal':{'at':int(DAY.timestamp()*1000)}}))
        session.add(ManagedPositionRow(id='managed',symbol='APA',technique='options_cartel',portfolio_id='book',
            status='closed',config={'runId':'plan'},legs=[{'symbol':'APA261016C00045000','entryOrderId':'buy'}],
            state={'exits':[{'orderId':'sell','kind':'cartel:stop'}]},created_at=DAY))
    result=await report(engine,'book','2026-09-14')
    assert result['totals']['netRealized'] == pytest.approx(-61.13)
    assert result['closedCampaigns']==1 and result['openInstruments']==0
    assert result['filledOrders']==2 and result['entryOrders']==1 and result['exitOrders']==1
    assert result['rows'][0]['category']=='closed'
    assert result['rows'][0]['exitReasons']==['cartel:stop']
    assert result['missingFillEvidence']==2

async def test_partial_resume_retries_only_baseline_and_records_revision(engine):
    at,providers,calls=providers_for(['TEST'])
    original=providers['fetch']
    sparse=True
    async def fetch(symbol,tf,start,end,**kwargs):
        bars=await original(symbol,tf,start,end,**kwargs)
        return bars[1:2] if sparse and tf=='1m' else bars
    providers['fetch']=fetch
    policy=PreparationPolicy(enabled=True,request_interval_seconds=0,
        portfolio_id=next(p['id'] for p in engine.positions.portfolios() if p['kind']=='sim'))
    await engine.settings.set(setting_key('practice'),policy.model_dump(mode='json'))
    runtime=engine.cartel_observer=CartelRuntime(engine);runtime.clock=lambda:at
    try:
        initial=await run_preparation(engine,policy,clock=lambda:at,**providers)
        assert initial['result']['planErrors']==1
        calls.clear(); sparse=False
        later=at+601000;runtime.clock=lambda:later
        started=await submit_preparation(engine,scheduled=True,clock=lambda:later,**providers)
        assert started['runId'] != initial['runId']
        resumed=await engine._cartel_preparation_task
        assert resumed['result']['planErrors']==0
        assert resumed['result']['resumedAnalyses']==1
        assert ('TEST','1d') not in calls
        assert resumed['result']['recovery']['attempt']==1
        async with engine.sf() as session:
            attempts=(await session.scalars(select(CartelPreparationAttempt))).all()
        assert len(attempts)>=2
    finally:
        await runtime.stop()

def test_morning_gets_a_new_bounded_retry_window_after_overnight_exhaustion():
    from zargar.techniques.options_cartel.preparation_attempts import recovery_window
    morning=int((DAY+dt.timedelta(hours=12,minutes=45)).timestamp()*1000)
    row=SimpleNamespace(config={'session':'2026-09-14'},result={'recovery':{'attempt':3,'window':'2026-09-14:evening','nextRetryAt':morning+1000}})
    assert recovery_due(row,morning)
    row.result['recovery']['window']=recovery_window(morning,'2026-09-14')
    assert not recovery_due(row,morning)
    row.result['userCancelled']=True
    row.result['recovery']['window']='2026-09-14:evening'
    assert not recovery_due(row,morning)

async def test_quote_coverage_survives_worker_reset_and_marks_sampling_gaps(engine):
    from zargar.marketstructure.sessions import session_bounds
    from zargar.models import CartelOptionQuote, TechniqueRun
    from zargar.techniques.options_cartel.quote_coverage import coverage_report
    start=session_bounds('2026-09-14')[0]
    async with engine.sf() as session,session.begin():
        session.add(TechniqueRun(id='coverage-plan',symbol='APA',technique='options_cartel',mode='plan',as_of=start,status='done'))
        await session.flush()
        session.add(TechniqueArmed(run_id='coverage-plan',symbol='APA',technique='options_cartel',portfolio_id='book',plan_for='2026-09-14',status='disarmed'))
        for i,offset in enumerate([0,1000,40000]):
            session.add(CartelOptionQuote(id=f'q{i}',run_id='coverage-plan',contract='APA261016C00045000',source_at=start+offset,
                available_at=start+offset,confirmed_at=start+offset,bid=3,ask=3.1,bid_size=10,ask_size=10,source='opra',feed_mode='hybrid',delayed=False,halted=False))
    result=await coverage_report(engine,'book','2026-09-14')
    assert result['rows'][0]['eligible']==3
    assert result['rows'][0]['gapCount']==1 and result['rows'][0]['maxGapMs']==39000
    assert (await coverage_report(engine,'different','2026-09-14'))['rows']==[]

async def test_attempt_pages_keep_same_timestamp_records_and_account_scope(engine):
    from zargar.models import TechniqueRun
    from zargar.techniques.options_cartel.preparation_attempts import attempt_page
    async with engine.sf() as session,session.begin():
        session.add(TechniqueRun(id='prep-pages',symbol='MULTI',technique='options_cartel',mode='preparation',as_of=100,
            status='done',config={'session':'2026-09-14'}))
        session.add_all([CartelPreparationAttempt(id=f'page-{i:03d}',preparation_id='prep-pages',portfolio_id='book',at=100,
            evidence={'symbol':'TEST','status':'awaiting_contract'}) for i in range(205)])
        session.add(CartelPreparationAttempt(id='foreign',preparation_id='prep-pages',portfolio_id='other',at=100,evidence={}))
    first=await attempt_page(engine,'book','2026-09-14',100)
    second=await attempt_page(engine,'book','2026-09-14',100,first['nextCursor'])
    assert first['total']==205 and len(first['rows'])==200 and len(second['rows'])==5
    assert len({r['id'] for r in first['rows']+second['rows']})==205
    assert second['nextCursor'] is None
