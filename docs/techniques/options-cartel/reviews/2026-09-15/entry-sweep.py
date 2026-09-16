import sys,json,subprocess,datetime as dt,math
from pathlib import Path
REPO = next(p for p in Path(__file__).resolve().parents if (p/'backend'/'zargar').is_dir())
sys.path.insert(0,str(REPO/'backend'))
from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.automatic_plans import PreparationPolicy,automatic_review
from zargar.techniques.options_cartel.plans import CartelPlan
from zargar.techniques.options_cartel.prepare import build_volume_baseline
from zargar.techniques.options_cartel.preparation_readiness import baseline_coverage
from zargar.techniques.options_cartel.entry import read_entry

DAY='2026-09-15';OPEN,CLOSE=session_bounds(DAY)
def sql(q):
    raw=subprocess.check_output(['docker','exec','zargar-db','psql','-U','zargar','-d','zargar','-qAt','-c',"BEGIN READ ONLY; SET LOCAL statement_timeout='30s'; "+q+'; COMMIT;'],text=True)
    return [json.loads(line) for line in raw.splitlines() if line.startswith(('{','['))]
prep=sql("SELECT jsonb_build_object('id',id,'asOf',as_of,'config',config,'shortlist',result->'shortlist') FROM technique_runs WHERE id='b026e513a1714235ad78b417803f5f8e'")[0]
analyses=sql("SELECT jsonb_build_object('id',a.id,'symbol',a.symbol,'config',a.config,'analysis',a.result->'analysis') FROM technique_runs p, jsonb_array_elements(p.result->'shortlist') j JOIN technique_runs a ON a.id=j->>'analysisId' WHERE p.id='b026e513a1714235ad78b417803f5f8e'")
history=sql("SELECT jsonb_build_object('symbol',symbol,'observedAt',observed_at,'end',end_ms,'payload',payload) FROM cartel_history_cache WHERE symbol IN ('BOX','NTNX','ARE','PPC','EL') AND timeframe='1m' AND payload->>'provider' LIKE '%:intraday' ORDER BY observed_at")
today=sql(f"SELECT jsonb_build_object('symbol',symbol,'bar',jsonb_build_array(ts,open,high,low,close,volume,source)) FROM bars WHERE symbol IN ('BOX','NTNX','ARE','PPC','EL') AND tf='1m' AND ts>={OPEN} AND ts<{CLOSE} ORDER BY symbol,ts")
prior={r['symbol']:r for r in history}; tapes={s:[] for s in prior}
for r in today:tapes[r['symbol']].append(Bar(r['symbol'],'1m',*r['bar'][:6],source=r['bar'][6]))
policy=PreparationPolicy.model_validate(prep['config']['policy'])
variants=[('baseline',{}),('5m',{'timeframe_minutes':5}),('30m',{'timeframe_minutes':30}),('volume_1x',{'volume_multiple':1.0}),('volume_2x',{'volume_multiple':2.0}),('breakout_bar_stop',{'stop_mode':'breakout_bar'}),('retest',{'mode':'retest'})]
rows=[]
for saved in analyses:
    s=saved['symbol'];item=next(r for r in prep['shortlist'] if r['symbol']==s)
    review=automatic_review(saved['config']['inputs'],saved['analysis'],policy,research_only=True)
    hist=[Bar(s,'1m',*b[:6],source=b[6]) for b in prior[s]['payload']['bars']]
    assert prior[s]['observedAt']<OPEN and prior[s]['end']<OPEN
    for name,overrides in variants:
        entry=review.entry_policy.model_copy(update={**overrides,'require_exchange_bars':True,'allow_simulated_bars':False})
        baseline=build_volume_baseline(hist,s,entry.timeframe_minutes,prep['asOf'],require_exchange=True)
        plan=CartelPlan(id=f'research-{s}-{name}',symbol=s,direction='long',setup=item['setup'],created_at=prep['asOf'],first_session=dt.date.fromisoformat(DAY),last_session=dt.date.fromisoformat(DAY),trigger=item['trigger'],invalidation=item['invalidation'],targets=item['targets'],source_refs=(saved['id'],),rationale='EOD no-market-permission counterfactual, not a trade',rules=saved['config']['inputs']['rules'],entry=entry,volume_baseline=baseline['baselines'],baseline_as_of=prep['asOf'])
        coverage=baseline_coverage(plan);slots=coverage['usableEntryPeriods'];first_hour=all(i in slots for i in range(60//entry.timeframe_minutes))
        covered=coverage['ready'] and (policy.coverage_policy!='opening_and_broad' or first_hour and len(slots)>=math.ceil((coverage['expected']-1)*.8)) and (policy.coverage_policy!='full_session' or coverage['available']==coverage['expected'])
        row={'symbol':s,'variant':name,'baseline':f"{coverage['available']}/{coverage['expected']}",'coverageAllowed':covered,'status':'coverage_excluded','marketPermission':False}
        if covered:
            result=read_entry(plan,tapes[s],CLOSE)
            row.update(status=result['status'],rejections=[r for r in result['trace'] if r['decision']=='watch_only'])
            signal=result.get('signal')
            if signal:
                future=[b for b in tapes[s] if b.ts>=signal['at']]
                row.update(signal=signal)
                if future:
                    first=future[0];entry_price=first.open;stop=signal['stop'];target=plan.targets[0]
                    # Descriptive price path only; no invented option fills or partial exits.
                    risk=entry_price-stop
                    stop_bars=[b for b in future if b.low<=stop]
                    target_bars=[b for b in future if b.high>=target]
                    st=stop_bars[0].ts if stop_bars else None;tt=target_bars[0].ts if target_bars else None
                    row['path']={'nextMinuteOpen':entry_price,'stop':stop,'firstTarget':target,'stopAt':st,'targetAt':tt,
                        'firstTouch':'ambiguous_same_minute' if st and tt and st==tt else 'stop' if st and (tt is None or st<tt) else 'target' if tt else 'neither',
                        'underlyingClose':future[-1].close,'closeR':(future[-1].close-entry_price)/risk if risk>0 else None,
                        'maxFavorableR':(max(b.high for b in future)-entry_price)/risk if risk>0 else None,
                        'maxAdverseR':(min(b.low for b in future)-entry_price)/risk if risk>0 else None}
        rows.append(row)
summary=[{'variant':name,'eligibleCoverage':sum(r['coverageAllowed'] for r in rows if r['variant']==name),'signals':sum(r['status']=='triggered' for r in rows if r['variant']==name),'firstTouches':[r['symbol']+':'+r.get('path',{}).get('firstTouch','none') for r in rows if r['variant']==name and r['status']=='triggered']} for name,_ in variants]
output={'session':DAY,'preparationId':prep['id'],'basis':'Retrospective underlying-only counterfactual. Actual market permission stayed blocked. No option returns or size changes inferred. One session, five selected names, not an optimization verdict.','summary':summary,'rows':rows}
Path(__file__).with_name('entry-sweep-results.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
print(json.dumps({'summary':summary,'baseline':[r for r in rows if r['variant']=='baseline']},indent=2))
