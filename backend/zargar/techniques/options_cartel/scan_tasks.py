"""Tracked background research workers; no order or position authority."""
from __future__ import annotations

import asyncio
import logging

from .scans import retry_scan, scan_focus_list

log = logging.getLogger('zargar.options_cartel.scan_tasks')


async def submit_scan(service, body=None, *, retry_id=None, collect=None, now_ms=None):
    engine = service.engine
    if getattr(getattr(engine, 'cartel_observer', None), 'stopping', False):
        raise ValueError('Cartel runtime is stopping')
    retries = getattr(engine, '_cartel_retry_submissions', None)
    if retries is None:
        retries = engine._cartel_retry_submissions = {}
    existing = retries.get(retry_id) if retry_id else None
    if existing is not None and not existing[1].done():
        return await asyncio.shield(existing[0])
    workers = getattr(engine, '_cartel_background_scans', None)
    if workers is None:
        workers = engine._cartel_background_scans = set()
    if sum(not task.done() for task in workers) >= 3:
        raise ValueError('Three scans are already running; wait for one to finish')
    ready = asyncio.get_running_loop().create_future()
    # A disconnected caller must not cancel the shared acknowledgement future.
    ready.add_done_callback(lambda future: future.exception() if not future.cancelled() else None)

    def started(record):
        if not ready.done():
            ready.set_result(record)

    kwargs = {'on_started': started, 'now_ms': now_ms}
    if collect is not None:
        kwargs['collect'] = collect
    coroutine = retry_scan(service, retry_id, **kwargs) if retry_id else scan_focus_list(service, body, **kwargs)
    task = asyncio.create_task(coroutine, name='cartel-research-scan')
    workers.add(task)
    if retry_id:
        retries[retry_id] = (ready, task)

    def finished(worker):
        workers.discard(worker)
        if retry_id and retries.get(retry_id, (None, None))[1] is worker:
            retries.pop(retry_id)
        if worker.cancelled():
            if not ready.done():
                ready.cancel()
            return
        error = worker.exception()
        if error is not None:
            if not ready.done():
                ready.set_exception(error)
            else:
                log.error('Background Cartel scan failed', exc_info=error)

    task.add_done_callback(finished)
    return await asyncio.shield(ready)


async def stop_background_scans(engine):
    # Never cancel registry entries belonging to the shared scheduler loop.
    workers = list(getattr(engine, '_cartel_background_scans', ()))
    for task in workers:
        task.cancel()
    if workers:
        await asyncio.gather(*workers, return_exceptions=True)
