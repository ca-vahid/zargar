"""Attributed SIP observations for research; no guessing from configured provider."""
import math


MAX_VENUE_AHEAD_MS=30_000   # bounded host/venue clock skew tolerated between a print's venue time and its receipt


def underlying_snapshot(engine,symbol,clock):
    from ...brokers.alpaca import AlpacaQuoteFeed,HybridQuoteFeed
    feed=engine.feed
    venue=feed.alpaca if isinstance(feed,HybridQuoteFeed) else feed
    raw=venue.venue_snapshot(symbol) if isinstance(venue,AlpacaQuoteFeed) else None
    at=clock();out={'symbol':symbol,'observedAt':at,'status':'unavailable','raw':raw,
                   'reason':'A recent attributed SIP price is required.'}
    if not raw or raw.get('feed')!='sip': return out
    number=lambda n:isinstance(n,(int,float)) and not isinstance(n,bool) and math.isfinite(n)
    def fresh(venue_key,received_key):
        # P7 (2026-09-22): freshness is judged on the LOCAL receipt time (never in the future on the host
        # clock). The venue time is kept as evidence and must sit within a bounded skew of receipt: the
        # host clock was measured ~9 s behind venue time, which made every fresh SIP print look future-dated.
        venue,received=raw.get(venue_key),raw.get(received_key)
        if not number(venue) or venue<=0:
            return False
        if number(received) and received>0:
            return 0<=at-received<=10000 and -MAX_VENUE_AHEAD_MS<=received-venue<=10000
        return 0<=at-venue<=10000   # feeds without receipt stamps keep the original rule
    if number(raw.get('last')) and raw['last']>0 and fresh('last_ts','last_received_ts'):
        out.update(status='observed',price=raw['last'],sourceAt=raw['last_ts'],receivedAt=raw.get('last_received_ts'),priceBasis='qualified_last',reason=None)
    elif all(number(raw.get(k)) for k in ('bid','ask','quote_ts')) and 0<raw['bid']<=raw['ask'] and fresh('quote_ts','quote_received_ts'):
        out.update(status='observed',price=raw['ask'],sourceAt=raw['quote_ts'],receivedAt=raw.get('quote_received_ts'),priceBasis='fresh_ask',reason=None)
    if out['status']=='observed' and number(out.get('receivedAt')):
        out['venueAheadOfReceiptMs']=max(0,out['sourceAt']-out['receivedAt'])
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
