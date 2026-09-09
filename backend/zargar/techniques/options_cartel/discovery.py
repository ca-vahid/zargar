"""Cartel market discovery from the publisher's primary US listing screener."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import math
import re

import httpx

from ...domain import now_ms
from ...marketstructure.sessions import ET
from .rules import CartelRules

URL = 'https://scanner.tradingview.com/america/scan'
COLUMNS = ('name', 'description', 'type', 'typespecs', 'close', 'volume', 'market_cap_basic',
           'industry', 'sector', 'exchange', 'currency', 'time', 'update_mode')


def request_body(rules: CartelRules, offset: int, size: int, *, funds_only=False):
    # Do not apply current-volume filters to profiles that require average volume.
    # EMA, ADR and setup calculations remain in our completed-bar analysis.
    body = {'filter': [
        {'left': 'is_primary', 'operation': 'equal', 'right': True},
        {'left': 'type', 'operation': 'in_range', 'right': ['stock', 'dr']},
        {'left': 'exchange', 'operation': 'in_range', 'right': ['NASDAQ', 'NYSE', 'AMEX']},
        {'left': 'currency', 'operation': 'equal', 'right': 'USD'},
        {'left': 'close', 'operation': 'greater', 'right': rules.min_price},
        {'left': 'market_cap_basic', 'operation': 'greater', 'right': rules.min_market_cap}],
        'options': {'lang': 'en'}, 'symbols': {'query': {'types': []}, 'tickers': []},
        'columns': list(COLUMNS), 'sort': {'sortBy': 'volume', 'sortOrder': 'desc'},
        'range': [offset, offset+size]}
    if funds_only:
        body['filter'] = [f for f in body['filter'] if f['left'] not in ('type', 'market_cap_basic')]
        body['symbols']['query']['types'] = ['fund']
        next(f for f in body['filter'] if f['left'] == 'exchange')['right'] = ['NASDAQ', 'NYSE', 'AMEX', 'CBOE']
        body['filter'] += [{'left': 'type', 'operation': 'equal', 'right': 'fund'},
                           {'left': 'name', 'operation': 'in_range', 'right': list(rules.reviewed_etfs)}]
    return body


def normalize(row, observed_at, reviewed_etfs=()):
    values = row.get('d')
    if not isinstance(values, list) or len(values) != len(COLUMNS):
        raise ValueError('discovery response columns do not match the request')
    data = dict(zip(COLUMNS, values))
    symbol, exchange = data['name'], data['exchange']
    etf = data['type'] == 'fund' and symbol in reviewed_etfs and 'etf' in (data['typespecs'] or [])
    if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}', symbol) \
            or exchange not in (('NASDAQ', 'NYSE', 'AMEX', 'CBOE') if etf else ('NASDAQ', 'NYSE', 'AMEX')) or row.get('s') != f'{exchange}:{symbol}':
        raise ValueError('discovery returned an unsupported or mismatched listing identity')
    if data['currency'] != 'USD' or not (data['type'] in ('stock', 'dr') or etf):
        raise ValueError('discovery returned a listing outside the requested equity/currency universe')
    def number(value):
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None
    stamp = number(data['time'])
    if stamp is not None and stamp > observed_at/1000:
        raise ValueError('discovery returned a future source bar timestamp')
    stamp = int(stamp*1000) if stamp is not None and stamp > 0 else None
    return {'symbol': symbol, 'exchange': exchange, 'listingId': row['s'], 'name': data['description'],
        'securityType': 'etf' if etf else data['type'], 'typeDetails': data['typespecs'], 'currency': data['currency'],
        'price': number(data['close']), 'dailyVolume': number(data['volume']),
        'marketCap': number(data['market_cap_basic']), 'industry': data['industry'], 'sector': data['sector'],
        'sourceBarOpenAt': stamp, 'sourceSession': dt.datetime.fromtimestamp(stamp/1000, ET).date().isoformat() if stamp else None,
        'observedAt': observed_at, 'updateMode': data['update_mode'], 'source': URL}


async def discover_market(rules: CartelRules, *, client=None, clock=now_ms, page_size=250, max_rows=10000, pace=.25, on_progress=None, funds_only=False):
    if not 1 <= page_size <= 1000 or not 1 <= max_rows <= 10000 or pace < 0:
        raise ValueError('invalid discovery bounds')
    own = client is None
    client = client or httpx.AsyncClient(timeout=30.)
    started, raw, identities, expected = clock(), [], set(), None
    try:
        while expected is None or len(raw) < expected:
            if on_progress:
                await on_progress({'received': len(raw), 'total': expected, 'message': f'Requesting discovery page {len(raw)//page_size+1}'})
            response = await client.post(URL, json=request_body(rules, len(raw), page_size, funds_only=funds_only))
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError('invalid discovery page envelope')  # noqa: TRY004 - external data validation
            total, page = body.get('totalCount'), body.get('data')
            if not isinstance(total, int) or isinstance(total, bool) or total < 0 or not isinstance(page, list):
                raise ValueError('invalid discovery page envelope')
            if total > max_rows:
                raise ValueError(f'discovery universe exceeds the {max_rows}-listing limit; no partial universe accepted')
            if expected is not None and total != expected:
                raise ValueError('discovery universe changed during pagination; rerun after the data stabilizes')
            expected = total
            if len(page) > page_size or len(raw)+len(page) > expected or not page and len(raw) < expected:
                raise ValueError('incomplete or inconsistent discovery pagination')
            for row in page:
                identity = row.get('s') if isinstance(row, dict) else None
                if not isinstance(identity, str) or identity in identities:
                    raise ValueError('duplicate or missing discovery identity; no partial universe accepted')
                identities.add(identity); raw.append(row)
            if on_progress:
                await on_progress({'received': len(raw), 'total': expected, 'message': f'Received {len(raw)} of {expected} listings'})
            if len(raw) < expected and pace:
                await asyncio.sleep(pace)
    finally:
        if own:
            await client.aclose()
    observed = clock()
    rows, excluded = [], []
    for row in raw:
        try:
            rows.append(normalize(row, observed, rules.reviewed_etfs))
        except ValueError as exc:
            excluded.append({'listingId': row['s'], 'reason': str(exc)})
    result = {'source': URL, 'requestStartedAt': started, 'observedAt': observed,
        'providerTotal': expected, 'received': len(raw), 'complete': len(raw) == expected,
        'rows': rows, 'excluded': excluded, 'placesOrders': False,
        'query': request_body(rules, 0, page_size, funds_only=funds_only),
        'inputSha256': hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest(),
        'timestampMeaning': 'Source timestamp identifies the provider daily bar, not a live executable quote.',
        'note': 'Discovery applies only basic listing, USD price and capitalization filters; completed-bar rules still apply.'}

    if rules.reviewed_etfs and not funds_only:
        funds = await discover_market(rules, client=None if own else client, clock=clock, page_size=page_size,
            max_rows=max_rows, pace=pace, funds_only=True)
        result['observedAt'] = max(result['observedAt'], funds['observedAt'])
        result['rows'] += funds['rows']
        if len({r['symbol'] for r in result['rows']}) != len(result['rows']):
            raise ValueError('Stock/ETF discovery returned duplicate symbols; no ambiguous universe accepted')
        if result['received']+funds['received'] > max_rows:
            raise ValueError('Combined stock/ETF universe exceeds the configured discovery limit')
        result['rows'].sort(key=lambda r: -(r.get('dailyVolume') or 0))
        result['providerTotal'] += funds['providerTotal']; result['received'] += funds['received']
        result['excluded'] += funds['excluded']
        result['etfQuery'] = funds['query']
        result['inputSha256'] = hashlib.sha256((result['inputSha256']+funds['inputSha256']).encode()).hexdigest()
    return result
