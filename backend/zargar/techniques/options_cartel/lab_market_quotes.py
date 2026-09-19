"""Attributed SIP observations for research; no guessing from configured provider."""
import math


def underlying_snapshot(engine,symbol,clock):
    from ...brokers.alpaca import AlpacaQuoteFeed,HybridQuoteFeed
    feed=engine.feed
    venue=feed.alpaca if isinstance(feed,HybridQuoteFeed) else feed
    raw=venue.venue_snapshot(symbol) if isinstance(venue,AlpacaQuoteFeed) else None
    at=clock();out={'symbol':symbol,'observedAt':at,'status':'unavailable','raw':raw,
                   'reason':'A recent attributed SIP price is required.'}
    if not raw or raw.get('feed')!='sip': return out
    number=lambda n:isinstance(n,(int,float)) and not isinstance(n,bool) and math.isfinite(n)
    if number(raw.get('last')) and raw['last']>0 and number(raw.get('last_ts')) and 0<=at-raw['last_ts']<=10000:
        out.update(status='observed',price=raw['last'],sourceAt=raw['last_ts'],priceBasis='qualified_last',reason=None)
    elif all(number(raw.get(k)) for k in ('bid','ask','quote_ts')) and 0<raw['bid']<=raw['ask'] and 0<=at-raw['quote_ts']<=10000:
        out.update(status='observed',price=raw['ask'],sourceAt=raw['quote_ts'],priceBasis='fresh_ask',reason=None)
    return out


def entry_geometry(snapshot,bounds):
    if snapshot.get('status')!='observed': return ['underlying_quote_unavailable']
    price=snapshot['price'];trigger=bounds['trigger'];stop=bounds['stop'];target=bounds['firstTarget']
    reasons=[]
    if price<trigger: reasons.append('underlying_below_trigger')
    if price<=stop: reasons.append('underlying_stop_invalid')
    if price-trigger>abs(trigger-bounds['invalidation'])*bounds['maxChaseR']: reasons.append('underlying_chase_limit')
    if price>=target or price>stop and (target-price)/(price-stop)<bounds['minTargetR']: reasons.append('underlying_target_room')
    return reasons


def share_observation(underlying,funding,bounds):
    """Use feed-normalized share counts; never apply a second lot multiplier."""
    raw=underlying.get('raw') or {};at=underlying.get('observedAt',0)
    quote={'contract':underlying.get('symbol'),'source':'alpaca_sip','observedAt':at,
        'sourceAt':raw.get('quote_ts'),'bid':raw.get('bid'),'ask':raw.get('ask'),
        'bidSize':raw.get('bid_size'),'askSize':raw.get('ask_size'),'status':'observed',
        'sizeBasis':raw.get('sizeBasis','feed_normalized_shares')}
    from .receipt_economics import usable_quote
    out={'status':'unavailable','observedAt':at,'timely':False,'quote':quote,'funding':funding,
         'underlyingEvidence':underlying,'selected':{'symbol':underlying.get('symbol')}}
    if underlying.get('status')!='observed' or not usable_quote(quote,at,instrument='shares'):
        return {**out,'reason':'Fresh attributed SIP trade and two-sided quote required for shares.'}
    failures=entry_geometry({**underlying,'price':quote['ask']},bounds)
    if failures: return {**out,'reason':', '.join(failures)}
    fee=funding.get('stockFeePerOrder');cap=funding.get('cashCapUsd')
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in (fee,cap)):
        return {**out,'reason':'Explicit share fees and cash cap required.'}
    quantity=max(0,min(int(quote['askSize']),math.floor((cap-fee)/quote['ask'])))
    return {**out,'status':'observed' if quantity else 'budget_unavailable','reason':None if quantity else 'No whole share fits cash and size.',
        'funding':{**funding,'quantity':quantity,'instrument':'shares'},'timely':True}
