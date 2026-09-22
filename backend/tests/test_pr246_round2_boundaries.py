from types import SimpleNamespace
from unittest.mock import AsyncMock

from zargar.techniques.options_cartel.cadence import control_config
from zargar.techniques.options_cartel.review_attribution import attribute
from zargar.techniques.options_cartel.review_ledger import summarize_fills
from zargar.techniques.options_cartel.runtime import CartelRuntime
from .test_options_cartel_entry import OPEN, MIN, plan
from .test_options_cartel_state import repo


async def test_restored_retired_control_restores_its_market_data_subscription(repo, monkeypatch):
    await repo.engine.positions.load()
    block=control_config('breakout_5m_v1',{'timeframeMinutes':15,'baselines':{i:1000 for i in range(26)}},OPEN-MIN)
    await repo.arm('r1','pf','alert',{'cadence':block},now_ms=OPEN)
    await repo.set_status('r1','disarmed')
    ensure=AsyncMock();monkeypatch.setattr(repo.engine,'ensure_symbol',ensure)
    runner=CartelRuntime(repo.engine);runner.clock=lambda:OPEN+7*MIN
    repo.engine.cartel_observer=runner
    try:
        await runner.restore()
        assert 'r1' in runner.controls
        ensure.assert_any_await('HOOD')
    finally:
        await runner.stop()


def test_asof_partial_fills_do_not_use_later_order_cumulative_totals():
    order=SimpleNamespace(id='o',symbol='HOOD',sec_type='STK',portfolio_id='pf',side='BUY')
    def fill(key,qty,ts):
        return SimpleNamespace(id=key,symbol='HOOD',portfolio_id='pf',side='BUY',qty=qty,price=49,commission=0,ts=ts)
    cutoff=OPEN+2*MIN
    assets,issues=summarize_fills([(fill('first',2,OPEN+MIN),order),(fill('later',1,OPEN+3*MIN),order)],
                                 OPEN,cutoff,{'o':'r1'})
    assert not issues and assets[0]['entryFilledQty']==2
    result=attribute(plan(id='r1'),{'orderId':'o','minutes':{}},plan().first_session.isoformat(),cutoff,
        assets=assets,entry_orders=[{'id':'o','qty':3,'filledQty':3,'status':'FILLED'}])
    assert result['entry']['filledQty']==2, 'Order row was updated after the cutoff; executions are the as-of authority'
