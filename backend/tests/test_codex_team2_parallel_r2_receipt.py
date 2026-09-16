"""Receipt integration boundaries at78fb14a; no DB/network/engine actions."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from .test_team2_experiments2 import _receipt_rig, FULL, PFS, ARMED, RUNS, _armed, _run


async def receipt(monkeypatch,tmp_path,armed,runs):
    from zargar.tools import team2_receipt
    target=_receipt_rig(monkeypatch,tmp_path,FULL,PFS,armed,runs,
                        {'ok':True,'version':'0.7.94','build':'review-build'},{'pausedBooks':[]})
    monkeypatch.setattr(team2_receipt,'c6_status',lambda:{'satisfied':True,'evidence':{'reviewedBy':'fixture'}})
    await team2_receipt.main(SimpleNamespace(date='2026-09-16',out=str(target)))
    return json.loads(target.read_text(encoding='utf-8'))


async def test_receipt_accepts_current_service_plan_identity(monkeypatch,tmp_path):
    from zargar.techniques.team2.service import CODE_VERSION
    runs=copy.deepcopy(RUNS)
    for run in runs:
        run.config['codeVersion']=CODE_VERSION  # exact value mint_plan_run writes, not an invented app version
    report=await receipt(monkeypatch,tmp_path,ARMED,runs)
    assert report['activation'].startswith('READY'), report['blockers']


async def test_receipt_rejects_duplicate_symbol_plan_on_same_book(monkeypatch,tmp_path):
    report=await receipt(monkeypatch,tmp_path,ARMED+[_armed('duplicate','SPY','siz')],
                         RUNS+[_run('duplicate','sizing',{'size_full':.5})])
    assert report['activation'].startswith('NOT READY'), 'duplicate armed plan was collapsed into the symbol dictionary'


async def test_readonly_settings_load_does_not_write_legacy_mode():
    from zargar.settings_service import SettingsService
    from zargar.bus import Bus
    row=SimpleNamespace(key='trading.mode',value={'v':'sim'})
    session=SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda:SimpleNamespace(all=lambda:[row]))),
                            get=AsyncMock(return_value=row),commit=AsyncMock())
    class Context:
        async def __aenter__(self): return session
        async def __aexit__(self,*args): return False
    journal=SimpleNamespace(append=AsyncMock())
    settings=SettingsService(Context,Bus(),journal)
    settings.readonly=True
    await settings.load()
    assert settings.get('trading.mode')=='practice'
    session.commit.assert_not_awaited()
    journal.append.assert_not_awaited()
    assert row.value=={'v':'sim'}


@pytest.mark.parametrize('has_exposure',[False,True])
async def test_failed_old_book_transition_blocks_experiment_minting(has_exposure):
    from .test_team2_experiments2 import _svc,_old_plan,SIM
    old=_old_plan('old-plan','practice-old',exposure=has_exposure)
    svc,engine,runner=_svc(FULL,{'old-plan':old},{**SIM,'practice-old':{'kind':'sim'}})
    operation=engine.pause_book if has_exposure else runner.disarm
    operation.side_effect=RuntimeError('transition failed before confirmation')
    out=await svc.nightly_plans('2026-09-16',arm=False,force=True)
    assert not any(r['portfolioId'] in ('siz','c1b') for r in out['runs']), 'new experiment plans minted after transition failure'
    assert out['failed']
