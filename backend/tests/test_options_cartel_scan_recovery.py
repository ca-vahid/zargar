import asyncio

from sqlalchemy import select

from tests.test_options_cartel_api import research_payload
from zargar.models import TechniqueRun
from zargar.techniques.options_cartel.scan_recovery import recover_interrupted_scans
from zargar.techniques.options_cartel.service import CartelService, ResearchInput


async def pending(engine, symbols):
    body = ResearchInput.model_validate(research_payload())
    row = TechniqueRun(id='interrupted-scan', technique='options_cartel', mode='scan', symbol='MULTI',
        as_of=body.as_of_ms, status='running', verdict='running',
        result={'rows': [{'symbol': s, 'status': 'pending'} for s in symbols], 'placesOrders': False})
    async with engine.sf() as session:
        session.add(row)
        await session.commit()
    child = await CartelService(engine).analyze(body, parent_run_id=row.id)
    return row.id, child


async def test_startup_recovers_child_before_parent_checkpoint_and_preserves_unknowns(engine):
    rid, child = await pending(engine, ['TEST', 'WAIT'])
    async with engine.sf() as session:
        session.add(TechniqueRun(id='foreign', technique='team2', mode='analysis', parent_run_id=rid,
            symbol='WAIT', as_of=child['asOfMs'], status='done', result={}))
        await session.commit()
    result = await recover_interrupted_scans(engine)
    assert result[0]['pending'] == 1
    saved = await CartelService(engine).detail(rid)
    assert saved['verdict'] == 'interrupted' and saved['status'] == 'failed'
    assert saved['result']['rows'][0]['runId'] == child['runId']
    assert saved['result']['rows'][1]['status'] == 'pending'
    async with engine.sf() as session:
        assert (await session.scalar(select(TechniqueRun).where(TechniqueRun.id == 'foreign'))).result == {}


async def test_live_task_is_skipped_and_complete_child_set_can_finish_after_task_ends(engine):
    rid, child = await pending(engine, ['TEST'])
    engine._cartel_scan_tasks = {rid: asyncio.current_task()}
    assert await recover_interrupted_scans(engine) == []
    assert (await CartelService(engine).detail(rid))['status'] == 'running'
    engine._cartel_scan_tasks.clear()
    assert (await recover_interrupted_scans(engine))[0]['verdict'] == 'complete'
    saved = await CartelService(engine).detail(rid)
    assert saved['status'] == 'done' and saved['result']['rows'][0]['runId'] == child['runId']
    assert await recover_interrupted_scans(engine) == []
