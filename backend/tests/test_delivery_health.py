import asyncio
from types import SimpleNamespace

from zargar import delivery_health
from zargar.bus import Bus
from zargar.domain import Bar


async def test_telemetry_distinguishes_dispatch_wait_from_handler_time(monkeypatch):
    at=100_000; persisted=[]
    async def append(kind, evidence): persisted.append((kind,evidence))
    engine=SimpleNamespace(journal=SimpleNamespace(append=append),_event_loop_lag_ms=12)
    monkeypatch.setattr(delivery_health,'now_ms',lambda:at)
    message={'bar':Bar('TEST','1m',0,1,2,1,2,100,source='exchange'),
             'sourceReceivedAt':61000,'publishedAt':62000}
    delivery_health.observe(engine,'cartel',message,3)
    at+=500
    delivery_health.observe(engine,'cartel',message,2,handled_ms=500)
    await engine._delivery_health_task
    state=engine._delivery_health['cartel']
    assert state['samples']==1 and state['maxQueueMs']==38000
    assert state['maxHandlerMs']==500 and state['maxReceiveToPublishMs']==1000
    assert len(persisted)==1

async def test_slow_telemetry_sink_does_not_create_unbounded_tasks(monkeypatch):
    release=asyncio.Event()
    async def append(*args): await release.wait()
    engine=SimpleNamespace(journal=SimpleNamespace(append=append))
    monkeypatch.setattr(delivery_health,'now_ms',lambda:100000)
    message={'bar':Bar('TEST','1m',0,1,2,1,2),'publishedAt':99000}
    delivery_health.observe(engine,'cartel',message,0)
    task=engine._delivery_health_task
    for _ in range(100): delivery_health.observe(engine,'cartel',message,0)
    assert engine._delivery_health_task is task
    release.set();await task


# --- KFIN-03 (2026-09-14): one bounded writer, fair per consumer, finally-recorded outcomes, bounded shutdown ---

def _engine(append, **extra):
    return SimpleNamespace(journal=SimpleNamespace(append=append), **extra)


async def test_blocked_sink_with_two_consumers_flushes_both_without_another_bar(monkeypatch):
    """The second consumer dirties its snapshot while the first write is stuck; the SAME writer
    task drains it after the sink releases — no later market event, no second task."""
    release = asyncio.Event(); started = asyncio.Event(); persisted = []
    async def append(_kind, payload):
        started.set()
        await release.wait()
        persisted.append(payload)
    eng = _engine(append)
    clock = {'t': 100_000}
    monkeypatch.setattr(delivery_health, 'now_ms', lambda: clock['t'])
    message = {'bar': Bar('X', '1m', 0, 1, 2, 1, 2), 'publishedAt': 99_000}
    delivery_health.observe(eng, 'first', message, 0)
    writer = eng._delivery_health_task
    await started.wait()
    delivery_health.observe(eng, 'second', message, 0)
    delivery_health.observe(eng, 'third', message, 0)
    # a consumer that re-dirties while waiting keeps its earlier place (fairness: `second` before `third`)
    clock['t'] += delivery_health.PERSIST_EVERY_MS
    delivery_health.observe(eng, 'second', message, 4)
    assert list(eng._delivery_health_dirty) == ['second', 'third']
    assert eng._delivery_health_dirty['second']['queueDepth'] == 4          # the retained snapshot is the LATEST
    assert eng._delivery_health_task is writer                               # still one writer
    assert delivery_health.snapshot(eng)['writer'] == {'busy': True, 'pending': ['second', 'third'],
                                                       'unflushedAtShutdown': None}
    release.set()
    await writer
    assert [row['consumer'] for row in persisted] == ['first', 'second', 'third']
    assert not eng._delivery_health_dirty and not delivery_health.snapshot(eng)['writer']['busy']


async def test_handling_records_start_and_outcome_in_finally(monkeypatch):
    persisted = []
    async def append(_kind, payload): persisted.append(payload)
    bus = Bus(maxsize=2)
    eng = _engine(append, bus=bus)
    clock = {'t': 100_000}
    monkeypatch.setattr(delivery_health, 'now_ms', lambda: clock['t'])
    q, _ = bus.subscribe('bars')
    for i in range(4):                       # a 2-deep queue sheds two of four publications
        bus.publish('bars', {'bar': Bar('X', '1m', i*60_000, 1, 2, 1, 2), 'publishedAt': 99_000})
    assert bus.drops(q) == 2 and bus.drop_counts() == {'bars': 2, 'total': 2}
    msg = q.get_nowait()

    # ok: start is visible WHILE the handler runs, the end lands afterwards
    with delivery_health.handling(eng, 'cartel', msg, queue=q):
        flight = delivery_health.snapshot(eng)['consumers']['cartel']
        assert flight['inFlight']['symbol'] == 'X' and flight['inFlightAgeMs'] == 0
        clock['t'] += 350
    st = eng._delivery_health['cartel']
    assert st['inFlight'] is None and st['handled'] == 1 and st['maxHandlerMs'] == 350 and st['subscriberDrops'] == 2

    # failed: the exception propagates AND stays on the record
    class Boom(RuntimeError): ...
    try:
        with delivery_health.handling(eng, 'cartel', msg, queue=q):
            clock['t'] += 20
            raise Boom('handler blew up')
    except Boom:
        pass
    else:
        raise AssertionError('handling must re-raise')
    assert st['failed'] == 1 and st['inFlight'] is None
    assert st['lastFailure']['outcome'] == 'failed' and st['lastFailure']['error'] == 'Boom: handler blew up'
    assert st['lastFailure']['handlerMs'] == 20

    # cancelled: recorded as such, still re-raised
    try:
        with delivery_health.handling(eng, 'cartel', msg, queue=q):
            raise asyncio.CancelledError()
    except asyncio.CancelledError:
        pass
    assert st['cancelled'] == 1 and st['lastFailure']['outcome'] == 'cancelled' and st['lastFailure']['error'] is None

    # blocked: a handler that never returns keeps ageing on the endpoint
    gate = asyncio.Event()
    async def stuck():
        with delivery_health.handling(eng, 'position_manager', msg, queue=q):
            await gate.wait()
    task = asyncio.create_task(stuck())
    await asyncio.sleep(0)
    clock['t'] += 90_000
    snap = delivery_health.snapshot(eng)
    assert snap['consumers']['position_manager']['inFlightAgeMs'] == 90_000
    assert snap['busDrops'] == {'bars': 2, 'total': 2}
    task.cancel()
    with __import__('contextlib').suppress(asyncio.CancelledError):
        await task
    assert eng._delivery_health['position_manager']['cancelled'] == 1
    await eng._delivery_health_task
    assert persisted and persisted[0]['consumer'] == 'cartel'
    # a message without a bar is handled without telemetry, and still re-raises
    with delivery_health.handling(eng, 'cartel', {'tf': '5m'}, queue=q):
        pass


async def test_shutdown_is_bounded_on_a_stuck_sink(monkeypatch):
    never = asyncio.Event()
    async def append(*_): await never.wait()
    eng = _engine(append)
    monkeypatch.setattr(delivery_health, 'now_ms', lambda: 100_000)
    message = {'bar': Bar('X', '1m', 0, 1, 2, 1, 2), 'publishedAt': 99_000}
    delivery_health.observe(eng, 'first', message, 0)
    await asyncio.sleep(0)
    delivery_health.observe(eng, 'second', message, 0)
    loop = asyncio.get_running_loop(); t0 = loop.time()
    out = await delivery_health.shutdown(eng, timeout=0.2)
    assert loop.time()-t0 < 1.5
    assert out == {'flushed': False, 'pending': 2, 'timedOut': True}      # the in-progress one is owed again too
    assert eng._delivery_health_task.cancelled() or eng._delivery_health_task.done()
    assert delivery_health.snapshot(eng)['writer']['unflushedAtShutdown'] == 2
    # an idle writer is a no-op
    assert (await delivery_health.shutdown(eng, timeout=0.2))['flushed'] is True


async def test_trading_callback_never_awaits_the_journal(monkeypatch):
    """observe()/handling() are synchronous: a sink that never answers cannot delay the handler."""
    async def append(*_): await asyncio.Event().wait()
    eng = _engine(append)
    monkeypatch.setattr(delivery_health, 'now_ms', lambda: 100_000)
    msg = {'bar': Bar('X', '1m', 0, 1, 2, 1, 2), 'publishedAt': 99_000}
    ran = []
    async def consumer():
        with delivery_health.handling(eng, 'tip', msg):
            ran.append(1)
    await asyncio.wait_for(consumer(), timeout=0.5)
    assert ran == [1] and not eng._delivery_health_task.done()
    await delivery_health.shutdown(eng, timeout=0.05)
