"""Cross-path and quote-order acceptance for the v0.7.54 confirmation rule."""
from zargar.domain import Bar

from .test_premium_stop_debounce import BASE, _mgr, _pos, _q, _tick


async def test_bar_does_not_confirm_the_same_single_option_flash():
    position = _pos()
    manager = _mgr(lambda s: None)
    quote = _q(.82, BASE)
    await _tick(manager, position, quote, BASE + 1000)
    assert manager.close.await_count == 0
    manager._now = lambda: (BASE + 2000) / 1000
    bar = Bar(symbol="DAL", tf="1m", ts=BASE, open=91.3, high=91.4, low=91.2, close=91.35)
    await manager._decide(position, bar, [bar])
    assert manager.close.await_count == 0, manager.close.call_args_list


async def test_out_of_order_option_quote_is_not_confirmation():
    position = _pos()
    manager = _mgr(lambda s: None)
    await _tick(manager, position, _q(.85, BASE + 10_000), BASE + 11_000)
    # Older packet arrives later, still within freshness age. It is not forward evidence.
    await _tick(manager, position, _q(.83, BASE + 5000), BASE + 12_000)
    assert manager.close.await_count == 0, manager.close.call_args_list


async def test_underlying_bar_stop_still_exits_while_premium_is_pending():
    position = _pos()
    position.policy["stop"] = {"kind": "fixed", "price": 89}
    manager = _mgr(lambda s: None)
    await _tick(manager, position, _q(.85, BASE), BASE + 1000)
    bar = Bar(symbol="DAL", tf="1m", ts=BASE, open=90, high=90, low=88, close=88)
    await manager._decide(position, bar, [bar])
    assert manager.close.await_count == 1
    assert manager.close.call_args.kwargs["kind"] == "stop"
