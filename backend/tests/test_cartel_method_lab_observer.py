from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select,func

from zargar.models import BarRow,TechniqueRun,Order,TechniqueArmed
from zargar.techniques.options_cartel import method_lab as lab
from zargar.techniques.options_cartel.method_lab_observer import collect
from . import test_options_cartel_profitability_research as prior
from .test_cartel_method_lab import candidate

research=prior.research


async def prepared(rig,symbol=None):
    rig.engine.settings[lab.SETTING]=True
    rig.engine.positions=SimpleNamespace(portfolio=lambda _: {'kind':'sim'},equity=AsyncMock(return_value=10000))
    c=candidate(symbol);c['entryPolicy']['max_chase_r']=2
    result=await lab.freeze(rig.engine,rig.prep,rig.policy,[c],clock=lambda:prior.OPEN-60000)
    async with rig.sf() as s: context=await s.get(TechniqueRun,result['contextId'])
    frozen=context.result['candidates'][0]
    matrices={str(tf):{'baselines':{i:500 for i in range(390//tf)}} for tf in (5,15)}
    await lab.insert_record(rig.engine,key='baseline',mode='lab_baseline',at=prior.OPEN-1000,parent=context.id,
        config=context.config,result={'candidateId':frozen['id'],'status':'ready','baselines':matrices,
            'baselineAvailableAt':prior.OPEN-1000,'specs':lab.build_specs(frozen,prior.DAY,matrices,prior.OPEN-1000)})
    async with rig.sf() as s,s.begin():
        for i in range(5):
            s.add(BarRow(symbol=frozen['symbol'],tf='1m',ts=prior.OPEN+i*60000,
                open=99.05,high=99.1,low=98.95,close=99.08,volume=200,source='exchange',provider='alpaca'))
    return context


async def test_observer_captures_one_prospective_signal_and_no_orders(research,monkeypatch):
    rig=research;await prepared(rig)
    runtime=SimpleNamespace(engine=rig.engine,clock=lambda:prior.OPEN-500,stopping=False)
    await collect(runtime)  # starts before open; does not fabricate an earlier observation
    runtime.clock=lambda:prior.OPEN+5*60000+20000
    monkeypatch.setattr('zargar.techniques.options_cartel.method_lab_observer.observe_contract',
        AsyncMock(return_value={'status':'unavailable','observedAt':runtime.clock()}))
    await collect(runtime);await collect(runtime)
    async with rig.sf() as s:
        signals=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_signal'))).all()
        ticks=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_tick'))).all()
        assert len(signals)==len(ticks)==1
        assert signals[0].result['variant']=='undercut_reclaim_5m_v1'
        assert signals[0].result['observedAt']>signals[0].result['signal']['at']
        assert signals[0].result['placesOrders'] is False
        assert await s.scalar(select(func.count()).select_from(Order))==0
        assert await s.scalar(select(func.count()).select_from(TechniqueArmed))==0
    view=await lab.status(rig.engine,rig.policy,prior.DAY)
    assert view['signalCount']==1 and view['pricedSignals']==0 and view['activationAllowed'] is False


async def test_restart_after_confirmation_does_not_capture_historical_signal(research):
    rig=research;await prepared(rig)
    runtime=SimpleNamespace(engine=rig.engine,clock=lambda:prior.OPEN+5*60000+20000,stopping=False)
    await collect(runtime)
    async with rig.sf() as s:
        assert await s.scalar(select(func.count()).select_from(TechniqueRun).where(TechniqueRun.mode=='lab_signal'))==0
    rig.engine.feed.watch.assert_awaited()


async def test_failed_quote_is_retried_after_restart_but_never_after_deadline(research,monkeypatch):
    from zargar.techniques.options_cartel.method_lab_observer import pending_quotes
    rig=research;context=await prepared(rig)
    runtime=SimpleNamespace(engine=rig.engine,clock=lambda:prior.OPEN-500,stopping=False)
    await collect(runtime)
    runtime.clock=lambda:prior.OPEN+5*60000+20000
    observe=AsyncMock(side_effect=[TimeoutError(),{'status':'observed','observedAt':runtime.clock()+20000,
        'selected':{'symbol':'TEST0261016C00100000'},'quote':{'status':'observed'},'funding':{'quantity':1}}])
    monkeypatch.setattr('zargar.techniques.options_cartel.method_lab_observer.observe_contract',observe)
    monkeypatch.setattr('zargar.techniques.options_cartel.lab_market_quotes.underlying_snapshot',
        lambda *args:{'status':'observed','price':99.08,'observedAt':prior.OPEN+340000})
    await collect(runtime)
    # A fresh owner sees durable attempts rather than forgetting the failure.
    restarted=SimpleNamespace(engine=rig.engine,clock=lambda:prior.OPEN+5*60000+40000,stopping=False)
    await pending_quotes(restarted,context,rig.policy)
    await pending_quotes(restarted,context,rig.policy)
    assert observe.await_count==2
    async with rig.sf() as s:
        saved=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_quote'))).all()
        assert sum(r.result.get('purpose')=='entry_attempt' for r in saved)==2
        final=[r for r in saved if r.result.get('purpose')=='entry_selection']
        assert len(final)==1 and final[0].result['observation']['timely']
    view=await lab.status(rig.engine,rig.policy,prior.DAY)
    assert view['rows'][0]['models']['undercut_reclaim_5m_v1']['quoteStatus']=='observed'


async def test_expired_quote_window_records_missing_evidence_without_provider_call(research,monkeypatch):
    from zargar.techniques.options_cartel.method_lab_observer import pending_quotes
    rig=research;context=await prepared(rig)
    await lab.insert_record(rig.engine,key='unpriced-signal',mode='lab_signal',at=prior.OPEN+300000,
        parent=context.id,config=context.config,result={'variant':'breakout_5m_v1','symbol':'TEST0','signal':{'at':prior.OPEN+300000}})
    observe=AsyncMock();monkeypatch.setattr('zargar.techniques.options_cartel.method_lab_observer.observe_contract',observe)
    runtime=SimpleNamespace(engine=rig.engine,clock=lambda:prior.OPEN+420001,stopping=False)
    await pending_quotes(runtime,context,rig.policy)
    observe.assert_not_awaited()
    async with rig.sf() as s:
        result=await s.get(TechniqueRun,lab.identity('unpriced-signal','entry_quote'))
        assert result.result['observation']['status']=='deadline_missed'


async def test_carry_collection_continues_without_a_new_daily_context(research,monkeypatch):
    from zargar.marketstructure.sessions import session_bounds
    from zargar.techniques.options_cartel.method_lab_observer import capture_quotes
    rig=research;context=await prepared(rig,'TESTA')
    next_open=session_bounds('2026-09-16')[0];now=next_open+120000
    rig.engine.options=SimpleNamespace(track=AsyncMock())
    await lab.insert_record(rig.engine,key='carry-entry',mode='lab_quote',at=prior.OPEN+320000,
        parent='carry-signal',config=context.config,result={'purpose':'entry_selection','observation':{
            'status':'observed','timely':True,'selected':{'symbol':'TESTA261016C00100000'}}})
    async with rig.sf() as s,s.begin():
        s.add(BarRow(symbol='TESTA',tf='1m',ts=next_open,open=100,high=101,low=99,close=100,
            volume=1000,source='exchange',provider='alpaca'))
    monkeypatch.setattr('zargar.techniques.options_cartel.method_lab_observer.snapshot_quote',lambda *args:{
        'contract':'TESTA261016C00100000','status':'observed','observedAt':now,'sourceAt':now,'bid':2.,'ask':2.1})
    runtime=SimpleNamespace(engine=rig.engine,clock=lambda:now,stopping=False)
    await capture_quotes(runtime)
    async with rig.sf() as s:
        prices=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_prices'))).all()
        assert any(r.config['session']=='2026-09-16' and 'TESTA' in r.result['symbols'] for r in prices)
        assert await s.scalar(select(func.count()).select_from(Order))==0
    rig.engine.feed.watch.assert_awaited_with('TESTA')


async def test_data_revision_cannot_resurrect_a_committed_invalidation(research):
    from sqlalchemy import update
    rig=research;await prepared(rig,'TESTA')
    async with rig.sf() as s,s.begin():
        await s.execute(update(BarRow).where(BarRow.symbol=='TESTA').values(low=95))
    runtime=SimpleNamespace(engine=rig.engine,clock=lambda:prior.OPEN-500,stopping=False)
    await collect(runtime);runtime.clock=lambda:prior.OPEN+320000;await collect(runtime)
    async with rig.sf() as s,s.begin():
        await s.execute(update(BarRow).where(BarRow.symbol=='TESTA').values(low=99.01))
        for i in range(5,10):
            s.add(BarRow(symbol='TESTA',tf='1m',ts=prior.OPEN+i*60000,open=99.05,high=99.1,low=98.95,
                close=99.08,volume=200,source='exchange',provider='alpaca'))
    runtime.clock=lambda:prior.OPEN+620000;await collect(runtime)
    async with rig.sf() as s:
        assert await s.scalar(select(func.count()).select_from(TechniqueRun).where(TechniqueRun.mode=='lab_signal'))==0
    view=await lab.status(rig.engine,rig.policy,prior.DAY)
    assert view['rows'][0]['models']['undercut_reclaim_5m_v1']['status']=='invalidated'


async def test_disable_during_quote_request_preserves_attempt_without_accepting_entry(research,monkeypatch):
    rig=research;await prepared(rig)
    runtime=SimpleNamespace(engine=rig.engine,clock=lambda:prior.OPEN-500,stopping=False)
    await collect(runtime);runtime.clock=lambda:prior.OPEN+320000
    async def disable(*args):
        rig.engine.settings[lab.SETTING]=False
        return {'status':'unavailable','observedAt':runtime.clock()}
    monkeypatch.setattr('zargar.techniques.options_cartel.method_lab_observer.observe_contract',disable)
    await collect(runtime)
    async with rig.sf() as s:
        quotes=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_quote'))).all()
        assert [r.result['purpose'] for r in quotes]==['entry_attempt']
        assert await s.scalar(select(func.count()).select_from(Order))==0
