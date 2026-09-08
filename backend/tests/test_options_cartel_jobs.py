from types import SimpleNamespace

from tests.test_options_cartel_position_adapter import minute, prepared
from zargar.domain import Bar
from zargar.techniques.options_cartel.jobs import PREFIX, nightly_scan, recover_positions, register_jobs


async def test_disabled_jobs_do_not_collect_or_touch_positions():
    engine = SimpleNamespace(settings={})
    assert await nightly_scan(engine) == {'status': 'disabled'}
    assert await recover_positions(engine) == {'status': 'disabled'}


async def test_stopped_runtime_callbacks_do_not_start_work():
    engine = SimpleNamespace(cartel_observer=SimpleNamespace(stopping=True))
    assert await nightly_scan(engine) == {'status': 'stopping'}
    assert await recover_positions(engine) == {'status': 'stopping'}


def test_unregister_removes_only_cartel_jobs():
    from zargar.techniques.options_cartel.jobs import JOB_NAMES, unregister_jobs

    jobs = dict.fromkeys([*JOB_NAMES, 'other_technique'])
    engine = SimpleNamespace(scheduler=SimpleNamespace(unregister=lambda name: jobs.pop(name, None)))
    unregister_jobs(engine)
    assert list(jobs) == ['other_technique']


async def test_nightly_scan_passes_fixed_cutoff_and_owned_settings(engine):
    from zargar.marketstructure.sessions import session_bounds

    await engine.settings.set(PREFIX+'scan_enabled', True)
    await engine.settings.set(PREFIX+'scan_symbols', ['MU', 'HOOD'])
    at = session_bounds('2026-05-05')[1]+4*3600_000
    calls = []

    async def scan(service, body, *, now_ms):
        assert service.engine is engine
        calls.append(body)
        assert body.as_of_ms == now_ms == at
        return {'verdict': 'complete', 'runId': 'scan-test', 'result': {'summary': {'requested': 2}}}

    result = await nightly_scan(engine, now_ms=at, scan=scan)
    assert result['runId'] == 'scan-test' and calls[0].symbols == ['MU', 'HOOD']
    assert calls[0].facts == {}  # no invented industry/fundamental evidence


def test_register_jobs_preserves_existing_scheduler_entries():
    jobs = {'other_technique': ('12:00', None)}
    engine = SimpleNamespace(scheduler=SimpleNamespace(register=lambda name, at, fn: jobs.update({name: (at, fn)})))
    register_jobs(engine)
    assert jobs['other_technique'] == ('12:00', None)
    assert {name: at for name, (at, _) in jobs.items() if name.startswith('options_cartel')} == {
        'options_cartel_nightly_scan': '20:15', 'options_cartel_close_recovery': '20:10',
        'options_cartel_preopen_recovery': '09:05', 'options_cartel_nightly_preparation': '20:20',
        'options_cartel_morning_preparation': '08:45'}


async def test_scheduled_history_recovery_prepares_owned_batch_without_orders(engine):
    rig = await prepared(engine)
    await minute(rig, 0, 100)
    rig.pm._now = lambda: rig.closes/1000
    calls = []

    async def fetch(symbol, tf, start, end, *, client):
        calls.append((symbol, tf, end))
        return [Bar('TEST', '1d', rig.opens, 100, 112, 99, 111, 1000)]

    job_engine = SimpleNamespace(settings={PREFIX+'recovery_enabled': True}, position_manager=rig.pm)
    result = await recover_positions(job_engine, now_ms=rig.closes, fetch=fetch)
    assert calls == [('TEST', '1d', rig.closes)]
    assert result['positions'][0]['catchupStatus'] == 'reviewed'
    assert engine.orders.placed == [] and rig.p.legs[0].qty == 8


async def test_schedule_status_reads_persisted_partial_outcomes(engine):
    from zargar.scheduler import SCHEDULED_JOB_RAN
    from zargar.techniques.options_cartel.jobs import schedule_status

    register_jobs(engine)
    result = {'status': 'partial', 'positions': [{'positionId': 'owned', 'status': 'unavailable',
                                               'reason': 'missing completed daily candle'}]}
    await engine.journal.append(SCHEDULED_JOB_RAN, {'job': 'options_cartel_preopen_recovery',
                                                   'date': '2026-05-05', 'result': result})
    register_jobs(engine)  # restart-like reset of in-memory counters
    status = await schedule_status(engine)
    job = next(j for j in status['jobs'] if j['name'] == 'options_cartel_preopen_recovery')
    assert job['runs'] == 0 and job['lastOutcome']['result'] == result
    assert all(j['name'].startswith('options_cartel_') for j in status['jobs'])


async def test_shutdown_during_fetch_does_not_apply_recovered_history(engine):
    rig = await prepared(engine)
    await minute(rig, 0, 100)
    rig.pm._now = lambda: rig.closes/1000
    observer = SimpleNamespace(stopping=False)
    job_engine = SimpleNamespace(settings={PREFIX+'recovery_enabled': True},
                                 position_manager=rig.pm, cartel_observer=observer)

    async def fetch(symbol, tf, start, end, *, client):
        observer.stopping = True
        return [Bar('TEST', '1d', rig.opens, 100, 112, 99, 111, 1000)]

    result = await recover_positions(job_engine, now_ms=rig.closes, fetch=fetch)
    assert result['status'] == 'stopping'
    assert 'recovery' not in rig.p.policy['cartel'] and engine.orders.placed == []
