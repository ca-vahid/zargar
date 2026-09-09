import datetime as dt

import httpx
import pytest

from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.discovery import discover_market, normalize, request_body
from zargar.techniques.options_cartel.plans import CartelPlan
from zargar.techniques.options_cartel.preparation_readiness import (
    entry_readiness,
    load_session_context,
    retain_decisions,
)
from zargar.techniques.options_cartel.rules import CartelRules
from zargar.techniques.options_cartel.screen import screen_listing
from zargar.techniques.options_cartel.sweeps import SweepVariant, evaluate_sweep

from .test_options_cartel_discovery import listing
from .test_options_cartel_prepare import input_data
from .test_options_cartel_sweeps import snapshot


def test_etf_is_explicit_and_market_cap_exemption_does_not_apply_to_stocks():
    args = input_data()
    rules = args['rules'].model_copy(update={'reviewed_etfs': ('TEST',)})
    facts = args['facts'].model_copy(update={'security_type': 'etf', 'market_cap': None})
    report = screen_listing(args['history'], facts, args['indices'], rules, args['as_of_ms'])
    assert next(g for g in report['gates'] if 'ETF' in g['label'])['status'] == 'pass'
    facts = facts.model_copy(update={'security_type': 'stock'})
    report = screen_listing(args['history'], facts, args['indices'], rules, args['as_of_ms'])
    assert next(g for g in report['gates'] if 'capitalization' in g['label'])['status'] == 'unknown'
    fund = listing('DRAM', type='fund', typespecs=['etf'], market_cap_basic=None)
    fund['s'] = 'CBOE:DRAM'
    from zargar.techniques.options_cartel.discovery import COLUMNS
    fund['d'][COLUMNS.index('exchange')] = 'CBOE'
    assert normalize(fund, 200000, ('DRAM',))['securityType'] == 'etf'
    with pytest.raises(ValueError):
        normalize(fund, 200000)
    filters = request_body(rules, 0, 250, funds_only=True)['filter']
    assert not any(f['left'] == 'market_cap_basic' for f in filters)


async def test_discovery_combines_reviewed_etfs_and_stocks():
    import json
    def response(request):
        filters = json.loads(request.content)['filter']
        fund = any(f['left'] == 'name' for f in filters)
        row = listing('DRAM', type='fund', typespecs=['etf'], market_cap_basic=None) if fund else listing('TEST')
        return httpx.Response(200, json={'totalCount': 1, 'data': [row]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        result = await discover_market(CartelRules(reviewed_etfs=('DRAM',)), client=client, clock=lambda: 200000)
    assert result['providerTotal'] == result['received'] == 2
    assert {r['symbol'] for r in result['rows']} == {'DRAM', 'TEST'}


def plan():
    p = CartelPlan.model_validate(snapshot()['config']['planSnapshot']['plan'])
    return p.model_copy(update={'volume_baseline': {i: 100 for i in range(390//p.entry.timeframe_minutes)}})


def test_pending_arm_blocks_stale_target_gaps_and_sparse_baselines():
    p = plan()
    opens, _ = session_bounds(p.first_session.isoformat())
    assert entry_readiness(p, [], opens-60000)['ready']
    assert not entry_readiness(p.model_copy(update={'volume_baseline': {0: 100}}), [], opens-60000)['ready']
    price = p.trigger
    tape = [Bar(p.symbol, '1m', opens+i*60000, price, price, price, price, 100) for i in range(15)]
    assert entry_readiness(p, tape, opens+15*60000)['ready']
    assert not entry_readiness(p, tape[1:], opens+15*60000)['ready']
    tape[-1] = Bar(p.symbol, '1m', tape[-1].ts, p.targets[0], p.targets[0], p.targets[0], p.targets[0], 100)
    assert any('First target' in r for r in entry_readiness(p, tape, opens+15*60000)['reasons'])


def test_restart_preserves_and_deduplicates_rejection_explanations():
    rejection = {'at': 100, 'decision': 'watch_only', 'reason': 'Close quality below threshold'}
    first = retain_decisions([], {'trace': [rejection]})
    assert retain_decisions(first, {'trace': []}) == first
    assert retain_decisions(first, {'trace': [rejection]}) == first


async def test_pending_context_backfill_is_bounded_and_does_not_write_shared_bars(engine):
    from sqlalchemy import func, select

    from zargar.models import BarRow
    p = plan()
    opens, _ = session_bounds(p.first_session.isoformat())
    async def fetch(symbol, tf, start, end, *, client):
        assert symbol == p.symbol and tf == '1m' and start == opens and end == opens+900000
        return [Bar(symbol, tf, opens+i*60000, p.trigger, p.trigger, p.trigger, p.trigger, 100) for i in range(15)]
    context = await load_session_context(engine, p, opens+900000, fetch=fetch)
    assert len(context) == 15 and entry_readiness(p, context, opens+900000)['ready']
    async with engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(BarRow).where(BarRow.symbol == p.symbol)) == 0


def test_timeframe_comparison_requires_its_own_historical_baseline():
    saved = snapshot()
    original = CartelPlan.model_validate(saved['config']['planSnapshot']['plan'])
    new_tf = 15 if original.entry.timeframe_minutes == 5 else 5
    with pytest.raises(ValueError, match='baseline minutes'):
        evaluate_sweep([saved], [SweepVariant(name='other timeframe', timeframe_minutes=new_tf)])
    source = []
    day = original.first_session-dt.timedelta(days=1)
    while len(source) < 5*390:
        if day.weekday() < 5:
            opens, _ = session_bounds(day.isoformat())
            source.extend({'ts': opens+i*60000, 'open': 100, 'high': 101, 'low': 99, 'close': 100, 'volume': 10} for i in range(390))
        day -= dt.timedelta(days=1)
    saved['config']['baselineMinutes'] = source
    result = evaluate_sweep([saved], [SweepVariant(name='other timeframe', timeframe_minutes=new_tf, mode='retest')])
    assert result['placesOrders'] is False
    assert result['rows'][1]['entryPolicy']['timeframe_minutes'] == new_tf
    assert saved['config']['planSnapshot']['plan']['entry']['timeframe_minutes'] == original.entry.timeframe_minutes


def test_comparison_list_needs_source_and_policy_is_explicit():
    with pytest.raises(ValueError, match='dated source'):
        PreparationPolicy(comparison_symbols=('MU',), comparison_source='')
    assert PreparationPolicy().industry_policy == 'context'
    assert PreparationPolicy(industry_policy='strict').industry_policy == 'strict'
