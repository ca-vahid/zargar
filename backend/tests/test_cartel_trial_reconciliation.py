import datetime as dt
from types import SimpleNamespace

from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.lab_protocol import TrialProtocol,trial_review
from zargar.techniques.options_cartel.method_lab_review import trial_observations

DAY='2026-05-05';OPEN,CLOSE=session_bounds(DAY)


def fixture():
    p=TrialProtocol(portfolio_id='p',policy_hash='a'*64,first_session=DAY,frozen_at=OPEN-1000,
        initial_capital=10000,cash_cap=500,full_debit_risk_pct=10)
    context=SimpleNamespace(config={'session':DAY},result={'observedIds':['c'],
        'market':{'indices':{s:{'direction':'long'} for s in ('SPY','QQQ')}}})
    ticks=[SimpleNamespace(id=str(t),as_of=t+1000,result={'boundary':t,'rows':[{'candidateId':'c','models':{
        v:{'status':'waiting','trace':[],'signal':None} for v in (p.control,p.challenger)}}]})
        for t in range(OPEN+300000,CLOSE,300000)]
    return p,context,ticks


def test_complete_nonentries_are_zero_but_missing_windows_remain_unknown():
    p,context,ticks=fixture()
    assert trial_observations(context,{'rows':[]},[],p,OPEN-1)==[]
    rows=trial_observations(context,{'rows':[]},ticks,p,CLOSE)
    assert all(r.complete and r.disposition=='no_signal' for r in rows)
    missing=trial_observations(context,{'rows':[]},ticks[1:],p,CLOSE)
    assert all(not r.complete and r.net_pnl is None for r in missing)
    assert trial_review(p,missing)['incompletePairs']==1
    ticks[0].result['rows'][0]['models'][p.challenger]['trace']=[{
        'status':'confirmation_refused','blockers':['baseline_unavailable']}]
    incomplete=trial_observations(context,{'rows':[]},ticks,p,CLOSE)
    assert not next(r for r in incomplete if r.variant==p.challenger).complete


def test_recorded_receipt_costs_feed_closed_outcome_without_inventing_zero_spread():
    p,context,ticks=fixture()
    economics={'rows':[{'candidateId':'c','variant':p.challenger,'signalId':'signal','trialEligible':True,
        'receiptEconomics':{'status':'closed','gaps':[],'closedAt':OPEN+3600000,'netPnl':-52.,
            'fees':2.,'spreadCost':10.,'entryDebit':201.,'observedMaxAdversePnl':-52.,'inputHash':'b'*64}}]}
    rows=trial_observations(context,economics,ticks,p,CLOSE)
    challenger=next(r for r in rows if r.variant==p.challenger)
    assert challenger.closed_session==dt.date.fromisoformat(DAY)
    assert challenger.complete and challenger.spread_slippage_cost==10
    assert trial_review(p,rows)['metrics'][p.challenger]['stressNetPnl']==-64
