"""Parallel-book contract probes at41ec565. All I/O mocked; no engine/DB/provider use."""
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from zargar.techniques.team2.rules import experiment_books
from zargar.techniques.team2.service import Team2Service


def test_combined_c1_sizing_is_rejected_not_applied():
    settings={'techniques.team2.experiments': {'enabled':True,'books':[
        {'portfolioId':'mixed','label':'sizing','overrides':{'size_full':.5,'no_trade_zone':'conjunction'}}]}}
    try:
        books=experiment_books(settings)
    except ValueError:
        return
    assert not any(b.get('overrides')=={'size_full':.5,'no_trade_zone':'conjunction'} for b in books), 'combined arm accepted'


async def test_empty_label_cannot_bypass_practice_only_mint_guard():
    settings={'techniques.team2.symbols':['SPY'],'techniques.team2.default_portfolio':'control',
        'techniques.team2.experiments':{'enabled':True,'books':[
            {'portfolioId':'real','label':'','overrides':{'size_full':.5}}]}}
    session=SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda:SimpleNamespace(all=lambda:[]))))
    class Context:
        async def __aenter__(self): return session
        async def __aexit__(self,*args): return False
    engine=SimpleNamespace(settings=settings,sf=Context,positions=SimpleNamespace(
        portfolio=lambda pid:{'kind':'live' if pid=='real' else 'sim'}))
    svc=Team2Service(engine,SimpleNamespace(_armed={}))
    svc.mint_plan_run=AsyncMock(side_effect=lambda *args,**kw:{'runId':'synthetic','symbol':'SPY','plan':{}})
    out=await svc.nightly_plans('2026-09-16',arm=False)
    assert not any(r['portfolioId']=='real' for r in out['runs']), 'live-kind experiment plan minted because label was empty'


async def test_receipt_cannot_be_ready_with_only_control_no_plans_and_unhealthy_engine(monkeypatch,tmp_path):
    import urllib.request
    import pathlib
    import zargar.config as config
    import zargar.db as db
    import zargar.settings_service as settings_module
    from zargar.tools import team2_receipt
    values={'techniques.team2.default_portfolio':'control','techniques.team2.experiments':{'enabled':True,'books':[]}}
    class Settings:
        def __init__(self,*args): pass
        async def load(self): pass
        def get(self,k,d=None): return values.get(k,d)
    portfolio=SimpleNamespace(id='control',name='Control',kind='sim',cash=10000,starting_cash=10000,archived=False)
    queried=[SimpleNamespace(scalars=lambda:SimpleNamespace(all=lambda:[portfolio])),
             SimpleNamespace(scalars=lambda:SimpleNamespace(all=lambda:[]))]
    session=SimpleNamespace(execute=AsyncMock(side_effect=queried))
    class Context:
        async def __aenter__(self): return session
        async def __aexit__(self,*args): return False
    monkeypatch.setattr(config,'get_config',lambda:SimpleNamespace(database_url='unused'))
    monkeypatch.setattr(db,'make_engine',lambda _:SimpleNamespace(dispose=AsyncMock()))
    monkeypatch.setattr(db,'make_session_factory',lambda _:Context)
    monkeypatch.setattr(settings_module,'SettingsService',Settings)
    monkeypatch.setattr(urllib.request,'urlopen',lambda url,**kw:io.BytesIO(json.dumps({'ok':False} if url.endswith('/health') else {}).encode()))
    # Assume C6 independently satisfied to isolate the remaining readiness requirements.
    monkeypatch.setattr(pathlib.Path,'read_text',lambda *args,**kw:'C6 satisfied')
    target=tmp_path/'receipt.json'
    await team2_receipt.main(SimpleNamespace(date='2026-09-16',out=str(target)))
    with open(target,encoding='utf-8') as f: receipt=json.load(f)
    assert receipt['activation'].startswith('NOT READY'), receipt['activation']
