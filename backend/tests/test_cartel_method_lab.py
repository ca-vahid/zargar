import datetime as dt
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select,func

from zargar.marketstructure.market_calendar import previous_trading_day
from zargar.models import TechniqueRun,Order,TechniqueArmed
from zargar.techniques.options_cartel.method_lab import SETTING,enabled,freeze_candidates,freeze,build_specs,insert_record
from zargar.techniques.options_cartel.plans import EntryPolicy
from . import test_options_cartel_profitability_research as prior

research=prior.research


def candidate():
    row=prior.candidate();row['entryPolicy']=EntryPolicy().model_dump(mode='json')
    day=previous_trading_day(dt.date.fromisoformat(prior.DAY));days=[]
    for _ in range(25):days.append(day);day=previous_trading_day(day)
    row['daily']=[{'symbol':row['symbol'],'session':d.isoformat(),'open':100,'high':102,
                   'low':99,'close':101,'volume':10000} for d in reversed(days)]
    return row


def test_feature_is_practice_only_and_does_not_require_runtime_when_disabled():
    assert enabled(SimpleNamespace(settings={}),SimpleNamespace(workspace='practice')) is False
    for kind,workspace,expected in [('sim','practice',True),('live','live',False),('paper','practice',False)]:
        engine=SimpleNamespace(settings={SETTING:True},positions=SimpleNamespace(portfolio=lambda _: {'kind':kind}))
        assert enabled(engine,SimpleNamespace(workspace=workspace,portfolio_id='x')) is expected


def test_freeze_is_preopen_deterministic_and_retains_capacity_denominator():
    c=candidate();other={**deepcopy(c),'analysisId':'other','symbol':'OTHER'}
    other['daily']=[{**b,'symbol':'OTHER'} for b in other['daily']]
    original=deepcopy([c,other])
    result=freeze_candidates([c,other],at=prior.OPEN-60000,day=prior.DAY,cap=1)
    assert len(result['candidates'])==2 and len(result['omittedIds'])==1
    assert result==freeze_candidates([other,c],at=prior.OPEN-60000,day=prior.DAY,cap=1)
    assert [c,other]==original
    with pytest.raises(ValueError):freeze_candidates([c],at=prior.OPEN,day=prior.DAY)
    with pytest.raises(ValueError):freeze_candidates([c,c],at=prior.OPEN-60000,day=prior.DAY)
    stale={**c,'daily':c['daily'][:-1]}
    assert not freeze_candidates([stale],at=prior.OPEN-60000,day=prior.DAY)['candidates']


def test_spec_baselines_are_timeframe_specific_and_no_author_threshold_is_claimed():
    frozen=freeze_candidates([candidate()],at=prior.OPEN-60000,day=prior.DAY)['candidates'][0]
    specs=build_specs(frozen,prior.DAY,{'5':{'baselines':{0:123}},'15':{'baselines':{0:999}}},prior.OPEN-1000)
    assert set(specs)=={'undercut_reclaim_5m_v1','pivot_30m_5m_v1'}
    assert all(s['volume_baseline']=={'0':123.} for s in specs.values())
    assert all(s['source_status']=='mirrored_unverified' for s in specs.values())


async def test_frozen_records_are_immutable_and_never_become_orders_or_arms(research):
    rig=research;rig.engine.settings[SETTING]=True
    rig.engine.positions=SimpleNamespace(portfolio=lambda _: {'kind':'sim'},equity=AsyncMock(return_value=10000))
    first=await freeze(rig.engine,rig.prep,rig.policy,[candidate()],clock=lambda:prior.OPEN-60000)
    await freeze(rig.engine,rig.prep,rig.policy,[],clock=lambda:prior.OPEN-30000)
    async with rig.sf() as s:
        row=await s.get(TechniqueRun,first['contextId'])
        assert len(row.result['candidates'])==1 and row.result['frozenAt']==prior.OPEN-60000
        assert row.mode=='lab_context' and row.result['placesOrders'] is False
        assert await s.scalar(select(func.count()).select_from(Order))==0
        assert await s.scalar(select(func.count()).select_from(TechniqueArmed))==0
    with pytest.raises(ValueError,match='non-ordering'):
        await insert_record(rig.engine,key='bad',mode='plan',at=0,config={},result={},parent=rig.prep.id)
    from zargar.techniques.options_cartel.service import CartelService
    rig.engine.position_manager=SimpleNamespace(_policy_adapters={'options_cartel':object()})
    service=CartelService(rig.engine)
    assert not await service.runs(mode='lab_context',workspace='live')
    assert not any(r['mode'].startswith('lab_') for r in await service.runs(workspace='practice'))
