import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock


from zargar.models import Event, TechniqueArmed
from zargar.techniques.options_cartel.session_review import report
from zargar.techniques.options_cartel.profitability_research import prewarm_next_session
from zargar.techniques.options_cartel.research_economics import entry_policy_study
from tests import test_options_cartel_state as state_tests
from tests import test_options_cartel_profitability_research as research_tests
from tests.test_options_cartel_entry import plan, tape, OPEN as ENTRY_OPEN, MIN

repo = state_tests.repo
research = research_tests.research


async def test_daily_review_reports_spread_refusal_and_excludes_future_foreign_checks(repo):
    at = dt.datetime(2026,9,15,19,tzinfo=dt.UTC)
    async with repo.engine.sf() as session, session.begin():
        session.add(TechniqueArmed(run_id='review', technique='options_cartel', symbol='QS',
            plan_for='2026-09-15', portfolio_id='pf', mode='auto', status='expired',
            config={}, state={'day':'2026-09-15','decisionHistory':[{'at':int(at.timestamp()*1000),'decision':'triggered'}]}))
        for offset, book in [(1,'pf'), (86400,'pf'), (2,'other')]:
            session.add(Event(ts=at+dt.timedelta(seconds=offset), type='TechniqueCartelPreflight', portfolio_id=book,
                aggregate_type='technique_run', aggregate_id='review', payload={'runId':'review','report':{
                    'passed':False,'checks':[{'name':'entry_contract_spread','passed':False,'reason':'Spread exceeds 20%'}],
                    'expression':{'bid':1.86,'ask':2.39}}}))
    result = await report(repo.engine,'pf','2026-09-15')
    row = next(r for r in result['rows'] if r['planId']=='review')
    assert row['category']=='execution_rejected'
    assert row['latestExecutionCheck']['reasons']==['Spread exceeds 20%']
    assert len(row['executionChecks'])==1 and result['orderCount']==0
    async with repo.engine.sf() as session, session.begin():
        session.add(Event(ts=at+dt.timedelta(seconds=3), type='TechniqueCartelPreflight',portfolio_id='pf',
            aggregate_type='technique_run',aggregate_id='review',payload={'runId':'review','report':{'passed':True,'checks':[]}}))
    result = await report(repo.engine,'pf','2026-09-15')
    assert next(r for r in result['rows'] if r['planId']=='review')['category']=='signalled'


async def test_research_baselines_warm_the_previous_evening_without_signals(research, monkeypatch):
    context = await research_tests.seed_context(research)
    target = dt.date.fromisoformat(research_tests.DAY)
    from zargar.marketstructure.market_calendar import previous_trading_day
    from zargar.marketstructure.sessions import session_bounds
    now = session_bounds(previous_trading_day(target).isoformat())[1]+3600000
    async with research.sf() as session, session.begin():
        stored = await session.get(research_tests.TechniqueRun, context.id)
        stored.as_of = now-1000
        stored.result = {**stored.result, 'frozenAt': now-1000}
    runtime = SimpleNamespace(engine=research.engine,clock=lambda:now,stopping=False)
    warm = AsyncMock(return_value=context)
    monkeypatch.setattr('zargar.techniques.options_cartel.profitability_research._warm_baselines',warm)
    await prewarm_next_session(runtime)
    warm.assert_awaited_once()
    assert warm.await_args.kwargs['attempt_limit']==3
    assert runtime._profitability_status['session']==research_tests.DAY
    research.engine.feed.watch.assert_not_awaited()
    runtime.clock=lambda:research_tests.OPEN+60000
    warm.reset_mock()
    await prewarm_next_session(runtime)
    warm.assert_not_awaited()


def test_entry_policy_diagnostics_preserve_execution_plan_and_stay_order_free():
    from dataclasses import replace
    p=plan()
    original=p.model_dump()
    bars=[replace(b,source='exchange',volume=240) for b in tape()]
    study=entry_policy_study(p,bars,as_of_ms=ENTRY_OPEN+10*MIN,entry_after=p.created_at)
    variants={r['variant']:r for r in study['rows']}
    assert variants['saved_entry_v1']['signal'] is None  # 1200 < 1500 requirement
    assert variants['volume_1x_v1']['signal'] is not None
    assert variants['gap_retest_v1']['policy']['mode']=='retest'
    assert p.model_dump()==original
    assert not study['placesOrders'] and not study['automaticPermissionChanged']
