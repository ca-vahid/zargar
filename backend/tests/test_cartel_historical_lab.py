import datetime as dt

import pytest

from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.tools.cartel_historical_lab import choose_preparations,tape,evaluate,legacy_analysis,native_history
from zargar.techniques.options_cartel.method_lab import freeze_candidates
from .test_cartel_method_lab import candidate
from . import test_options_cartel_profitability_research as prior


def test_preparation_must_finish_before_open_and_latest_is_time_not_outcome():
    def row(key,at):
        return {'id':key,'status':'done','created_at':dt.datetime.fromtimestamp((prior.OPEN-10000)/1000,dt.timezone.utc),
                'config':{'session':prior.DAY},'result':{'finishedAt':at,'evaluated':1}}
    rows=[row('early',prior.OPEN-2000),row('later',prior.OPEN-1000),row('too_late',prior.OPEN)]
    rows.append({**row('failed',prior.OPEN-500),'status':'failed'})
    assert choose_preparations(rows)[prior.DAY]['id']=='later'


def test_conflicting_prices_are_refused():
    bars=[[prior.OPEN,100,101,99,100,100,'exchange']]
    assert len(tape('TEST',bars+bars))==1
    with pytest.raises(ValueError): tape('TEST',bars+[[prior.OPEN,100,102,99,100,100,'exchange']])


def test_legacy_context_fallback_never_overrides_explicit_research_refusal():
    result={'analysis':{'candidates':[{'contextPassed':True},
        {'contextPassed':True,'researchContextPassed':False}]}}
    adapted=legacy_analysis(result)['analysis']['candidates']
    assert adapted[0]['researchContextPassed'] is True
    assert adapted[1]['researchContextPassed'] is False
    assert 'researchContextPassed' not in result['analysis']['candidates'][0]


async def test_native_history_clips_end_and_rejects_incomplete_pagination(monkeypatch):
    from unittest.mock import AsyncMock
    def bar(t):
        return {'t':dt.datetime.fromtimestamp(t/1000,dt.timezone.utc).isoformat(),
                'o':100,'h':101,'l':99,'c':100,'v':100}
    rows=[bar(prior.OPEN),bar(prior.OPEN+60000)]
    monkeypatch.setattr('zargar.tools.cartel_historical_lab.pages',AsyncMock(return_value=(rows,['hash'],True)))
    bars,manifest=await native_history(None,'TEST',prior.OPEN,prior.OPEN+60000)
    assert len(bars)==1 and bars[0].ts==prior.OPEN and manifest['complete']
    monkeypatch.setattr('zargar.tools.cartel_historical_lab.pages',AsyncMock(return_value=(rows,['hash'],False)))
    bars,manifest=await native_history(None,'TEST',prior.OPEN,prior.OPEN+60000)
    assert bars==[] and not manifest['complete']


def test_six_models_have_distinct_baselines_and_unknown_option_pnl():
    original=candidate();frozen=freeze_candidates([original],at=prior.OPEN-1,day=prior.DAY)['candidates'][0]
    history=[]
    for daily in original['daily'][-6:]:
        opened,closed=session_bounds(daily['session'])
        history.extend(Bar(original['symbol'],'1m',t,100,101,99.5,100,100,'exchange')
                       for t in range(opened,closed,60000))
    result=evaluate(frozen,original,prior.DAY,history,[],prior.OPEN-1)
    assert result['baselineSlots']=={'5':78,'15':26}
    assert len(result['models'])==6
    assert all(r['signal'] is None and r['optionsNetPnl'] is None for r in result['models'])
    assert result['minuteCount']==0

    # A reconstructible reclaim gets a costed share scenario, never option P&L.
    frozen['entryPolicy']['max_chase_r']=2
    minutes=[Bar(original['symbol'],'1m',prior.OPEN+i*60000,99,99.1,98.95,99.08,1000,'exchange')
             for i in range(6)]
    result=evaluate(frozen,original,prior.DAY,history,minutes,prior.OPEN-1)
    reclaim=next(r for r in result['models'] if r['variant']=='undercut_reclaim_5m_v1')
    assert reclaim['signal'] is not None
    assert reclaim['shareScenario']['cashUsedUsd']<=500
    assert reclaim['optionsNetPnl'] is None
