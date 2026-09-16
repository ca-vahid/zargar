import asyncio

from zargar.domain import Quote
from tests.test_em_forward_measurement import NOW, Quotes, plan, runner, trade


def quotes(*, bid=1.9, size=50):
    return Quotes({
        'X': Quote('X', bid=101.99, ask=102.01, last=102.0, ts=NOW, source='sip', source_ts=NOW),
        'X260918C00101000': Quote('X260918C00101000', bid=bid, ask=max(2.0, bid), last=bid,
                                bid_size=size, ask_size=50, ts=NOW, source='opra', source_ts=NOW),
    })


def test_research_journal_wait_cannot_delay_a_premium_stop(monkeypatch):
    monkeypatch.setattr('zargar.execution.planrunner.time.time', lambda: NOW / 1000)
    async def scenario():
        q = quotes(bid=0.4)
        r = runner(q)
        r.rt = lambda key, default=None: {'quote_exit_polls': 1}.get(key, default)
        ap = plan(); tr = trade(); ap.trades['b1'] = tr; r._armed[ap.run_id] = ap
        entered = asyncio.Event(); release = asyncio.Event()
        async def append(kind, *args, **kwargs):
            if kind == 'TechniqueExitShadow':
                entered.set()
                await release.wait()
        r.engine.journal.append.side_effect = append
        task = asyncio.create_task(r.on_quote_watch())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await asyncio.sleep(0)
            stop_dispatched_without_research = r._exit.await_count > 0
        finally:
            release.set()
            await asyncio.wait_for(task, 1)
        assert stop_dispatched_without_research, 'Slow shadow journaling must not hold up the production premium stop'
    asyncio.run(scenario())


def test_unknown_bid_size_does_not_cover_the_whole_position():
    q = quotes(size=None); r = runner(q); ap = plan(); tr = trade()
    asyncio.run(r._shadow_target_pass(ap, [tr], q['X'], NOW, 0.25))
    p = r.engine.journal.append.await_args.args[1]
    assert p['modeled']['coveredQty'] == 0, 'Unknown depth cannot establish fully covered quantity'
    assert p['modeled']['unresolvedQty'] == 2


def test_shadow_share_trim_matches_production_quantity_not_full_remaining():
    q = quotes(); q['X'].bid_size = 500
    r = runner(q); ap = plan(); tr = trade(instrument='shares', remaining=100, filled_qty=100)
    asyncio.run(r._shadow_target_pass(ap, [tr], q['X'], NOW, 0.25))
    p = r.engine.journal.append.await_args.args[1]
    assert p['modeled']['coveredQty'] == 30, 'TP1 is a 30-share trim, not liquidation of all 100 shares'


def test_partial_ladder_does_not_become_small_original_position_policy():
    r = runner(quotes()); ap = plan()
    tr = trade(filled_qty=4, remaining=1, trims_done=2)
    idx, label = r._full_exit_rung(ap, tr, tr.remaining)
    assert idx == 2, 'Four-contract ladder with one left at TP3 must not switch back to small-position TP2'


def test_failed_shadow_write_does_not_permanently_consume_observation():
    q = quotes(); r = runner(q); ap = plan(); tr = trade()
    r.engine.journal.append.side_effect = [RuntimeError('journal unavailable'), None]
    async def scenario():
        try:
            await r._shadow_target_pass(ap, [tr], q['X'], NOW, 0.25)
        except RuntimeError:
            pass
        await r._shadow_target_pass(ap, [tr], q['X'], NOW + 1, 0.25)
        assert r.engine.journal.append.await_count == 2, 'A failed durable write must remain retryable'
    asyncio.run(scenario())
