"""Practice research observations. No executable plans, arms, approvals or orders."""
from __future__ import annotations

import datetime as dt
import hashlib
import math

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ...domain import Bar
from ...marketstructure.history import UA, fetch_window
from ...marketstructure.market_calendar import is_trading_day, previous_trading_day
from ...marketstructure.sessions import ET, session_bounds
from ...models import BarRow, TechniqueRun
from .automatic_plans import PreparationPolicy, automatic_review
from .data_quality import evidence, pack
from .entry import read_entry
from .plans import CartelPlan
from .preparation_io import DATA_ERRORS, PreparationHistory
from .preparation_readiness import baseline_coverage
from .preparation_scope import read_policy, workspace_filter
from .prepare import build_volume_baseline

SETTING = 'techniques.options_cartel.intraday_research'
VERSION = 'daily_ema_intraday_research_v1'
STEP = 15*60_000


def identity(preparation_id, suffix):
    return hashlib.sha256(f'{VERSION}:{preparation_id}:{suffix}'.encode()).hexdigest()[:32]


def closed_bucket(bars, symbol, boundary):
    rows = {b.ts:b for b in bars if b.symbol == symbol and b.tf == '1m' and boundary-STEP <= b.ts < boundary}
    if set(rows) != set(range(boundary-STEP, boundary, 60_000)):
        return {'status':'unavailable', 'reason':'Incomplete closed 15-minute bucket'}
    ordered = [rows[t] for t in sorted(rows)]
    if any(b.source != 'exchange' or not all(math.isfinite(v) for v in (b.open,b.high,b.low,b.close,b.volume))
           or b.low <= 0 or b.volume < 0 or b.high < max(b.open,b.close) or b.low > min(b.open,b.close) for b in ordered):
        return {'status':'unavailable', 'reason':'Untrusted or invalid minute evidence'}
    return {'status':'observed', 'close':ordered[-1].close, 'sourceEvidence':evidence({str(b.ts):pack(b) for b in ordered}), 'sourceBars':[pack(b) for b in ordered]}


def market_observation(saved_market, bars, boundary, observed_at, previous=None):
    day=dt.datetime.fromtimestamp(boundary/1000,ET).date()
    expected=previous_trading_day(day).isoformat()
    reads={}
    for symbol in ('SPY','QQQ'):
        read=closed_bucket(bars,symbol,boundary)
        daily=saved_market.get('indices',{}).get(symbol,{})
        emas=daily.get('emas',{})
        if daily.get('session') != expected or not all(isinstance(emas.get(str(p)),(int,float)) and math.isfinite(emas[str(p)]) and emas[str(p)]>0 for p in (8,21,50)):
            read={'status':'unavailable','reason':'Missing or stale completed-daily EMA reference'}
        read.update(dailySession=daily.get('session'),dailyEmas=emas)
        if read['status']=='observed':
            read['aboveDailyEmas']={str(p):read['close']>emas[str(p)] for p in (8,21,50)}
        reads[symbol]=read
    timely=0 <= observed_at-boundary <= 120_000
    usable=timely and all(r['status']=='observed' for r in reads.values())
    mode=saved_market.get('alignmentMode','strict')
    all_above=lambda r:all(r.get('aboveDailyEmas',{}).get(str(p)) is True for p in (8,21,50))
    aligned=usable and (all(all_above(r) for r in reads.values()) if mode=='strict' else
        any(all_above(r) for r in reads.values()) and all(r['aboveDailyEmas']['50'] for r in reads.values()))
    consecutive=bool(aligned and previous and previous.get('boundary')==boundary-STEP and previous.get('aligned'))
    since=(previous.get('improvedSince') or observed_at) if consecutive else None
    return {'boundary':boundary,'observedAt':observed_at,'indices':reads,'aligned':aligned,
        'sustained':consecutive,'improvedSince':since,'status':'sustained_improvement' if consecutive else 'improvement_observed' if aligned else 'not_aligned' if usable else 'unavailable',
        'reference':'Frozen prior-session daily EMAs; not 15-minute EMAs', 'alignmentMode':mode}


async def save(engine, key, mode, prep, at, result, config=None):
    from ... import __version__
    async with engine.sf() as session,session.begin():
        await session.execute(insert(TechniqueRun).values(id=key,technique='options_cartel',symbol='MULTI',mode=mode,
            status='done',verdict='research_only',as_of=at,parent_run_id=prep.id,
            config={'workspace':'practice','portfolioId':prep.config['portfolioId'],'session':prep.config['session'],
                    'researchVersion':VERSION,'codeVersion':__version__,**(config or {})},
            result={**result,'placesOrders':False,'automaticPermissionChanged':False}).on_conflict_do_nothing(index_elements=['id']))


async def collect(runtime):
    engine=runtime.engine; now=runtime.clock()
    if not engine.settings.get(SETTING,False):
        runtime._intraday_research_started=None
        return
    policy=read_policy(engine,'practice')
    if not policy.enabled:
        return
    day=dt.datetime.fromtimestamp(now/1000,ET).date()
    opens,closes=session_bounds(day.isoformat())
    if not is_trading_day(day) or not opens-45*60_000 <= now <= closes+120_000:
        return
    async with engine.sf() as session:
        prep=await session.scalar(select(TechniqueRun).where(TechniqueRun.technique=='options_cartel',TechniqueRun.mode=='preparation',
            TechniqueRun.status=='done',workspace_filter('practice'),TechniqueRun.config['session'].as_string()==day.isoformat(),
            TechniqueRun.config['portfolioId'].as_string()==policy.portfolio_id).order_by(TechniqueRun.created_at.desc()).limit(1))
    if prep is None or not prep.result.get('armingBlocked') or prep.result.get('researchDirection') != 'long':
        return
    if PreparationPolicy.model_validate(prep.config.get('policy',{})) != policy:
        runtime._intraday_research_status={'phase':'fresh_preparation_required'}
        return
    if runtime._intraday_research_started is None:
        runtime._intraday_research_started=now
    candidates=[r for r in prep.result.get('shortlist',[]) if r.get('status')=='market_blocked' and r.get('analysisId')][:5]
    # Subscription is data collection only; no option contracts or execution permissions are requested.
    for symbol in ['SPY','QQQ',*[r['symbol'] for r in candidates]]:
        if symbol not in runtime._intraday_research_watched:
            await engine.feed.watch(symbol)
            runtime._intraday_research_watched.add(symbol)
    context_id=identity(prep.id,'context')
    async with engine.sf() as session:
        context=await session.get(TechniqueRun,context_id)
    if context is None:
        async def progress(**kwargs):
            runtime._intraday_research_status={'phase':'collecting_baselines','message':kwargs.get('message')}
        reader=PreparationHistory(engine,fetch_window,progress,policy,runtime.clock)
        plans=[]
        async with httpx.AsyncClient(timeout=20,headers={'User-Agent':UA},follow_redirects=True) as client:
            for candidate in candidates:
                if runtime.stopping or not engine.settings.get(SETTING,False):
                    return
                try:
                    async with engine.sf() as session:
                        analysis=await session.get(TechniqueRun,candidate['analysisId'])
                    if analysis is None or analysis.technique!='options_cartel' or analysis.mode!='analysis' or analysis.symbol!=candidate['symbol'] or analysis.as_of!=prep.as_of:
                        raise ValueError('Owned research analysis unavailable')
                    review=automatic_review(analysis.config['inputs'],analysis.result['analysis'],policy,research_only=True)
                    if review is None:
                        raise ValueError('Research setup no longer matches saved policy')
                    if review.setup != candidate['setup']:
                        raise ValueError('Saved research candidate differs from its reviewed setup')
                    if review.entry_policy.timeframe_minutes == 5:
                        # P6: the executing 5m pilot is compared by its matched control; this panel keeps its
                        # incumbent 15-minute research basis for the same candidate (labelled on the plan).
                        review = review.model_copy(update={'entry_policy': review.entry_policy.model_copy(update={'timeframe_minutes': 15}),
                                                           'cadence_version': 'breakout_15m_v1'})
                    if review.entry_policy.timeframe_minutes != 15:
                        raise ValueError('Research v1 supports 15-minute stock confirmations; execution policy was not changed')
                    minutes=await reader.baseline(candidate['symbol'],prep.as_of,client)
                    baseline=build_volume_baseline(minutes,candidate['symbol'],review.entry_policy.timeframe_minutes,prep.as_of,require_exchange=True)
                    plan=CartelPlan(id=identity(prep.id,candidate['symbol']),symbol=candidate['symbol'],direction='long',setup=candidate['setup'],
                        created_at=prep.as_of,first_session=day,last_session=day,trigger=candidate['trigger'],invalidation=candidate['invalidation'],
                        targets=candidate['targets'],source_refs=(candidate['analysisId'],),rationale='Non-executing intraday research experiment',
                        rules=analysis.config['inputs']['rules'],entry=review.entry_policy.model_copy(update={'require_exchange_bars':True,'allow_simulated_bars':False}),
                        volume_baseline=baseline['baselines'],baseline_as_of=prep.as_of)
                    coverage=baseline_coverage(plan)
                    slots=coverage['usableEntryPeriods']
                    if not coverage['ready'] or policy.coverage_policy=='full_session' and coverage['available']!=coverage['expected'] or policy.coverage_policy=='opening_and_broad' and (not all(i in slots for i in range(60//plan.entry.timeframe_minutes)) or len(slots)<math.ceil((coverage['expected']-1)*.8)):
                        raise ValueError(f"Baseline coverage insufficient: {coverage['available']}/{coverage['expected']} periods; existing coverage policy preserved")
                    plans.append({'symbol':candidate['symbol'],'plan':plan.model_dump(mode='json'),'baseline':baseline})
                except (*DATA_ERRORS,httpx.HTTPError) as exc:
                    plans.append({'symbol':candidate['symbol'],'error':str(exc)[:250]})
        if runtime.stopping or not engine.settings.get(SETTING,False) or read_policy(engine,'practice')!=policy:
            return
        await save(engine,context_id,'watch_context',prep,runtime.clock(),{'plans':plans,'watchStartedAt':runtime.clock()})
        async with engine.sf() as session:
            context=await session.get(TechniqueRun,context_id)
    now=runtime.clock();boundary=min(closes,opens+max(0,(now-opens)//STEP)*STEP)
    if boundary < opens+STEP:
        runtime._intraday_research_status={'phase':'waiting_first_close'}
        return
    if now-boundary < 60_000:
        return  # allow the completed minute's normal persistence; never read a forming bar
    key=identity(prep.id,str(boundary))
    async with engine.sf() as session:
        if await session.get(TechniqueRun,key):
            return
        previous=await session.get(TechniqueRun,identity(prep.id,str(boundary-STEP)))
        stored=(await session.scalars(select(BarRow).where(BarRow.tf=='1m',BarRow.symbol.in_(['SPY','QQQ',*[r['symbol'] for r in candidates]]),BarRow.ts>=opens,BarRow.ts<boundary))).all()
    bars=[Bar(b.symbol,b.tf,b.ts,b.open,b.high,b.low,b.close,b.volume,source=b.source) for b in stored]
    market=market_observation(prep.result.get('market',{}),bars,boundary,now,previous.result.get('market') if previous else None)
    observations=[]
    for candidate in context.result['plans']:
        symbol=candidate['symbol']; item={'symbol':symbol,'status':'waiting_market','optionEligibility':'not_evaluated','hypotheticalOnly':True}
        if candidate.get('error'):
            item.update(status='data_unavailable',reason=candidate['error'])
        elif market['sustained']:
            stock_bars=[b for b in bars if b.symbol==symbol]
            if {b.ts for b in stock_bars} != set(range(opens,boundary,60_000)):
                item.update(status='data_unavailable',reason='Current-session context is incomplete; no crossing inferred')
                observations.append(item)
                continue
            plan=CartelPlan.model_validate(candidate['plan'])
            after=max(market['improvedSince'],context.result['watchStartedAt'],runtime._intraday_research_started)
            try:
                result=read_entry(plan,[b for b in bars if b.symbol==symbol],boundary,entry_after=after)
            except ValueError as exc:
                item.update(status='data_unavailable',reason=str(exc)[:250])
                observations.append(item)
                continue
            status=('hypothetical_stock_confirmation' if result['signal']['at']==boundary else 'previous_confirmation') if result.get('signal') else result['status']
            item.update(status=status,
                entryRead=result,entryAfter=after,sourceEvidence=evidence({str(b.ts):pack(b) for b in bars if b.symbol==symbol}), sourceBars=[pack(b) for b in bars if b.symbol==symbol])
        observations.append(item)
    # Recheck cancellation immediately before recording; no result is trading authority in any case.
    if runtime.stopping or not engine.settings.get(SETTING,False) or read_policy(engine,'practice')!=policy:
        return
    await save(engine,key,'intraday_watch',prep,now,{'market':market,'candidates':observations,'boundary':boundary,
        'note':'Research only. Two consecutive observed 15-minute closes against frozen daily EMAs; no automatic unlock, contract eligibility or P&L claim.'})
    runtime._intraday_research_status={'phase':'observing','lastObservedAt':now}
