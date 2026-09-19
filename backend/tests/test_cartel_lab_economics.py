from zargar.techniques.options_cartel.exits import ExitCampaign
from zargar.techniques.options_cartel.lab_economics import compare_vehicles
from zargar.techniques.options_cartel.shadow_entries import read_shadow_entry
from .test_cartel_shadow_entries import spec,bar,OPEN,MIN


def test_share_quantity_respects_cash_and_costs_and_options_are_not_stock_returns():
    s=spec();tape=[bar(i) for i in range(5)]
    signal=read_shadow_entry(s,tape,OPEN+5*MIN,entry_after=OPEN)['signal']
    tape += [bar(5,opening=10.15,low=10.1,close=10.15)]
    campaign=ExitCampaign.for_profile('june_2026',list(s.targets))
    result=compare_vehicles(s,signal,tape,[],campaign,as_of_ms=OPEN+6*MIN,
        observed_at=OPEN+5*MIN,signal_after=OPEN,
        funding={'cashCapUsd':100,'asOfMs':OPEN+5*MIN,'usdToAccountFx':1,'stockFeePerOrder':1})
    assert result['shares']['entry']['quantity']==9
    assert result['shares']['cashUsedUsd']<=100
    assert result['options'] is None and 'eligible_option_and_quantity_unavailable' in result['gaps']
    assert result['pass']['netPnl']==0 and result['placesOrders'] is False


def test_missing_fees_and_stale_funding_are_not_zero_cost_results():
    s=spec();tape=[bar(i) for i in range(6)]
    signal=read_shadow_entry(s,tape,OPEN+5*MIN,entry_after=OPEN)['signal']
    args=dict(as_of_ms=OPEN+6*MIN,observed_at=OPEN+5*MIN,signal_after=OPEN)
    campaign=ExitCampaign.for_profile('june_2026',list(s.targets))
    stale=compare_vehicles(s,signal,tape,[],campaign,funding={'cashCapUsd':100,'asOfMs':OPEN,'usdToAccountFx':1},**args)
    assert stale['gaps']==['missing_or_stale_funding']
    fees=compare_vehicles(s,signal,tape,[],campaign,funding={'cashCapUsd':100,'asOfMs':OPEN+5*MIN,'usdToAccountFx':1},**args)
    assert 'share_fees_unknown' in fees['gaps'] and fees['shares'] is None
