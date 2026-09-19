"""Immutable storage and pre-open preparation for the non-ordering method lab."""
from __future__ import annotations

import asyncio
import datetime as dt

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ...marketstructure.history import UA, fetch_window
from ...marketstructure.sessions import session_bounds
from ...marketstructure.market_calendar import previous_trading_day
from ...models import TechniqueRun
from .data import DailyBar, completed_daily
from .lab_features import selection_features, compression_order
from .preparation_io import PreparationHistory
from .prepare import build_volume_baseline
from .setups import _targets
from .shadow_entries import ShadowEntrySpec, digest

SETTING='techniques.options_cartel.method_lab'
VERSION='cartel-method-lab-v1'
RECORD_MODES=('lab_context','lab_baseline','lab_tick','lab_signal','lab_quote','lab_trial','lab_review','lab_prices')
VARIANTS=('breakout_5m_v1','breakout_15m_v1','undercut_reclaim_5m_v1','pivot_30m_5m_v1')


def enabled(engine, policy):
    if engine.settings.get(SETTING,False) is not True or policy.workspace!='practice': return False
    book=engine.positions.portfolio(policy.portfolio_id) or {}
    return book.get('kind')=='sim' and not book.get('archived')


def identity(*parts): return digest([VERSION,*parts])[:32]


async def insert_record(engine, *, key, mode, at, config, result, parent):
    """Append-only research records; no updates and never mode=plan."""
    if mode not in RECORD_MODES:
        raise ValueError('unknown non-ordering lab record type')
    if config.get('workspace')!='practice' or not config.get('portfolioId'):
        raise ValueError('lab records require an explicit Practice book')
    async with engine.sf() as s,s.begin():
        await s.execute(insert(TechniqueRun).values(id=key,technique='options_cartel',symbol='MULTI',mode=mode,
            status='done',verdict='research_only',as_of=at,parent_run_id=parent,
            config={**config,'labVersion':VERSION},result={**result,'researchOnly':True,
                'placesOrders':False,'automaticPermissionChanged':False}).on_conflict_do_nothing(index_elements=['id']))


def freeze_candidates(candidates, *, at, day, cap=50):
    """Existing analyzed long pool, including weak-market research; never today's winners."""
    if at>=session_bounds(day)[0]: raise ValueError('lab universe must be frozen before the open')
    if type(cap) is not int or not 1<=cap<=100: raise ValueError('invalid lab candidate cap')
    found=[];excluded=[]
    for candidate in candidates:
        if candidate['direction']!='long': continue
        history=completed_daily([DailyBar.model_validate(b) for b in candidate['daily']],candidate['sourceAt'])
        expected=previous_trading_day(dt.date.fromisoformat(day))
        if not history or candidate['sourceAt']>at or history[-1].session!=expected or history[-1].symbol!=candidate['symbol']:
            excluded.append({'symbol':candidate['symbol'],'reason':'missing_or_future_daily_context'});continue
        feature=selection_features(history,candidate['sourceAt'])
        supports={'undercut_reclaim_5m_v1':history[-1].low,
                  'pivot_30m_5m_v1':feature['emas'].get('8')}
        definitions={}
        for variant,support in supports.items():
            if support is None: continue
            targets=_targets(history,support,'long',.5,existing=[history[-1].high])
            if not targets: continue
            definitions[variant]={'support':support,'targets':targets,
                'support_kind':'prior_day_low' if variant.startswith('undercut') else 'ema8'}
        row={k:candidate[k] for k in ('analysisId','symbol','direction','setup','trigger','invalidation',
                                      'targets','ranking','leaderEvidence','rules','entryPolicy','exitCampaign','sourceAt')}
        row.update(id=identity(day,candidate['analysisId']),labFeatures=feature,definitions=definitions,
            previousClose=history[-1].close,priorSession=history[-1].session.isoformat(),
            dailyInputHash=digest([b.model_dump(mode='json') for b in history]))
        found.append(row)
    if len({c['id'] for c in found})!=len(found): raise ValueError('duplicate lab candidate identity')
    # Stable ranked denominator and deterministic capacity sampling. Every omitted
    # candidate remains in the immutable context with a named exclusion reason.
    from .quality import quality_key
    found.sort(key=lambda c:quality_key(c['ranking'],c['symbol']))
    ids=[c['id'] for c in found]
    near=sorted(found,key=lambda c:((c['trigger']/c['previousClose']-1)<0,
        (c['trigger']/c['previousClose']-1) if c['trigger']>=c['previousClose'] else float('inf'),c['symbol']))
    liquid=sorted(found,key=lambda c:(-(c['leaderEvidence'].get('dailyDollarVolume') or 0),c['symbol']))
    orders=[ids,[c['id'] for c in near],[c['id'] for c in liquid],compression_order(found)]
    selected=[]
    for i in range(max(map(len,orders),default=0)):
        for order in orders:
            if i<len(order) and order[i] not in selected and len(selected)<cap: selected.append(order[i])
    return {'candidates':found,'observedIds':selected,'omittedIds':[cid for cid in ids if cid not in selected],
            'excluded':excluded,'rankings':{'quality':orders[0],'nearest':orders[1],'liquidity':orders[2],'compression':orders[3]},
            'populationHash':digest(found),'variants':list(VARIANTS)}


async def freeze(engine, prep, policy, candidates, *, clock):
    if not enabled(engine,policy): return {'status':'disabled'}
    day=prep.config['session'];at=clock();key=identity(prep.id,'context')
    async with engine.sf() as s:
        existing=await s.get(TechniqueRun,key)
    if existing:
        return {'status':'frozen','contextId':key,'candidates':len(existing.result['candidates'])}
    if at>=session_bounds(day)[0]: return {'status':'preopen_required'}
    from .profitability_research import _study
    result=await _study(freeze_candidates,candidates,at=at,day=day)
    if not enabled(engine,policy) or clock()>=session_bounds(day)[0]: return {'status':'preopen_required'}
    trial=await begin_trial(engine,policy,day,clock=clock)
    if not enabled(engine,policy) or clock()>=session_bounds(day)[0]: return {'status':'preopen_required'}
    at=clock()  # availability of the complete bundle, including the trial contract
    await insert_record(engine,key=key,mode='lab_context',at=at,parent=prep.id,
        config={'workspace':'practice','portfolioId':policy.portfolio_id,'session':day,'policy':policy.model_dump(mode='json')},
        result={**result,'frozenAt':at,'sourceStatus':'mirrored_unverified','trial':trial,
                'market':prep.result.get('market',{}),'protocol':'All new entries are closed-bar engineering interpretations; never order authority.'})
    return {'status':'frozen','contextId':key,'candidates':len(result['candidates'])}


async def begin_trial(engine,policy,day,*,clock):
    from .lab_protocol import TrialProtocol
    signature=digest(policy.model_dump(mode='json'))
    async with engine.sf() as s:
        existing=await s.scalar(select(TechniqueRun).where(TechniqueRun.mode=='lab_trial',
            TechniqueRun.technique=='options_cartel',TechniqueRun.config['portfolioId'].as_string()==policy.portfolio_id,
            TechniqueRun.config['policyHash'].as_string()==signature).order_by(TechniqueRun.as_of.desc()).limit(1))
    if existing:
        return {'id':existing.id,'protocol':existing.result['protocol'],'hash':existing.result['protocolHash']}
    book=engine.positions.portfolio(policy.portfolio_id) or {}
    if book.get('baseCurrency','USD')!='USD':
        return {'status':'unavailable','reason':'Method-lab v1 requires USD economics; no FX assumptions invented'}
    equity=await engine.positions.equity(policy.portfolio_id)
    at=clock()
    if at>=session_bounds(day)[0] or not enabled(engine,policy): return {'status':'preopen_required'}
    protocol=TrialProtocol(portfolio_id=policy.portfolio_id,policy_hash=signature,frozen_at=at,
        first_session=day,initial_capital=equity,cash_cap=min(equity,policy.budget),
        full_debit_risk_pct=policy.risk_pct,
        option_fee_per_contract=engine.settings.get('options.fee_per_contract',.99)+engine.settings.get('sim.reg_fee_per_contract',.05),
        share_fee_per_order=engine.settings.get('sim.stock_commission',0.))
    key=identity('trial',policy.portfolio_id,signature)
    await insert_record(engine,key=key,mode='lab_trial',at=at,parent=None,
        config={'workspace':'practice','portfolioId':policy.portfolio_id,'session':day,'policyHash':signature},
        result={'protocol':protocol.model_dump(mode='json'),'protocolHash':protocol.fingerprint,
                'status':'collecting_shadow_only','activationAllowed':False})
    async with engine.sf() as s:
        stored=await s.get(TechniqueRun,key)
    return {'id':key,'protocol':stored.result['protocol'],'hash':stored.result['protocolHash']}


def build_specs(candidate, day, baselines, frozen_at):
    specs={}
    for variant,definition in candidate['definitions'].items():
        specs[variant]=ShadowEntrySpec(id=f"{candidate['id']}:{variant}",symbol=candidate['symbol'],session=day,
            model='undercut_reclaim' if variant.startswith('undercut') else 'pivot_30m',
            **definition,source_at=candidate['sourceAt'],frozen_at=frozen_at,baseline_at=frozen_at,
            volume_baseline=baselines['5']['baselines'],
            volume_multiple=candidate['entryPolicy']['volume_multiple'],
            min_close_location=candidate['entryPolicy']['min_close_location'],
            max_chase_r=candidate['entryPolicy']['max_chase_r'],
            min_target_r=candidate['entryPolicy']['min_target_r']).model_dump(mode='json')
    return specs


async def warm(runtime, context, policy, *, fetch=fetch_window):
    """Two candidates/pass before open; attempts are durable and do not alter context."""
    if not enabled(runtime.engine,policy) or runtime.stopping: return
    opens,_=session_bounds(context.config['session'])
    if runtime.clock()>=opens: return
    async with runtime.engine.sf() as s:
        records=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_baseline',
            TechniqueRun.parent_run_id==context.id).order_by(TechniqueRun.as_of))).all()
    latest={r.result['candidateId']:r for r in records}
    attempts={c['id']:sum(r.result['candidateId']==c['id'] for r in records) for c in context.result['candidates']}
    due=[c for c in context.result['candidates'] if c['id'] in context.result['observedIds'] and
         attempts[c['id']]<3 and
         (c['id'] not in latest or latest[c['id']].result['status']!='ready' and runtime.clock()-latest[c['id']].as_of>=300000)]
    due.sort(key=lambda c:(sum(r.result['candidateId']==c['id'] for r in records),c['id']))
    async def report(**kwargs): pass
    reader=PreparationHistory(runtime.engine,fetch,report,policy,runtime.clock)
    async with httpx.AsyncClient(timeout=18,headers={'User-Agent':UA}) as client:
        for candidate in due[:2]:
            if runtime.stopping or not enabled(runtime.engine,policy): return
            try:
                if fetch is fetch_window and getattr(getattr(runtime.engine,'config',None),'quote_source',None)=='sim':
                    raise ValueError('Native history required; synthetic feed cannot supply research evidence')
                bars=await asyncio.wait_for(reader.baseline(candidate['symbol'],candidate['sourceAt'],client),20)
                from .profitability_research import _study
                matrices={str(tf):await _study(build_volume_baseline,bars,candidate['symbol'],tf,candidate['sourceAt'],require_exchange=True)
                          for tf in (5,15)}
                at=runtime.clock()
                if at>=opens: return
                specs=build_specs(candidate,context.config['session'],matrices,at)
                counts={tf:len(m['baselines']) for tf,m in matrices.items()}
                readiness='ready' if counts=={'5':78,'15':26} else 'partial' if any(counts.values()) else 'unavailable'
                result={'candidateId':candidate['id'],'status':readiness,'baselines':matrices,'specs':specs,
                    'coverage':counts,'attempt':attempts[candidate['id']]+1,
                    'baselineSourceCutoff':candidate['sourceAt'],'baselineAvailableAt':at,
                    'note':'Only covered slots can confirm; missing slots remain explicit refusals.'}
            except (ValueError,OSError,httpx.HTTPError,TimeoutError) as exc:
                at=runtime.clock();result={'candidateId':candidate['id'],'status':'unavailable',
                    'reason':str(exc)[:200] if isinstance(exc,ValueError) else f'History unavailable ({type(exc).__name__})',
                    'attempt':attempts[candidate['id']]+1}
            if at>=opens or runtime.stopping or not enabled(runtime.engine,policy): return
            await insert_record(runtime.engine,key=identity(context.id,candidate['id'],at),mode='lab_baseline',at=at,
                parent=context.id,config=context.config,result=result)


async def status(engine,policy,day):
    from .method_lab_observer import context_for
    out={'version':VERSION,'workspace':'practice','session':day,'portfolioId':policy.portfolio_id,
        'enabled':enabled(engine,policy),'status':'awaiting_preparation','rows':[],
        'researchOnly':True,'placesOrders':False,'activationAllowed':False,'trial':None,
        'sourceStatus':'mirrored_unverified','denominator':{},'signalCount':0,'pricedSignals':0,
        'freezeError':getattr(engine,'_cartel_method_lab_freeze_error',None)}
    context=await context_for(engine,policy,day)
    if context is None: return out
    async with engine.sf() as s:
        ticks=(await s.scalars(select(TechniqueRun).where(TechniqueRun.parent_run_id==context.id,
            TechniqueRun.mode=='lab_tick').order_by(TechniqueRun.as_of.desc()).limit(3))).all()
        baselines=(await s.scalars(select(TechniqueRun).where(TechniqueRun.parent_run_id==context.id,
            TechniqueRun.mode=='lab_baseline').order_by(TechniqueRun.as_of))).all()
        signals=(await s.scalars(select(TechniqueRun).where(TechniqueRun.parent_run_id==context.id,
            TechniqueRun.mode=='lab_signal').order_by(TechniqueRun.as_of))).all()
        quotes=(await s.scalars(select(TechniqueRun).where(TechniqueRun.parent_run_id.in_([r.id for r in signals]),
            TechniqueRun.mode=='lab_quote',TechniqueRun.result['purpose'].as_string()=='entry_selection'))).all()
    latest={r.result['candidateId']:r for r in baselines};reads={}
    for tick in reversed(ticks):
        for row in tick.result['rows']:
            earlier=reads.get(row['candidateId'],{});models={**earlier.get('models',{}),**row.get('models',{})}
            reads[row['candidateId']]={**row,'models':models}
    source=context.result
    out.update(status='collecting' if ticks else 'prepared',contextId=context.id,frozenAt=source['frozenAt'],
        lastObservedAt=ticks[0].as_of if ticks else None,trial=source.get('trial'),rankings=source['rankings'],
        denominator={'eligible':len(source['candidates']),'observedLimit':len(source['observedIds']),
                     'omitted':len(source['omittedIds']),'excluded':len(source['excluded'])},
        signalCount=len(signals),pricedSignals=sum(q.result['observation'].get('status')=='observed'
            and q.result['observation'].get('timely') is True for q in quotes),
        signals=[{'id':r.id,**{k:r.result.get(k) for k in ('symbol','variant','signal','observedAt','market')}} for r in signals])
    for candidate in source['candidates']:
        baseline=latest.get(candidate['id'])
        out['rows'].append({**{k:candidate[k] for k in ('id','symbol','labFeatures','definitions','ranking')},
            'observed':candidate['id'] in source['observedIds'],
            'baselineStatus':baseline.result['status'] if baseline else 'pending',
            'baselineReason':baseline.result.get('reason') if baseline else None,
            'models':reads.get(candidate['id'],{}).get('models',{})})
    return out
