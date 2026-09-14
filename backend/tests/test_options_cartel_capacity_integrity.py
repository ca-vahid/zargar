"""Capacity follows actual durable holdings, without double-counting their arm."""
import pytest

from zargar.models import ManagedPositionRow, TechniqueArmed
from zargar.techniques.options_cartel.adoption import adopt_confirmed_entry
from zargar.techniques.options_cartel.preparation import occupied_plans

from .test_options_cartel_adoption import setup_entry
from .test_options_cartel_state import repo as repo  # noqa: PLC0414


async def test_confirmed_fill_and_its_arm_reserve_one_plan_after_arm_retires(repo):
    await setup_entry(repo)
    try:
        adopted = await adopt_confirmed_entry(repo.engine, 'r1')
        async with repo.engine.sf() as session:
            held = await session.get(ManagedPositionRow, adopted['positionId'])
            assert held.config['runId'] == 'r1' and held.status == 'open'
            assert held.legs[0]['qty'] == 2
        assert await occupied_plans(repo.engine, 'pf') == [{'planId': 'r1', 'symbol': 'HOOD'}]
        async with repo.engine.sf() as session, session.begin():
            arm = await session.get(TechniqueArmed, 'r1')
            arm.status = 'disarmed'
        # Retiring observation cannot free a slot while the campaign is held.
        assert await occupied_plans(repo.engine, 'pf') == [{'planId': 'r1', 'symbol': 'HOOD'}]
    finally:
        await repo.engine.position_manager.stop()


@pytest.mark.parametrize('status', ['opening', 'open', 'closing', 'attention'])
async def test_capacity_retains_unlinked_holdings_and_excludes_other_books_or_desks(repo, status):
    async with repo.engine.sf() as session, session.begin():
        session.add_all([
            ManagedPositionRow(id='unlinked', portfolio_id='pf', technique='options_cartel',
                               symbol='HOOD', status=status, config={}),
            ManagedPositionRow(id='other-book', portfolio_id='other', technique='options_cartel',
                               symbol='TEST', status='open', config={'runId': 'other-book-plan'}),
            ManagedPositionRow(id='other-desk', portfolio_id='pf', technique='tip',
                               symbol='TEST', status='open', config={'runId': 'other-desk-plan'}),
            ManagedPositionRow(id='closed', portfolio_id='pf', technique='options_cartel',
                               symbol='TEST', status='closed', config={'runId': 'closed-plan'}),
            ManagedPositionRow(id='archived', portfolio_id='pf', technique='options_cartel',
                               symbol='TEST', status='archived', config={'runId': 'archived-plan'}),
        ])
    assert await occupied_plans(repo.engine, 'pf') == [{'planId': 'managed:unlinked', 'symbol': 'HOOD'}]
