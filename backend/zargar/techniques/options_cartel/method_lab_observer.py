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
    if runtime.stopping or not lab.enabled(runtime.engine,read_policy(runtime.engine,'practice')): return
    proofs={}
    for row in getattr(runtime,'rows',{}).values():
        if row.get('portfolioId')==context.config['portfolioId'] and row.get('symbol') in symbols:
            proofs.setdefault(row['symbol'],{}).update(row.get('state',{}).get('verifiedIntervals',{}))
    from .shadow_entries import digest
    key=lab.identity(context.id,'price_receipt',end,digest([data,proofs]))
    await lab.insert_record(runtime.engine,key=key,mode='lab_prices',at=runtime.clock(),parent=context.id,
        config=context.config,result={'observedAt':runtime.clock(),'provider':'alpaca','start':start,'end':end,
            'symbols':symbols,'bars':data,'verifiedIntervals':proofs,
            'note':'Receipt time is availability to this collector, not a claim of earlier live delivery.'})


async def context_for(engine,policy,day):
    async with engine.sf() as s:
        return await s.scalar(select(TechniqueRun).where(TechniqueRun.technique=='options_cartel',
            TechniqueRun.mode=='lab_context',TechniqueRun.config['workspace'].as_string()=='practice',
            TechniqueRun.config['portfolioId'].as_string()==policy.portfolio_id,
            TechniqueRun.config['session'].as_string()==day).order_by(TechniqueRun.as_of.desc()).limit(1))


def _observe(observer,*args,**kwargs):
    """Call the (possibly monkeypatched) contract observer; drop per-call hints it cannot accept."""
    import inspect
    try:
        parameters=inspect.signature(observer).parameters
    except (TypeError,ValueError):
        return observer(*args,**kwargs)
    if any(p.kind==inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return observer(*args,**kwargs)
    return observer(*args,**{k:v for k,v in kwargs.items() if k in parameters})


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
        if existing:
            await pending_quotes(runtime,context,policy)
            return
        baselines=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_baseline',
            TechniqueRun.parent_run_id==context.id,TechniqueRun.as_of<opens).order_by(TechniqueRun.as_of))).all()
        stored=(await s.scalars(select(BarRow).where(BarRow.tf=='1m',BarRow.provider=='alpaca',
            BarRow.symbol.in_(['SPY','QQQ',*[c['symbol'] for c in candidates]]),BarRow.ts>=opens,BarRow.ts<boundary))).all()
        arms=(await s.scalars(select(TechniqueArmed).where(TechniqueArmed.technique=='options_cartel',
            TechniqueArmed.portfolio_id==policy.portfolio_id,TechniqueArmed.plan_for==day.isoformat()))).all()
        prior=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_signal',
            TechniqueRun.parent_run_id==context.id))).all()
        old_ticks=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_tick',
            TechniqueRun.parent_run_id==context.id).order_by(TechniqueRun.as_of))).all()
    baseline_map={r.result['candidateId']:r for r in baselines}
    consumed={(r.result['candidateId'],r.result['variant']) for r in prior}
    terminal={}
    for tick in old_ticks:
        for item in tick.result['rows']:
            for variant,read in item.get('models',{}).items():
                if read.get('status') in ('invalidated','expired_setup'):
                    terminal.setdefault((item['candidateId'],variant),{**read,'terminalRecordId':tick.id})
    proofs={}
    for arm in arms: proofs.setdefault(arm.symbol,{}).update(arm.state.get('verifiedIntervals',{}))
    bars=[Bar(b.symbol,b.tf,b.ts,b.open,b.high,b.low,b.close,b.volume,source=b.source) for b in stored]
    from .intraday_research import market_observation
    # Current rolling 15m context is diagnostic, never a replacement for live permissions.
    market=market_observation(context.result['market'],bars,boundary,runtime.clock())
    rows=[]
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
            for variant in models:
                if (candidate['id'],variant) in terminal:
                    models[variant]=terminal[(candidate['id'],variant)]
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
                    'trial':context.result.get('trial'),
                    'entryBounds':{'trigger':signal.get('trigger',(result.get('plan') or {}).get('trigger')),
                        'stop':signal['stop'],'firstTarget':signal['targets'][0],
                        'invalidation':signal['stop'] if variant.startswith(('undercut','pivot')) else candidate['invalidation'],
                        'maxChaseR':candidate['entryPolicy']['max_chase_r'],'minTargetR':candidate['entryPolicy']['min_target_r']}}
                await lab.insert_record(engine,key=signal_id,mode='lab_signal',at=decision_at,
                    parent=context.id,config=context.config,result=payload)
                consumed.add((candidate['id'],variant));result['signalRecordId']=signal_id
                result['quoteStatus']='pending_observation'
        rows.append(row)
    await lab.insert_record(engine,key=key,mode='lab_tick',at=runtime.clock(),parent=context.id,
        config=context.config,result={'boundary':boundary,'rows':rows,'market':market,
            'collectorStartedAt':runtime._method_lab_started,'provider':'alpaca',
            'note':'Data was available when this snapshot was read; a repaired historical signal cannot become a prospective entry.'})
    await pending_quotes(runtime,context,policy)
    runtime._method_lab_status={'status':'collecting','session':day.isoformat(),'boundary':boundary,'candidates':len(rows)}


async def pending_quotes(runtime,context,policy):
    """Durable bounded attempts; capacity/HTTP failures do not disappear on restart."""
    engine=runtime.engine
    if runtime.stopping or not lab.enabled(engine,policy): return
    async with engine.sf() as s:
        signals=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_signal',
            TechniqueRun.parent_run_id==context.id).order_by(TechniqueRun.as_of))).all()
        observations=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_quote',
            TechniqueRun.parent_run_id.in_([r.id for r in signals])))).all()
    finished={r.parent_run_id for r in observations if r.result.get('purpose')=='entry_selection'}
    attempts={r.id:[q for q in observations if q.parent_run_id==r.id and q.result.get('purpose')=='entry_attempt'] for r in signals}
    priority={'breakout_5m_v1':0,'undercut_reclaim_5m_v1':1,'pivot_30m_5m_v1':2,'breakout_15m_v1':3}
    due=sorted((r for r in signals if r.id not in finished),key=lambda r:(len(attempts[r.id]),r.as_of,priority.get(r.result['variant'],9),r.id))
    requests=0
    for row in due:
        if runtime.stopping or not lab.enabled(engine,policy) or read_policy(engine,'practice')!=policy: return
        now=runtime.clock();signal=row.result['signal'];prior=attempts[row.id]
        if now-signal['at']>120000 or len(prior)>=3:
            observation={'status':'deadline_missed' if now-signal['at']>120000 else 'attempt_limit',
                         'observedAt':now,'timely':False,'reason':'No timely eligible quote was captured; no fill or zero-return outcome inferred.'}
        else:
            if requests>=2 or prior and now-max(p.as_of for p in prior)<15000: continue
            requests+=1;attempt=len(prior)+1
            key=lab.identity(row.id,'attempt',attempt)
            await lab.insert_record(engine,key=key,mode='lab_quote',at=now,parent=row.id,config=context.config,
                result={'purpose':'entry_attempt','signalId':row.id,'attempt':attempt,'status':'started'})
            try:
                async with asyncio.timeout(20):
                    # The armed Practice contract for the same symbol (if any) gets first refresh
                    # consideration; the signal deadline bounds the search.
                    reviewed=next((r['config']['execution'].get('contract_symbol') for r in getattr(runtime,'rows',{}).values()
                        if r.get('symbol')==row.result['symbol'] and (r.get('config') or {}).get('execution')),None)
                    observation=await _observe(observe_contract,engine,SimpleNamespace(id=row.id,symbol=row.result['symbol'],direction='long'),policy,runtime.clock,
                        preferred=reviewed,deadline_ms=signal['at']+120000)
            except (ValueError,OSError,TimeoutError,httpx.HTTPError) as exc:
                observation={'status':'unavailable','observedAt':runtime.clock(),'reason':type(exc).__name__}
            if observation.get('status')=='observed' and (not observation.get('selected')
                    or (observation.get('quote') or {}).get('status')!='observed'
                    or type((observation.get('funding') or {}).get('quantity')) is not int
                    or observation['funding']['quantity']<1):
                observation={**observation,'status':'incomplete_observation','reason':'Selected contract, fresh quote and funded quantity are required.'}
            if observation.get('funding'):
                from .lab_market_quotes import underlying_snapshot,entry_geometry,share_observation
                underlying=underlying_snapshot(engine,row.result['symbol'],runtime.clock)
                reasons=entry_geometry(underlying,row.result['entryBounds'])
                observation={**observation,'underlyingEvidence':underlying,'underlyingFailures':reasons}
                if reasons and observation.get('status')=='observed': observation['status']='underlying_entry_refused'
                shares=share_observation(underlying,observation['funding'],row.result['entryBounds'])
                shares['timely']=0<=runtime.clock()-signal['at']<=120000
                if shares['status']=='observed' and shares['timely'] and not runtime.stopping and lab.enabled(engine,policy):
                    await lab.insert_record(engine,key=lab.identity(row.id,'share_entry_quote'),mode='lab_quote',at=runtime.clock(),
                        parent=row.id,config=context.config,result={'purpose':'share_entry_selection','signalId':row.id,'observation':shares})
            observation['timely']=0<=runtime.clock()-signal['at']<=120000
            if runtime.stopping or not lab.enabled(engine,policy): return
            await lab.insert_record(engine,key=lab.identity(key,'result'),mode='lab_quote',at=runtime.clock(),
                parent=row.id,config=context.config,result={'purpose':'entry_attempt_result','signalId':row.id,'attempt':attempt,'observation':observation})
            if observation.get('status')!='observed' and observation['timely']: continue
        await lab.insert_record(engine,key=lab.identity(row.id,'entry_quote'),mode='lab_quote',at=runtime.clock(),
            parent=row.id,config=context.config,result={'purpose':'entry_selection','signalId':row.id,'observation':observation})


async def capture_quotes(runtime):
    """Bounded observation only; no order or capital reservation side effects."""
    engine=runtime.engine;policy=read_policy(engine,'practice');now=runtime.clock()
    if runtime.stopping or not lab.enabled(engine,policy): return
    day=dt.datetime.fromtimestamp(now/1000,ET).date();opens,closes=session_bounds(day.isoformat())
    if not is_trading_day(day) or not opens<=now<=closes+120000: return
    async with engine.sf() as s:
        selections=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_quote',
            TechniqueRun.config['portfolioId'].as_string()==policy.portfolio_id,
            TechniqueRun.result['purpose'].as_string().in_(('entry_selection','share_entry_selection')),TechniqueRun.as_of>=now-90*86400000)
            .order_by(TechniqueRun.as_of.desc()).limit(100))).all()
    tracked=getattr(runtime,'_method_lab_contracts',set());carry=set();carry_config=None;carry_parent=None
    for selection in selections:
        if runtime.stopping or not lab.enabled(engine,policy): return
        observation=selection.result['observation'];chosen=observation.get('selected')
        if not observation.get('timely') or observation.get('status')!='observed' or not chosen: continue
        contract=chosen['symbol']
        if selection.result['purpose']=='share_entry_selection':
            from .lab_market_quotes import underlying_snapshot
            from .receipt_economics import usable_quote
            snapshot=underlying_snapshot(engine,contract,runtime.clock);raw=snapshot.get('raw') or {}
            quote={'contract':contract,'source':'alpaca_sip','observedAt':runtime.clock(),'sourceAt':raw.get('quote_ts'),
                'bid':raw.get('bid'),'ask':raw.get('ask'),'bidSize':raw.get('bid_size'),'askSize':raw.get('ask_size'),'status':'observed'}
            if not usable_quote(quote,runtime.clock(),instrument='shares'): quote['status']='unavailable'
            carry.add(contract);carry_config=selection.config;carry_parent=selection.parent_run_id
            from .shadow_entries import digest
            await lab.insert_record(engine,key=lab.identity(selection.parent_run_id,'share_mark',digest(quote)),mode='lab_quote',at=runtime.clock(),
                parent=selection.parent_run_id,config=selection.config,result={'purpose':'share_mark','signalId':selection.parent_run_id,'quote':quote})
            continue
        from ...options.occ import parse
        option=parse(contract)
        if option is None or option.expiry<day: continue
        carry.add(option.underlying);carry_config=selection.config;carry_parent=selection.parent_run_id
        if contract not in tracked:
            await asyncio.wait_for(engine.options.track(contract),5);tracked.add(contract)
        if runtime.stopping or not lab.enabled(engine,policy): return
        quote=snapshot_quote(engine,contract,runtime.clock)
        key=lab.identity(selection.parent_run_id,'mark',quote.get('sourceAt'),quote.get('evidenceSha256'))
        await lab.insert_record(engine,key=key,mode='lab_quote',at=runtime.clock(),parent=selection.parent_run_id,
            config=selection.config,result={'purpose':'mark','signalId':selection.parent_run_id,'quote':quote})
    runtime._method_lab_contracts=tracked
    if carry and now-getattr(runtime,'_method_lab_carry_price_at',0)>=30000:
        runtime._method_lab_carry_price_at=now
        watched=getattr(runtime,'_method_lab_watched',set())
        for symbol in sorted(carry-watched):
            await engine.feed.watch(symbol);watched.add(symbol)
        runtime._method_lab_watched=watched
        await capture_prices(runtime,SimpleNamespace(id=carry_parent,config={**carry_config,'session':day.isoformat()}),sorted(carry))
