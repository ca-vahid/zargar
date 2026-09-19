"""Same-signal options/shares/pass comparisons, with explicit measured-cost gaps."""
from __future__ import annotations

import math

from .exits import ExitCampaign, allocation_preview
from .plans import CartelPlan, EntryPolicy
from .research_economics import ResearchCosts, evaluate_exit_variants
from .shadow_entries import ShadowEntrySpec


def valuation_plan(spec: ShadowEntrySpec, signal):
    """A private replay adapter; never stored as mode=plan or submitted for arming."""
    return CartelPlan(id=spec.id,symbol=spec.symbol,direction='long',setup='ma_pullback',
        created_at=spec.frozen_at,first_session=spec.session,last_session=spec.session,
        trigger=signal['trigger'],invalidation=signal['stop'],targets=spec.targets,
        source_refs=('method_lab:closed_bar_engineering_v1',),rationale='Non-ordering shadow valuation adapter',
        entry=EntryPolicy(timeframe_minutes=spec.confirmation_minutes,require_exchange_bars=True,
            max_chase_r=spec.max_chase_r,min_target_r=spec.min_target_r),
        baseline_as_of=spec.baseline_at,volume_baseline=spec.volume_baseline)


def compare_vehicles(spec, signal, minutes, daily, campaign, *, as_of_ms, observed_at,
                     signal_after, funding, option_observation=None, premium_input=None,
                     verified_intervals=None, share_slippage_bps=2):
    spec=ShadowEntrySpec.model_validate(spec);plan=valuation_plan(spec,signal)
    campaign=ExitCampaign.model_validate(campaign)
    out={'version':'cartel-lab-vehicles-v1','placesOrders':False,'activationAllowed':False,
         'pass':{'netPnl':0,'capitalUsed':0,'basis':'No-trade counterfactual'},
         'shares':None,'options':None,'gaps':[],
         'basis':'Research using next observable underlying open, recorded option asks/bids and frozen fees; not actual executions.'}
    if any(r.kind=='target' and r.target not in spec.targets for r in campaign.rungs):
        raise ValueError('shadow exits must retain the pre-open resistance levels')
    numeric=lambda v:isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
    fields=('cashCapUsd','asOfMs','usdToAccountFx')
    if not funding or any(not numeric(funding.get(k)) for k in fields) or funding['cashCapUsd']<=0 \
            or funding['usdToAccountFx']<=0 or not 0<=observed_at-funding['asOfMs']<=120000:
        out['gaps'].append('missing_or_stale_funding');return out
    if not numeric(funding.get('stockFeePerOrder')) or funding['stockFeePerOrder']<0:
        out['gaps'].append('share_fees_unknown')
    else:
        costs=ResearchCosts(slippage_bps=share_slippage_bps,fee_per_unit=0,fee_per_order=funding['stockFeePerOrder'])
        args=dict(signal=signal,as_of_ms=as_of_ms,observed_at=observed_at,entry_after=observed_at,
            signal_after=signal_after,shadow_spec=spec,verified_intervals=verified_intervals)
        probe=evaluate_exit_variants(plan,campaign,minutes,daily,quantity=None,costs=costs,instrument='shares',**args)
        if probe['entry'] is None:
            out['shares']=probe
        else:
            price=probe['entry']['price'];qty=max(0,math.floor((funding['cashCapUsd']-costs.fee_per_order)/price))
            if qty:
                out['shares']=evaluate_exit_variants(plan,campaign,minutes,daily,quantity=qty,costs=costs,
                    instrument='shares',quantity_basis='frozen_equal_cash_cap',**args)
                out['shares']['cashUsedUsd']=qty*price+costs.fee_per_order
                out['shares']['stopRiskUsd']=qty*(price-signal['stop'])
                out['shares']['fullDebitStressUsd']=qty*price+costs.fee_per_order
                out['shares']['allocation']=allocation_preview(campaign,qty)
            else:
                out['shares']={'status':'unaffordable','quantity':0,'netPnl':None}
    option=option_observation or {};qty=funding.get('quantity')
    if option.get('status')!='observed' or type(qty) is not int or qty<1:
        out['gaps'].append('eligible_option_and_quantity_unavailable')
    elif premium_input is None:
        out['gaps'].append('option_quote_path_unavailable')
    elif not numeric(funding.get('optionFeePerContractUsd')):
        out['gaps'].append('option_fees_unknown')
    else:
        premium={**premium_input,'fee_per_contract':funding['optionFeePerContractUsd']}
        out['options']=evaluate_exit_variants(plan,campaign,minutes,daily,signal=signal,quantity=qty,
            as_of_ms=as_of_ms,observed_at=observed_at,entry_after=observed_at,signal_after=signal_after,
            shadow_spec=spec,verified_intervals=verified_intervals,premium_input=premium,funding=funding,
            quantity_basis='current_funding_estimate')
        out['options']['allocation']=allocation_preview(campaign,qty)
        out['options']['executionEvidenceComplete']=False
        out['options']['executionEvidenceGap']='Recorded-quote valuation does not certify exit displayed size, resting fills or actual fill quality; trial promotion needs that evidence separately.'
    return out
