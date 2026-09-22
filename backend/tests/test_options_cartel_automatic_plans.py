import datetime as dt
from types import SimpleNamespace

import pytest

from zargar.options.occ import Occ
from zargar.techniques.options_cartel.automatic_plans import (
    PreparationPolicy,
    automatic_review,
    planning_contract,
)

from .test_options_cartel_prepare import input_data


def test_automatic_targets_are_explicit_engineering_choices_and_ignore_future_bars():
    data = input_data()
    candidate = {'setup': 'base', 'trigger': 150., 'invalidation': 140., 'targets': [], 'contextPassed': True}
    policy = PreparationPolicy()
    first = automatic_review(data, {'candidates': [candidate]}, policy)
    assert first is not None and 'Engineering Fibonacci anchors' in first.target_source
    future = data['history'][-1].model_copy(update={'session': dt.date(2026, 9, 9), 'high': 10000., 'low': .01})
    later = automatic_review({**data, 'history': [*data['history'], future]}, {'candidates': [candidate]}, policy)
    assert later.reviewed_targets == first.reviewed_targets
    assert automatic_review(data, {'candidates': [candidate]}, policy.model_copy(update={'allow_fibonacci_targets': False})) is None
    assert automatic_review(data, {'candidates': [{**candidate, 'contextPassed': False}]}, policy) is None


async def test_contract_selection_rejects_bad_interest_and_expiry_identity():
    first = dt.date(2026, 9, 8)
    expiry = first+dt.timedelta(days=45)
    good = Occ('TEST', expiry, 'C', 100).symbol
    wrong = Occ('TEST', expiry+dt.timedelta(days=1), 'C', 100).symbol
    class Provider:
        async def expirations(self, symbol):
            return [expiry.isoformat()]
        async def chain(self, symbol, date):
            template = {'symbol': good, 'bid': .9, 'ask': 1., 'greeks': {'delta': .5}, 'open_interest': 200}
            return [{**template, 'open_interest': v} for v in ('1000', True, float('nan'), None)] + [
                {**template, 'symbol': wrong}, template]
    engine = SimpleNamespace(options=SimpleNamespace(provider=lambda: Provider()))
    plan = SimpleNamespace(symbol='TEST', direction='long', first_session=first)
    result = await planning_contract(engine, plan, PreparationPolicy().contract_policy)
    assert result['selected']['symbol'] == good
    assert len(result['candidates']) == 1
    assert result['planningOnly']


def test_invalid_exit_allocations_rejected():
    with pytest.raises(ValueError):
        PreparationPolicy(september_fractions=(.5, .5, .5, .5, .5))


async def test_contract_search_continues_beyond_three_expiries_and_explains_premium_rejections():
    first = dt.date(2026, 9, 8)
    expiries = [(first+dt.timedelta(days=n)).isoformat() for n in (45, 46, 47, 48)]
    class Provider:
        async def expirations(self, symbol):
            return expiries
        async def chain(self, symbol, expiry):
            ask = 1. if expiry == expiries[-1] else 3.
            return [{'symbol': Occ('TEST', dt.date.fromisoformat(expiry), 'C', 100).symbol,
                     'bid': ask*.95, 'ask': ask, 'greeks': {'delta':.5}, 'open_interest':200}]
    engine = SimpleNamespace(options=SimpleNamespace(provider=lambda: Provider()))
    result = await planning_contract(engine, SimpleNamespace(symbol='TEST', direction='long', first_session=first),
                                    PreparationPolicy().contract_policy.model_copy(update={'max_ask':1.}))
    assert result['selected']['expiry'] == expiries[-1]
    assert result['audit']['expiriesChecked'] == 4
    assert result['audit']['rejections']['premium'] == 3
    assert result['audit']['maxDebitUsd'] == 100



# ---- 2026-09-21 brief F3: planning ranking by delayed-chain friction is explicit and compared with legacy ----

async def test_planning_cost_ranking_prefers_lower_friction_within_bounds_and_records_legacy_choice():
    first = dt.date(2026, 9, 8)
    near, far = first+dt.timedelta(days=45), first+dt.timedelta(days=25)
    near_sym, far_sym = Occ('TEST', near, 'C', 100).symbol, Occ('TEST', far, 'C', 100).symbol
    class Provider:
        async def expirations(self, symbol):
            return [near.isoformat(), far.isoformat()]
        async def chain(self, symbol, expiry):
            if expiry == near.isoformat():
                return [{'symbol': near_sym, 'bid': 4.2, 'ask': 5., 'greeks': {'delta': .5}, 'open_interest': 200}]   # 17.4% of mid
            return [{'symbol': far_sym, 'bid': 9.8, 'ask': 10.3, 'greeks': {'delta': .5}, 'open_interest': 200}]      # ~5% of mid
    engine = SimpleNamespace(options=SimpleNamespace(provider=lambda: Provider()), settings={})
    plan = SimpleNamespace(symbol='TEST', direction='long', first_session=first)
    base = PreparationPolicy().contract_policy.model_copy(update={'max_ask': 20.})
    legacy = await planning_contract(engine, plan, base)
    assert legacy['selected']['symbol'] == near_sym and legacy['audit']['rankingVersion'] == 'legacy'
    cost = await planning_contract(engine, plan, base.model_copy(update={'ranking_version': 'executable_cost_v1'}))
    assert cost['selected']['symbol'] == far_sym and cost['audit']['legacySelected'] == near_sym
    assert cost['audit']['selectionChangedFromLegacy'] is True and 'planning basis' in cost['audit']['ranking']
    economics = cost['selected']['economics']
    assert economics['status'] == 'fees_only' and economics['frictionPctOfDebit'] == pytest.approx((50+2.08)/1030*100, abs=1e-3)
    assert economics['sizeCoverage'] is None and economics['quantity'] is None
