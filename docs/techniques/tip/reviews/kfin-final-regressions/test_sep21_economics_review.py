import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from zargar.approvals.proposals import ProposalService
from zargar.techniques.tip import geometry, execcost
from zargar.tools import tip_review_gate_eval as gate_eval

async def card(monkeypatch):
    from zargar.clock import now_ms
    now = now_ms()
    q = NS(last=5.0, bid=.14, ask=.15, source='opra', source_ts=now, ts=now, delayed=False)
    eng = NS(settings={'options.fee_per_contract':.99,'sim.reg_fee_per_contract':.05},
        ensure_symbol=AsyncMock(), quotes=NS(get=lambda s:q),
        positions=NS(equity=AsyncMock(return_value=9000)),
        feed=type('SimQuoteFeed',(),{})(),
        options=NS(snapshot_cached=lambda s:{'greeks':{'delta':.3},'asOf':now,'greeksLive':True}))
    plan={'targets':[5.7], 'fractions':[1.0], 'maxHoldSessions':3}
    rp=NS(qty=5,unitLoss=12.,reviewRequired=None,reviewClass=None)
    monkeypatch.setattr(geometry,'plan_risk',lambda **kw:(plan,rp))
    monkeypatch.setattr(execcost,'diagnose',lambda *a,**k:{'status':'known'})
    await ProposalService._compute_risk_plan(NS(engine=eng),mode='enforce',underlying='ACHR',direction='long',pid='p',
        exit_plan=plan,vehicle={'multiplier':100,'optionType':'call','strike':5.5,'expiry':'2026-09-25'},
        sec_type='OPT',symbol='ACHR260925C00005500',limit=.14,qty=5,entry_hint=5.)
    return rp.payoff

async def test_card_uses_the_same_complete_option_fee_as_execution(monkeypatch):
    p=await card(monkeypatch)
    assert p['feePerUnit'] == pytest.approx(1.04)

async def test_card_preserves_known_contract_and_holding_metadata(monkeypatch):
    p=await card(monkeypatch)
    assert p['breakEven']['expiration'] == pytest.approx(5.64)
    assert p['horizon']['expiryDate'] == '2026-09-25'

async def test_unresolved_observe_review_is_not_reported_as_zero_false_negatives(monkeypatch,capsys):
    class Conn:
        async def fetch(self,q,*a):
            if "type='TipReviewGate'" in q:
                return [{'ts':dt.datetime(2026,9,21,14,tzinfo=dt.timezone.utc),
                    'payload':{'mode':'observe','decision':'skip','applied':False,'intakeRunId':'missing'}}]
            return []
    monkeypatch.setattr(gate_eval,'_rates',AsyncMock(return_value={}))
    await gate_eval.prospective(Conn(),'2026-09-21')
    out=capsys.readouterr().out.lower()
    assert 'unresolved' in out or 'unmatched' in out or 'unevaluable' in out

async def test_every_human_review_candidate_is_exported(monkeypatch,capsys):
    class Conn:
        async def fetch(self,q,*a):
            if "type='TipReviewGate'" in q:
                return [{'ts':dt.datetime(2026,9,21,14,tzinfo=dt.timezone.utc),
                    'payload':{'mode':'observe','decision':'skip','applied':False,
                    'intakeRunId':f'r{i}','tickers':[f'CASE{i:02d}']}} for i in range(27)]
            return [{'id':f'r{i}','opinion':{'watch':[f'CASE{i:02d}']}} for i in range(27)]
    monkeypatch.setattr(gate_eval,'_rates',AsyncMock(return_value={}))
    await gate_eval.prospective(Conn(),'2026-09-21')
    out=capsys.readouterr().out
    assert 'CASE26' in out, 'the required human-review list must not silently stop at 20'
