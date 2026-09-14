"""Bounded asynchronous delivery telemetry; never blocks the trading callback."""
import asyncio
import logging

from .domain import now_ms

log = logging.getLogger(__name__)


def observe(engine, consumer, message, queued, *, handled_ms=None):
    bar = message.get('bar')
    if bar is None:
        return
    at = now_ms()
    states = getattr(engine, '_delivery_health', None)
    if states is None:
        states = engine._delivery_health = {}
    state = states.setdefault(consumer, {'samples': 0, 'maxQueueMs': 0, 'maxCloseToConsumerMs': 0,
        'maxHandlerMs': 0, 'lastPersistedAt': 0})
    state.update(samples=state['samples']+int(handled_ms is None), lastAt=at, symbol=bar.symbol, source=bar.source,
        publishedAt=message.get('publishedAt'), sourceReceivedAt=message.get('sourceReceivedAt'),
        barCloseAt=bar.ts+60_000, queueDepth=queued, eventLoopLagMs=getattr(engine, '_event_loop_lag_ms', None))
    if message.get('sourceReceivedAt') and message.get('publishedAt'):
        state['maxReceiveToPublishMs'] = max(state.get('maxReceiveToPublishMs', 0), message['publishedAt']-message['sourceReceivedAt'])
    if message.get('publishedAt') and handled_ms is None:
        state['maxQueueMs'] = max(state['maxQueueMs'], at-message['publishedAt'])
    if handled_ms is None:
        state['maxCloseToConsumerMs'] = max(state['maxCloseToConsumerMs'], at-bar.ts-60_000)
    if handled_ms is not None:
        state['maxHandlerMs'] = max(state['maxHandlerMs'], handled_ms)
    task = getattr(engine, '_delivery_health_task', None)
    if at-state['lastPersistedAt'] < 60_000 or task is not None and not task.done():
        return
    state['lastPersistedAt'] = at
    snapshot = {'consumer': consumer, **state}
    async def persist():
        try:
            await engine.journal.append('BarDeliveryHealth', snapshot)
        except Exception:
            log.debug('Delivery telemetry persistence failed', exc_info=True)
    engine._delivery_health_task = asyncio.create_task(persist(), name='bar-delivery-health')
