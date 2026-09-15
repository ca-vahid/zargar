"""Bounded asynchronous delivery telemetry; never blocks the trading callback.

One writer per engine (KFIN-03, 2026-09-14). A bar consumer records what it saw
with `observe()` / `handling()` — pure in-memory bookkeeping, no await — and a
snapshot becomes DIRTY at most once per `PERSIST_EVERY_MS` per consumer. The
single writer task drains the dirty set in first-dirty order (one entry per
consumer, so the set is bounded by the number of consumers, and a consumer that
re-dirties while waiting keeps its place — it can never starve another) and
keeps draining after the active write finishes: a snapshot marked dirty while
the sink was busy is flushed without another market event. Shutdown waits a
bounded time for the writer and then cancels it, reporting what was not flushed.

Handler start and end are recorded in `finally` (via the `handling` context
manager) on every path — ok, failed, cancelled — so a hung or failing consumer
stays diagnosable on `/api/ops/delivery-health` (`inFlight` + `inFlightAgeMs`,
`failed`, `cancelled`, `lastFailure`) together with the bus's subscriber drops.
"""
import asyncio
import contextlib
import logging

from .domain import now_ms

log = logging.getLogger(__name__)

PERSIST_EVERY_MS = 60_000          # per-consumer journal cadence (since-process maxima live in memory)
SHUTDOWN_FLUSH_SECONDS = 2.0       # bound on waiting for a stuck sink at engine stop
JOURNAL_KIND = 'BarDeliveryHealth'
_NEW_STATE = {'samples': 0, 'maxQueueMs': 0, 'maxCloseToConsumerMs': 0, 'maxHandlerMs': 0,
              'lastPersistedAt': 0, 'handled': 0, 'failed': 0, 'cancelled': 0,
              'subscriberDrops': 0, 'inFlight': None, 'lastFailure': None}


def _states(engine) -> dict:
    states = getattr(engine, '_delivery_health', None)
    if states is None:
        states = engine._delivery_health = {}
    return states


def _dirty(engine) -> dict:
    dirty = getattr(engine, '_delivery_health_dirty', None)
    if dirty is None:
        dirty = engine._delivery_health_dirty = {}
    return dirty


def _state(engine, consumer) -> dict:
    return _states(engine).setdefault(consumer, dict(_NEW_STATE))


def _snapshot(consumer, state, at) -> dict:
    snap = {'consumer': consumer, **state}
    flight = state.get('inFlight')
    snap['inFlightAgeMs'] = (at - flight['startedAt']) if flight else None
    return snap


def observe(engine, consumer, message, queued, *, handled_ms=None, drops=None):
    """Record one delivery (or, with `handled_ms`, its completion). Never awaits."""
    bar = message.get('bar')
    if bar is None:
        return
    at = now_ms()
    state = _state(engine, consumer)
    state.update(samples=state['samples']+int(handled_ms is None), lastAt=at, symbol=bar.symbol, source=bar.source,
        publishedAt=message.get('publishedAt'), sourceReceivedAt=message.get('sourceReceivedAt'),
        barCloseAt=bar.ts+60_000, queueDepth=queued, eventLoopLagMs=getattr(engine, '_event_loop_lag_ms', None))
    if drops is not None:
        state['subscriberDrops'] = int(drops)
    if message.get('sourceReceivedAt') and message.get('publishedAt'):
        state['maxReceiveToPublishMs'] = max(state.get('maxReceiveToPublishMs', 0), message['publishedAt']-message['sourceReceivedAt'])
    if message.get('publishedAt') and handled_ms is None:
        state['maxQueueMs'] = max(state['maxQueueMs'], at-message['publishedAt'])
    if handled_ms is None:
        state['maxCloseToConsumerMs'] = max(state['maxCloseToConsumerMs'], at-bar.ts-60_000)
    if handled_ms is not None:
        state['maxHandlerMs'] = max(state['maxHandlerMs'], handled_ms)
    _mark_dirty(engine, consumer, state, at)


def _mark_dirty(engine, consumer, state, at) -> None:
    if at-state['lastPersistedAt'] < PERSIST_EVERY_MS:
        return
    state['lastPersistedAt'] = at
    dirty = _dirty(engine)
    dirty[consumer] = _snapshot(consumer, state, at)   # an existing key keeps its (earlier) place: fair per consumer
    _ensure_writer(engine)


def _ensure_writer(engine) -> None:
    task = getattr(engine, '_delivery_health_task', None)
    if task is not None and not task.done():
        return                                          # the running writer drains the dirty set before it exits
    engine._delivery_health_task = asyncio.create_task(_writer(engine), name='bar-delivery-health')


async def _writer(engine) -> None:
    """Drain the dirty set to the journal, one consumer at a time, until it is empty."""
    dirty = _dirty(engine)
    while dirty:
        consumer = next(iter(dirty))
        snapshot = dirty.pop(consumer)
        try:
            await engine.journal.append(JOURNAL_KIND, snapshot)
        except asyncio.CancelledError:
            dirty.setdefault(consumer, snapshot)        # still owed; shutdown reports it as unflushed
            raise
        except Exception:
            log.debug('Delivery telemetry persistence failed for %s', consumer, exc_info=True)


class handling:
    """`with handling(engine, name, msg, queue=q): await handler(...)` — records the
    delivery, the in-flight start, and in `__exit__` (i.e. `finally`) the outcome:
    ok / failed (exception kept for the record) / cancelled. Re-raises everything."""

    def __init__(self, engine, consumer, message, queued=0, *, queue=None):
        self.engine, self.consumer, self.message = engine, consumer, message
        self.queue = queue
        self.queued = queue.qsize() if queue is not None else queued
        self.started = None

    def _drops(self):
        bus = getattr(self.engine, 'bus', None)
        fn = getattr(bus, 'drops', None)
        if self.queue is None or fn is None:
            return None
        try:
            return fn(self.queue)
        except Exception:                                # a stub bus is not a reason to skip the handler
            return None

    def __enter__(self):
        bar = self.message.get('bar')
        if bar is None:
            return self
        self.started = now_ms()
        observe(self.engine, self.consumer, self.message, self.queued, drops=self._drops())
        _state(self.engine, self.consumer)['inFlight'] = {'symbol': bar.symbol, 'startedAt': self.started,
                                                          'barCloseAt': bar.ts+60_000}
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.started is None:
            return False
        at = now_ms()
        state = _state(self.engine, self.consumer)
        state['inFlight'] = None
        queued = self.queue.qsize() if self.queue is not None else self.queued
        if exc_type is None:
            state['handled'] += 1
            outcome = 'ok'
        elif issubclass(exc_type, asyncio.CancelledError):
            state['cancelled'] += 1
            outcome = 'cancelled'
        else:
            state['failed'] += 1
            outcome = 'failed'
        if outcome != 'ok':
            state['lastFailure'] = {'at': at, 'symbol': self.message['bar'].symbol, 'outcome': outcome,
                                    'error': (f'{exc_type.__name__}: {exc}'[:200] if outcome == 'failed' else None),
                                    'handlerMs': at-self.started}
        observe(self.engine, self.consumer, self.message, queued, handled_ms=at-self.started, drops=self._drops())
        return False


def snapshot(engine) -> dict:
    """What the ops endpoint shows: per-consumer state with the in-flight age computed now,
    the bus's subscriber drops per topic, and the writer's own backlog."""
    at = now_ms()
    consumers = {name: _snapshot(name, st, at) for name, st in _states(engine).items()}
    bus = getattr(engine, 'bus', None)
    counts = getattr(bus, 'drop_counts', None)
    task = getattr(engine, '_delivery_health_task', None)
    return {'consumers': consumers,
            'busDrops': counts() if callable(counts) else {},
            'writer': {'busy': bool(task is not None and not task.done()),
                       'pending': sorted(_dirty(engine)),
                       'unflushedAtShutdown': getattr(engine, '_delivery_health_unflushed', None)}}


async def shutdown(engine, timeout: float = SHUTDOWN_FLUSH_SECONDS) -> dict:
    """Bounded flush at engine stop: wait `timeout` for the writer, then cancel it and
    report what stayed unflushed. Never awaits a stuck sink indefinitely."""
    task = getattr(engine, '_delivery_health_task', None)
    out = {'flushed': True, 'pending': 0, 'timedOut': False}
    if task is None or task.done():
        return out
    done, _ = await asyncio.wait({task}, timeout=timeout)
    if not done:
        task.cancel()
        await asyncio.wait({task}, timeout=min(0.5, timeout))   # a sink that ignores cancel cannot hold us either
        pending = len(_dirty(engine))
        engine._delivery_health_unflushed = pending
        out.update(flushed=False, pending=pending, timedOut=True)
        log.warning('delivery telemetry flush timed out after %.1fs; %d consumer snapshot(s) unflushed', timeout, pending)
        return out
    with contextlib.suppress(Exception):
        task.result()
    return out
