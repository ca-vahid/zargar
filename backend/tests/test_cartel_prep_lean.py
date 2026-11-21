"""C3/C4 (2026-09-27): lean preparation - keep evidence only for setups and near misses; check the benchmark first."""
from zargar.models import TechniqueRun
from zargar.marketstructure.sessions import next_session_date
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.preparation import evaluation_row, keep_evidence
from zargar.techniques.options_cartel.preparation_resume import saved_work

from .test_options_cartel_preparation import inputs as prep_inputs


def gate(status):
    return {'label': f'gate-{status}', 'status': status}


def test_keep_evidence_for_setups_and_single_failures_only():
    passing = {'gates': [gate('pass')]}
    assert keep_evidence(passing, {'candidates': [{'contextPassed': True}], 'checks': [gate('fail'), gate('fail')]})
    assert keep_evidence(passing, {'candidates': [{'researchContextPassed': True}], 'checks': []})
    assert keep_evidence(passing, {'candidates': [], 'checks': [gate('fail')]})               # near miss kept
    assert not keep_evidence({'gates': [gate('fail')]}, {'candidates': [], 'checks': [gate('fail')]})
    assert not keep_evidence(passing, {'candidates': [], 'checks': [gate('unknown'), gate('fail')]})


def test_unsaved_filtered_row_is_marked_and_links_nothing():
    saved = {'runId': None, 'symbol': 'THIN', 'result': {'screen': {'gates': [gate('fail')]}, 'analysis': {'checks': [gate('fail')]}}}
    row = evaluation_row(saved, None)
    assert row['analysisId'] is None and row['evidenceSaved'] is False and row['status'] == 'filtered'


async def test_stale_benchmark_stops_before_discovery(engine):
    from zargar.techniques.options_cartel.preparation import SETTING, run_preparation
    from zargar.techniques.options_cartel.runtime import CartelRuntime
    at, providers = prep_inputs()
    full, discovered = providers['fetch'], []

    async def stale(symbol, tf, start, end, *, client):
        bars = await full(symbol, tf, start, end, client=client)
        return bars[:-1] if tf == '1d' and symbol in ('SPY', 'QQQ') else bars

    async def discover(rules, *, clock):
        discovered.append(1)
        raise AssertionError('discovery must not run while the benchmark is stale')
    providers.update(fetch=stale, discover=discover)
    runtime = CartelRuntime(engine); runtime.clock = lambda: at
    engine.cartel_observer = runtime
    policy = PreparationPolicy(enabled=True, request_interval_seconds=0)
    await engine.settings.set(SETTING, policy.model_dump(mode='json'))
    try:
        result = (await run_preparation(engine, policy, clock=lambda: at, **providers))['result']
        assert result['phase'] == 'waiting_for_benchmark' and result['benchmarkPrecheck'] is True
        assert set(result['marketDataErrors']) == {'SPY', 'QQQ'} and not discovered and result['discovered'] == 0
    finally:
        await runtime.stop()


async def test_resume_reuses_an_unsaved_filtered_row_without_loading(engine):
    at, _ = prep_inputs()
    policy = PreparationPolicy(enabled=True, portfolio_id='book')
    cfg = {'coverageVersion': 7, 'session': next_session_date(at), 'workspace': 'practice', 'portfolioId': 'book',
           'policy': policy.model_dump(mode='json')}
    async with engine.sf() as s, s.begin():
        s.add(TechniqueRun(id='lean', technique='options_cartel', mode='preparation', symbol='MULTI', status='failed', as_of=at,
                           config=cfg, result={'rows': [{'symbol': 'THIN', 'analysisId': None, 'evidenceSaved': False,
                                                         'status': 'filtered', 'reasons': ['a', 'b']}]}))
    async with engine.sf() as s:
        row = await s.get(TechniqueRun, 'lean')
    rows, _, reused = await saved_work(engine, row)
    assert 'THIN' in reused and reused['THIN'] is None and rows['THIN']['evidenceSaved'] is False
