import httpx
import pytest

from zargar.techniques.options_cartel.fundamentals import capture_fundamentals, normalize
from zargar.techniques.options_cartel.service import CartelService


@pytest.mark.parametrize('offset,expected', [(0, 'pass'), (1, 'unknown'), (-9*86_400_000, 'unknown')])
def test_capitalization_has_its_own_causal_clock(offset, expected):
    from zargar.techniques.options_cartel.rules import CartelRules
    from zargar.techniques.options_cartel.screen import screen_listing

    from .test_options_cartel_screen import inputs
    bars, facts, indices, at = inputs()
    facts = facts.model_copy(update={'observed_at': at-10*86_400_000,
        'cap_observed_at': at+offset, 'cap_data_as_of_ms': at+offset,
        'fundamentals_snapshot_id': 'capture'})
    result = screen_listing(bars, facts, indices, CartelRules(), at)
    assert next(g for g in result['gates'] if 'capitalization' in g['label'])['status'] == expected
    assert next(g for g in result['gates'] if g['label'].startswith('Industry ranks'))['status'] == 'unknown'
    if expected == 'unknown':
        assert result['facts'].get('market_cap') is None


async def test_saved_capture_applies_cap_without_inventing_industry_mapping(engine):
    from zargar.techniques.options_cartel.service import ResearchInput

    from .test_options_cartel_api import research_payload
    body = ResearchInput.model_validate(research_payload())
    at, symbol = body.as_of_ms, body.facts.symbol
    class Provider:
        async def quote_summary(self, requested, modules):
            return response(symbol=symbol, regularMarketTime=(at-1000)//1000)
    service = CartelService(engine)
    saved = await capture_fundamentals(service, symbol, provider=Provider(), clock=lambda: at)
    facts = body.facts.model_copy(update={'industry': None, 'market_cap': None})
    body = body.model_copy(update={'fundamentals_snapshot_id': saved['runId'], 'facts': facts})
    analyzed = await service.analyze(body)
    persisted = analyzed['config']['inputs']['facts']
    assert persisted['market_cap'] == 500_000_000 and persisted['industry'] is None
    assert persisted['fundamentals_snapshot_id'] == saved['runId']
    assert persisted['observed_at'] == facts.observed_at
    with pytest.raises(ValueError, match='this symbol'):
        await service.analyze(body.model_copy(update={'facts': facts.model_copy(update={'symbol': 'OTHER'})}))


def response(**price_updates):
    return {'price': {'symbol': 'MU', 'currency': 'USD', 'marketCap': {'raw': 500_000_000},
                      'regularMarketTime': 900, **price_updates},
            'assetProfile': {'industry': 'Semiconductors', 'sector': 'Technology', 'unneeded': 'omit'}}


async def test_scan_keeps_per_symbol_capture_and_retry_cutoff_with_invalid_sibling(engine):
    from zargar.techniques.options_cartel.scans import ScanRequest, retry_scan, scan_focus_list
    from zargar.techniques.options_cartel.service import ResearchInput

    from .test_options_cartel_api import research_payload

    service = CartelService(engine)
    body = ResearchInput.model_validate(research_payload())
    at = body.as_of_ms
    class Provider:
        async def quote_summary(self, symbol, modules):
            return response(symbol=symbol, regularMarketTime=(at-1000)//1000)
    capture = await capture_fundamentals(service, 'TEST', provider=Provider(), clock=lambda: at)
    ids = {'TEST': capture['runId'], 'FAIL': 'missing-capture'}
    calls = []
    async def collect(request, *, now_ms):
        calls.append((request.symbol, request.fundamentals_snapshot_id, request.as_of_ms))
        return body.model_copy(update={'fundamentals_snapshot_id': request.fundamentals_snapshot_id,
            'facts': body.facts.model_copy(update={'symbol': request.symbol})}), {'warnings': []}
    saved = await scan_focus_list(service, ScanRequest(symbols=['TEST', 'FAIL'],
        fundamentals_snapshot_ids=ids), collect=collect, now_ms=at)
    assert saved['status'] == 'done' and saved['verdict'] == 'partial'
    rows = {row['symbol']: row for row in saved['result']['rows']}
    assert rows['FAIL']['status'] == 'data_error'
    assert rows['TEST']['screen']['facts']['fundamentals_snapshot_id'] == capture['runId']
    calls.clear()
    retried = await retry_scan(service, saved['runId'], collect=collect, now_ms=at+86_400_000)
    assert calls == [('FAIL', 'missing-capture', at)]
    assert retried['config']['request']['fundamentals_snapshot_ids'] == ids
    assert retried['result']['rows'][0]['runId'] == rows['TEST']['runId']


@pytest.mark.parametrize('mapping', [{'OTHER': 'id'}, {'TEST': ''}, {'TEST': 'x'*65}])
def test_scan_rejects_unrelated_or_invalid_capture_ids(mapping):
    from zargar.techniques.options_cartel.scans import ScanRequest
    with pytest.raises(ValueError):
        ScanRequest(symbols=['TEST'], fundamentals_snapshot_ids=mapping)


def test_capitalization_dates_and_industry_suggestion_are_separate():
    result = normalize('MU', response(), observed_at=1_000_000)
    assert result['marketCapUsd'] == 500_000_000
    assert result['observedAt'] == 1_000_000 and result['providerPriceAt'] == 900_000
    assert result['providerIndustry'] == 'Semiconductors' and not result['industryMappingVerified']


@pytest.mark.parametrize('updates', [{'currency': 'CAD'}, {'regularMarketTime': None},
                                     {'regularMarketTime': 2000}, {'marketCap': {'raw': float('nan')}}])
def test_incomplete_currency_or_time_does_not_become_usable_usd_capitalization(updates):
    result = normalize('MU', response(**updates), observed_at=1_000_000)
    assert result['marketCapUsd'] is None and result['warnings']


def test_wrong_symbol_is_rejected():
    with pytest.raises(ValueError, match='symbol'):
        normalize('MU', response(symbol='OTHER'), observed_at=1_000_000)


@pytest.mark.parametrize('body', [[], {'price': [1]}])
def test_malformed_provider_shapes_are_rejected(body):
    with pytest.raises(TypeError):
        normalize('MU', body, observed_at=1_000_000)


async def test_capture_persists_only_relevant_provider_fields(engine):
    class Provider:
        async def quote_summary(self, symbol, modules):
            assert symbol == 'MU' and modules == ('price', 'assetProfile')
            return response()

    service = CartelService(engine)
    saved = await capture_fundamentals(service, 'mu', provider=Provider(), clock=lambda: 1_000_000)
    assert saved['mode'] == 'fundamentals' and saved['result']['placesOrders'] is False
    assert saved['config']['inputs']['summary']['assetProfile'] == {'industry': 'Semiconductors', 'sector': 'Technology'}
    assert (await service.detail(saved['runId']))['result'] == saved['result']


async def test_owned_client_is_closed_and_provider_url_is_not_exposed(monkeypatch):
    from zargar.techniques.options_cartel import fundamentals

    class Provider:
        closed = False
        async def quote_summary(self, symbol, modules):
            request = httpx.Request('GET', 'https://example.test/?crumb=SECRET')
            raise httpx.HTTPStatusError('SECRET', request=request, response=httpx.Response(403, request=request))
        async def aclose(self):
            self.closed = True

    provider = Provider()
    monkeypatch.setattr(fundamentals, 'EventCalendar', lambda: provider)
    with pytest.raises(ValueError) as error:
        await capture_fundamentals(None, 'MU')
    assert 'SECRET' not in str(error.value) and provider.closed
