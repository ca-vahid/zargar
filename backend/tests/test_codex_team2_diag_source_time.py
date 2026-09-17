"""Actual Quote field semantics: receipt ts can be newer than source_ts.
No providers, DB, orders or engine startup. Real diagnostic adapters, mocked quote I/O.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from .test_team2_diagnostics import rig


@pytest.mark.parametrize('source_age,known',[(0,True),(120_000,False)])
async def test_followup_uses_source_confirmation_not_generic_receipt_time(monkeypatch,source_age,known):
    import zargar.techniques.team2.runner as module
    now=2_000_000
    monkeypatch.setattr(module.time,'time',lambda:now/1000)
    runner,ap=rig()
    quote=SimpleNamespace(bid=.6,ask=.61,ts=now,source='opra',source_ts=now-source_age)
    runner.engine.options=SimpleNamespace(refresh_now=AsyncMock(return_value=quote),served_live=lambda _:True)
    runner._diag_emit=lambda *args,**kwargs:None
    rec=runner._diag_attempt(ap,'setup#1')
    rec['candidates']=[{'symbol':'OPT','followed':True}]
    pending={'attempt':'setup#1','horizon':'2m','dueTs':now,'status':'inflight'}
    await runner._diag_observe(ap,pending)
    got=rec['observations']['2m']['quotes'].get('OPT')
    assert (got is not None)==known, 'recent receipt timestamp concealed stale source evidence'


def test_candidate_entry_does_not_retimestamp_old_source_prices(monkeypatch):
    import zargar.techniques.team2.runner as module
    now=2_000_000
    monkeypatch.setattr(module.time,'time',lambda:now/1000)
    runner,ap=rig()
    runner._diag_emit=lambda *args,**kwargs:None
    runner.engine.quotes=SimpleNamespace(get=lambda _:SimpleNamespace(ts=now,source='opra',source_ts=now-120_000))
    qres={'examined':[{'symbol':'OPT','strike':101,'bid':.5,'ask':.51,'priced':'opra','eligible':True}]}
    runner._diag_candidates(ap,'setup#1',qres,'OPT',100,runner.rules_for(ap),[],None)
    assert runner._diag_attempt(ap,'setup#1')['candidates'][0]['priceKnown'] is False
