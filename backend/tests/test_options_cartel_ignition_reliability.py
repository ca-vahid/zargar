import datetime as dt
from dataclasses import replace

import httpx
import pytest

from zargar.domain import Bar
from zargar.marketstructure.market_calendar import next_trading_day
from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy
from zargar.techniques.options_cartel.data import DailyBar
from zargar.techniques.options_cartel.data_quality import evidence, merge, pack, unpack
from zargar.techniques.options_cartel.ignition import detect, record, watchlist
from zargar.techniques.options_cartel.preparation_io import PreparationHistory

from .test_options_cartel_preparation import inputs


def history():
    day=dt.date(2026,1,2)
    bars=[]
    for i in range(60):
        price=10+i*.05
        bars.append(DailyBar(symbol='IGN',session=day,open=price-.1,high=price+.5,low=price-.5,close=price,volume=600000))
        day=next_trading_day(day)
    price=bars[-1].close*1.065
    bars.append(DailyBar(symbol='IGN',session=day,open=price-.1,high=price+.15,low=price-.2,close=price,volume=2400000))
    for i in range(5):
        day=next_trading_day(day)
        bars.append(DailyBar(symbol='IGN',session=day,open=price,high=price+.1,low=price-.15,close=price-.02,volume=120000))
    return bars


def test_source_roundtrip_upgrade_and_downgrade():
    b=Bar('A','1m',60000,1,2,1,2,100,source='sampled')
    tape={str(b.ts): b.to_row()}
    assert unpack('A',b.to_row()).source=='unknown'
    assert merge(tape,b)
    exchange=replace(b,source='exchange',volume=250)
    assert merge(tape,exchange)
    assert not merge(tape,b)
    assert unpack('A',tape[str(b.ts)])==exchange
    assert evidence(tape)['sourceCounts']=={'exchange':1}
    assert evidence(tape)['inputHash']!=evidence({str(b.ts):pack(b)})['inputHash']


def test_ignition_waits_for_consolidation_without_reapplying_event_change():
    bars=history()
    event_at=session_bounds(bars[60].session.isoformat())[1]
    initial=detect(bars,event_at)
    assert len(initial)==1 and initial[0]['stage']=='ignition_verified'
    at=session_bounds(bars[-1].session.isoformat())[1]
    ready=detect(bars,at)
    assert ready[0]['id']==initial[0]['id']
    assert ready[0]['stage']=='setup_ready',ready
    assert ready[0]['consolidationSessions']==5
    assert ready[0]['placesOrders'] is False
    bad=[*bars[:-1],bars[-1].model_copy(update={'close':bars[60].low-.1,'low':bars[60].low-.2,'volume':3000000})]
    assert detect(bad,at)[0]['stage']=='invalidated'


async def test_ignition_records_are_idempotent_and_do_not_regress(engine):
    bars=history();at=session_bounds(bars[-1].session.isoformat())[1]
    await record(engine,bars,at)
    await record(engine,bars,session_bounds(bars[60].session.isoformat())[1])
    rows=(await watchlist(engine))['rows']
    assert len(rows)==1 and rows[0]['stage']=='setup_ready'


async def test_durable_cache_reuses_without_an_analysis_record(engine):
    at,providers=inputs();calls=[]
    async def fetch(*args,**kwargs):
        calls.append(args)
        return await providers['fetch'](*args,**kwargs)
    async def report(**kwargs):
        pass
    reader=PreparationHistory(engine,fetch,report,PreparationPolicy(request_interval_seconds=0),lambda:at)
    first,_=await reader.daily('SPY',at,None)
    again,provenance=await reader.daily('SPY',at+1,None)
    assert first==again and len(calls)==1
    assert provenance['historyReusedFrom']=='durable_cache'


async def test_native_pagination_keeps_later_symbols_and_rejects_repeated_token(monkeypatch):
    from zargar.marketstructure import history as module
    monkeypatch.setitem(module._ALPACA,'key','fixture')
    monkeypatch.setitem(module._ALPACA,'secret','fixture')
    row={'t':'2026-09-10T04:00:00Z','o':10,'h':11,'l':9,'c':10,'v':500000}
    async def handler(request):
        if request.url.params.get('page_token'):
            return httpx.Response(200,json={'bars':{'BBB':[row]},'next_page_token':None})
        return httpx.Response(200,json={'bars':{'AAA':[row]},'next_page_token':'next'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result=await module.fetch_daily_batch(['AAA','BBB'],1789000000000,1789160000000,client=client)
    assert all(len(result[s])==1 for s in ('AAA','BBB'))
    assert result['AAA'][0].source=='exchange'
    async def loop(request):
        return httpx.Response(200,json={'bars':{},'next_page_token':'same'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(loop)) as client:
        with pytest.raises(module.HistoryError,match='repeated'):
            await module.fetch_daily_batch(['AAA'],1789000000000,1789160000000,client=client)


@pytest.mark.parametrize('bad_source', ['sampled', 'unknown', 'sim'])
def test_verified_entry_rejects_untrusted_confirmation(bad_source):
    from zargar.techniques.options_cartel.entry import read_entry

    from .test_options_cartel_entry import MIN, OPEN, plan, tape
    p = plan()
    p = p.model_copy(update={'entry':p.entry.model_copy(update={'require_exchange_bars':True})})
    bars = [replace(b,source='exchange') for b in tape()]
    assert read_entry(p,bars,OPEN+10*MIN)['signal']
    bars[-1] = replace(bars[-1],source=bad_source)
    result = read_entry(p,bars,OPEN+10*MIN)
    assert result['signal'] is None
    assert any(t['decision']=='untrusted_confirmation' for t in result['trace'])


async def test_lease_cannot_be_stolen_or_released_by_previous_owner(engine):
    from zargar.techniques.options_cartel.preparation_lease import claim, release, renew
    await claim(engine,'practice','one',1000)
    with pytest.raises(ValueError,match='active'):
        await claim(engine,'practice','two',1001)
    await claim(engine,'practice','two',121001)
    with pytest.raises(ValueError,match='ownership'):
        await renew(engine,'practice','one',121002)
    await release(engine,'practice','one')
    with pytest.raises(ValueError,match='active'):
        await claim(engine,'practice','three',121003)
    await release(engine,'practice','two')


async def test_pilot_analysis_uses_sequence_instead_of_generic_weekly_base(engine):
    from zargar.techniques.options_cartel.rules import CartelRules
    from zargar.techniques.options_cartel.service import CartelService, FactsInput, ResearchInput
    bars=history();at=session_bounds(bars[-1].session.isoformat())[1]+1000
    body=ResearchInput(history=bars,indices={s:[b.model_copy(update={'symbol':s}) for b in bars] for s in ('SPY','QQQ')},
        facts=FactsInput(symbol='IGN',observed_at=at,source='synthetic event fixture',market_cap=1000000000,
            cap_observed_at=at,cap_data_as_of_ms=session_bounds(bars[-1].session.isoformat())[0]),
        rules=CartelRules.for_profile('post_ignition_2026_09_11'),as_of_ms=at,data_source='synthetic event fixture')
    result=await CartelService(engine).analyze(body)
    candidates=result['result']['analysis']['candidates']
    assert len(candidates)==1 and candidates[0]['setup']=='post_ignition'
    assert candidates[0]['contextPassed'] is True
    assert result['config']['inputs']['parameters']['family']=='post_ignition'


def test_live_cannot_select_pilot_or_disable_source_quality():
    with pytest.raises(ValueError,match='Practice-only'):
        PreparationPolicy(workspace='live',profile='post_ignition_2026_09_11')
    with pytest.raises(ValueError,match='exchange'):
        PreparationPolicy(workspace='live',require_exchange_history=False)


def test_sampled_predecessor_cannot_manufacture_a_new_crossing():
    from zargar.techniques.options_cartel.entry import read_entry

    from .test_options_cartel_entry import MIN, OPEN, plan, tape
    p=plan()
    p=p.model_copy(update={'entry':p.entry.model_copy(update={'require_exchange_bars':True,'stop_mode':'breakout_bar'})})
    bars=[replace(b,source='sampled' if i<5 else 'exchange',open=b.open if i<5 else 48.9) for i,b in enumerate(tape())]
    assert read_entry(p,bars,OPEN+10*MIN)['signal'] is None


def test_weekend_automatic_evidence_lasts_until_monday_close():
    from zargar.techniques.options_cartel.preparation_readiness import automatic_valid_until

    from .test_options_cartel_entry import plan
    friday_close=session_bounds('2026-09-11')[1]
    monday=dt.date(2026,9,14)
    p=plan(created_at=friday_close+60000,first_session=monday,last_session=monday,baseline_as_of=friday_close)
    assert automatic_valid_until(p)==session_bounds('2026-09-14')[1]
    assert automatic_valid_until(p)>p.created_at+86400000


@pytest.mark.parametrize('source,terminal',[('exchange',True),('sampled',False)])
def test_pending_invalidation_cannot_be_revived_by_a_rebound(source,terminal):
    from zargar.techniques.options_cartel.preparation_readiness import entry_readiness

    from .test_options_cartel_entry import MIN, OPEN, plan, tape
    p=plan()
    p=p.model_copy(update={'entry':p.entry.model_copy(update={'require_exchange_bars':True})})
    bars=[replace(b,source='exchange') for b in tape()]
    bars[:5]=[replace(b,open=48.2,high=48.3,low=48.,close=48.2,source=source) for b in bars[:5]]
    result=entry_readiness(p,bars,OPEN+10*MIN)
    assert not result['ready']
    assert result['terminal'] is terminal
    if terminal: assert result['terminalStatus']=='invalidated'


async def test_ignition_watchlist_hides_retired_theses_by_default(engine):
    from zargar.models import CartelIgnitionThesis
    bars=history();at=session_bounds(bars[-1].session.isoformat())[1]
    rows=await record(engine,bars,at)
    async with engine.sf() as session,session.begin():
        saved=await session.get(CartelIgnitionThesis,rows[0]['id'])
        saved.stage='expired'
        saved.evidence={**saved.evidence,'stage':'expired'}
    assert (await watchlist(engine))['rows']==[]
    assert len((await watchlist(engine,include_inactive=True))['rows'])==1
