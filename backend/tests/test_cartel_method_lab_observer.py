from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select,func

from zargar.models import BarRow,TechniqueRun,Order,TechniqueArmed
from zargar.techniques.options_cartel import method_lab as lab
from zargar.techniques.options_cartel.method_lab_observer import collect
from . import test_options_cartel_profitability_research as prior
from .test_cartel_method_lab import candidate

research=prior.research


async def prepared(rig):
    rig.engine.settings[lab.SETTING]=True
    rig.engine.positions=SimpleNamespace(portfolio=lambda _: {'kind':'sim'},equity=AsyncMock(return_value=10000))
    c=candidate();c['entryPolicy']['max_chase_r']=2
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
