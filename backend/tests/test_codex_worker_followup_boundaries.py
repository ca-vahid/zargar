import datetime as dt
from unittest.mock import AsyncMock

import pytest

from tests.test_em_source_wiring import CH, T1, msg, run
from zargar.technique import source_revisions as src
from zargar.technique.ingest import StaleWorker

pytestmark = pytest.mark.usefixtures('fresh_db')

EX = {'material': 'setups_brief', 'summary': 'old', 'stance': 'neutral',
      'symbols': ['OLD'], 'board': [], 'claims': [], 'vetoes': []}


def test_manual_board_cannot_relabel_old_extraction_as_current_revision():
    async def scenario(rig):
        await rig.deliver('create', msg(content='OLD is a conditional long setup at a morning level'), seq=1)
        note = await rig.note('123')
        rig.ing._llm_extract = AsyncMock(return_value=dict(EX))
        await rig.ing.extract(note.id)
        await rig.deliver('update', {'id': '123', 'channel_id': CH, 'guild_id': 'guild',
                                    'content': 'NEW replaces the old setup', 'edited_timestamp': T1}, seq=2)
        try:
            await rig.ing.board_check(note.id)
        except StaleWorker:
            pass
        assert rig.technique.analyze.await_count == 0, 'Old artifact cannot be used as the new revision board input'
    run(scenario)


def test_expired_board_lease_cannot_arm_before_checkpoint_rejects():
    async def scenario(rig):
        rig.settings['techniques.enhanced_market.ingest.auto_arm'] = True
        await rig.deliver('create', msg(content='OLD is a conditional long setup at a morning level'), seq=1)
        note = await rig.note('123')
        rig.ing._llm_extract = AsyncMock(return_value=dict(EX))
        await rig.ing.extract(note.id)

        async def analyze(*args, **kwargs):
            async with rig.sf() as session:
                job = await src.job_for_note(session, note.id)
                job.lease_until = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
                await session.commit()
            return {'id': 'run-old', 'result': {'plan': {'triggers': [
                {'id': 'trigger', 'valid': True, 'kind': 'bounce',
                 'assessment': {'grade': 'A', 'score': 9}, 'riskReward': 4.0}]}}}

        rig.technique.analyze = AsyncMock(side_effect=analyze)
        try:
            await rig.ing.board_check(note.id)
        except StaleWorker:
            pass
        assert rig.technique.arm_plan.await_count == 0, 'Lease expiry must stop arming, not only final checkpoint'
    run(scenario)


def test_revision_only_failure_cannot_mutate_another_owners_live_work():
    async def scenario(rig):
        await rig.deliver('create', msg(content='A source post with enough detail for extraction'), seq=1)
        note = await rig.note('123')
        async with rig.sf() as session:
            job = await src.claim_for_note(session, note.id, owner='other-worker')
            await session.commit()
        await rig.ing._fail(note.id, 'late board failure', revision_id=job['revisionId'])
        current = await rig.note('123')
        assert current.status != 'failed' and current.error is None, 'Revision identity alone is not lease authority'
    run(scenario)
