from unittest.mock import AsyncMock

from zargar.models import TechniqueRun
from zargar.technique.service import TechniqueService
from zargar.techniques.options_cartel import preparation as prep
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.preparation_scope import SETTING
from zargar.marketstructure.sessions import next_session_date
from .test_options_cartel_preparation import inputs


async def test_shared_cleanup_leaves_cartel_checkpoint_to_owner(engine):
    async with engine.sf() as s,s.begin():
        s.add_all([TechniqueRun(id='cartel-restart',technique='options_cartel',mode='preparation',
            symbol='MULTI',status='running',as_of=1,config={},result={'resumeReady':True}),
            TechniqueRun(id='other-analysis',technique='enhanced_market',mode='analysis',
            symbol='TEST',status='running',as_of=1,config={},result={})])
    await TechniqueService(engine).fail_orphaned_sweeps()
    async with engine.sf() as s:
        assert (await s.get(TechniqueRun,'cartel-restart')).status=='running'
        assert (await s.get(TechniqueRun,'other-analysis')).status=='failed'
    await prep.recover_interrupted_preparations(engine)
    async with engine.sf() as s:
        row=await s.get(TechniqueRun,'cartel-restart')
        assert row.status=='failed' and row.result['phase']=='interrupted'
        assert row.result['resumeReady'] is True


async def test_legacy_restart_failure_recovers_without_touching_real_failure_or_cancel(engine,monkeypatch):
    at,_=inputs();day=next_session_date(at)
    book=next(p['id'] for p in engine.positions.portfolios() if p['kind']=='sim')
    policy=PreparationPolicy(enabled=True,portfolio_id=book)
    await engine.settings.set(SETTING,policy.model_dump(mode='json'))
    cfg={'coverageVersion':7,'session':day,'workspace':'practice','portfolioId':book,
         'policy':policy.model_dump(mode='json')}
    async with engine.sf() as s,s.begin():
        for key,error,cancelled in [('legacy','interrupted by a restart — run it again',False),
            ('real-failure','Provider rejected request',False),
            ('cancelled','interrupted by a restart — run it again',True)]:
            s.add(TechniqueRun(id=key,technique='options_cartel',mode='preparation',symbol='MULTI',
                status='failed',as_of=at,config=cfg,result={'phase':'market_context','resumeReady':True,
                'savedAnalysesAvailable':3072,'userCancelled':cancelled,'recovery':{'attempt':2}},error=error))
    await prep.recover_interrupted_preparations(engine)
    async with engine.sf() as s:
        row=await s.get(TechniqueRun,'legacy')
        assert row.result['phase']=='interrupted' and row.result['savedAnalysesAvailable']==3072
        assert prep.resumable(row,policy,at+1)
        assert (await s.get(TechniqueRun,'real-failure')).error=='Provider rejected request'
        assert (await s.get(TechniqueRun,'cancelled')).result['phase']=='market_context'
    # Make the resumable row latest to model the real startup ordering.
    import datetime as dt
    async with engine.sf() as s,s.begin():
        row=await s.get(TechniqueRun,'legacy');row.created_at=dt.datetime.now(dt.UTC)+dt.timedelta(seconds=1)
        s.add(TechniqueRun(id='other-book',technique='options_cartel',mode='preparation',symbol='MULTI',
            status='failed',as_of=at,config={**cfg,'portfolioId':'different-book'},
            result={'phase':'interrupted','resumeReady':True},
            created_at=dt.datetime.now(dt.UTC)+dt.timedelta(seconds=2)))
    submit=AsyncMock();monkeypatch.setattr(prep,'submit_preparation',submit)
    engine.cartel_observer=object()
    await prep.automatic_recovery(engine,clock=lambda:at+1)
    submit.assert_awaited_once()
    assert submit.call_args.kwargs['resume_run_id']=='legacy'


async def test_retry_lineage_reuses_ancestor_and_uncheckpointed_child(engine):
    from zargar.techniques.options_cartel.preparation_resume import saved_work
    at,_=inputs();policy=PreparationPolicy(enabled=True,portfolio_id='book')
    cfg={'coverageVersion':7,'session':next_session_date(at),'workspace':'practice','portfolioId':'book',
         'policy':policy.model_dump(mode='json')}
    async with engine.sf() as s,s.begin():
        s.add_all([
            TechniqueRun(id='ancestor',technique='options_cartel',mode='preparation',symbol='MULTI',
                status='done',as_of=at,config=cfg,result={'rows':[{'symbol':'A','analysisId':'a','status':'filtered'}]}),
            TechniqueRun(id='retry',technique='options_cartel',mode='preparation',symbol='MULTI',
                status='failed',as_of=at,config=cfg,result={'resumedFrom':'ancestor','rows':[]}),
            TechniqueRun(id='b',technique='options_cartel',mode='analysis',symbol='B',status='done',
                parent_run_id='retry',as_of=at,config={'inputs':{'as_of_ms':at}},
                result={'collection':{'historyCacheVersion':1}}),
            TechniqueRun(id='future',technique='options_cartel',mode='analysis',symbol='C',status='done',
                parent_run_id='retry',as_of=at+1,config={'inputs':{'as_of_ms':at+1}},
                result={'collection':{'historyCacheVersion':1}})])
    async with engine.sf() as s: row=await s.get(TechniqueRun,'retry')
    rows,_,reused=await saved_work(engine,row)
    assert reused=={'A':'a','B':'b'} and rows['A']['status']=='filtered'
    async with engine.sf() as s,s.begin():
        ancestor=await s.get(TechniqueRun,'ancestor');ancestor.config={**cfg,'portfolioId':'other-book'}
    _,_,reused=await saved_work(engine,row)
    assert reused=={'B':'b'}


async def test_pre_attachment_recovery_does_not_consume_throttle(engine):
    engine.cartel_observer=None
    await prep.automatic_recovery(engine,clock=lambda:123456789)
    assert not hasattr(engine,'_cartel_auto_recovery_at')


async def test_benchmark_wait_retries_are_spaced(engine,monkeypatch):
    at,_=inputs();day=next_session_date(at)
    book=next(p['id'] for p in engine.positions.portfolios() if p['kind']=='sim')
    policy=PreparationPolicy(enabled=True,portfolio_id=book)
    await engine.settings.set(SETTING,policy.model_dump(mode='json'))
    async with engine.sf() as s,s.begin():
        s.add(TechniqueRun(id='waiting',technique='options_cartel',mode='preparation',symbol='MULTI',status='done',
            as_of=at,config={'coverageVersion':7,'session':day,'workspace':'practice','portfolioId':book,
            'policy':policy.model_dump(mode='json')},result={'phase':'waiting_for_benchmark'}))
    submit=AsyncMock();monkeypatch.setattr(prep,'submit_preparation',submit)
    engine.cartel_observer=object()
    await prep.automatic_recovery(engine,clock=lambda:at+5*60_000)
    submit.assert_not_awaited()
    engine._cartel_auto_recovery_at=0
    await prep.automatic_recovery(engine,clock=lambda:at+prep.BENCHMARK_RETRY_MS)
    submit.assert_awaited_once()


def test_order_free_research_defaults_off():
    from zargar.settings_service import DEFAULTS
    assert DEFAULTS['techniques.options_cartel.intraday_research'] is False
    assert DEFAULTS['techniques.options_cartel.profitability_research'] is False
    assert DEFAULTS['techniques.options_cartel.method_lab'] is False
    assert PreparationPolicy().ignition_research is False
