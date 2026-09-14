import asyncio
from types import SimpleNamespace

from zargar import delivery_health
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
