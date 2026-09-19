"""Read-only historical method-lab reconstruction; never prospective evidence.

Uses the latest completed pre-open preparation, including cited reused analyses.
Daily candidate inputs retain their original availability cutoff. Minute caches
are revised retrospective data: no historical delivery or fill claim is made.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import datetime as dt
import json
import os
from pathlib import Path

import httpx

from ..domain import Bar
from ..marketstructure.sessions import session_bounds
from ..techniques.options_cartel.automatic_plans import PreparationPolicy
from ..techniques.options_cartel.data import DailyBar
from ..techniques.options_cartel.entry import read_entry
from ..techniques.options_cartel.exits import ExitCampaign
from ..techniques.options_cartel.lab_economics import compare_vehicles
from ..techniques.options_cartel.method_lab import freeze_candidates, build_specs
from ..techniques.options_cartel.prepare import build_volume_baseline
from ..techniques.options_cartel.profitability_research import candidate_from_analysis, make_plan
from ..techniques.options_cartel.shadow_entries import ShadowEntrySpec, read_shadow_entry, digest
from .cartel_volume_audit import pages


async def native_history(client,symbol,start,end):
    from ..brokers.alpaca import parse_rfc3339_ms
    from ..marketstructure.sessions import ET
    from ..marketstructure.market_calendar import is_trading_day
    if not symbol.isalnum(): raise ValueError('Unsupported native stock symbol')
    iso=lambda ms:dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).isoformat()
    params={'start':iso(start),'end':iso(end),'feed':'sip','timeframe':'1Min',
            'adjustment':'raw','limit':10000,'sort':'asc'}
    rows,hashes,complete=await pages(client,f'https://data.alpaca.markets/v2/stocks/{symbol}/bars',params,'bars',8)
    manifest={'symbol':symbol,'request':params,'pageHashes':hashes,'complete':complete,
              'observedAt':dt.datetime.now(dt.timezone.utc).isoformat()}
    if not complete: return [],manifest
    output=[]
    for row in rows:
        ts=parse_rfc3339_ms(row['t']);day=dt.datetime.fromtimestamp(ts/1000,ET).date()
        if not start<=ts<end or not is_trading_day(day): continue
        opened,closed=session_bounds(day.isoformat())
        if opened<=ts<closed:
            output.append([ts,row['o'],row['h'],row['l'],row['c'],row['v'],'exchange'])
    return tape(symbol,output),manifest


def load(x):
    return json.loads(x) if isinstance(x, str) else x


def legacy_analysis(result):
    # Older saved analyses predate the separate research flag. Preserve their
    # stricter original context gate; never replace an explicit research refusal.
    result=load(json.dumps(result))
    for item in result.get('analysis',{}).get('candidates',[]):
        if 'researchContextPassed' not in item:
            item['researchContextPassed']=item.get('contextPassed',False)
    return result


def choose_preparations(records):
    selected={}
    for raw in records:
        if raw.get('status')!='done': continue
        cfg,res=load(raw['config']),load(raw['result']);day=cfg.get('session')
        if not day: continue
        opened,_=session_bounds(day)
        finished=res.get('finishedAt')
        if not isinstance(finished,(int,float)) or finished>=opened or not res.get('evaluated'): continue
        if int(raw['created_at'].timestamp()*1000)>=opened: continue
        if day not in selected or finished>load(selected[day]['result'])['finishedAt']:
            selected[day]=raw
    return selected


def tape(symbol, rows):
    """One canonical input per minute; conflicting duplicates are not smoothed."""
    found={}
    for r in rows:
        b=Bar(symbol,'1m',*r[:6],source=r[6],provider='alpaca')
        if b.ts in found and found[b.ts]!=b: raise ValueError('Conflicting minute inputs')
        found[b.ts]=b
    return [found[t] for t in sorted(found)]


def evaluate(candidate, original, day, history, minutes, frozen_at):
    opened,closed=session_bounds(day)
    matrices={str(tf):build_volume_baseline(history,candidate['symbol'],tf,candidate['sourceAt'],require_exchange=True)
              for tf in (5,15)}
    specs=build_specs(candidate,day,matrices,frozen_at)
    # The historical sensitivity includes both confirmation frames for each model.
    for key,raw in list(specs.items()):
        key15=key.replace('_5m_','_15m_')
        specs[key15]={**raw,'id':raw['id']+':15m','confirmation_minutes':15,
                      'volume_baseline':matrices['15']['baselines']}
    output=[]
    for variant in ('breakout_5m_v1','breakout_15m_v1',*specs):
        spec=None;plan=None
        if variant in specs:
            spec=ShadowEntrySpec.model_validate(specs[variant])
            read=read_shadow_entry(spec,minutes,closed-1,entry_after=opened)
        else:
            tf=5 if variant=='breakout_5m_v1' else 15
            pc={**candidate,'entryPolicy':{**candidate['entryPolicy'],'timeframe_minutes':tf}}
            plan=make_plan(pc,day,matrices[str(tf)])
            read=read_entry(plan,minutes,closed-1,entry_after=opened)
        signal=read.get('signal')
        row={'variant':variant,'status':read['status'],'signal':signal,
             'traceCounts':dict(Counter(t.get('status',t.get('decision','unknown')) for t in read['trace'])),
             'blockers':dict(Counter(b for t in read['trace'] for b in t.get('blockers',[]))),
             'optionsNetPnl':None,'optionReason':'No matching historical entry/exit quote receipt sequence supplied'}
        if signal:
            campaign=ExitCampaign.model_validate(candidate['exitCampaign'])
            if spec:
                campaign=ExitCampaign.for_profile(campaign.profile,list(spec.targets),
                    allocation_policy=campaign.allocation_policy,
                    september_fractions=[r.fraction for r in campaign.rungs] if campaign.profile=='september_2026' else None)
            models=compare_vehicles(spec,signal,minutes,[DailyBar.model_validate(b) for b in original['daily']],campaign,
                as_of_ms=closed,observed_at=signal['at'],signal_after=opened,
                funding={'cashCapUsd':500,'asOfMs':signal['at'],'usdToAccountFx':1,'stockFeePerOrder':0},
                control_plan=plan.model_dump(mode='json') if plan else None)
            row['shareScenario']=models['shares'];row['vehicleGaps']=models['gaps']
        output.append(row)
    return {'symbol':candidate['symbol'],'candidateId':candidate['id'],
        'minuteCount':len(minutes),'expectedMinutes':(closed-opened)//60000,
        'baselineSlots':{tf:len(m['baselines']) for tf,m in matrices.items()},
        'baselineSessions':{tf:m['sourceSessions'] for tf,m in matrices.items()},
        'inputHash':digest({'candidate':candidate,'minutes':[b.to_row() for b in minutes],
                            'baselines':matrices}), 'models':output}


async def run(args):
    import asyncpg
    conn=await asyncpg.connect(os.environ['CARTEL_AUDIT_DATABASE_URL'],
                              server_settings={'default_transaction_read_only':'on'})
    sessions=[];native={};manifests=[];client=None
    if args.env_file:
        from ..config import AppConfig
        cfg=AppConfig(_env_file=args.env_file)
        if not cfg.alpaca_key_id or not cfg.alpaca_secret: raise ValueError('Native data credentials unavailable')
        client=httpx.AsyncClient(headers={'APCA-API-KEY-ID':cfg.alpaca_key_id,
            'APCA-API-SECRET-KEY':cfg.alpaca_secret},timeout=30)
    try:
        async with conn.transaction(isolation='repeatable_read',readonly=True):
            preps=await conn.fetch("select id,status,created_at,config,result from technique_runs where technique='options_cartel' "
                "and mode='preparation' and config->>'workspace'='practice' and config->>'portfolioId'=$1 "
                "and config->>'session'>=$2 and config->>'session'<=$3 order by created_at,id",args.portfolio,args.start,args.end)
            chosen=choose_preparations(preps)
            for day,prep in sorted(chosen.items()):
                cfg,res=load(prep['config']),load(prep['result']);opened,closed=session_bounds(day)
                policy=PreparationPolicy.model_validate(cfg['policy'])
                cited=[r['analysisId'] for r in res.get('rows',[]) if r.get('analysisId')]
                saved=await conn.fetch("select id,symbol,as_of,created_at, "
                    "case when exists(select 1 from jsonb_array_elements(coalesce(result->'analysis'->'candidates','[]'::jsonb)) x "
                    "where coalesce(x->>'researchContextPassed',x->>'contextPassed')='true') then config else '{}'::jsonb end config, "
                    "result from technique_runs "
                    "where technique='options_cartel' and mode='analysis' and (parent_run_id=$1 or id=any($2::text[])) "
                    "and created_at<to_timestamp($3::double precision/1000) order by created_at,id",prep['id'],cited,opened)
                by_symbol={}
                for r in saved:
                    old=by_symbol.get(r['symbol'])
                    if old is None or r['id'] in cited: by_symbol[r['symbol']]=r
                candidates=[];errors=[]
                for r in by_symbol.values():
                    body=load(r['config'])
                    # Original direction retained; short sessions are not converted into long hindsight pools.
                    if body.get('inputs',{}).get('direction')!='long': continue
                    try:
                        c=candidate_from_analysis({'runId':r['id'],'symbol':r['symbol'],'config':body,'result':legacy_analysis(load(r['result']))},policy,'primary')
                        if c: candidates.append(c)
                    except (ValueError,KeyError,TypeError) as exc: errors.append({'symbol':r['symbol'],'reason':str(exc)[:180]})
                frozen=freeze_candidates(candidates,at=int(res['finishedAt']),day=day,cap=100)
                originals={c['analysisId']:c for c in candidates};rows=[]
                for c in frozen['candidates']:
                    cached=await conn.fetchrow("select observed_at,payload from cartel_history_cache where symbol=$1 "
                        "and timeframe='1m' order by observed_at desc,id limit 1",c['symbol'])
                    payload=load(cached['payload']) if cached else {}
                    historical=tape(c['symbol'],payload.get('bars',[])) if payload.get('provenance',{}).get('responseProvider')=='alpaca' else []
                    native_complete=False
                    if client:
                        if c['symbol'] not in native:
                            try:
                                start=int(dt.datetime.combine(dt.date.fromisoformat(args.start)-dt.timedelta(days=45),
                                    dt.time(),dt.timezone.utc).timestamp()*1000)
                                native[c['symbol']]=await native_history(client,c['symbol'],start,session_bounds(args.end)[1])
                            except (httpx.HTTPError,ValueError) as exc:
                                native[c['symbol']]=([] ,{'symbol':c['symbol'],'complete':False,'error':type(exc).__name__})
                            manifests.append(native[c['symbol']][1])
                        downloaded,manifest=native[c['symbol']];native_complete=manifest['complete']
                        if native_complete: historical=downloaded
                    raw=await conn.fetch("select ts,open,high,low,close,volume,source from bars where symbol=$1 "
                        "and tf='1m' and provider='alpaca' and source='exchange' and ts>=$2 and ts<$3 order by ts",c['symbol'],opened,closed)
                    # Retrospective stored bars take priority over the replaceable cache;
                    # count revisions explicitly rather than implying first-arrival data.
                    from_cache={b.ts:b for b in historical if opened<=b.ts<closed}
                    stored=[] if native_complete else tape(c['symbol'],[list(r.values()) for r in raw])
                    revisions=sum(b.ts in from_cache and from_cache[b.ts]!=b for b in stored)
                    from_cache.update({b.ts:b for b in stored})
                    minutes=[from_cache[t] for t in sorted(from_cache)]
                    try:
                        result=evaluate(c,originals[c['analysisId']],day,historical,minutes,int(res['finishedAt']))
                        result['cacheObservedAt']=cached['observed_at'] if cached else None
                        result['minuteSource']='native_retrieved_now' if native_complete else 'retained_cache_and_bars'
                        result['storedVsCacheRevisions']=revisions;rows.append(result)
                    except (ValueError,KeyError,TypeError) as exc: errors.append({'symbol':c['symbol'],'reason':str(exc)[:180]})
                summary={'session':day,'preparationId':prep['id'],'market':res.get('market'),
                    'frozenAt':res['finishedAt'],'analysisPopulation':len(by_symbol),'prefiltered':res.get('prefiltered'),
                    'longCandidates':len(candidates),'excluded':frozen['excluded'],'rankings':frozen['rankings'],
                    'rows':rows,'errors':errors}
                sessions.append(summary)
                print(json.dumps({'session':day,'population':len(by_symbol),'longCandidates':len(candidates),'evaluated':len(rows),'errors':len(errors)}),flush=True)
    finally:
        await conn.close()
        if client: await client.aclose()
    result={'version':'cartel-historical-lab-v1','generatedAt':dt.datetime.now(dt.timezone.utc).isoformat(),
        'start':args.start,'end':args.end,'portfolio':args.portfolio,'sessions':sessions,'placesOrders':False,
        'nativeRequests':manifests,
        'assumptions':{'cashCapUsd':500,'shareSlippageBps':2,'shareFeePerOrder':0,'horizon':'entry session only'},
        'limitations':['Retrospective revised minute data, not historical receipt-time execution.',
            'No synthetic bars or assumed zero-volume absent minutes; no retrospective certificates.',
            'Only saved original long analyses; short sessions are reported with zero long population.',
            'Prefiltered and missing analyses unavailable; latest completed pre-open lineage only.',
            'New model definitions chosen after sample; exploratory, not held-out performance.',
            'Legacy missing research-context flags use the stricter saved contextPassed flag; explicit false stays false.',
            'Share scenario has explicit hypothetical costs and no quote-depth proof; open marks are not closed P&L.',
            'Historical option P&L unavailable without matched quote sequences; no conversion from stock returns.']}
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,sort_keys=True,indent=1,allow_nan=False),encoding='utf-8')
    print(json.dumps({'output':str(path),'hash':digest(result)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start',required=True);parser.add_argument('--end',required=True)
    parser.add_argument('--portfolio',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--env-file',help='Read existing native data credentials in place for a retrospective SIP fetch')
    asyncio.run(run(parser.parse_args()))
