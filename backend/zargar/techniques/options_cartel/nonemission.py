"""Evidence for SIP intervals with no price-eligible trade, never fabricated bars.

Alpaca emits no OHLCV minute when no trade can establish its prices. Provider
multi-minute bars aggregate emitted minutes only. Suppressed eligible shares are
audited separately and are NOT added to provider-bar confirmation volume.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math

import httpx

from .volume_reconstruction import VERSION as RULES_VERSION, eligibility, trade_timestamp_ns

SETTING = 'techniques.options_cartel.verified_intervals'
VERSION = 'alpaca-sip-nonemission-v1'


def groups_valid(proof):
    try:
        groups = proof.get('conditionGroups')
        if not isinstance(groups,list) or not groups:
            return False
        count = shares = 0
        for group in groups:
            if type(group['trades']) is not int or group['trades'] <= 0 or type(group['shares']) is not int or group['shares'] <= 0:
                return False
            oc,hl,vol = eligibility(group['tape'],group['conditions'])
            if oc or hl:
                return False
            count += group['trades']
            shares += group['shares'] if vol else 0
        return count == proof['tradeCount'] and shares == proof['suppressedEligibleShares']
    except (KeyError,TypeError,ValueError):
        return False


def valid(proof, symbol, minute, at):
    if not isinstance(proof, dict):
        return False
    observed = proof.get('observedAt')
    hashes = proof.get('responseHashes')
    return (proof.get('version') == VERSION and proof.get('symbol') == symbol
            and proof.get('rulesVersion') == RULES_VERSION
            and proof.get('minute') == minute and minute % 60000 == 0
            and type(observed) is int and minute+180000 <= observed <= at
            and proof.get('barsComplete') is True and proof.get('tradesComplete') is True
            and proof.get('barPresent') is False and type(proof.get('priceEligibleTrades')) is int
            and proof['priceEligibleTrades'] == 0 and type(proof.get('unknownConditions')) is int and proof['unknownConditions'] == 0
            and type(proof.get('tradeCount')) is int and proof['tradeCount'] > 0
            and type(proof.get('suppressedEligibleShares')) is int and proof['suppressedEligibleShares'] >= 0
            and groups_valid(proof)
            and isinstance(hashes, list) and len(hashes) >= 2
            and all(isinstance(h,str) and len(h)==64 and all(c in '0123456789abcdef' for c in h) for h in hashes)
            and proof.get('evidenceHash') == evidence_hash(proof))


def evidence_hash(proof):
    return hashlib.sha256(json.dumps({k:v for k,v in proof.items() if k!='evidenceHash'},
                                    sort_keys=True,separators=(',',':')).encode()).hexdigest()


def minute_set(proofs, symbol, at):
    return {p['minute'] for p in (proofs or {}).values()
            if isinstance(p,dict) and type(p.get('minute')) is int and valid(p,symbol,p['minute'],at)}


def enabled(engine, row):
    if engine.settings.get(SETTING,False) is not True:
        return False
    book = engine.positions.portfolio(row['portfolioId']) or {}
    return book.get('kind') == 'sim'


def effective(engine, row):
    return row['state'].get('verifiedIntervals',{}) if enabled(engine,row) else {}


async def verify(config, symbol, minutes, clock):
    """Bounded, owned HTTP calls. Any incomplete/unknown response refuses evidence."""
    if not config.alpaca_key_id or not config.alpaca_secret:
        return {}
    now = clock()
    selected = list(dict.fromkeys(t for t in minutes if type(t) is int and not t%60000 and t+180000<=now))[:8]
    if not selected:
        return {}
    from urllib.parse import quote
    url = 'https://data.alpaca.markets/v2/stocks/'+quote(symbol,safe='')
    iso = lambda t: dt.datetime.fromtimestamp(t/1000,dt.timezone.utc).isoformat().replace('+00:00','Z')
    headers = {'APCA-API-KEY-ID':config.alpaca_key_id,'APCA-API-SECRET-KEY':config.alpaca_secret}
    proofs = {}
    async with httpx.AsyncClient(headers=headers,timeout=10) as client:
        for minute in selected:
            params = {'start':iso(minute),'end':iso(minute+60000),'feed':'sip','limit':10000}
            bars = await client.get(url+'/bars',params={**params,'timeframe':'1Min','adjustment':'raw'})
            bars.raise_for_status()
            body = bars.json()
            if body.get('next_page_token') or 'bars' not in body or body.get('symbol',symbol)!=symbol:
                continue
            if any(minute*1000000 <= trade_timestamp_ns(b['t']) < (minute+60000)*1000000 for b in body['bars'] or []):
                continue
            trades = await client.get(url+'/trades',params=params)
            trades.raise_for_status()
            body = trades.json()
            if body.get('next_page_token') or 'trades' not in body or body.get('symbol',symbol)!=symbol:
                continue  # no pagination shortcuts; retry later, never certify a partial page
            rows = [t for t in body['trades'] or [] if minute*1000000 <= trade_timestamp_ns(t['t']) < (minute+60000)*1000000]
            if not rows:
                continue  # empty responses do not establish this positive-evidence protocol
            price_count = unknown = shares = 0
            groups = {}
            for trade in rows:
                try:
                    if not math.isfinite(trade['p']) or trade['p'] <= 0 or type(trade['s']) is not int or trade['s'] <= 0:
                        raise ValueError('Invalid trade price/size')
                    oc,hl,volume = eligibility(trade.get('z'),trade.get('c') or [])
                    key = (trade['z'],tuple(sorted(trade['c'])))
                    group = groups.setdefault(key,{'tape':key[0],'conditions':list(key[1]),'trades':0,'shares':0})
                    group['trades'] += 1; group['shares'] += trade['s']
                    price_count += int(oc or hl)
                    if volume:
                        shares += int(trade['s'])
                except (ValueError,TypeError,KeyError):
                    unknown += 1
            if price_count or unknown:
                continue
            proof = {'version':VERSION,'rulesVersion':RULES_VERSION,'symbol':symbol,'minute':minute,'observedAt':clock(),
                     'barsComplete':True,'tradesComplete':True,'barPresent':False,
                     'tradeCount':len(rows),'priceEligibleTrades':0,'unknownConditions':0,
                     'suppressedEligibleShares':shares,'conditionGroups':list(groups.values()),
                     'responseHashes':[hashlib.sha256(r.content).hexdigest() for r in (bars,trades)]}
            proof['evidenceHash'] = evidence_hash(proof)
            proofs[str(minute)] = proof
    return proofs
