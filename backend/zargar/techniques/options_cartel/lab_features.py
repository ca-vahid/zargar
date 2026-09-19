"""Dated advisory features for method-lab selection, not new production gates."""
from __future__ import annotations

from statistics import mean

from ...marketstructure.indicators import ema_series
from .data import DailyBar, completed_daily
from .shadow_entries import digest

VERSION='cartel-lab-features-v1'


def selection_features(history: list[DailyBar], as_of: int):
    bars=completed_daily(history,as_of)
    output={'version':VERSION,'asOf':as_of,'lastSession':bars[-1].session.isoformat() if bars else None,
        'bars':len(bars),'adr20Pct':None,'base10RangePct':None,'baseRangeAdr':None,
        'recent5RangeAdr':None,'volume5Vs20':None,'compressionSessions':None,
        'emas':{},'emaSlope5Pct':{},'sma200':None,'aboveSma200':None,
        'revenueGrowth':'unknown_not_supplied','stage':'not_classified',
        'placesOrders':False,'inputSha256':digest([b.model_dump(mode='json') for b in bars])}
    if not bars: return output
    closes=[b.close for b in bars]
    for p in (8,21,50):
        values=ema_series(closes,p)
        output['emas'][str(p)]=values[-1]
        output['emaSlope5Pct'][str(p)]=(values[-1]/values[-6]-1)*100 \
            if len(values)>=6 and values[-1] is not None and values[-6] else None
    if len(bars)>=200:
        output['sma200']=mean(closes[-200:]);output['aboveSma200']=closes[-1]>output['sma200']
    if len(bars)<20: return output
    adr=mean((b.high-b.low)/b.low*100 for b in bars[-20:])
    span=lambda subset:(max(b.high for b in subset)-min(b.low for b in subset))/min(b.low for b in subset)*100
    base_range=span(bars[-10:]);volume20=mean(b.volume for b in bars[-20:])
    output.update(adr20Pct=adr,base10RangePct=base_range,baseRangeAdr=base_range/adr if adr else None,
                  recent5RangeAdr=span(bars[-5:])/adr if adr else None,
                  volume5Vs20=mean(b.volume for b in bars[-5:])/volume20 if volume20 else None)
    # A measured suffix under a fixed range bound, not a claim that the full
    # formation is a mature author-approved base. Bound fixed before outcomes.
    count=0
    if adr:
        for n in range(1,min(60,len(bars))+1):
            if span(bars[-n:])>1.5*adr: break
            count=n
    output['compressionSessions']=count
    output['compressionDefinition']='Longest recent suffix, capped at 60 completed sessions, with full range <=1.5x ADR20; engineering interpretation of provisional mirrored guidance.'
    return output


def compression_order(candidates):
    def key(c):
        f=c.get('labFeatures') or {};rank=c.get('ranking') or {}
        ratio=f.get('recent5RangeAdr');strength=rank.get('directionalRelativeStrength')
        return (ratio is None,ratio if ratio is not None else float('inf'),
                -strength if strength is not None else float('inf'),c['symbol'],c['id'])
    return [c['id'] for c in sorted(candidates,key=key) if (c.get('labFeatures') or {}).get('recent5RangeAdr') is not None]
