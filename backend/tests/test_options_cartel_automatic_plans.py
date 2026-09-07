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
