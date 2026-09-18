"""PR204 boundary probes. Synthetic data/I/O only; no DB, provider or orders."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from .test_codex_team2_data_eod import rig,bar,ms
from zargar.techniques.team2.diagnostics import payoff_estimate


@pytest.mark.parametrize('live_spot,entries',[(100.4,1),(101.1,0)])
async def test_target_must_remain_ahead_of_live_price_before_entry(monkeypatch,live_spot,entries):
    import zargar.techniques.team2.runner as module
    import zargar.execution.planrunner as shared
    runner,ap=rig(); now=ms(13,10); ap.bar_index=10
    monkeypatch.setattr(module.time,'time',lambda:now/1000)
    monkeypatch.setattr(shared,'now_ms',lambda:now)
    runner.engine.quotes=SimpleNamespace(get=lambda _:SimpleNamespace(last=live_spot,bid=live_spot-.01,ask=live_spot+.01,ts=now,source_ts=now,source='alpaca'))
    e={'event':'fire','ts':now,'setup':'pm_break_up@12:15','touch':1,'spot':100.1,'target':101.,'targetKind':'plan',
       'entryKind':'ema','sizeMult':.5,'bucket':'small','why':'valid closed-bar signal','regime':{'stack':'bull','atr':.3}}
    res=SimpleNamespace(setups=[{'id':e['setup'],'kind':'pm_break_up','direction':'long','anchor':100.,'target':101.}])
    runner.pick_contract=AsyncMock(return_value={'symbol':'TEST','ask':.5})
    runner._enter=AsyncMock()
    await runner._fire_from_event(ap,e,bar(13,9,100.3),res,halted=False,journal=True)
    await runner.wait_fires(ap.run_id)
    assert runner._enter.await_count==entries,'closed candle passed but the current quote has already crossed the target'


@pytest.mark.parametrize('bid',[None,0.,.8])
def test_missing_or_invalid_spread_cannot_be_treated_as_zero_cost(bid):
    r=payoff_estimate(.69,bid,.46,.05,.03,1.04)
    assert r['status']=='insufficient evidence','missing/crossed bid became a zero-spread payoff estimate'


async def test_cancelled_fetch_owner_settles_coalesced_waiter():
    runner,_=rig(); started=asyncio.Event(); finish=asyncio.Event()
    async def fetch():
        started.set(); await finish.wait(); return ['listing']
    key=('provider','SPY','2026-09-14')
    owner=asyncio.create_task(runner._cached_chain_call(key,fetch,ttl_s=900,max_age_s=14400))
    await started.wait()
    waiter=asyncio.create_task(runner._cached_chain_call(key,fetch,ttl_s=900,max_age_s=14400))
    await asyncio.sleep(0)
    owner.cancel(); await asyncio.gather(owner,return_exceptions=True)
    await asyncio.sleep(0)
    settled=waiter.done()
    waiter.cancel(); await asyncio.gather(waiter,return_exceptions=True)
    assert settled,'owner cancellation left a shared pending future that cannot complete'


async def test_cancelled_waiter_does_not_cancel_the_shared_fetch():
    runner,_=rig(); started=asyncio.Event(); finish=asyncio.Event()
    async def fetch():
        started.set(); await finish.wait(); return ['listing']
    key=('provider','SPY','2026-09-14')
    owner=asyncio.create_task(runner._cached_chain_call(key,fetch,ttl_s=900,max_age_s=14400))
    await started.wait()
    waiter=asyncio.create_task(runner._cached_chain_call(key,fetch,ttl_s=900,max_age_s=14400))
    await asyncio.sleep(0)
    waiter.cancel(); await asyncio.gather(waiter,return_exceptions=True)
    finish.set()
    result=(await asyncio.gather(owner,return_exceptions=True))[0]
    assert not isinstance(result,BaseException),f'cancelled waiter poisoned shared result: {result!r}'
    assert result[0]==['listing']
