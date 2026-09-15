import asyncio

from tests.test_em_forward_measurement import NOW, Quotes, plan, runner, trade
from zargar.domain import Bar, Quote
from zargar.execution.exits import plan_exit


def test_last_rung_preserves_the_production_runner_remainder():
    r = runner(Quotes()); ap = plan()
    tr = trade(instrument='shares', filled_qty=100, remaining=30, trims_done=2)
    bar = Bar(symbol='X', tf='1m', ts=NOW, open=103.0, high=103.1, low=102.9, close=103.0, volume=100)
    actual = plan_exit(tr, bar, close_ms=NOW + 3600000, flatten_minutes=5)
    assert actual is not None and actual.qty == 15
    idx, label = r._full_exit_rung(ap, tr, tr.filled_qty)
    assert r._production_exit_qty(ap, tr, idx, label) == actual.qty, 'TP3 must not liquidate the runner production retains'


def test_observations_captured_before_first_write_do_not_duplicate_the_rung():
    q = Quotes({
        'X': Quote('X', bid=101.99, ask=102.01, last=102, ts=NOW, source='sip', source_ts=NOW),
        'X260918C00101000': Quote('X260918C00101000', bid=1.9, ask=2.0, last=1.95,
                                bid_size=40, ask_size=40, ts=NOW, source='opra', source_ts=NOW),
    })
    r = runner(q); ap = plan(); tr = trade(entry_order_id='entry-A')
    # Two quote passes capture while the background recorder has not yet acknowledged its first append.
    first = r._shadow_capture(ap, [tr], q['X'], NOW, 0.25)
    second = r._shadow_capture(ap, [tr], q['X'], NOW + 1, 0.25)
    async def scenario():
        await r._shadow_record(ap, first)
        await r._shadow_record(ap, second)
        assert r.engine.journal.append.await_count == 1, 'Queued observations for the same trade/version/rung must be deduplicated'
    asyncio.run(scenario())
