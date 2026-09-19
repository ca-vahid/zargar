"""Stored-evidence reconciliation. Pure modeled economics are not fill receipts."""
from __future__ import annotations

from sqlalchemy import select

from ...models import TechniqueRun
from .data import DailyBar,completed_daily
from .data_quality import unpack
from .exits import ExitCampaign
from .lab_economics import compare_vehicles
from .lab_protocol import TrialProtocol
from .profitability_research import _study,make_plan
from .shadow_entries import ShadowEntrySpec,digest


def reconcile_signal(signal_run,context,baseline,history,quote_runs,price_runs,cutoff):
    """Respect immutable entry inputs; later price receipts are labeled research.

    This comparison is descriptive until post-entry decisions/fills are replayed
    by their receipt time, rather than historical candle time. It never grants
    a complete trial outcome merely because a next-open model returned numbers.
    """
    saved=signal_run.result;variant=saved['variant'];candidate=next(c for c in context.result['candidates'] if c['id']==saved['candidateId'])
    output={'signalId':signal_run.id,'candidateId':candidate['id'],'symbol':candidate['symbol'],'variant':variant,
        'signalAt':saved['signal']['at'],'observedAt':saved['observedAt'],'status':'evidence_missing',
        'models':None,'gaps':[],'trialEligible':False,'placesOrders':False}
    selections=[q for q in quote_runs if q.result.get('purpose')=='entry_selection' and q.as_of<=cutoff]
    selected=selections[0].result['observation'] if selections else None
    share_selections=[q for q in quote_runs if q.result.get('purpose')=='share_entry_selection' and q.as_of<=cutoff]
    share_entry=share_selections[0].result['observation'] if share_selections else None
    attempts=[q for q in quote_runs if q.result.get('purpose')=='entry_attempt']
    output['quoteAttempts']=len(attempts)
    output['quoteDisposition']=selected.get('status') if selected else 'not_observed'
    anchor=selected if selected and selected.get('timely') else share_entry
    if not anchor or not anchor.get('timely'):
        output['gaps'].append('No timely funding/option observation; do not infer a fill or zero return.')
        return output
    funding=anchor.get('funding')
    if not funding:
        output['gaps'].append('Funding snapshot missing.');return output
    if digest([b.model_dump(mode='json') for b in completed_daily(history,candidate['sourceAt'])])!=candidate['dailyInputHash']:
        raise ValueError('daily context no longer matches its frozen input hash')
    tape={b[0]:unpack(candidate['symbol'],b) for b in saved['decisionBars']}
    availability={}
    for receipt in sorted(price_runs,key=lambda r:(r.as_of,r.id)):
        if receipt.as_of>cutoff: continue
        for item in receipt.result.get('bars',[]):
            b=item['bar']
            if item['symbol']!=candidate['symbol'] or b[0]<saved['signal']['at'] or b[0]+60000>cutoff or b[6]!='exchange':continue
            if b[0] not in tape:
                tape[b[0]]=unpack(candidate['symbol'],b);availability[str(b[0])]=receipt.as_of
    quotes=[];raw_quotes=[]
    if selected and selected.get('quote'): raw_quotes.append(selected['quote'])
    raw_quotes.extend(q.result['quote'] for q in quote_runs if q.as_of<=cutoff and q.result.get('purpose')=='mark')
    for q in raw_quotes:
        if q.get('status')=='observed' and q.get('observedAt',cutoff+1)<=cutoff:
            quotes.append({'source_at':q.get('sourceAt'),'available_at':q['observedAt'],
                'bid':q['bid'],'ask':q['ask'],'delayed':q.get('delayed',False),'halted':q.get('halted',False)})
    premium={'contract_symbol':selected['selected']['symbol'],'source':'method-lab prospective quote receipts','quotes':quotes} \
        if selected and selected.get('selected') else None
    spec=None;control=None
    if variant in baseline.result.get('specs',{}):
        spec=ShadowEntrySpec.model_validate(baseline.result['specs'][variant])
        original=ExitCampaign.model_validate(candidate['exitCampaign'])
        campaign=ExitCampaign.for_profile(original.profile,list(spec.targets),
            september_fractions=[r.fraction for r in original.rungs] if original.profile=='september_2026' else None,
            allocation_policy=original.allocation_policy)
    else:
        tf=5 if variant=='breakout_5m_v1' else 15
        control=make_plan({**candidate,'entryPolicy':{**candidate['entryPolicy'],'timeframe_minutes':tf}},
            context.config['session'],baseline.result['baselines'][str(tf)])
        campaign=ExitCampaign.model_validate(candidate['exitCampaign'])
    output['models']=compare_vehicles(spec,saved['signal'],list(tape.values()),history,campaign,
        as_of_ms=cutoff,observed_at=saved['observedAt'],signal_after=saved['entryAfter'],funding=funding,
        option_observation=selected,premium_input=premium,verified_intervals=saved.get('verifiedIntervals'),control_plan=control)
    from .receipt_economics import value_receipts
    receipt_result=value_receipts(symbol=candidate['symbol'],signal=saved['signal'],entry_observation=selected,
        campaign=campaign,daily=[b.model_dump(mode='json') for b in history],decision_bars=saved['decisionBars'],
        price_receipts=[p.result for p in price_runs if p.as_of<=cutoff],quotes=raw_quotes,cutoff=cutoff,
        proofs=saved.get('verifiedIntervals'),decision_observed_at=saved['observedAt'])
    output['receiptEconomics']=receipt_result
    if share_entry:
        share_quotes=[share_entry['quote'],*[q.result['quote'] for q in quote_runs if q.as_of<=cutoff and q.result.get('purpose')=='share_mark']]
        output['shareReceiptEconomics']=value_receipts(symbol=candidate['symbol'],signal=saved['signal'],entry_observation=share_entry,
            campaign=campaign,daily=[b.model_dump(mode='json') for b in history],decision_bars=saved['decisionBars'],
            price_receipts=[p.result for p in price_runs if p.as_of<=cutoff],quotes=share_quotes,cutoff=cutoff,
            proofs=saved.get('verifiedIntervals'),decision_observed_at=saved['observedAt'],instrument='shares')
    output.update(status='modeled_research',priceReceiptCount=len(availability),optionQuoteCount=len(quotes),
        priceAvailability=availability,modelInputHash=digest({'signal':saved,'funding':funding,'quotes':quotes,
            'availability':availability,'prices':[b.to_row() for b in tape.values()],'cutoff':cutoff}))
    output['gaps'].extend(receipt_result['gaps'])
    output['trialEligible']=receipt_result['status']=='closed' and not receipt_result['gaps']
    return output


async def report(engine,context,cutoff):
    async with engine.sf() as s:
        signals=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_signal',
            TechniqueRun.parent_run_id==context.id,TechniqueRun.as_of<=cutoff).order_by(TechniqueRun.as_of))).all()
        quotes=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_quote',
            TechniqueRun.parent_run_id.in_([r.id for r in signals]),TechniqueRun.as_of<=cutoff).order_by(TechniqueRun.as_of))).all()
        baselines=(await s.scalars(select(TechniqueRun).where(TechniqueRun.id.in_([r.result['baselineId'] for r in signals])))).all()
        prices=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_prices',
            TechniqueRun.config['portfolioId'].as_string()==context.config['portfolioId'],
            TechniqueRun.as_of>=context.as_of,TechniqueRun.as_of<=cutoff).order_by(TechniqueRun.as_of))).all()
        histories=(await s.execute(select(TechniqueRun.id,TechniqueRun.config['inputs']['history']).where(
            TechniqueRun.id.in_([c['analysisId'] for c in context.result['candidates']])))).all()
        ticks=(await s.scalars(select(TechniqueRun).where(TechniqueRun.parent_run_id==context.id,
            TechniqueRun.mode=='lab_tick',TechniqueRun.as_of<=cutoff))).all()
    baseline_map={r.id:r for r in baselines};history_map=dict(histories);rows=[]
    candidates={c['id']:c for c in context.result['candidates']}
    for signal in signals:
        try:
            candidate=candidates[signal.result['candidateId']]
            history=[DailyBar.model_validate(b) for b in history_map.get(candidate['analysisId']) or []]
            row=await _study(reconcile_signal,signal,context,baseline_map[signal.result['baselineId']],history,
                [q for q in quotes if q.parent_run_id==signal.id],prices,cutoff)
        except (ValueError,KeyError,TypeError) as exc:
            row={'signalId':signal.id,'symbol':signal.result['symbol'],'variant':signal.result['variant'],
                 'status':'evidence_missing','gaps':[f'{type(exc).__name__}: stored evidence cannot support valuation'],
                 'trialEligible':False,'placesOrders':False}
        rows.append(row)
    trial=context.result.get('trial') or {};protocol=trial.get('protocol')
    from .lab_protocol import trial_review
    observations=trial_observations(context,{'rows':rows},ticks,TrialProtocol.model_validate(protocol),cutoff) if protocol else []
    review=trial_review(TrialProtocol.model_validate(protocol),observations) if protocol else {'status':'protocol_unavailable','activationAllowed':False}
    return {'schemaVersion':1,'contextId':context.id,'session':context.config['session'],'asOfMs':cutoff,
        'rows':rows,'trialReview':review,'trialObservationsIncluded':sum(r.complete for r in observations),'placesOrders':False,'activationAllowed':False,
        'note':'Modeled economics are separate from qualified trial outcomes. Missing receipts are not zero-profit observations.'}


def trial_observations(context,economics,ticks,protocol,cutoff):
    """Keep every monitored candidate paired, including missing-data non-entries."""
    import datetime as dt
    from ...marketstructure.sessions import ET,session_bounds
    from .lab_protocol import TrialObservation
    day=dt.date.fromisoformat(context.config['session']);opens,closes=session_bounds(day.isoformat())
    results={(r['candidateId'],r['variant']):r for r in economics['rows'] if 'candidateId' in r}
    market=context.result.get('market',{});directions=[market.get('indices',{}).get(s,{}).get('direction') for s in ('SPY','QQQ')]
    regime='unknown' if any(d not in ('long','short','mixed') for d in directions) else \
        'strong' if all(d=='long' for d in directions) else 'weak' if all(d=='short' for d in directions) else 'mixed'
    available={t.result['boundary']:t for t in ticks if t.as_of<=cutoff and 0<=t.as_of-t.result['boundary']<=120000}
    output=[]
    for cid in context.result['observedIds']:
        for variant in (protocol.control,protocol.challenger):
            row=results.get((cid,variant));value=(row or {}).get('receiptEconomics') or {}
            common={'protocol_hash':protocol.fingerprint,'session':day,'candidate_id':cid,'variant':variant,'regime':regime}
            if row and row.get('trialEligible') and value.get('status')=='closed':
                output.append(TrialObservation(**common,disposition='closed',coverage_complete=True,
                    closed_session=dt.datetime.fromtimestamp(value['closedAt']/1000,ET).date(),
                    net_pnl=value['netPnl'],fees=value['fees'],spread_slippage_cost=value['spreadCost'],
                    cash_debit=value['entryDebit'],peak_exposure=value['entryDebit'],
                    max_adverse_pnl=value['observedMaxAdversePnl'],evidence_ids=(row['signalId'],value['inputHash'])))
                continue
            complete=cutoff>=closes;refs=[]
            for boundary in range(opens+300000,closes,300000):
                tick=available.get(boundary)
                read=next((r for r in tick.result['rows'] if r['candidateId']==cid),None) if tick else None
                model=(read or {}).get('models',{}).get(variant)
                if not model or model.get('signal') or any(d.get('status',d.get('decision')) in
                    ('data_gap','missing_bucket','untrusted_confirmation','unsupported_volume_period')
                    or set(d.get('blockers',[])) & {'baseline_unavailable','session_stop_coverage'} for d in model.get('trace',[])):
                    complete=False
                elif tick: refs.append(tick.id)
            no_signal=complete and row is None
            output.append(TrialObservation(**common,disposition='no_signal' if no_signal else 'data_missing',
                coverage_complete=no_signal,net_pnl=0 if no_signal else None,cash_debit=0 if no_signal else None,
                peak_exposure=0 if no_signal else None,evidence_ids=tuple(refs)))
    return output


async def trial_report(engine,trial_id,cutoff):
    from .lab_protocol import trial_review
    from ...marketstructure.sessions import session_bounds
    async with engine.sf() as s:
        trial=await s.get(TechniqueRun,trial_id)
        if trial is None or trial.mode!='lab_trial' or trial.technique!='options_cartel':
            raise ValueError('Method-lab trial not found')
        protocol=TrialProtocol.model_validate(trial.result['protocol'])
        contexts=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_context',
            TechniqueRun.technique=='options_cartel',TechniqueRun.config['portfolioId'].as_string()==protocol.portfolio_id,
            TechniqueRun.result['trial']['id'].as_string()==trial_id,TechniqueRun.as_of<=cutoff).order_by(TechniqueRun.as_of))).all()
    selected={}
    for context in contexts:
        day=context.config['session']
        if context.as_of<session_bounds(day)[0] and context.result['trial']['hash']==protocol.fingerprint:
            selected[day]=context  # predetermined latest pre-open context, never select by outcome
    observations=[];sessions=[]
    for day,context in sorted(selected.items()):
        economics=await report(engine,context,cutoff)
        async with engine.sf() as s:
            ticks=(await s.scalars(select(TechniqueRun).where(TechniqueRun.parent_run_id==context.id,
                TechniqueRun.mode=='lab_tick',TechniqueRun.as_of<=cutoff))).all()
        rows=trial_observations(context,economics,ticks,protocol,cutoff);observations.extend(rows)
        control={r.candidate_id:r for r in rows if r.variant==protocol.control}
        selections={}
        slots=context.config.get('policy',{}).get('focus_count',5)
        names={c['id']:c['symbol'] for c in context.result['candidates']}
        for name,ordered in context.result['rankings'].items():
            chosen=ordered[:slots];measured=[control[cid] for cid in chosen if cid in control]
            complete=len(measured)==len(chosen) and all(r.complete for r in measured)
            selections[name]={'selectedIds':chosen,'selectedSymbols':[names[cid] for cid in chosen],
                'complete':complete,'covered':sum(r.complete for r in measured),
                'selectedCount':len(chosen),'closedTrades':sum(r.disposition=='closed' for r in measured),
                'netPnl':sum(r.net_pnl for r in measured) if complete else None,
                'basis':'Fixed breakout-5m control; incomplete selection outcomes are not scored as zero.'}
        sessions.append({'session':day,'contextId':context.id,'observations':len(rows),
                         'completeObservations':sum(r.complete for r in rows),'economics':economics,'selectionComparisons':selections})
    review=trial_review(protocol,observations)
    return {'trialId':trial_id,'asOfMs':cutoff,'protocol':protocol.model_dump(mode='json'),
        'review':review,'sessions':sessions,'placesOrders':False,'activationAllowed':False,
        'basis':'Receipt-timed quote model; distinct from actual Practice account executions.'}


async def scheduled_review(engine):
    import datetime as dt
    from ...domain import now_ms
    from ...marketstructure.sessions import ET,session_bounds
    from ...marketstructure.market_calendar import is_trading_day
    from . import method_lab as lab
    from .preparation_scope import read_policy
    from .jobs import stopping
    policy=read_policy(engine,'practice');at=now_ms();day=dt.datetime.fromtimestamp(at/1000,ET).date()
    if stopping(engine) or not lab.enabled(engine,policy) or not is_trading_day(day) or at<session_bounds(day.isoformat())[1]+120000:
        return {'status':'not_due','placesOrders':False}
    async with engine.sf() as s:
        trials=(await s.scalars(select(TechniqueRun).where(TechniqueRun.mode=='lab_trial',
            TechniqueRun.config['portfolioId'].as_string()==policy.portfolio_id,
            TechniqueRun.technique=='options_cartel').order_by(TechniqueRun.as_of.desc()).limit(3))).all()
    recorded=[]
    for trial in trials:
        key=lab.identity(trial.id,'daily_review',day.isoformat())
        async with engine.sf() as s:
            if await s.get(TechniqueRun,key): continue
        result=await trial_report(engine,trial.id,at)
        if stopping(engine) or not lab.enabled(engine,policy): break
        await lab.insert_record(engine,key=key,mode='lab_review',at=at,parent=trial.id,
            config={**trial.config,'session':day.isoformat()},
            result={**result,'weeklyCheckpoint':day.weekday()==4,'recordedAt':now_ms()})
        recorded.append(key)
    return {'status':'recorded','records':recorded,'weeklyCheckpoint':day.weekday()==4,'placesOrders':False}
