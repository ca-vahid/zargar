import httpx
import pytest

from zargar.techniques.options_cartel.discovery import COLUMNS, discover_market, normalize, request_body
from zargar.techniques.options_cartel.rules import CartelRules


def listing(symbol, **changes):
    fields = {'name': symbol, 'description': symbol+' company', 'type': 'stock', 'typespecs': ['common'],
        'close': 10., 'volume': 100, 'market_cap_basic': 500_000_000, 'industry': 'Semiconductors',
        'sector': 'Electronic technology', 'exchange': 'NASDAQ', 'currency': 'USD', 'time': 100,
        'update_mode': 'delayed_streaming_900', **changes}
    return {'s': 'NASDAQ:'+symbol, 'd': [fields[k] for k in COLUMNS]}


def test_discovery_does_not_replace_cartel_with_most_active_or_current_volume_filter():
    query = request_body(CartelRules.for_profile('september_2026_video'), 250, 250)
    assert query['range'] == [250, 500]
    filters = {f['left']: f['right'] for f in query['filter']}
    assert filters['market_cap_basic'] == 300_000_000 and filters['close'] == 3
    assert 'volume' not in filters and 'relative_volume_10d_calc' not in filters


async def test_all_pages_are_collected_with_a_shared_capture_cutoff():
    calls = []
    progress = []
    async def on_progress(value):
        progress.append(value)
    def respond(request):
        import json
        body = json.loads(request.content)
        calls.append(body['range'])
        rows = [listing('AAA'), listing('BBB'), listing('CCC')]
        return httpx.Response(200, json={'totalCount': 3, 'data': rows[body['range'][0]:body['range'][1]]})
    times = iter([200_000, 201_000])
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await discover_market(CartelRules(), client=client, clock=lambda: next(times), page_size=2, pace=0, on_progress=on_progress)
    assert calls == [[0, 2], [2, 4]]
    assert progress[0]['total'] is None
    assert any(p['received'] == 2 and p['total'] == 3 for p in progress)
    assert progress[-1]['received'] == progress[-1]['total'] == 3
    assert result['complete'] and result['received'] == 3 and not result['excluded']
    assert {r['observedAt'] for r in result['rows']} == {201_000}
    assert result['rows'][0]['sourceBarOpenAt'] == 100_000
    assert result['rows'][0]['dailyVolume'] == 100  # averages evaluated from history later


@pytest.mark.parametrize('second', [
    {'totalCount': 2, 'data': [listing('AAA')]},
    {'totalCount': 3, 'data': [listing('BBB')]},
    {'totalCount': 2, 'data': []},
])
async def test_duplicate_changed_or_missing_pages_cannot_be_reported_as_complete(second):
    responses = iter([{'totalCount': 2, 'data': [listing('AAA')]}, second])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=next(responses)))) as client:
        with pytest.raises(ValueError):
            await discover_market(CartelRules(), client=client, clock=lambda: 200_000, page_size=1, pace=0)


def test_missing_provider_time_is_not_replaced_with_capture_time():
    result = normalize(listing('AAA', time=None), 200_000)
    assert result['observedAt'] == 200_000 and result['sourceBarOpenAt'] is None


@pytest.mark.parametrize('changes', [{'time': 300}, {'currency': 'EUR'}, {'exchange': 'NYSE'}])
def test_inconsistent_provider_metadata_is_rejected(changes):
    with pytest.raises(ValueError):
        normalize(listing('AAA', **changes), 200_000)
