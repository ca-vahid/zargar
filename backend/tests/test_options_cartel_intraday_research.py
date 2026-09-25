import datetime as dt
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from zargar.db import make_engine
from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.models import BarRow, Order, TechniqueArmed, TechniqueRun
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.intraday_research import collect, identity, market_observation
from zargar.techniques.options_cartel.plans import CartelPlan, EntryPolicy

from .conftest import make_test_config

DAY='2026-09-15'
OPEN=session_bounds(DAY)[0]
STEP=900000

def market():
    return {'alignmentMode':'moderate','indices':{s:{'session':'2026-09-14','emas':{'8':100.,'21':99.,'50':98.}} for s in ('SPY','QQQ')}}

def bars(symbol,boundary,close=101.):
    return [Bar(symbol,'1m',t,close-.1,close+.05,close-.2,close,1000,source='exchange') for t in range(boundary-STEP,boundary,60000)]

def test_requires_sustained_closed_observations_and_preserves_daily_references():
    saved=market();original=deepcopy(saved)
    first=market_observation(saved,bars('SPY',OPEN+STEP)+bars('QQQ',OPEN+STEP),OPEN+STEP,OPEN+STEP+60000)
    assert first['aligned'] and not first['sustained']
    second=market_observation(saved,bars('SPY',OPEN+2*STEP)+bars('QQQ',OPEN+2*STEP),OPEN+2*STEP,OPEN+2*STEP+60000,first)
    assert second['sustained'] and second['improvedSince']==OPEN+2*STEP+60000
    assert saved==original
    assert first['indices']['SPY']['sourceEvidence']['sourceCounts']=={'exchange':15}

def test_missing_stale_sampled_and_late_data_never_establish_alignment():
    boundary=OPEN+STEP
    complete=bars('SPY',boundary)+bars('QQQ',boundary)
    assert market_observation(market(),complete[:-1],boundary,boundary+60000)['status']=='unavailable'
    complete[0].source='sampled'
    assert not market_observation(market(),complete,boundary,boundary+60000)['aligned']
    complete[0].source='exchange'
    assert not market_observation(market(),complete,boundary,boundary+120001)['aligned']
    stale=market();stale['indices']['QQQ']['session']='2026-09-11'
    assert not market_observation(stale,complete,boundary,boundary+60000)['aligned']

def test_gap_resets_streak_and_below_daily_50_stays_blocked():
    boundary=OPEN+STEP
    first=market_observation(market(),bars('SPY',boundary)+bars('QQQ',boundary),boundary,boundary+60000)
    skipped=boundary+2*STEP
    assert not market_observation(market(),bars('SPY',skipped)+bars('QQQ',skipped),skipped,skipped+60000,first)['sustained']
    assert not market_observation(market(),bars('SPY',boundary)+bars('QQQ',boundary,97),boundary,boundary+60000)['aligned']

async def test_hypothetical_confirmation_persists_without_arming_or_changing_preparation(fresh_db):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    database=make_engine(make_test_config().database_url)
    sf=async_sessionmaker(database,expire_on_commit=False)
    policy=PreparationPolicy(enabled=True,portfolio_id='research-book')
    settings={'techniques.options_cartel.preparation':policy.model_dump(mode='json'),
              'techniques.options_cartel.intraday_research':True}  # off by default since 0.8.50
    engine=SimpleNamespace(sf=sf,settings=settings,feed=SimpleNamespace(watch=AsyncMock()))
    now=OPEN+STEP+60000
    runtime=SimpleNamespace(engine=engine,clock=lambda:now,stopping=False,_intraday_research_started=None,
        _intraday_research_watched=set(),_intraday_research_status={})
    prep=TechniqueRun(id='research-prep',technique='options_cartel',symbol='MULTI',mode='preparation',status='done',as_of=OPEN-3600000,
        config={'workspace':'practice','portfolioId':'research-book','session':DAY,'policy':policy.model_dump(mode='json')},
        result={'armingBlocked':True,'researchDirection':'long','market':market(),'shortlist':[{'symbol':'TEST','status':'market_blocked','analysisId':'analysis'}]})
    plan=CartelPlan(id='research-test',symbol='TEST',direction='long',setup='base',created_at=OPEN-3600000,
        first_session=dt.date.fromisoformat(DAY),last_session=dt.date.fromisoformat(DAY),trigger=101,invalidation=99,targets=(110,),
        source_refs=('research-fixture',),rationale='research test',entry=EntryPolicy(require_exchange_bars=True),
        volume_baseline={i:100 for i in range(26)},baseline_as_of=OPEN-3600000)
    original=deepcopy(prep.result)
    try:
        async with sf() as session,session.begin():
            session.add(prep)
            session.add(TechniqueRun(id=identity(prep.id,'context'),technique='options_cartel',symbol='MULTI',mode='watch_context',status='done',as_of=OPEN-1000,
                result={'plans':[{'symbol':'TEST','plan':plan.model_dump(mode='json')}],'watchStartedAt':OPEN-1000}))
        for bucket in range(1,5):
            boundary=OPEN+bucket*STEP; now=boundary+60000
            async with sf() as session,session.begin():
                for bar in bars('SPY',boundary)+bars('QQQ',boundary)+bars('TEST',boundary,101.2 if bucket==4 else 100):
                    session.add(BarRow(symbol=bar.symbol,tf=bar.tf,ts=bar.ts,open=bar.open,high=bar.high,low=bar.low,close=bar.close,volume=bar.volume,source=bar.source))
            await collect(runtime)
        await collect(runtime)
        async with sf() as session:
            snapshots=(await session.scalars(select(TechniqueRun).where(TechniqueRun.mode=='intraday_watch'))).all()
            assert len(snapshots)==4
            last=await session.get(TechniqueRun,identity(prep.id,str(OPEN+4*STEP)))
            assert last.result['candidates'][0]['status']=='hypothetical_stock_confirmation',last.result
            assert last.result['placesOrders'] is False and last.result['automaticPermissionChanged'] is False
            assert (await session.get(TechniqueRun,prep.id)).result==original
            assert await session.scalar(select(func.count()).select_from(Order))==0
            assert await session.scalar(select(func.count()).select_from(TechniqueArmed))==0
            assert await session.scalar(select(func.count()).select_from(TechniqueRun).where(TechniqueRun.mode=='plan'))==0
        from zargar.techniques.options_cartel.state import ArmRepository
        with pytest.raises(ValueError,match='owned reviewed plan'):
            await ArmRepository(engine).arm(identity(prep.id,str(OPEN+4*STEP)),'research-book','auto',{},now_ms=now)
        settings['techniques.options_cartel.intraday_research']=False
        now+=STEP
        await collect(runtime)
        assert engine.feed.watch.await_count==3
    finally:
        await database.dispose()
