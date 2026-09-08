import asyncio

import pytest

from tests.test_options_cartel_api import research_payload
from zargar.techniques.options_cartel.scan_tasks import stop_background_scans, submit_scan
from zargar.techniques.options_cartel.scans import ScanRequest
from zargar.techniques.options_cartel.service import CartelService, ResearchInput


async def test_submission_returns_persisted_progress_before_collection_finishes(engine):
    release = asyncio.Event()
    body = ResearchInput.model_validate(research_payload())

    async def collect(request, *, now_ms):
        await release.wait()
        return body, {'warnings': []}

    service = CartelService(engine)
    try:
        accepted = await asyncio.wait_for(submit_scan(service, ScanRequest(symbols=['TEST']),
            collect=collect, now_ms=body.as_of_ms), timeout=5)
        assert accepted['status'] == 'running' and accepted['result']['summary']['completed'] == 0
        assert (await service.detail(accepted['runId']))['status'] == 'running'
        release.set()
        await asyncio.gather(*list(engine._cartel_background_scans))
        assert (await service.detail(accepted['runId']))['status'] == 'done'
    finally:
        await stop_background_scans(engine)


async def test_shutdown_cancels_only_owned_workers_and_preserves_interruption(engine):
    body = ResearchInput.model_validate(research_payload())

    async def collect(request, *, now_ms):
        await asyncio.Event().wait()

    service = CartelService(engine)
    accepted = await submit_scan(service, ScanRequest(symbols=['TEST']), collect=collect, now_ms=body.as_of_ms)
    current = asyncio.current_task()
    engine._cartel_scan_tasks['shared-scheduler-task'] = current
    await stop_background_scans(engine)
    assert current.cancelling() == 0
    engine._cartel_scan_tasks.pop('shared-scheduler-task')
    saved = await service.detail(accepted['runId'])
    assert saved['status'] == 'failed' and saved['verdict'] == 'interrupted'
    assert not engine._cartel_background_scans


async def test_concurrent_retries_share_one_worker_and_scan_record(engine):
    from zargar.techniques.options_cartel.scans import scan_focus_list

    service = CartelService(engine)
    inputs = ResearchInput.model_validate(research_payload())

    async def failed(request, *, now_ms):
        raise ValueError('synthetic provider failure')

    previous = await scan_focus_list(service, ScanRequest(symbols=['TEST']), collect=failed, now_ms=inputs.as_of_ms)
    release = asyncio.Event()
    calls = []

    async def collect(request, *, now_ms):
        calls.append(request.symbol)
        await release.wait()
        return inputs, {'warnings': []}

    try:
        first, second = await asyncio.gather(*[submit_scan(service, retry_id=previous['runId'],
            collect=collect, now_ms=inputs.as_of_ms) for _ in range(2)])
        assert first['runId'] == second['runId']
        assert len(engine._cartel_background_scans) == 1
        release.set()
        await asyncio.gather(*list(engine._cartel_background_scans))
        assert calls == ['TEST'] and not engine._cartel_retry_submissions
    finally:
        await stop_background_scans(engine)


async def test_caller_disconnect_before_acknowledgement_does_not_cancel_worker(engine, monkeypatch):
    from zargar.techniques.options_cartel import scan_tasks

    real_scan = scan_tasks.scan_focus_list
    entered, release = asyncio.Event(), asyncio.Event()
    inputs = ResearchInput.model_validate(research_payload())

    async def controlled(service, body, **kwargs):
        entered.set()
        await release.wait()
        return await real_scan(service, body, **kwargs)

    async def collect(request, *, now_ms):
        return inputs, {'warnings': []}

    monkeypatch.setattr(scan_tasks, 'scan_focus_list', controlled)
    service = CartelService(engine)
    caller = asyncio.create_task(submit_scan(service, ScanRequest(symbols=['TEST']),
                                            collect=collect, now_ms=inputs.as_of_ms))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert len(engine._cartel_background_scans) == 1
        release.set()
        await asyncio.gather(*list(engine._cartel_background_scans))
        scans = [row for row in await service.runs() if row['mode'] == 'scan']
        assert len(scans) == 1 and scans[0]['status'] == 'done'
    finally:
        release.set()
        await stop_background_scans(engine)
