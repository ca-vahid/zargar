import datetime as dt

import pytest

from tests.test_options_cartel_exits import position
from tests.test_options_cartel_setups import histories
from zargar.marketstructure.market_calendar import next_trading_day
from zargar.techniques.options_cartel.catchup import review_missed_closes
from zargar.techniques.options_cartel.data import DailyBar
from zargar.techniques.options_cartel.exits import ExitCampaign


def run(prices, **overrides):
    history, _ = histories()
    cutoff = history[-1].closes_at
    missed = []
    for price in prices:
        day = next_trading_day(history[-1].session)
        history.append(DailyBar(symbol='TEST', session=day, open=price, high=price+1,
                                low=price-1, close=price, volume=1000))
        missed.append(history[-1].closes_at)
    args = {"state_since_ms": cutoff, "as_of_ms": history[-1].closes_at}
    args.update(overrides)
    return review_missed_closes(ExitCampaign.for_profile('may_2026', [110]), position(), history, missed, **args)


def test_repeated_target_does_not_create_fills_or_enable_later_ema_allocations():
    result = run([111, 111])
    assert [(r['rung'], r['qty']) for r in result['requirements']] == [('target1', 2)]
    assert result['state']['remaining_qty'] == 8 and not result['state']['breakeven']
    assert not result['placesOrders'] and not result['fillsCreated']


def test_protective_breach_replaces_prior_profit_requirements():
    result = run([111, 94])
    assert [(r['rung'], r['qty']) for r in result['requirements']] == [('stop', 8)]


def test_later_position_state_cannot_be_applied_to_earlier_closes():
    with pytest.raises(ValueError, match='verified state cutoff'):
        run([111], state_since_ms=int(dt.datetime(2099, 1, 1, tzinfo=dt.UTC).timestamp()*1000))


def test_incomplete_requested_interval_rejected():
    with pytest.raises(ValueError, match='as-of'):
        run([111], as_of_ms=0)
