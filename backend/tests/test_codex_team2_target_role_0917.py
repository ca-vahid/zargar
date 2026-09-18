"""Proposed structural invariant from Sep17: the broken PM level cannot also
be the breakout's destination. Synthetic routing probe, not a strategy sweep.
Expect collision cases to fail before implementation; no actual orders.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import datetime as dt
import pytest
from zargar.marketstructure.sessions import ET
from .test_codex_team2_data_eod import rig,bar


@pytest.mark.parametrize('direction', ['long','short'])
@pytest.mark.parametrize('collision',[True,False])
async def test_pm_break_destination_is_distinct_from_its_anchor(monkeypatch,direction,collision):
    import zargar.techniques.team2.runner as module
    import zargar.execution.planrunner as shared
    runner,ap=rig()
    now=int(dt.datetime(2026,9,14,13,10,tzinfo=ET).timestamp()*1000)
    monkeypatch.setattr(module.time,'time',lambda:now/1000)
    monkeypatch.setattr(shared,'now_ms',lambda:now)
    ap.bar_index=10
    up=direction=='long'
    anchor=100.0
    entry=99.9957 if up else 100.0043
    target=anchor if collision else (101.0 if up else 99.0)
    sid='pm_break_up@12:15' if up else 'pm_break_down@12:15'
    ap.plan.update({'pmh':100.0,'pml':100.0})
    e={'event':'fire','ts':now,'setup':sid,'touch':2,'spot':entry,'target':target,'targetKind':'plan',
       'entryKind':'ema','sizeMult':.5,'bucket':'small','why':'synthetic EMA retest',
       'regime':{'stack':'bull' if up else 'bear','atr':.3145}}
    res=SimpleNamespace(setups=[{'id':sid,'kind':sid.split('@')[0],'direction':direction,'anchor':anchor,'target':target}])
    runner.pick_contract=AsyncMock(return_value={'symbol':'TEST','ask':.69})
    runner._enter=AsyncMock()
    await runner._fire_from_event(ap,e,bar(13,9,100.04 if up else 99.96),res,halted=False,journal=True)
    await runner.wait_fires(ap.run_id)
    assert runner._enter.await_count==(0 if collision else 1), 'the PM breakout trades toward its own entry level'
