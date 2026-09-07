import httpx
import pytest

from zargar.techniques.options_cartel.industry_feed import capture_industries


def payload():
    return {'totalCount': 2, 'data': [
        {'s': 'INDUSTRY_US:SOFTWARE', 'd': ['SOFTWARE', 'Software', 2.1, 4.2, None, 'streaming']},
        {'s': 'INDUSTRY_US:BANKS', 'd': ['BANKS', 'Banks', -1.2, 3.4, None, 'streaming']}]}


async def capture(data):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))) as client:
        return await capture_industries(client=client, clock=lambda: 123456)


async def test_publisher_performance_preserved_without_inventing_constituent_time():
    snapshot, raw = await capture(payload())
    assert snapshot.data_as_of_ms is None
    assert snapshot.observed_at == 123456
    assert snapshot.freshness_basis == 'publisher_observation'
    assert snapshot.rows[0].week_pct == 2.1
    assert raw['publisherRows'] == payload()['data']


@pytest.mark.parametrize('fault', ['partial', 'duplicate', 'wrong_identity', 'delayed'])
async def test_incomplete_or_unexpected_publication_rejected(fault):
    data = payload()
    if fault == 'partial':
        data['totalCount'] = 3
    elif fault == 'duplicate':
        data['data'][1]['s'] = data['data'][0]['s']
    elif fault == 'wrong_identity':
        data['data'][0]['s'] = 'NASDAQ:SOFTWARE'
    else:
        data['data'][0]['d'][-1] = 'delayed_streaming_900'
    with pytest.raises(ValueError):
        await capture(data)
