"""Shadow-measurement boundaries only. No DB, providers or orders."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zargar.techniques.team2 import diagnostics as d
from zargar.techniques.team2.runner import Team2Runner


def test_stale_cached_quote_is_unknown_even_when_observer_runs_on_time():
    due=1_000_000
    obs=d.observation('2m',due,due,{'OPT':{'bid':.6,'ask':.61,'priced':'opra','quoteTs':due-120_000}})
    assert obs['status']=='unknown' or obs.get('quotes',{}).get('OPT') is None, 'two-minute-old cached quote counted as fresh horizon observation'


def test_missing_entry_price_does_not_crash_or_create_a_return():
    rec={'trigger':'setup#1','setup':'setup','candidates':[
        {'symbol':'selected','selected':True,'inBand':True,'ask':.5,'mid':.495},
        {'symbol':'unpriced','selected':False,'inBand':False,'ask':0.0,'mid':None}],
        'observations':{'2m':{'status':'observed','quotes':{
            'selected':{'bid':.6,'mid':.605},'unpriced':{'bid':.4,'mid':.405}}}}}
    report=d.summarize_day([rec],1.04)
    row=report['perAttempt'][0]['candidates'][1]
    assert row['outcomes']['2m'] is None or row['outcomes']['2m']['askToBidPct'] is None
    assert report['contractChoice']['2m']['compared']==0


def test_exit_price_uses_confirmed_fill_quantity_not_stale_order_status():
    trade=SimpleNamespace(status='closed',filled_qty=2,avg_fill=.5,order_symbol='OPT',realized_pnl=60,
        opened_ts=1,closed_ts=2,exits=[{'status':'SUBMITTED','filledQty':2,'qty':2,'price':.8}])
    routing=Team2Runner._diag_routing(trade,4.16)
    assert routing['netPnl']==55.84
    assert routing['exitPrice']==.8, 'confirmed filled exit price lost because exit record status was not rewritten'


async def test_shadow_unknown_price_cannot_interrupt_session_close():
    from .test_codex_team2_data_eod import rig
    runner,ap=rig()
    runner._last_sim[ap.run_id]={'trades':[],'bias':{}}
    runner.disarm=AsyncMock(return_value=True)
    runner._diag_of(ap.run_id)['attempts']['setup#1']={
        'trigger':'setup#1','candidates':[
            {'symbol':'selected','selected':True,'inBand':True,'ask':.5,'mid':.495},
            {'symbol':'unpriced','selected':False,'inBand':False,'ask':0.0,'mid':None}],
        'observations':{'2m':{'status':'observed','quotes':{
            'selected':{'bid':.6,'mid':.605},'unpriced':{'bid':.4,'mid':.405}}}}}
    await runner._end_session(ap,journal=True)
    runner.disarm.assert_awaited_once()
