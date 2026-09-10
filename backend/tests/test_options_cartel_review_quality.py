import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from zargar.domain import Bar
from zargar.models import Order
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy, automatic_review
from zargar.techniques.options_cartel.entry import read_entry
from zargar.techniques.options_cartel.exits import ExitCampaign
from zargar.techniques.options_cartel.observation_health import coverage, repair_gaps
from zargar.techniques.options_cartel.plans import EntryPolicy
from zargar.techniques.options_cartel.quality import quality_key
from zargar.techniques.options_cartel.replay import replay_campaign

from .test_options_cartel_entry import MIN, OPEN, plan, tape
from .test_options_cartel_prepare import input_data
from .test_options_cartel_state import repo as _repo_fixture

repo = _repo_fixture


def test_nearby_resistance_is_not_skipped_to_pass_target_quality():
    data = input_data()
    research = {'history':[b.model_dump(mode='json') for b in data['history']], 'as_of_ms':data['as_of_ms'],'direction':'long'}
    candidate = {'contextPassed':True,'setup':'base','trigger':100.,'invalidation':90.,'targets':[100.1,110.]}
    assert automatic_review(research, {'candidates':[candidate]}, PreparationPolicy()) is None
    reviewed = automatic_review(research, {'candidates':[candidate]}, PreparationPolicy(min_target_distance_pct=0))
    assert reviewed.reviewed_targets[0] == 100.1
    assert reviewed.entry_policy.min_target_r == .25


def test_quality_ranking_uses_room_before_volume_and_stable_symbol_tie_break():
    room = {'structuralTargetR':2,'directionalRelativeStrength':5,'dailyVolume':100}
    volume = {**room,'structuralTargetR':.1,'dailyVolume':1e9}
    assert quality_key(room,'B') < quality_key(volume,'A')
    assert quality_key(room,'A') < quality_key(room,'B')


def test_entry_and_replay_recheck_target_room_at_the_actual_price():
    policy = EntryPolicy(timeframe_minutes=5,stop_mode='preplanned',max_chase_r=2,min_target_r=.25)
    too_close = plan(targets=(48.95,55.),entry=policy)
    read = read_entry(too_close,tape(),OPEN+10*MIN)
    assert read['signal'] is None and any('requires 0.25R' in r['reason'] for r in read['trace'])
    p = plan(targets=(49.15,55.),entry=policy)
    bars = tape()+[Bar(p.symbol,'1m',OPEN+10*MIN,49.08,49.1,49.,49.05,500)]
    campaign = ExitCampaign.for_profile('june_2026',list(p.targets))
    assert read_entry(p,bars,OPEN+11*MIN)['signal']
    assert replay_campaign(p,campaign,bars,[],as_of_ms=OPEN+11*MIN)['status'] == 'entry_price_rejected'
    legacy = p.model_copy(update={'entry':policy.model_copy(update={'min_target_r':0})})
    assert replay_campaign(legacy,campaign,bars,[],as_of_ms=OPEN+11*MIN)['fills']


def test_recent_unclosed_delivery_delay_is_not_an_overdue_gap():
    state = {'minutes':{str(b.ts):b.to_row() for b in tape()[:-1]}}
    assert coverage(state,OPEN+10*MIN)['missingMinutes'] == 1
    assert coverage(state,OPEN+10*MIN)['overdueMissingMinutes'] == 0
    del state['minutes'][str(OPEN)]
    assert coverage(state,OPEN+10*MIN)['overdueMissingMinutes'] == 1


async def make_runtime(repo):
    await repo.arm('r1','pf','auto',{},now_ms=OPEN)
    async with repo.engine.sf() as session, session.begin():
        row = await repo._locked(session,'r1')
        row.state = {**row.state,'day':'2026-05-05','lastMinute':OPEN+9*MIN,
                     'minutes':{str(b.ts):b.to_row() for i,b in enumerate(tape()) if i != 2}}
    return SimpleNamespace(engine=repo.engine,repository=repo,rows={'r1':await repo.load('r1')},
        plans={'r1':plan(id='r1')},clock=lambda:OPEN+10*MIN,stopping=False,_publish=lambda _:None)


async def test_gap_repair_restores_context_without_firing_missed_signal(repo):
    runtime = await make_runtime(repo)
    async def load(*args): return tape()
    await repair_gaps(runtime,load=load)
    row = await repo.load('r1')
    assert len(row['state']['minutes']) == 10
    assert row['state']['observeAfter'] == OPEN+10*MIN
    assert row['state']['signal'] is None and row['state']['phase'] == 'waiting'
    assert coverage(row['state'],OPEN+10*MIN)['recoveries'] == 1
    assert read_entry(runtime.plans['r1'],tape(),OPEN+10*MIN,entry_after=row['state']['observeAfter'])['signal'] is None
    async with repo.engine.sf() as session:
        assert await session.scalar(select(func.count()).select_from(Order)) == 0


async def test_gap_repair_does_not_overwrite_a_signal_that_arrived_during_fetch(repo):
    runtime = await make_runtime(repo)
    async def load(*args):
        signal = read_entry(runtime.plans['r1'],tape(),OPEN+10*MIN)['signal']
        await repo.consume_signal('r1',signal,now_ms=OPEN+10*MIN)
        return tape()
    await repair_gaps(runtime,load=load)
    row = await repo.load('r1')
    assert row['state']['phase'] == 'signalled' and row['state']['signal']
    assert len(row['state']['minutes']) == 9


async def test_cancelled_gap_repair_does_not_leave_an_unowned_fetch(repo):
    runtime = await make_runtime(repo)
    started=asyncio.Event(); stopped=asyncio.Event()
    async def load(*args):
        started.set()
        try: await asyncio.Event().wait()
        finally: stopped.set()
    task=asyncio.create_task(repair_gaps(runtime,load=load))
    await started.wait(); task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert stopped.is_set()


def test_health_stops_entry_coverage_at_signal_and_keeps_its_original_session():
    state = {'day':'2026-05-05','minutes':{str(b.ts):b.to_row() for b in tape()}, 'signal':{'at':OPEN+10*MIN}}
    report = coverage(state, OPEN+86400000)
    assert report['expectedMinutes'] == report['recordedMinutes'] == 10
    assert report['missingMinutes'] == 0 and report['session'] == '2026-05-05'


def test_breadth_is_advisory_and_missing_nymo_is_not_fabricated():
    from zargar.techniques.options_cartel.breadth import read_breadth
    data = input_data()
    result = read_breadth(data['indices'], data['as_of_ms'])
    assert result['advisoryOnly'] and result['indices']['SPY']['available']
    assert not result['indices']['RSP']['available'] and not result['nymo']['available']


async def test_failed_gap_repair_does_not_restore_a_retired_plan(repo):
    runtime = await make_runtime(repo)
    async def load(*args):
        await repo.set_status('r1','disarmed')
        runtime.rows.pop('r1')
        raise ValueError('provider failed after retirement')
    await repair_gaps(runtime,load=load)
    assert 'r1' not in runtime.rows
    assert (await repo.load('r1'))['status'] == 'disarmed'
