from types import SimpleNamespace
from unittest.mock import AsyncMock

from zargar.techniques.options_cartel.method_lab_observer import collect,pending_quotes
from zargar.techniques.options_cartel.method_lab_review import report
from . import test_options_cartel_profitability_research as prior
from .test_cartel_method_lab_observer import prepared

research=prior.research


async def test_future_trial_has_no_overdue_observations(research):
    from zargar.techniques.options_cartel.method_lab_review import trial_report
    context=await prepared(research)
    result=await trial_report(research.engine,context.result['trial']['id'],prior.OPEN-1)
    assert result['review']['status']=='awaiting_sessions'
    assert result['review']['incompletePairs']==0
    assert result['review']['failures']==[]
    assert result['activationAllowed'] is False


async def test_missing_quotes_stay_unknown_in_reconciled_report(research,monkeypatch):
    rig=research;context=await prepared(rig)
    runtime=SimpleNamespace(engine=rig.engine,clock=lambda:prior.OPEN-500,stopping=False)
    await collect(runtime)
    runtime.clock=lambda:prior.OPEN+320000
    monkeypatch.setattr('zargar.techniques.options_cartel.method_lab_observer.observe_contract',
        AsyncMock(return_value={'status':'unavailable','observedAt':runtime.clock()}))
    await collect(runtime)
    runtime.clock=lambda:prior.OPEN+430000
    await pending_quotes(runtime,context,rig.policy)
    result=await report(rig.engine,context,runtime.clock())
    assert result['rows'][0]['quoteDisposition']=='deadline_missed'
    assert result['rows'][0]['models'] is None and result['rows'][0]['trialEligible'] is False
    assert result['trialReview']['status']=='not_ready'
    assert result['activationAllowed'] is False and result['placesOrders'] is False


async def test_review_before_signal_time_cannot_see_future_results(research,monkeypatch):
    rig=research;context=await prepared(rig)
    runtime=SimpleNamespace(engine=rig.engine,clock=lambda:prior.OPEN-500,stopping=False)
    await collect(runtime)
    runtime.clock=lambda:prior.OPEN+320000
    monkeypatch.setattr('zargar.techniques.options_cartel.method_lab_observer.observe_contract',
        AsyncMock(return_value={'status':'unavailable','observedAt':runtime.clock()}))
    await collect(runtime)
    result=await report(rig.engine,context,prior.OPEN+300000)
    assert result['rows']==[] and result['trialObservationsIncluded']==0


async def test_full_stored_path_values_options_and_shares_at_receipt_times(research,monkeypatch):
    from sqlalchemy import select,func
    from zargar.models import TechniqueRun,Order
    from zargar.techniques.options_cartel import method_lab as lab
    from .test_cartel_method_lab import candidate
    rig=research;context=await prepared(rig,'TESTA')
    c=candidate('TESTA')
    async with rig.sf() as s,s.begin():
        s.add(TechniqueRun(id=c['analysisId'],technique='options_cartel',mode='analysis',symbol=c['symbol'],
            status='done',as_of=c['sourceAt'],config={'inputs':{'history':c['daily']}},result={}))
    runtime=SimpleNamespace(engine=rig.engine,clock=lambda:prior.OPEN-500,stopping=False)
    await collect(runtime);runtime.clock=lambda:prior.OPEN+320000
    contract='TESTA261016C00100000';at=runtime.clock()
    q={'contract':contract,'status':'observed','source':'opra','sourceAt':at,'observedAt':at,
       'bid':1.9,'ask':2.,'bidSize':10,'askSize':10}
    funding={'quantity':1,'cashCapUsd':500,'asOfMs':at,'usdToAccountFx':1,'stockFeePerOrder':0,
             'optionFeePerContractUsd':1,'maxAskUsd':5,'maxSpreadPct':20,'maxContracts':10,
             'displayedAskSize':10,'optionAsk':2}
    monkeypatch.setattr('zargar.techniques.options_cartel.method_lab_observer.observe_contract',
        AsyncMock(return_value={'status':'observed','observedAt':at,'selected':{'symbol':contract},'quote':q,'funding':funding}))
    monkeypatch.setattr('zargar.techniques.options_cartel.lab_market_quotes.underlying_snapshot',lambda *args:{
        'symbol':c['symbol'],'status':'observed','price':99.08,'observedAt':at,'sourceAt':at,
        'raw':{'bid':99.07,'ask':99.08,'bid_size':2,'ask_size':2,'quote_ts':at}})
    await collect(runtime)
    async with rig.sf() as s:
        signal=await s.scalar(select(TechniqueRun).where(TechniqueRun.mode=='lab_signal'))
    await lab.insert_record(rig.engine,key='later-price',mode='lab_prices',at=prior.OPEN+380000,parent=context.id,
        config=context.config,result={'observedAt':prior.OPEN+380000,'bars':[{'symbol':c['symbol'],
            'bar':[prior.OPEN+300000,99.08,99.1,98.8,98.9,100,'exchange']}]})
    for purpose,quote in [('mark',{**q,'sourceAt':prior.OPEN+390000,'observedAt':prior.OPEN+390000,'bid':1.5,'ask':1.6}),
        ('share_mark',{'contract':c['symbol'],'status':'observed','source':'alpaca_sip','sourceAt':prior.OPEN+390000,
            'observedAt':prior.OPEN+390000,'bid':98.85,'ask':98.86,'bidSize':10,'askSize':10})]:
        await lab.insert_record(rig.engine,key=purpose,mode='lab_quote',at=prior.OPEN+390000,parent=signal.id,
            config=context.config,result={'purpose':purpose,'quote':quote})
    result=await report(rig.engine,context,prior.OPEN+420000)
    row=result['rows'][0]
    assert row['receiptEconomics']['netPnl']==-52, row['receiptEconomics']['gaps']
    assert abs(row['shareReceiptEconomics']['netPnl']+.46)<1e-8
    assert row['receiptEconomics']['fills'][-1]['at']==prior.OPEN+390000
    async with rig.sf() as s:
        assert await s.scalar(select(func.count()).select_from(Order))==0


async def test_daily_review_is_idempotent_and_marks_friday_checkpoint(research,monkeypatch):
    from sqlalchemy import select
    from zargar.models import TechniqueRun
    from zargar.marketstructure.sessions import session_bounds
    from zargar.techniques.options_cartel.method_lab_review import scheduled_review
    rig=research;await prepared(rig)
    at=session_bounds('2026-09-18')[1]+600000
    monkeypatch.setattr('zargar.domain.now_ms',lambda:at)
    first=await scheduled_review(rig.engine);second=await scheduled_review(rig.engine)
    assert len(first['records'])==1 and first['weeklyCheckpoint']
    assert second['records']==[]
    async with rig.sf() as s:
        row=await s.get(TechniqueRun,first['records'][0])
        assert row.result['weeklyCheckpoint'] and row.result['placesOrders'] is False
