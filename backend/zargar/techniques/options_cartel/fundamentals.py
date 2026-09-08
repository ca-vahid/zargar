"""Current provider evidence; never backdate observation or infer industry membership."""
from __future__ import annotations

import hashlib
import json
import math
import re

import httpx

from ...calendar_service import EventCalendar
from ...domain import now_ms


def number(value):
    value = value.get('raw') if isinstance(value, dict) else value
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        converted = float(value)
    except OverflowError:
        return None
    return converted if math.isfinite(converted) else None


def normalize(symbol, summary, *, observed_at):
    if not isinstance(summary, dict):
        raise TypeError('invalid fundamentals response')
    price = summary.get('price') or {}
    profile = summary.get('assetProfile') or {}
    if not isinstance(price, dict) or not isinstance(profile, dict):
        raise TypeError('invalid fundamentals response')
    returned = price.get('symbol')
    if not isinstance(returned, str) or returned.upper() != symbol:
        raise ValueError('fundamentals provider returned a different or missing symbol')
    reported = number(price.get('marketCap'))
    quote_time = number(price.get('regularMarketTime'))
    quote_at = int(quote_time*1000) if quote_time is not None and 0 < quote_time <= observed_at/1000 else None
    currency = price.get('currency')
    warnings = []
    cap = reported if reported is not None and reported > 0 and currency == 'USD' else None
    if cap is None:
        warnings.append('Positive USD capitalization is unavailable; no currency conversion was inferred.')
    if quote_at is None or quote_at > observed_at:
        cap = None
        warnings.append('Provider price time is missing or future-dated; capitalization cannot qualify a screen.')
    return {'symbol': symbol, 'observedAt': observed_at, 'providerPriceAt': quote_at,
            'currency': currency, 'reportedMarketCap': reported, 'marketCapUsd': cap,
            'providerIndustry': profile.get('industry'), 'providerSector': profile.get('sector'),
            'industryMappingVerified': False, 'source': 'Yahoo quoteSummary price and assetProfile',
            'warnings': warnings, 'placesOrders': False}


async def capture_fundamentals(service, symbol, *, provider=None, clock=now_ms):
    symbol = symbol.strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}', symbol):
        raise ValueError('unsupported US equity symbol')
    own = provider is None
    provider = provider or EventCalendar()
    try:
        summary = await provider.quote_summary(symbol, ('price', 'assetProfile'))
        result = normalize(symbol, summary, observed_at=clock())
    except (httpx.HTTPError, TypeError) as exc:
        raise ValueError('Fundamentals provider is unavailable; no evidence was captured.') from exc
    finally:
        if own:
            await provider.aclose()
    evidence = {'price': {key: summary['price'].get(key) for key in
        ('symbol', 'currency', 'marketCap', 'regularMarketTime')},
        'assetProfile': {key: (summary.get('assetProfile') or {}).get(key) for key in ('industry', 'sector')}}
    inputs = {'symbol': symbol, 'observedAt': result['observedAt'], 'summary': evidence}
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    return await service._store(mode='fundamentals', symbol=symbol, at=result['observedAt'],
        verdict='captured' if result['marketCapUsd'] is not None else 'incomplete', result=result,
        config={'inputs': inputs, 'inputSha256': digest, 'dataSource': result['source'],
                'codeVersion': 'cartel-fundamentals-1'})
