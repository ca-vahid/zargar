"""Current TradingView classification, verified against the industry member table."""
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from ...domain import now_ms

ORIGIN = 'https://www.tradingview.com'
INDUSTRY = '/markets/stocks-usa/sectorandindustry-industry/'


class EvidenceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.canonicals = set()
        self.industries = set()
        self.members = set()
        self.anchor = None
        self.label = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonicals.add(attrs.get('href'))
        if tag == 'tr' and attrs.get('data-rowkey'):
            self.members.add(attrs['data-rowkey'])
        if tag == 'a':
            href = attrs.get('href', '')
            absolute = urljoin(ORIGIN, href)
            self.anchor = absolute if re.fullmatch(re.escape(ORIGIN+INDUSTRY)+r'[a-z0-9-]+/', absolute) else None
            self.label = []

    def handle_data(self, data):
        if self.anchor:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.anchor:
            label = ' '.join(''.join(self.label).split())
            if label:
                self.industries.add((self.anchor, label))
            self.anchor = None


def stock_mapping(html, source):
    parser = EvidenceParser()
    parser.feed(html)
    if parser.canonicals != {source} or len(parser.industries) != 1:
        raise ValueError('Stock page identity or industry classification is missing or ambiguous')
    return next(iter(parser.industries))


async def capture_membership(service, exchange, symbol, *, client=None, clock=now_ms):
    exchange, symbol = exchange.strip().upper(), symbol.strip().upper()
    if exchange not in ('NASDAQ', 'NYSE', 'AMEX') or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}', symbol):
        raise ValueError('Select a supported US exchange and equity symbol')
    source = f'{ORIGIN}/symbols/{exchange}-{symbol}/'
    own = client is None
    client = client or httpx.AsyncClient(timeout=25, follow_redirects=False)
    try:
        stock = await client.get(source)
        stock.raise_for_status()
        industry_url, industry = stock_mapping(stock.text, source)
        members = await client.get(industry_url)
        members.raise_for_status()
        parser = EvidenceParser()
        parser.feed(members.text)
        if parser.canonicals != {industry_url} or f'{exchange}:{symbol}' not in parser.members:
            raise ValueError('Industry member table does not confirm the requested exchange and symbol')
    except httpx.HTTPError as exc:
        raise ValueError('Industry membership source unavailable; no mapping captured') from exc
    finally:
        if own:
            await client.aclose()
    observed = clock()
    inputs = {'symbol': symbol, 'exchange': exchange, 'industry': industry, 'observedAt': observed,
              'source': source, 'industryUrl': industry_url, 'memberRowKey': f'{exchange}:{symbol}',
              'stockHtmlSha256': hashlib.sha256(stock.content).hexdigest(),
              'industryHtmlSha256': hashlib.sha256(members.content).hexdigest()}
    return await service._store(mode='membership', symbol=symbol, at=observed, verdict='verified',
        result={**inputs, 'placesOrders': False, 'verification': 'stock link and industry member row agree',
                'warning': 'Current classification observed at capture time; no historical effective date is inferred.'},
        config={'inputs': inputs, 'inputSha256': hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
                'dataSource': source, 'codeVersion': 'cartel-membership-1'})
