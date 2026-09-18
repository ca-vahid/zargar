from dataclasses import replace

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from zargar.models import CartelDecisionBundle, CartelDecisionContext, Event
from zargar.techniques.options_cartel.data_quality import pack, unpack
from zargar.techniques.options_cartel.decision_evidence import capture, digest
from zargar.techniques.options_cartel.entry import read_entry
from zargar.techniques.options_cartel.plans import CartelPlan

from .test_options_cartel_entry import MIN, OPEN, plan, tape
from .test_options_cartel_state import repo as repo_fixture

repo = repo_fixture


async def record(repo, *, bars=None, now=OPEN+10*MIN, fail=False):
    await repo.arm('r1', 'pf', 'alert', {}, now_ms=OPEN)
    bars = bars or tape()
    p = plan(id='r1')
    observation = read_entry(p,bars,now)
    async with repo.engine.sf() as session, session.begin():
        row = await repo._locked(session,'r1')
        events = await capture(session,row,p,{str(b.ts): pack(b) for b in bars},row.state,observation,now)
        if fail:
            raise RuntimeError('transaction aborted')
    return events


async def test_exact_retry_is_idempotent_and_changed_input_is_new_occurrence(repo):
    first = await record(repo)
    assert first and await record(repo) == []
    bars = tape(); bars[-1] = replace(bars[-1],volume=600)
    later = await record(repo,bars=bars)
    assert later and later[-1]['payload']['bundleId'] != first[-1]['payload']['bundleId']
    async with repo.engine.sf() as s:
        original = await s.get(CartelDecisionBundle,first[-1]['payload']['bundleId'])
        context = await s.get(CartelDecisionContext,original.context_id)
        assert context.payload['minutes'][-1][5] == 500
        assert digest(original.payload) == original.id


async def test_committed_bundle_replays_after_new_repository_and_context_reload(repo):
    events = await record(repo)
    async with repo.engine.sf() as s:
        bundle = await s.get(CartelDecisionBundle,events[-1]['payload']['bundleId'])
        context = (await s.get(CartelDecisionContext,bundle.context_id)).payload
        p = CartelPlan.model_validate(context['plan'])
        replay = read_entry(p,[unpack(p.symbol,b) for b in context['minutes']],context['asOfMs'],entry_after=context['entryAfter'])
        assert replay['trace'][-1] == bundle.payload['decision']
        assert await s.scalar(select(func.count()).select_from(Event).where(Event.type=='TechniqueCartelDecisionCaptured')) == len(events)


async def test_rollback_leaves_no_bundle_context_or_journal_reference(repo):
    with pytest.raises(RuntimeError,match='aborted'):
        await record(repo,fail=True)
    async with repo.engine.sf() as s:
        for model in (CartelDecisionBundle,CartelDecisionContext):
            assert await s.scalar(select(func.count()).select_from(model)) == 0
        assert await s.scalar(select(func.count()).select_from(Event).where(Event.type=='TechniqueCartelDecisionCaptured')) == 0


async def test_missing_context_reference_is_rejected_by_database(repo):
    with pytest.raises(IntegrityError):
        async with repo.engine.sf() as s, s.begin():
            s.add(CartelDecisionBundle(id='missing',run_id='r1',portfolio_id='pf',bucket_end=OPEN,
                                      observed_at=OPEN,context_id='absent',payload={}))
            await s.flush()
