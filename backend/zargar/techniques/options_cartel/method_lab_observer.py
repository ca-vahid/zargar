"""Bounded, restart-aware non-ordering observations for the method lab."""
from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace

import httpx

from sqlalchemy import select

from ...domain import Bar
from ...marketstructure.market_calendar import is_trading_day, next_trading_day
from ...marketstructure.sessions import ET, session_bounds
from ...models import BarRow, TechniqueArmed, TechniqueRun
from . import method_lab as lab
from .automatic_plans import PreparationPolicy
from .data_quality import pack
from .entry import read_entry
from .preparation_scope import read_policy
from .profitability_research import _study, make_plan
from .research_quotes import observe_contract, snapshot_quote
from .shadow_entries import ShadowEntrySpec, read_shadow_entry


async def capture_prices(runtime,context,symbols):
    """Timestamp actual availability, including late corrections, without overwrites."""
    now=runtime.clock();opens,closes=session_bounds(context.config['session'])
    if not opens<=now<=closes+120000: return
    end=min(closes,now//60000*60000);start=max(opens,end-120000)
    if end<=start: return
    async with runtime.engine.sf() as s:
        rows=(await s.scalars(select(BarRow).where(BarRow.tf=='1m',BarRow.provider=='alpaca',
            BarRow.symbol.in_(symbols),BarRow.ts>=start,BarRow.ts<end).order_by(BarRow.symbol,BarRow.ts))).all()
    data=[{'symbol':b.symbol,'bar':[b.ts,b.open,b.high,b.low,b.close,b.volume,b.source]} for b in rows]
    from .shadow_entries import digest
    key=lab.identity(context.id,'price_receipt',end,digest(data))
    await lab.insert_record(runtime.engine,key=key,mode='lab_prices',at=runtime.clock(),parent=context.id,
        config=context.config,result={'observedAt':runtime.clock(),'provider':'alpaca','start':start,'end':end,
            'symbols':symbols,'bars':data,'note':'Receipt time is availability to this collector, not a claim of earlier live delivery.'})


async def context_for(engine,policy,day):
    async with engine.sf() as s:
        return await s.scalar(select(TechniqueRun).where(TechniqueRun.technique=='options_cartel',
            TechniqueRun.mode=='lab_context',TechniqueRun.config['workspace'].as_string()=='practice',
            TechniqueRun.config['portfolioId'].as_string()==policy.portfolio_id,
            TechniqueRun.config['session'].as_string()==day).order_by(TechniqueRun.as_of.desc()).limit(1))


def read_models(candidate, baseline, bars, proofs, boundary, observed_at, started):
    """One exact tape shared by model variants; each result retains its own cutoff."""
    rows={}
    for variant,raw in baseline['specs'].items():
        spec=ShadowEntrySpec.model_validate(raw)
        result=read_shadow_entry(spec,bars,observed_at,entry_after=max(started,spec.frozen_at),verified_intervals=proofs)
        rows[variant]=result
    for tf in (5,15):
        if (boundary-session_bounds(candidate['session'])[0])%(tf*60000): continue
        plan_candidate={**candidate,'entryPolicy':{**candidate['entryPolicy'],'timeframe_minutes':tf}}
        plan=make_plan(plan_candidate,candidate['session'],baseline['baselines'][str(tf)])
        result=read_entry(plan,bars,observed_at,entry_after=max(started,baseline['baselineAvailableAt']),verified_intervals=proofs)
        rows[f'breakout_{tf}m_v1']={**result,'researchOnly':True,'placesOrders':False,'plan':plan.model_dump(mode='json')}
    return rows


async def collect(runtime):
    engine=runtime.engine;policy=read_policy(engine,'practice');now=runtime.clock()
    if runtime.stopping or not lab.enabled(engine,policy):
        runtime._method_lab_started=None;return
    today=dt.datetime.fromtimestamp(now/1000,ET).date();opens,closes=session_bounds(today.isoformat())
    day=today if is_trading_day(today) and now<closes+120000 else next_trading_day(today)
    context=await context_for(engine,policy,day.isoformat())
    if context is None:
        runtime._method_lab_status={'status':'awaiting_preparation'};return
    if PreparationPolicy.model_validate(context.config['policy'])!=policy:
        runtime._method_lab_status={'status':'fresh_preparation_required'};return
    opens,closes=session_bounds(day.isoformat())
    if context.as_of>=opens:
        runtime._method_lab_status={'status':'invalid_context'};return
    if now<opens:
        await lab.warm(runtime,context,policy)
        if now<opens-45*60000: return
    if not opens-45*60000<=now<=closes+120000: return
    if getattr(runtime,'_method_lab_context',None)!=context.id or getattr(runtime,'_method_lab_started',None) is None:
        runtime._method_lab_context=context.id;runtime._method_lab_started=now
    watched=getattr(runtime,'_method_lab_watched',set())
    candidates=[c for c in context.result['candidates'] if c['id'] in context.result['observedIds']]
    for symbol in sorted({'SPY','QQQ',*[c['symbol'] for c in candidates]}):
        if symbol not in watched:
            await engine.feed.watch(symbol);watched.add(symbol)
    runtime._method_lab_watched=watched
    await capture_prices(runtime,context,sorted({c['symbol'] for c in candidates}))
    now=runtime.clock();boundary=min(closes,opens+max(0,(now-opens)//300000)*300000)
    if boundary<=opens or now-boundary<15000: return
    key=lab.identity(context.id,'tick',boundary)
    async with engine.sf() as s:
        existing=await s.get(TechniqueRun,key)
        if existing: return
        baselines=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_baseline',
            TechniqueRun.parent_run_id==context.id,TechniqueRun.as_of<opens).order_by(TechniqueRun.as_of))).all()
        stored=(await s.scalars(select(BarRow).where(BarRow.tf=='1m',BarRow.provider=='alpaca',
            BarRow.symbol.in_(['SPY','QQQ',*[c['symbol'] for c in candidates]]),BarRow.ts>=opens,BarRow.ts<boundary))).all()
        arms=(await s.scalars(select(TechniqueArmed).where(TechniqueArmed.technique=='options_cartel',
            TechniqueArmed.portfolio_id==policy.portfolio_id,TechniqueArmed.plan_for==day.isoformat()))).all()
        prior=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_signal',
            TechniqueRun.parent_run_id==context.id))).all()
    baseline_map={r.result['candidateId']:r for r in baselines}
    consumed={(r.result['candidateId'],r.result['variant']) for r in prior}
    proofs={}
    for arm in arms: proofs.setdefault(arm.symbol,{}).update(arm.state.get('verifiedIntervals',{}))
    bars=[Bar(b.symbol,b.tf,b.ts,b.open,b.high,b.low,b.close,b.volume,source=b.source) for b in stored]
    from .intraday_research import market_observation
    # Current rolling 15m context is diagnostic, never a replacement for live permissions.
    market=market_observation(context.result['market'],bars,boundary,runtime.clock())
    rows=[];quote_requests=0
    for candidate in candidates:
        if runtime.stopping or not lab.enabled(engine,policy) or read_policy(engine,'practice')!=policy: return
        baseline=baseline_map.get(candidate['id'])
        row={'candidateId':candidate['id'],'symbol':candidate['symbol'],'models':{},'status':'baseline_unavailable'}
        tape=[b for b in bars if b.symbol==candidate['symbol']]
        raw_proofs=proofs.get(candidate['symbol'],{})
        if baseline and baseline.result['status'] in ('ready','partial'):
            observed_at=runtime.clock()
            models=await _study(read_models,{**candidate,'session':day.isoformat()},baseline.result,tape,
                raw_proofs,boundary,observed_at,runtime._method_lab_started)
            row.update(status='observed',models=models,baselineId=baseline.id,observedAt=observed_at)
            for variant,result in models.items():
                signal=result.get('signal')
                if (candidate['id'],variant) in consumed or not signal: continue
                # Deadline checked after all compute work; historical replays remain diagnostics.
                decision_at=runtime.clock()
                if signal['at']!=boundary or not 0<=decision_at-boundary<=120000:
                    result['captureStatus']='not_timely';continue
                signal_id=lab.identity(context.id,candidate['id'],variant,'signal')
                payload={'candidateId':candidate['id'],'symbol':candidate['symbol'],'variant':variant,
                    'signal':signal,'observedAt':decision_at,'entryAfter':runtime._method_lab_started,
                    'decisionBars':[pack(b) for b in tape],'verifiedIntervals':raw_proofs,
                    'baselineId':baseline.id,'contextId':context.id,'market':market,
                    'sourceStatus':'mirrored_unverified' if variant.startswith(('undercut','pivot')) else 'author_archive_engineering_thresholds',
                    'trial':context.result.get('trial')}
                await lab.insert_record(engine,key=signal_id,mode='lab_signal',at=decision_at,
                    parent=context.id,config=context.config,result=payload)
                consumed.add((candidate['id'],variant));result['signalRecordId']=signal_id
                if quote_requests>=2:
                    result['quoteStatus']='capacity_not_observed';continue
                quote_requests+=1
                try:
                    async with asyncio.timeout(20):
                        option=await observe_contract(engine,SimpleNamespace(id=signal_id,symbol=candidate['symbol'],direction='long'),policy,runtime.clock)
                except (ValueError,OSError,TimeoutError,httpx.HTTPError) as exc:
                    option={'status':'unavailable','observedAt':runtime.clock(),'reason':type(exc).__name__}
                option['timely']=0<=runtime.clock()-signal['at']<=120000
                await lab.insert_record(engine,key=lab.identity(signal_id,'entry_quote'),mode='lab_quote',at=runtime.clock(),
                    parent=signal_id,config=context.config,result={'purpose':'entry_selection','signalId':signal_id,'observation':option})
                result['quoteStatus']=option['status'] if option['timely'] else 'late'
        rows.append(row)
    await lab.insert_record(engine,key=key,mode='lab_tick',at=runtime.clock(),parent=context.id,
        config=context.config,result={'boundary':boundary,'rows':rows,'market':market,
            'collectorStartedAt':runtime._method_lab_started,'provider':'alpaca',
            'note':'Data was available when this snapshot was read; a repaired historical signal cannot become a prospective entry.'})
    runtime._method_lab_status={'status':'collecting','session':day.isoformat(),'boundary':boundary,'candidates':len(rows)}


async def capture_quotes(runtime):
    """Bounded observation only; no order or capital reservation side effects."""
    engine=runtime.engine;policy=read_policy(engine,'practice');now=runtime.clock()
    if runtime.stopping or not lab.enabled(engine,policy): return
    day=dt.datetime.fromtimestamp(now/1000,ET).date();opens,closes=session_bounds(day.isoformat())
    if not is_trading_day(day) or not opens<=now<=closes+120000: return
    async with engine.sf() as s:
        selections=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_quote',
            TechniqueRun.config['portfolioId'].as_string()==policy.portfolio_id,
            TechniqueRun.result['purpose'].as_string()=='entry_selection',TechniqueRun.as_of>=now-30*86400000)
            .order_by(TechniqueRun.as_of.desc()).limit(100))).all()
    tracked=getattr(runtime,'_method_lab_contracts',set())
    for selection in selections:
        if runtime.stopping or not lab.enabled(engine,policy): return
        observation=selection.result['observation'];chosen=observation.get('selected')
        if not observation.get('timely') or observation.get('status')!='observed' or not chosen: continue
        contract=chosen['symbol']
        if contract not in tracked:
            await asyncio.wait_for(engine.options.track(contract),5);tracked.add(contract)
        quote=snapshot_quote(engine,contract,runtime.clock)
        key=lab.identity(selection.parent_run_id,'mark',quote.get('sourceAt'),quote.get('evidenceSha256'))
        await lab.insert_record(engine,key=key,mode='lab_quote',at=runtime.clock(),parent=selection.parent_run_id,
            config=selection.config,result={'purpose':'mark','signalId':selection.parent_run_id,'quote':quote})
    runtime._method_lab_contracts=tracked
