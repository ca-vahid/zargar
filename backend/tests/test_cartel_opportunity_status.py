from dataclasses import replace

from zargar.techniques.options_cartel.data_quality import pack
from zargar.techniques.options_cartel.entry import read_entry
from zargar.techniques.options_cartel.observation_health import repair_cutoff
from zargar.techniques.options_cartel.opportunity_status import opportunity_status
from .test_options_cartel_entry import MIN, OPEN, plan, tape


def test_report_keeps_price_and_historical_refusals_separate():
    bars=[replace(b,source='exchange') for b in tape()]
    state={'minutes':{str(b.ts):pack(b) for b in bars},'decisionHistory':[
        {'at':OPEN+5*MIN,'decision':'untrusted_confirmation'}]}
    p=plan(trigger=100,targets=(101,102))
    r=opportunity_status(p,state,'2026-05-05',OPEN+10*MIN)
    assert r['status']=='level_not_reached' and r['unresolvedMinutes']==0
    assert r['historicalDataRefusals']=={'untrusted_confirmation':1}
    del state['minutes'][str(OPEN)]
    r=opportunity_status(p,state,'2026-05-05',OPEN+10*MIN)
    assert r['status']=='level_not_observed' and r['unresolvedMinutes']==1
    state['minutes'][str(OPEN)]=[OPEN,100,200,1,100,1,'sampled']
    assert opportunity_status(p,state,'2026-05-05',OPEN+10*MIN)['status']=='level_not_observed'


def test_repair_suppresses_closed_signal_but_not_next_fresh_confirmation():
    p=plan();state={'armedAt':OPEN,'observeAfter':OPEN}
    cutoff=repair_cutoff(p,state,OPEN+6*MIN,use_verified=True)
    assert cutoff==OPEN+5*MIN
    assert read_entry(p,tape(),OPEN+10*MIN,entry_after=cutoff)['signal']
    # Repair after that same confirmation must never backdate its entry.
    cutoff=repair_cutoff(p,state,OPEN+11*MIN,use_verified=True)
    assert cutoff==OPEN+10*MIN
    assert not read_entry(p,tape(),OPEN+11*MIN,entry_after=cutoff)['signal']
    # Live/default behavior and existing pause/restart barriers are unchanged.
    assert repair_cutoff(p,state,OPEN+6*MIN)==OPEN+6*MIN
    assert repair_cutoff(p,{**state,'observeAfter':OPEN+7*MIN},OPEN+8*MIN,use_verified=True)==OPEN+7*MIN


def test_touches_never_claim_a_valid_entry_or_profit():
    bars=[replace(b,source='exchange') for b in tape()]
    r=opportunity_status(plan(),{'minutes':{str(b.ts):pack(b) for b in bars}},'2026-05-05',OPEN+10*MIN)
    assert r['status']=='level_reached' and r['placesOrders'] is False
    assert 'confirmation' in r['summary']
