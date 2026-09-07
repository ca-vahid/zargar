import datetime as dt

from tests.test_options_cartel_position_adapter import minute, prepared
from zargar.domain import Quote
from zargar.execution.positions import PositionManager
from zargar.marketstructure.market_calendar import next_trading_day
from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.data import DailyBar
from zargar.techniques.options_cartel.position_adapter import CartelPositionAdapter


async def recovered(engine, close=111):
    rig = await prepared(engine)
    await minute(rig, 0, 100)
    day = dt.datetime.fromtimestamp(rig.opens/1000, dt.UTC).date()
    rig.pm._now = lambda: rig.closes/1000
    daily = DailyBar(symbol='TEST', session=day, open=100, high=112, low=min(99, close-1), close=close, volume=10000)
    await rig.pm._policy_adapter(rig.p).recover_daily(rig.pm, rig.p, [daily], source='synthetic recovery', as_of_ms=rig.closes)
    now = session_bounds(next_trading_day(day).isoformat())[0]+60_000
    rig.pm._now = lambda: now/1000
    quote = Quote(symbol='TEST', bid=112., ask=112.1, last=112., ts=now)
    engine.quotes.get = lambda symbol: quote if symbol == 'TEST' else None
    return rig


async def test_catchup_uses_current_quote_and_actual_fill_once(engine):
    rig = await recovered(engine)
    engine.orders.script[0] = {'price': 112.}
    adapter = rig.pm._policy_adapter(rig.p)
    await adapter.on_watch(rig.pm, rig.p)
    assert len(engine.orders.placed) == 1
    order = engine.orders.placed[0]
    assert order.reduce_only and order.qty == 2 and order.order_type == 'MKT'
    assert rig.p.exits[-1]['price'] == 112.
    assert rig.p.legs[0].qty == 6 and rig.p.state.stop == 100
    await adapter.on_watch(rig.pm, rig.p)
    await adapter.on_watch(rig.pm, rig.p)
    assert len(engine.orders.placed) == 1
    assert rig.p.policy['cartel']['catchupReview']['status'] == 'complete'
    assert rig.p.policy['cartel']['missedCloses'] == []


async def test_stale_quote_waits_without_inventing_a_fill(engine):
    rig = await recovered(engine)
    engine.quotes.get('TEST').ts -= 20_000
    await rig.pm._policy_adapter(rig.p).on_watch(rig.pm, rig.p)
    assert engine.orders.placed == [] and rig.p.legs[0].qty == 8
    assert rig.p.policy['cartel']['catchupReview']['status'] == 'executing'
    assert rig.p.policy['cartel']['missedCloses'] == [rig.closes]


async def test_restart_with_pending_catchup_order_does_not_resubmit(engine):
    rig = await recovered(engine)
    engine.orders.script[0] = {'status': 'ACCEPTED'}
    await rig.pm._policy_adapter(rig.p).on_watch(rig.pm, rig.p)
    restored = PositionManager(engine)
    restored._now = rig.pm._now
    restored.register_policy_adapter('options_cartel', CartelPositionAdapter())
    await restored.restore()
    p = restored.get(rig.p.id)
    await restored._policy_adapter(p).on_watch(restored, p)
    assert len(engine.orders.placed) == 1 and p.legs[0].qty == 8
    assert p.policy['cartel']['catchupReview']['status'] == 'executing'
    await restored.stop()


async def test_full_stop_fill_completes_batch_without_a_later_watch(engine):
    rig = await recovered(engine, close=94)
    engine.orders.script[0] = {'price': 112.}
    await rig.pm._policy_adapter(rig.p).on_watch(rig.pm, rig.p)
    assert rig.p.status == 'closed' and not rig.p.open_legs
    assert rig.p.policy['cartel']['catchupReview']['status'] == 'complete'
    assert rig.p.policy['cartel']['missedCloses'] == []


async def test_quote_is_rechecked_after_cancellation_io(engine):
    rig = await recovered(engine)
    adapter = rig.pm._policy_adapter(rig.p)
    original = adapter.exit_router.cancel

    async def slow_cancel(*args):
        result = await original(*args)
        engine.quotes.get('TEST').ts -= 20_000
        return result

    adapter.exit_router.cancel = slow_cancel
    await adapter.on_watch(rig.pm, rig.p)
    assert engine.orders.placed == [] and rig.p.legs[0].qty == 8
    assert rig.p.policy['cartel']['closeRequest']['remaining'] == 6
