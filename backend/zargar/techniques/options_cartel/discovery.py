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


def request_body(rules: CartelRules, offset: int, size: int):
    # Do not apply current-volume filters to profiles that require average volume.
    # EMA, ADR and setup calculations remain in our completed-bar analysis.
    return {'filter': [
        {'left': 'is_primary', 'operation': 'equal', 'right': True},
        {'left': 'type', 'operation': 'in_range', 'right': ['stock', 'dr']},
        {'left': 'exchange', 'operation': 'in_range', 'right': ['NASDAQ', 'NYSE', 'AMEX']},
        {'left': 'currency', 'operation': 'equal', 'right': 'USD'},
        {'left': 'close', 'operation': 'greater', 'right': rules.min_price},
        {'left': 'market_cap_basic', 'operation': 'greater', 'right': rules.min_market_cap}],
        'options': {'lang': 'en'}, 'symbols': {'query': {'types': []}, 'tickers': []},
        'columns': list(COLUMNS), 'sort': {'sortBy': 'volume', 'sortOrder': 'desc'},
        'range': [offset, offset+size]}


def normalize(row, observed_at):
    values = row.get('d')
    if not isinstance(values, list) or len(values) != len(COLUMNS):
        raise ValueError('discovery response columns do not match the request')
    data = dict(zip(COLUMNS, values))
    symbol, exchange = data['name'], data['exchange']
    if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}', symbol) \
            or exchange not in ('NASDAQ', 'NYSE', 'AMEX') or row.get('s') != f'{exchange}:{symbol}':
        raise ValueError('discovery returned an unsupported or mismatched listing identity')
    if data['currency'] != 'USD' or data['type'] not in ('stock', 'dr'):
        raise ValueError('discovery returned a listing outside the requested equity/currency universe')
    def number(value):
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None
    stamp = number(data['time'])
    if stamp is not None and stamp > observed_at/1000:
        raise ValueError('discovery returned a future source bar timestamp')
    stamp = int(stamp*1000) if stamp is not None and stamp > 0 else None
    return {'symbol': symbol, 'exchange': exchange, 'listingId': row['s'], 'name': data['description'],
        'securityType': data['type'], 'typeDetails': data['typespecs'], 'currency': data['currency'],
        'price': number(data['close']), 'dailyVolume': number(data['volume']),
        'marketCap': number(data['market_cap_basic']), 'industry': data['industry'], 'sector': data['sector'],
        'sourceBarOpenAt': stamp, 'sourceSession': dt.datetime.fromtimestamp(stamp/1000, ET).date().isoformat() if stamp else None,
        'observedAt': observed_at, 'updateMode': data['update_mode'], 'source': URL}


async def discover_market(rules: CartelRules, *, client=None, clock=now_ms, page_size=250, max_rows=10000, pace=.25):
    if not 1 <= page_size <= 1000 or not 1 <= max_rows <= 10000 or pace < 0:
        raise ValueError('invalid discovery bounds')
    own = client is None
    client = client or httpx.AsyncClient(timeout=30.)
    started, raw, identities, expected = clock(), [], set(), None
    try:
        while expected is None or len(raw) < expected:
            response = await client.post(URL, json=request_body(rules, len(raw), page_size))
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
            if len(raw) < expected and pace:
                await asyncio.sleep(pace)
    finally:
        if own:
            await client.aclose()
    observed = clock()
    rows, excluded = [], []
    for row in raw:
        try:
            rows.append(normalize(row, observed))
        except ValueError as exc:
            excluded.append({'listingId': row['s'], 'reason': str(exc)})
    return {'source': URL, 'requestStartedAt': started, 'observedAt': observed,
        'providerTotal': expected, 'received': len(raw), 'complete': len(raw) == expected,
        'rows': rows, 'excluded': excluded, 'placesOrders': False,
        'query': request_body(rules, 0, page_size),
        'inputSha256': hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest(),
        'timestampMeaning': 'Source timestamp identifies the provider daily bar, not a live executable quote.',
        'note': 'Discovery applies only basic listing, USD price and capitalization filters; completed-bar rules still apply.'}
