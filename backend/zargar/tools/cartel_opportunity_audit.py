"""Read-only selection audit. No orders, provider calls, settings or database writes.

Ranking inputs are frozen pre-open fields only. Recovered minute prices describe
opportunity, not timely executable fills. Unknown option costs stay unknown.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

from ..marketstructure.sessions import session_bounds
from ..marketstructure.market_calendar import is_trading_day

VERSION = 'cartel-opportunity-audit-1'


def load(value):
    return json.loads(value) if isinstance(value, str) else value


def distance(candidate, session):
    """Signed distance from the last completed pre-session close; no future bars."""
    daily = [b for b in candidate.get('daily', []) if b['session'] < session]
    if not daily:
        return None
    close = max(daily, key=lambda b: b['session'])['close']
    return (candidate['trigger']/close-1)*100*(1 if candidate['direction']=='long' else -1)


def selections(rows, slots=5):
    """Predeclared comparisons, never optimized on the measured outcomes."""
    def desc(x):
        return -x if isinstance(x, (int, float)) else float('inf')
    baseline = sorted(rows, key=lambda r: (desc(r['structuralR']), desc(r['relativeStrength']),
                                           desc(r['dailyVolume']), r['symbol']))
    near = sorted([r for r in rows if r['distancePct'] is not None and r['distancePct']>=0], key=lambda r: (
        r['distancePct'],
        desc(r['relativeStrength']), r['symbol']))
    liquid = sorted([r for r in rows if r['dollarVolume'] is not None], key=lambda r: (desc(r['dollarVolume']), desc(r['relativeStrength']), r['symbol']))
    return {key:[r['symbol'] for r in ranked[:slots]] for key,ranked in
            [('saved_quality',baseline),('nearest_unbroken',near),('liquid_first',liquid)]}


def price_evidence(candidate, bars, session):
    opens, closes = session_bounds(session)
    native = [b for b in bars if len(b)>6 and b[6]=='exchange' and opens<=b[0]<closes]
    reached = any(b[2]>=candidate['trigger'] if candidate['direction']=='long' else
                  b[3]<=candidate['trigger'] for b in native)
    return {'nativeMinutes':len({b[0] for b in native}), 'expectedMinutes':(closes-opens)//60000,
        'observedLevelTouch':reached if native else None,
        'high':max((b[2] for b in native),default=None), 'low':min((b[3] for b in native),default=None),
        'note':'Price touch is not a closed-bar confirmation or an executable option entry. Untouched incomplete tapes are inconclusive.'}


async def audit(conn, start, end, portfolio):
    contexts=await conn.fetch("select id,created_at,config,result from technique_runs where technique='options_cartel' "
        "and mode='profit_context' and config->>'workspace'='practice' and config->>'portfolioId'=$1 "
        "and config->>'session'>=$2 and config->>'session'<=$3 order by created_at,id",portfolio,start,end)
    chosen={}
    for item in contexts:
        cfg,res=load(item['config']),load(item['result']);day=cfg['session'];opens,_=session_bounds(day)
        if int(item['created_at'].timestamp()*1000)<opens and res.get('frozenAt',opens)<opens:
            chosen[day]=(item,cfg,res)  # latest available pre-open population, no intraday rerun
    arms=await conn.fetch("select a.run_id,a.symbol,a.plan_for,a.state,a.created_at,r.result,r.config->'inputs'->'history' daily from technique_armed a "
        "join technique_runs r on r.id=a.run_id where a.technique='options_cartel' and a.portfolio_id=$1 "
        "and a.plan_for >= $2 and a.plan_for <= $3 order by a.plan_for,a.symbol",portfolio,start,end)
    result=[]
    days=[]; cursor=dt.date.fromisoformat(start)
    while cursor<=dt.date.fromisoformat(end):
        if is_trading_day(cursor): days.append(cursor.isoformat())
        cursor+=dt.timedelta(days=1)
    for day in days:
        dayarms=[a for a in arms if str(a['plan_for'])==day];opens,closes=session_bounds(day)
        attempts=await conn.fetch("select a.at,a.evidence from cartel_preparation_attempts a join technique_runs r "
            "on r.id=a.preparation_id where a.portfolio_id=$1 and r.config->>'session'=$2 and a.at<$3 order by a.at,a.id",
            portfolio,day,opens)
        journal=await conn.fetch("select id,ts,type,payload from events where portfolio_id=$1 "
            "and type in ('TechniqueCartelStateChanged','TechniqueCartelPreflight') "
            "and ts>=to_timestamp($2::double precision/1000) and ts<=to_timestamp($3::double precision/1000) order by ts,id",
            portfolio,opens,closes)
        signal_events=[];preflights=[]
        for event in journal:
            body=load(event['payload'])
            if body.get('action')=='signal_consumed':
                signal_events.append({'id':event['id'],'at':str(event['ts']),'runId':body.get('runId'),'symbol':body.get('symbol')})
            elif event['type']=='TechniqueCartelPreflight':
                report=body.get('report') or {}
                preflights.append({'id':event['id'],'at':str(event['ts']),'runId':body.get('runId'),'symbol':body.get('symbol'),
                    'passed':report.get('passed'),'checks':report.get('checks'),'expression':report.get('expression')})
        by_symbol={}
        for attempt in attempts:
            e=load(attempt['evidence']);by_symbol[e.get('symbol')]={
                'at':attempt['at'],'status':e.get('status'),'reason':e.get('reason'),
                'retryable':e.get('retryable'),'contractSelection':e.get('contractSelection')}
        watches=await conn.fetch("select created_at,result from technique_runs where technique='options_cartel' and mode='profit_watch' "
            "and config->>'portfolioId'=$1 and config->>'session'=$2 order by created_at,id",portfolio,day)
        tapes={};observations={}
        for watch in watches:
            for candidate in load(watch['result']).get('candidates',[]):
                key=(candidate['symbol'],candidate.get('cohort','primary'))
                observations.setdefault(key,[]).append(candidate)
                for bar in candidate.get('sourceBars',[]):
                    tape=tapes.setdefault(key,{})
                    if str(bar[0]) not in tape or bar[6]=='exchange':
                        tape[str(bar[0])]=bar
        for arm in dayarms:
            for t,bar in load(arm['state']).get('minutes',{}).items():
                tape=tapes.setdefault((arm['symbol'],'primary'),{})
                if t not in tape or bar[6]=='exchange': tape[t]=bar
        if day in chosen:
            item,cfg,res=chosen[day];candidates=res.get('candidates',[]);population='frozen_preopen_context'
            source=item['id'];frozen=res['frozenAt']
        else:
            candidates=[];source=None;frozen=None;population='saved_arms_only_incomplete_denominator'
            for arm in dayarms:
                plan=load(arm['result']).get('plan',{}).get('plan',{})
                if plan and plan['created_at']<opens:
                    candidates.append({**plan,'cohort':'primary','daily':load(arm['daily']) or []})
        final_bars=await conn.fetch("select symbol,ts,open,high,low,close,volume,source from bars where tf='1m' "
            "and provider='alpaca' and source='exchange' and symbol=any($1::text[]) and ts>=$2 and ts<$3 order by ts",
            sorted({c['symbol'] for c in candidates}),opens,closes)
        provider_tapes={}
        for b in final_bars:
            provider_tapes.setdefault(b['symbol'],[]).append([b[k] for k in ('ts','open','high','low','close','volume','source')])
        rows=[]
        for candidate in candidates:
            symbol=candidate['symbol'];cohort=candidate.get('cohort','primary')
            rank=candidate.get('ranking',{});leader=candidate.get('leaderEvidence',{})
            reads=observations.get((symbol,cohort),[])
            actual=[a for a in dayarms if a['symbol']==symbol and cohort=='primary']
            signals=[load(a['state']).get('signal') for a in actual]
            research=[r.get('entry') for r in reads if r.get('entry')]
            quotes=[r.get('optionObservation') for r in reads if r.get('optionObservation')]
            rows.append({'symbol':symbol,'cohort':cohort,'direction':candidate['direction'],'trigger':candidate['trigger'],
                'distancePct':distance(candidate,day),'structuralR':rank.get('structuralTargetR'),
                'relativeStrength':rank.get('directionalRelativeStrength'),'dailyVolume':rank.get('dailyVolume'),
                'dollarVolume':leader.get('dailyDollarVolume'),'armed':bool(actual),
                'armedBeforeOpen':any(int(a['created_at'].timestamp()*1000)<opens for a in actual),
                'preopenAttempt':by_symbol.get(symbol) if cohort=='primary' else None,
                'price':price_evidence(candidate,list(tapes.get((symbol,cohort),{}).values()),day),
                'recoveredProviderPrice':price_evidence(candidate,provider_tapes.get(symbol,[]),day),
                'actualSignal':next((s for s in signals if s),None),
                'researchSignals':list({json.dumps(s,sort_keys=True):s for s in research}.values()),
                'optionObservations':quotes[-1:], 'optionNetOutcome':None,
                'optionNetOutcomeReason':'No linked entry/exit option executions supplied; underlying movement cannot price an option.',
                'researchStatuses':sorted({r.get('status','unknown') for r in reads})})
        comparisons={}
        for cohort in sorted({r['cohort'] for r in rows}):
            pool=[r for r in rows if r['cohort']==cohort]
            if population=='frozen_preopen_context':
                comparisons[cohort]=selections(pool)
        result.append({'session':day,'population':population,'contextId':source,'frozenAt':frozen,
            'rows':rows,'comparisons':comparisons,'actualArmedSymbols':[a['symbol'] for a in dayarms],
            'journaledSignals':signal_events,'journaledPreflights':preflights})
    return {'version':VERSION,'portfolio':portfolio,'sessions':result,'placesOrders':False,
        'automaticPermissionChanged':False,'limitations':[
            'Ranking experiments were defined after these sessions: exploratory, not out-of-sample validation.',
            'Primary and bearish research pools are separate. Missing pre-session populations are not reconstructed from winners.',
            'Option affordability, spread, baseline readiness and permissions are not inferred from price touches.',
            'A final context can contain mutable intraday fields. Rankings use frozen daily/ranking fields only.',
            'Research signals and recovered bars do not prove timely order eligibility or actual profits.']}


async def main(args):
    import asyncpg
    conn=await asyncpg.connect(os.environ['CARTEL_AUDIT_DATABASE_URL'],server_settings={'default_transaction_read_only':'on'})
    try:
        async with conn.transaction(isolation='repeatable_read',readonly=True):
            report=await audit(conn,args.start,args.end,args.portfolio)
    finally: await conn.close()
    raw=json.dumps(report,sort_keys=True,separators=(',',':'),allow_nan=False)
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(raw,encoding='utf-8')
    print(json.dumps({'output':str(path),'sha256':hashlib.sha256(raw.encode()).hexdigest(),
        'sessions':[{ 'session':s['session'],'population':s['population'],'candidates':len(s['rows'])} for s in report['sessions']]}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--start',required=True);p.add_argument('--end',required=True)
    p.add_argument('--portfolio',required=True);p.add_argument('--output',required=True)
    asyncio.run(main(p.parse_args()))
