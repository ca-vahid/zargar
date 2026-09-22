import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from zargar.domain import Quote
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.plans import CartelPlan
from zargar.techniques.options_cartel.research_quotes import observe_contract, snapshot_quote

NOW = int(dt.datetime(2026, 9, 16, 15, tzinfo=dt.UTC).timestamp()*1000)
CONTRACT = 'TEST261016C00100000'


def fixture(ask=1.25, cash=10000):
    quote = Quote(CONTRACT, bid=ask*.95, ask=ask, bid_size=10, ask_size=10, source='opra', source_ts=NOW, ts=NOW)
    book = {'id': 'cartel', 'kind': 'sim', 'cash': cash, 'baseCurrency': 'USD'}
    engine = SimpleNamespace(settings={}, quotes={CONTRACT: quote},
        positions=SimpleNamespace(portfolio=lambda _: book, equity=AsyncMock(return_value=10000),
            fx=SimpleNamespace(rate=lambda *args: 1)), orders=SimpleNamespace(place=AsyncMock()))
    policy = PreparationPolicy(portfolio_id='cartel')
    plan = CartelPlan(id='research', symbol='TEST', direction='long', setup='base', created_at=NOW-3600000,
        first_session=dt.date(2026,9,16), last_session=dt.date(2026,9,16), trigger=100, invalidation=99,
        targets=(105,), source_refs=('research',), rationale='Fixture', baseline_as_of=NOW-3600000)
    async def choose(*args):
        return {'candidates': [{'symbol': CONTRACT, 'bid': quote.bid, 'ask': quote.ask, 'delta': .5,
            'openInterest': 500, 'quoteAsOf': NOW, 'deltaAsOf': NOW, 'quoteSource': 'opra'}],
            'warnings': [], 'searchComplete': True}
    return engine, policy, plan, choose, quote, book


async def test_research_quantity_includes_fees_and_never_reserves_or_orders():
    engine, policy, plan, choose, _, _ = fixture()
    result = await observe_contract(engine, plan, policy, lambda: NOW, choose=choose)
    assert result['status'] == 'observed'
    assert result['funding']['quantity'] == 3  # 4 x $125 would exceed $500 once fees are included
    assert result['funding']['estimatedDebit'] == pytest.approx(378.12)
    assert result['funding']['reserved'] is False
    assert result['placesOrders'] is False
    engine.orders.place.assert_not_awaited()


async def test_displayed_size_caps_research_quantity_and_unknown_source_is_not_fresh():
    engine, policy, plan, choose, quote, _ = fixture()
    quote.ask_size = 1
    result = await observe_contract(engine, plan, policy, lambda: NOW, choose=choose)
    assert result['funding']['quantity'] == 1
    quote.source_ts = 0
    assert snapshot_quote(engine, CONTRACT, lambda: NOW)['status'] == 'unavailable'
    quote.source_ts = NOW
    quote.source = 'sim'
    assert snapshot_quote(engine, CONTRACT, lambda: NOW)['status'] == 'unavailable'


async def test_affordability_requires_all_other_contract_filters_and_a_current_quote():
    engine, policy, plan, choose, quote, _ = fixture(ask=6)
    result = await observe_contract(engine, plan, policy, lambda: NOW, choose=choose)
    assert result['affordabilityOnly'] is True
    quote.bid = 1  # wide spread is an independent failure, not an affordability-only case
    result = await observe_contract(engine, plan, policy, lambda: NOW, choose=choose)
    assert result['affordabilityOnly'] is False
    quote.bid = 5.8
    quote.source_ts = NOW-20000
    result = await observe_contract(engine, plan, policy, lambda: NOW, choose=choose)
    assert result['affordabilityOnly'] is False


async def test_missing_funding_or_archived_book_does_not_request_contracts():
    engine, policy, plan, choose, _, book = fixture()
    selector = AsyncMock(side_effect=choose)
    book['archived'] = True
    assert (await observe_contract(engine, plan, policy, lambda: NOW, choose=selector))['status'] == 'unavailable'
    selector.assert_not_awaited()
    book['archived'] = False
    book['cash'] = 0
    result = await observe_contract(engine, plan, policy, lambda: NOW, choose=selector)
    assert result['status'] == 'budget_unavailable' and result['affordabilityOnly'] is False
    selector.assert_not_awaited()


# ---- 2026-09-21 brief F2/F3: the observer forwards the reviewed contract, deadline and cash basis ----

async def test_observer_forwards_preferred_contract_deadline_and_economics_and_keeps_unrefreshed_rows():
    from zargar.techniques.options_cartel.contracts import SelectionRequest
    engine, policy, plan, choose, quote, _ = fixture()
    seen = {}

    async def selector(eng, p, pol, request):
        seen['request'] = request
        base = await choose(eng, p, pol)
        base['candidates'] = base['candidates']+[{'symbol': 'TEST261120C00100000', 'expiry': '2026-11-20', 'dte': 65,
            'openInterest': 5, 'liquidity': 'known_failure', 'refreshed': False, 'eligible': False,
            'reasons': ['open interest does not meet reviewed liquidity requirement', 'not refreshed: known static failure']}]
        return base
    result = await observe_contract(engine, plan, policy, lambda: NOW, choose=selector, preferred=CONTRACT, deadline_ms=NOW+120000)
    request = seen['request']
    assert isinstance(request, SelectionRequest) and request.preferred_contract == CONTRACT and request.deadline_ms == NOW+120000
    assert request.economics.cash_cap_usd == pytest.approx(500) and request.economics.max_units == policy.max_contracts
    assert request.economics.entry_fee_per_contract_usd == pytest.approx(1.04)
    assert result['status'] == 'observed' and result['selected']['symbol'] == CONTRACT
    unrefreshed = [c for c in result['selection']['candidates'] if c['symbol'] == 'TEST261120C00100000']
    assert unrefreshed and unrefreshed[0]['refreshed'] is False and unrefreshed[0]['eligible'] is False
    assert result['selected']['economics']['status'] == 'estimated'
