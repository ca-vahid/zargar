"""The recorded price and provenance must belong to one observation.
Synthetic quote-cache changes between picker examination and diagnostic capture.
"""
from types import SimpleNamespace
from .test_team2_diagnostics import rig


def test_candidate_cannot_pair_old_price_with_new_quote_timestamp(monkeypatch):
    import zargar.techniques.team2.runner as module
    now=2_000_000
    monkeypatch.setattr(module.time,'time',lambda:now/1000)
    runner,ap=rig()
    runner._diag_emit=lambda *args,**kwargs:None
    old={'symbol':'OPT','strike':101,'bid':.5,'ask':.51,'priced':'opra','eligible':True,
         'quoteTs':now-1000,'receivedTs':now-1000,'source':'opra'}
    current=SimpleNamespace(bid=.8,ask=.81,ts=now,source='opra',source_ts=now)
    runner.engine.quotes=SimpleNamespace(get=lambda _:current)
    runner._diag_candidates(ap,'s#1',{'examined':[old]},'OPT',100,runner.rules_for(ap),[],None)
    rec=runner._diag_attempt(ap,'s#1')['candidates'][0]
    if rec['priceKnown']:
        assert (rec['bid'],rec['ask'],rec['quoteTs']) in ((.5,.51,now-1000),(.8,.81,now)), 'mixed old prices with a new confirmation timestamp'


def test_entry_record_cannot_be_both_chain_sourced_and_known_live(monkeypatch):
    import zargar.techniques.team2.runner as module
    now=2_000_000
    monkeypatch.setattr(module.time,'time',lambda:now/1000)
    runner,ap=rig()
    runner._diag_emit=lambda *args,**kwargs:None
    runner.engine.quotes=SimpleNamespace(get=lambda _:SimpleNamespace(bid=.8,ask=.81,ts=now,source='chain',source_ts=now))
    old={'symbol':'OPT','strike':101,'bid':.5,'ask':.51,'priced':'opra','eligible':True}
    runner._diag_candidates(ap,'s#1',{'examined':[old]},'OPT',100,runner.rules_for(ap),[],None)
    rec=runner._diag_attempt(ap,'s#1')['candidates'][0]
    assert not (rec.get('source')=='chain' and rec['priceKnown']), 'chain source was attached after freshness validation and remains marked known/live'
