import datetime as dt

import pytest

from zargar.marketstructure.market_calendar import is_trading_day
from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.lab_protocol import TrialProtocol, TrialObservation, trial_review


def protocol(**kwargs):
    return TrialProtocol(**{'portfolio_id':'practice','first_session':dt.date(2026,5,5),'policy_hash':'a'*64,
        'frozen_at':session_bounds('2026-05-05')[0]-1000,'initial_capital':10000,
        'cash_cap':500,'full_debit_risk_pct':10,**kwargs})


def rows(p):
    days=[];day=p.first_session
    while len(days)<30:
        if is_trading_day(day):days.append(day)
        day+=dt.timedelta(days=1)
    return [TrialObservation(protocol_hash=p.fingerprint,session=day,closed_session=day,candidate_id=f'name-{i}',variant=v,
        regime='strong' if i%2 else 'mixed',disposition='closed',coverage_complete=True,
        net_pnl=1 if v==p.control else 2,fees=.1,spread_slippage_cost=.2,
        cash_debit=100,peak_exposure=100,max_adverse_pnl=-1,evidence_ids=(f'fills:{i}:{v}',))
        for i,day in enumerate(days) for v in (p.control,p.challenger)]


def test_protocol_hash_changes_when_any_trial_rule_changes_and_rejects_late_freeze():
    p=protocol()
    assert p.fingerprint!=protocol(cash_cap=400).fingerprint
    with pytest.raises(ValueError): protocol(frozen_at=session_bounds('2026-05-05')[0])


def test_no_data_is_not_success_and_small_winning_sample_cannot_promote():
    p=protocol()
    assert trial_review(p,[])['status']=='not_ready'
    r=trial_review(p,rows(p)[:4])
    assert 'insufficient_sessions' in r['failures'] and 'insufficient_closed_trades' in r['failures']
    assert r['activationAllowed'] is False


def test_paired_session_review_is_deterministic_and_never_execution_authority():
    p=protocol();data=rows(p)
    result=trial_review(p,data)
    assert result==trial_review(p,list(reversed(data)))
    assert result['status']=='review_ready' and result['sessions']==30
    assert result['metrics'][p.challenger]['netPnl']==60
    assert result['activationAllowed'] is False and result['placesOrders'] is False


def test_missing_quotes_cannot_be_scored_as_zero_or_removed_from_denominator():
    p=protocol();data=rows(p)
    data[1]=data[1].model_copy(update={'disposition':'quote_missing','net_pnl':None})
    r=trial_review(p,data)
    assert r['population']==30 and r['completePairs']==29 and r['incompletePairs']==1
    assert 'incomplete_or_unmatched_population' in r['failures']


def test_duplicates_foreign_protocol_and_oversized_trade_block_review():
    p=protocol();data=rows(p)
    data[1]=data[1].model_copy(update={'cash_debit':501})
    r=trial_review(p,data+[data[0],data[0].model_copy(update={'protocol_hash':'other'})])
    assert {'duplicate_observation','foreign_or_pretrial_observation','risk_or_exposure_violation'}<=set(r['failures'])


def test_multi_session_positions_are_counted_in_overlapping_exposure():
    p=protocol(cash_cap=1000,full_debit_risk_pct=10)
    data=rows(p)
    last=data[-1].session
    data=[r.model_copy(update={'closed_session':last,'cash_debit':1000,'peak_exposure':1000}) for r in data]
    result=trial_review(p,data)
    assert result['metrics'][p.challenger]['peakSessionExposureUpperBound']==30000
    assert 'risk_or_exposure_violation' in result['failures']
