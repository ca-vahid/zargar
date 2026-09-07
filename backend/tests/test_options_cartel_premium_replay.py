import pytest

from zargar.techniques.options_cartel.premium_replay import PremiumReplayInput, value_campaign

from .test_options_cartel_api import client as _client_fixture
from .test_options_cartel_entry import OPEN

client = _client_fixture


def valuation(*, quotes=None, contract='HOOD260515C00050000', **updates):
    return PremiumReplayInput(contract_symbol=contract, source='synthetic recorded bid/ask fixture',
        quotes=quotes or [{'sourceAt': OPEN+i*60_000, 'availableAt': OPEN+i*60_000,
                         'bid': bid, 'ask': ask} for i, bid, ask in [(10, 1.1, 1.2), (11, 1.8, 1.9), (12, 1.4, 1.5)]],
        fee_per_contract=.5, **updates)


def campaign():
    return {'dataComplete': True, 'fills': [
        {'kind': 'entry', 'at': OPEN+10*60_000, 'qty': 4},
        {'kind': 'target1', 'at': OPEN+11*60_000, 'qty': 1},
        {'kind': 'stop', 'at': OPEN+12*60_000, 'qty': 3}]}


@pytest.mark.parametrize('direction,right', [('long', 'C'), ('short', 'P')])
def test_bid_ask_partial_exits_and_fees_use_long_premium_for_calls_and_puts(direction, right):
    result = value_campaign(campaign(), valuation(contract=f'HOOD260515{right}00050000'),
                            symbol='HOOD', direction=direction, as_of_ms=OPEN+13*60_000)
    assert result['status'] == 'closed' and result['placesOrders'] is False
    assert result['totalPnl'] == pytest.approx(116.) and result['fees'] == 4
    assert result['returnOnDebitPct'] == pytest.approx(116/482*100)
    assert [f['premium'] for f in result['fills']] == [1.2, 1.8, 1.4]


@pytest.mark.parametrize('change', [{'available_at': OPEN+10*60_000+1},
    {'source_at': OPEN+9*60_000}, {'delayed': True}, {'bid': 0}])
def test_unavailable_stale_delayed_or_zero_bid_quote_cannot_manufacture_return(change):
    body = valuation()
    body.quotes[0] = body.quotes[0].model_copy(update=change)
    result = value_campaign(campaign(), body, symbol='HOOD', direction='long', as_of_ms=OPEN+13*60_000)
    assert result['status'] == 'incomplete' and result['totalPnl'] is None


def test_open_position_mark_allocates_entry_fees_without_inventing_future_exit_fees():
    replay = campaign(); replay['fills'].pop()
    result = value_campaign(replay, valuation(), symbol='HOOD', direction='long', as_of_ms=OPEN+12*60_000)
    assert result['remainingQty'] == 3 and result['fees'] == 2.5
    assert result['realizedPnl'] == pytest.approx(59.)
    assert result['openPnl'] == pytest.approx(58.5)


def test_wrong_contract_or_conflicting_quotes_are_rejected():
    with pytest.raises(ValueError, match='contract'):
        value_campaign(campaign(), valuation(contract='MU260515C00050000'), symbol='HOOD', direction='long', as_of_ms=OPEN)
    body = valuation(); body.quotes.append(body.quotes[0].model_copy(update={'bid': 1.15}))
    with pytest.raises(ValueError, match='conflicting'):
        value_campaign(campaign(), body, symbol='HOOD', direction='long', as_of_ms=OPEN)


def test_expired_contract_and_incomplete_underlying_replay_have_no_total_return():
    body = valuation(contract='HOOD260501C00050000')
    assert value_campaign(campaign(), body, symbol='HOOD', direction='long', as_of_ms=OPEN+13*60_000)['totalPnl'] is None
    replay = campaign(); replay['dataComplete'] = False
    assert value_campaign(replay, valuation(), symbol='HOOD', direction='long', as_of_ms=OPEN+13*60_000)['totalPnl'] is None


@pytest.mark.parametrize('changes', [{'source_at': None}, {'halted': True}, {'bid': 2, 'ask': 1}, {'bid': 0, 'ask': 0},
                                    {'source_at': OPEN, 'delayed': True}])
def test_new_unusable_observation_blocks_fallback_to_older_favorable_quote(changes):
    body = valuation()
    prior = body.quotes[0].model_copy(update={'available_at': OPEN+10*60_000-1, 'source_at': OPEN+10*60_000-1})
    body.quotes[0] = body.quotes[0].model_copy(update=changes)
    body.quotes.append(prior)
    result = value_campaign(campaign(), body, symbol='HOOD', direction='long', as_of_ms=OPEN+13*60_000)
    assert result['totalPnl'] is None and result['status'] == 'incomplete'


async def test_api_persists_owned_valuation_without_modifying_parent_or_creating_orders(client):
    from sqlalchemy import func, select

    from zargar.models import Order
    from zargar.techniques.options_cartel.service import CartelService

    http, engine = client
    service = CartelService(engine)
    original = campaign()
    parent = await service._store(mode='replay', symbol='HOOD', at=OPEN+13*60_000,
        verdict='closed', result=original, config={'planSnapshot': {'plan': {'direction': 'long'}}})
    response = await http.post(f"/api/options-cartel/runs/{parent['runId']}/premium-replay",
                               json=valuation().model_dump(mode='json', by_alias=True))
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['mode'] == 'premium_replay' and saved['parentRunId'] == parent['runId']
    assert saved['result']['totalPnl'] == pytest.approx(116.)
    assert (await service.detail(parent['runId']))['result'] == original
    assert saved['config']['underlyingReplay'] == original
    async with engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(Order)) == 0


async def test_stored_quote_valuation_is_plan_scoped_and_preserves_observation_ids(client):
    from zargar.domain import Quote
    from zargar.techniques.options_cartel.quote_observations import capture_cached_quote
    from zargar.techniques.options_cartel.service import CartelService

    http, engine = client
    service = CartelService(engine)
    plan = await service._store(mode='plan', symbol='HOOD', at=OPEN, verdict='plan', result={}, config={})
    replay = await service._store(mode='replay', symbol='HOOD', at=OPEN+13*60_000, parent=plan['runId'],
        verdict='closed', result=campaign(), config={'planSnapshot': {'plan': {'direction': 'long'}}})
    body = valuation()
    ids = []
    for q in body.quotes:
        engine.quotes.on_quote(Quote(body.contract_symbol, bid=q.bid, ask=q.ask, ts=q.available_at,
                                    source='opra', source_ts=q.source_at))
        saved = await capture_cached_quote(service, plan['runId'], body.contract_symbol, clock=lambda q=q: q.available_at)
        ids.append(saved['id'])
    response = await http.post(f"/api/options-cartel/runs/{replay['runId']}/premium-replay-stored",
        json={'contractSymbol': body.contract_symbol, 'feePerContract': .5})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['result']['totalPnl'] == pytest.approx(116.)
    assert saved['config']['quoteObservationIds'] == ids
    other = await service._store(mode='plan', symbol='HOOD', at=OPEN, verdict='plan', result={}, config={})
    other_replay = await service._store(mode='replay', symbol='HOOD', at=OPEN+13*60_000, parent=other['runId'],
        verdict='closed', result=campaign(), config={'planSnapshot': {'plan': {'direction': 'long'}}})
    response = await http.post(f"/api/options-cartel/runs/{other_replay['runId']}/premium-replay-stored",
        json={'contractSymbol': body.contract_symbol})
    assert response.status_code == 200 and response.json()['result']['totalPnl'] is None
    assert response.json()['config']['quoteObservationIds'] == []
