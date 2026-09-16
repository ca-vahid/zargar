import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.observation_health import plan_coverage, repair_gaps
from tests.test_options_cartel_entry import DAY, OPEN, MIN, plan


def test_future_plan_does_not_owe_previous_session_minutes():
    p = plan()
    previous = (DAY-dt.timedelta(days=1)).isoformat()
    state = {'day': previous, 'phase': 'waiting', 'minutes': {}}
    health = plan_coverage(p, state, session_bounds(previous)[1]+3600000)
    assert health['session'] == DAY.isoformat()
    assert health['expectedMinutes'] == health['overdueMissingMinutes'] == 0
    assert state['day'] == previous  # reporting does not rewrite persisted state


def test_active_session_ignores_old_state_day_and_still_reports_real_gaps():
    state = {'day': (DAY-dt.timedelta(days=1)).isoformat(), 'phase': 'waiting', 'minutes': {}}
    assert plan_coverage(plan(), state, OPEN-1)['expectedMinutes'] == 0
    health = plan_coverage(plan(), state, OPEN+10*MIN)
    assert health['session'] == DAY.isoformat()
    assert health['expectedMinutes'] == 10 and health['overdueMissingMinutes'] == 8


def test_terminal_session_keeps_historical_gap_evidence():
    state = {'day': DAY.isoformat(), 'phase': 'invalidated', 'minutes': {}}
    health = plan_coverage(plan(), state, OPEN+86400000)
    assert health['session'] == DAY.isoformat() and health['overdueMissingMinutes'] == 390


async def test_gap_repair_never_fetches_previous_day_for_a_future_plan():
    previous = (DAY-dt.timedelta(days=1)).isoformat()
    load = AsyncMock()
    runtime = SimpleNamespace(clock=lambda: session_bounds(previous)[0]+60*MIN, stopping=False,
        plans={'r1': plan()}, rows={'r1': {'status': 'armed', 'state': {'phase': 'waiting', 'day': previous}}})
    await repair_gaps(runtime, load=load)
    load.assert_not_awaited()
