from types import SimpleNamespace

from zargar.brokers.alpaca import AlpacaQuoteFeed
from zargar.techniques.options_cartel.lab_market_quotes import underlying_snapshot,entry_geometry


def test_raw_sip_provenance_ignores_other_cache_prices_and_returns_copy():
    feed=object.__new__(AlpacaQuoteFeed);feed._feed='sip'
    feed._state={'TEST':{'last':10.,'last_ts':100000,'bid':9.99,'ask':10.01,'quote_ts':100000,'bid_size':2,'ask_size':3}}
    engine=SimpleNamespace(feed=feed,quotes=SimpleNamespace(get=lambda _: {'last':999}))
    result=underlying_snapshot(engine,'TEST',lambda:105000)
    assert result['status']=='observed' and result['price']==10 and result['raw']['provider']=='alpaca'
    result['raw']['last']=999
    assert feed.venue_snapshot('TEST')['last']==10
    feed._feed='iex'
    assert underlying_snapshot(engine,'TEST',lambda:105000)['status']=='unavailable'


def test_geometry_and_stale_price_remain_separate_refusals():
    bounds={'trigger':10,'stop':9,'invalidation':9,'firstTarget':12,'maxChaseR':.5,'minTargetR':.25}
    assert entry_geometry({'status':'unavailable'},bounds)==['underlying_quote_unavailable']
    assert 'underlying_chase_limit' in entry_geometry({'status':'observed','price':11},bounds)
    assert not entry_geometry({'status':'observed','price':10.2},bounds)


def test_share_size_uses_normalized_share_count_without_second_multiplier():
    from zargar.techniques.options_cartel.lab_market_quotes import share_observation
    underlying={'symbol':'TEST','status':'observed','price':10.1,'observedAt':105000,'sourceAt':100000,
        'raw':{'bid':10.09,'ask':10.11,'quote_ts':100000,'bid_size':3,'ask_size':2}}
    bounds={'trigger':10,'stop':9,'invalidation':9,'firstTarget':12,'maxChaseR':.5,'minTargetR':.25}
    result=share_observation(underlying,{'cashCapUsd':500,'stockFeePerOrder':1},bounds)
    assert result['status']=='observed' and result['funding']['quantity']==2
