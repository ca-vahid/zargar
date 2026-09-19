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
    attempts=[q for q in quote_runs if q.result.get('purpose')=='entry_attempt']
    output['quoteAttempts']=len(attempts)
    output['quoteDisposition']=selected.get('status') if selected else 'not_observed'
    if not selected or not selected.get('timely'):
        output['gaps'].append('No timely funding/option observation; do not infer a fill or zero return.')
        return output
    funding=selected.get('funding')
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
    if selected.get('quote'): raw_quotes.append(selected['quote'])
    raw_quotes.extend(q.result['quote'] for q in quote_runs if q.as_of<=cutoff and q.result.get('purpose')=='mark')
    for q in raw_quotes:
        if q.get('status')=='observed' and q.get('observedAt',cutoff+1)<=cutoff:
            quotes.append({'source_at':q.get('sourceAt'),'available_at':q['observedAt'],
                'bid':q['bid'],'ask':q['ask'],'delayed':q.get('delayed',False),'halted':q.get('halted',False)})
    premium={'contract_symbol':selected['selected']['symbol'],'source':'method-lab prospective quote receipts','quotes':quotes} \
        if selected.get('selected') else None
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
    output.update(status='modeled_research',priceReceiptCount=len(availability),optionQuoteCount=len(quotes),
        priceAvailability=availability,modelInputHash=digest({'signal':saved,'funding':funding,'quotes':quotes,
            'availability':availability,'prices':[b.to_row() for b in tape.values()],'cutoff':cutoff}))
    output['gaps'].append('Post-entry receipt-timed execution reconciliation is required before this modeled schedule can enter the prospective trial score.')
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
    review={'status':'pending_receipt_reconciliation','protocolHash':TrialProtocol.model_validate(protocol).fingerprint,
            'activationAllowed':False,'reason':'No qualified receipt-timed outcome ledger has been assembled; this is not a zero-return trial.'} \
        if protocol else {'status':'protocol_unavailable','activationAllowed':False}
    return {'schemaVersion':1,'contextId':context.id,'session':context.config['session'],'asOfMs':cutoff,
        'rows':rows,'trialReview':review,'trialObservationsIncluded':0,'placesOrders':False,'activationAllowed':False,
        'note':'Modeled economics are separate from qualified trial outcomes. Missing receipts are not zero-profit observations.'}
