from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.exits import ExitCampaign
from zargar.techniques.options_cartel.receipt_economics import value_receipts

OPEN=session_bounds('2026-05-05')[0];MIN=60000
CONTRACT='TEST260619C00010000'


def quote(at,bid=1.9,ask=2.,size=10,source_at=None):
    return {'contract':CONTRACT,'status':'observed','source':'opra','sourceAt':source_at or at,
            'observedAt':at,'bid':bid,'ask':ask,'bidSize':size,'askSize':size}


def inputs(qty=1):
    at=OPEN+5*MIN+20000
    return dict(symbol='TEST',signal={'id':'s','at':OPEN+5*MIN,'referencePrice':10.,'stop':9.},
        entry_observation={'status':'observed','timely':True,'selected':{'symbol':CONTRACT},
            'underlyingEvidence':{'status':'observed','symbol':'TEST','observedAt':at,'sourceAt':at,'price':10.},
            'quote':quote(at),'funding':{'quantity':qty,'optionFeePerContractUsd':1.,'cashCapUsd':5000}},
        campaign=ExitCampaign.for_profile('june_2026',[11,12]),daily=[],
        decision_bars=[[OPEN+i*MIN,10,10.2,9.5,10,100,'exchange'] for i in range(5)],
        price_receipts=[],quotes=[],cutoff=OPEN+7*MIN)


def receipt(minute,received,close):
    return {'observedAt':received,'bars':[{'symbol':'TEST','bar':[OPEN+minute*MIN,10,max(10,close),min(10,close),close,100,'exchange']}]}


def test_exit_waits_for_price_receipt_and_fresh_quote_instead_of_backdating():
    data=inputs();decision_at=OPEN+6*MIN+20000;fill_at=decision_at+10000
    data.update(price_receipts=[receipt(5,decision_at,8.8)],
        quotes=[quote(OPEN+6*MIN,bid=1.8),quote(fill_at,bid=1.5,ask=1.6)])
    r=value_receipts(**data)
    assert r['status']=='closed' and r['netPnl']==-52
    assert r['fills'][-1]['at']==fill_at and r['fills'][-1]['decisionAt']==decision_at
    assert r['fees']==2 and r['placesOrders'] is False


def test_partial_exit_consumes_displayed_size_once_and_only_filled_trim_moves_stop():
    data=inputs(8);at=OPEN+6*MIN+20000
    data.update(price_receipts=[receipt(5,at,11.1)],quotes=[quote(at,bid=2.5,ask=2.6,size=1),
        quote(at+1000,bid=2.5,ask=2.6,size=1,source_at=at)],cutoff=at+1000)
    r=value_receipts(**data)
    assert r['remainingQty']==7 and r['breakeven'] is False
    data['quotes'].append(quote(at+5000,bid=2.5,ask=2.6,size=1));data['cutoff']=at+5000
    r=value_receipts(**data)
    assert r['remainingQty']==6 and r['breakeven'] and r['activeStop']==10


def test_coverage_gap_keeps_model_pnl_unknown_even_after_observed_exit():
    data=inputs();at=OPEN+7*MIN+20000
    data.update(price_receipts=[receipt(6,at,8.8)],quotes=[quote(at,bid=1.5,ask=1.6)],cutoff=at)
    r=value_receipts(**data)
    assert r['remainingQty']==0 and r['netPnl'] is None and r['status']=='incomplete'
    assert any('minute gaps' in s for s in r['gaps'])


def test_future_receipts_do_not_supply_early_exit_and_foreign_contract_is_refused():
    data=inputs();at=OPEN+6*MIN+20000
    data.update(price_receipts=[receipt(5,at,8.8)],quotes=[quote(at,bid=1.5,ask=1.6)],cutoff=at-1)
    assert len(value_receipts(**data)['fills'])==1
    data['entry_observation']['quote']['contract']='OTHER260619C00010000'
    assert value_receipts(**data)['fills']==[]


def test_unaffordable_or_unknown_entry_does_not_become_zero_pnl():
    data=inputs();data['entry_observation']['funding']['cashCapUsd']=100
    r=value_receipts(**data)
    assert r['netPnl'] is None and r['fills']==[]


def test_shares_use_one_multiplier_and_do_not_double_charge_partial_order_fee():
    data=inputs(10);entry=data['entry_observation'];at=OPEN+6*MIN+20000
    entry['selected']={'symbol':'TEST'}
    entry['quote'].update(contract='TEST',source='alpaca_sip',bid=9.9,ask=10.,askSize=20,bidSize=20)
    entry['funding']['stockFeePerOrder']=1
    q1={**quote(at,bid=8.5,ask=8.6,size=5),'contract':'TEST','source':'alpaca_sip'}
    q2={**q1,'sourceAt':at+5000,'observedAt':at+5000}
    data.update(price_receipts=[receipt(5,at,8.8)],quotes=[q1,q2],cutoff=at+5000,instrument='shares')
    result=value_receipts(**data)
    assert result['status']=='closed' and result['netPnl']==-17
    assert result['fees']==2 and [f['quantity'] for f in result['fills']]==[10,5,5]
