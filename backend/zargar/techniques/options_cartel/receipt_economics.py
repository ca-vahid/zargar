"""Forward option campaign model ordered by evidence receipt, never candle time.

Ask entry / bid exits are hypotheses using displayed size, not broker executions.
Unknown prices or coverage produce an incomplete result, never a zero return.
"""
from __future__ import annotations

import datetime as dt
import math

from ...marketstructure.sessions import ET,session_bounds
from ...options.occ import parse
from .data import DailyBar,completed_daily
from .exits import ExitCampaign,ExitState,decide_exits,record_fill,allocation_preview
from .nonemission import minute_set
from .shadow_entries import digest


def usable_quote(q,at,*,instrument='options'):
    number=lambda v:isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
    return (q.get('status')=='observed' and q.get('source') in (('opra','ibkr') if instrument=='options' else ('alpaca_sip',))
        and not q.get('delayed') and not q.get('halted')
        and all(number(q.get(k)) for k in ('sourceAt','observedAt','bid','ask','bidSize','askSize'))
        and 0<=at-q['sourceAt']<=10000 and q['sourceAt']<=q['observedAt']<=at
        and 0<q['bid']<=q['ask'] and min(q['bidSize'],q['askSize'])>0)


def value_receipts(*,symbol,signal,entry_observation,campaign,daily,decision_bars,price_receipts,quotes,cutoff,proofs=None,
                   decision_observed_at=None,instrument='options'):
    if instrument not in ('options','shares'): raise ValueError('unsupported research vehicle')
    multiplier=100 if instrument=='options' else 1
    campaign=ExitCampaign.model_validate(campaign)
    out={'version':'cartel-receipt-economics-v1','status':'incomplete','placesOrders':False,
        'exitModel':'receipt_minute_close_v1','instrument':instrument,
        'basis':'Prospective receipt-timed ask/bid model with displayed size; not actual fills.',
        'fills':[],'decisions':[],'gaps':[],'netPnl':None,'realizedNet':None,'openNet':None,
        'observedMaxAdversePnl':None,'observedMaxFavorablePnl':None,'remainingQty':None}
    observation=entry_observation or {};q=observation.get('quote') or {};funding=observation.get('funding') or {}
    contract=parse((observation.get('selected') or {}).get('symbol','')) if instrument=='options' else None
    underlying=observation.get('underlyingEvidence') or {}
    at=max(q.get('observedAt',cutoff+1),underlying.get('observedAt',0),decision_observed_at or signal['at']);qty=funding.get('quantity')
    fee=funding.get('optionFeePerContractUsd') if instrument=='options' else funding.get('stockFeePerOrder')
    valid_fee=isinstance(fee,(int,float)) and not isinstance(fee,bool) and math.isfinite(fee) and fee>=0
    identity_ok=(contract is not None and contract.underlying==symbol and contract.right=='C' and q.get('contract')==contract.symbol) \
        if instrument=='options' else (observation.get('selected') or {}).get('symbol')==q.get('contract')==symbol
    if (observation.get('status')!='observed' or observation.get('timely') is not True or not usable_quote(q,at,instrument=instrument)
        or not identity_ok or not signal['at']<=at<=min(cutoff,signal['at']+120000)
        or type(qty) is not int or qty<1 or qty>q['askSize'] or not valid_fee):
        out['gaps'].append('Entry requires a timely identity-matched quote, displayed size, funded quantity and explicit fees.');return out
    if (underlying.get('status')!='observed' or underlying.get('symbol')!=symbol
            or not isinstance(underlying.get('sourceAt'),(int,float)) or not 0<=at-underlying['sourceAt']<=10000
            or not isinstance(underlying.get('price'),(int,float)) or not math.isfinite(underlying['price'])
            or underlying['price']<=signal['stop']):
        out['gaps'].append('A fresh attributed underlying price is required at the modeled entry.');return out
    charge=lambda amount:amount*fee if instrument=='options' else fee
    debit=qty*q['ask']*multiplier+charge(qty)
    cap=funding.get('cashCapUsd')
    if not isinstance(cap,(int,float)) or not math.isfinite(cap) or debit>cap:
        out['gaps'].append('Entry debit exceeds or lacks its frozen cash cap.');return out
    state=ExitState(position_id='receipt:'+signal['id'],symbol=symbol,direction='long',entry=q['ask'] if instrument=='shares' else underlying['price'],
        stop=signal['stop'],initial_qty=qty,remaining_qty=qty)
    out.update(entryAt=at,entryDebit=debit,quantity=qty,contractSymbol=q['contract'],allocation=allocation_preview(campaign,qty))
    spread_cost=qty*(q['ask']-q['bid'])*multiplier/2
    out['fills'].append({'at':at,'side':'BUY','quantity':qty,'price':q['ask'],'fee':charge(qty),'quoteSourceAt':q['sourceAt']})
    seen={b[0]:b for b in decision_bars if len(b)>6 and b[6]=='exchange' and b[0]+60000<=signal['at']}
    history=completed_daily([DailyBar.model_validate(b) for b in daily],signal['at'])
    last_minute=max(seen,default=-1);last_quote=q;pending=[];proceeds=0.;exit_fees=0.;mae=min(0,qty*q['bid']*multiplier-debit);mfe=0.
    used={};events=[];missing=set();known_proofs=dict(proofs or {});charged_orders=set()
    for receipt in price_receipts:
        if at<=receipt['observedAt']<=cutoff:
            received_proofs=receipt.get('verifiedIntervals',{}).get(symbol,{})
            if received_proofs: events.append((receipt['observedAt'],-1,digest(received_proofs),received_proofs))
            for item in receipt.get('bars',[]):
                b=item['bar']
                if item['symbol']==symbol and len(b)>6 and b[6]=='exchange' and b[0]+60000<=receipt['observedAt']:
                    events.append((receipt['observedAt'],1,digest(b),b))
    for quote in quotes:
        if at<=quote.get('observedAt',-1)<=cutoff and quote.get('contract')==q['contract']:
            events.append((quote['observedAt'],0,digest(quote),quote))

    def quote_key(quote):
        return digest({k:quote.get(k) for k in ('contract','source','sourceAt','bid','ask','bidSize','askSize')})

    def fill_pending(now):
        nonlocal state,proceeds,exit_fees,pending,spread_cost
        if not pending or not usable_quote(last_quote,now,instrument=instrument): return
        key=quote_key(last_quote);capacity=max(0,int(last_quote['bidSize'])-used.get(key,0))
        leftover=[]
        for decision in pending:
            amount=min(decision['qty'],state.remaining_qty,capacity)
            if amount:
                fill_id=f"{key}:{len(out['fills'])}:{decision['rung']}"
                state=record_fill(campaign,state,fill_id=fill_id,rung=decision['rung'],qty=amount)
                capacity-=amount;used[key]=used.get(key,0)+amount
                order_key=(decision['decisionAt'],decision['rung'])
                fill_fee=charge(amount) if instrument=='options' or order_key not in charged_orders else 0
                charged_orders.add(order_key)
                proceeds+=amount*last_quote['bid']*multiplier;exit_fees+=fill_fee
                spread_cost+=amount*(last_quote['ask']-last_quote['bid'])*multiplier/2
                out['fills'].append({'at':now,'decisionAt':decision['decisionAt'],'side':'SELL','rung':decision['rung'],
                    'quantity':amount,'price':last_quote['bid'],'fee':fill_fee,'quoteSourceAt':last_quote['sourceAt']})
            if decision['qty']>amount: leftover.append({**decision,'qty':decision['qty']-amount})
        pending=leftover

    for received,kind,_,value in sorted(events):
        if not state.remaining_qty: break
        if kind==-1:
            known_proofs.update(value)
            continue
        if kind==0:
            if usable_quote(value,received,instrument=instrument): last_quote=value
        else:
            b=value;ts=b[0]
            if ts in seen: continue  # later revisions cannot rewrite decisions or their entry stop
            seen[ts]=b
            if ts<=last_minute: continue  # late recovery supplies context, not a historical exit
            day=dt.datetime.fromtimestamp(ts/1000,ET).date();opens,closes=session_bounds(day.isoformat())
            verified=minute_set(known_proofs,symbol,received)
            start=max(opens,signal['at'])
            missing.update(t for t in range(start,ts,60000) if t not in seen and t not in verified)
            last_minute=ts;daily_close=ts+60000==closes
            if daily_close:
                expected=range(opens,closes,60000)
                if all(t in seen or t in verified for t in expected):
                    candles=[seen[t] for t in expected if t in seen]
                    if candles:
                        complete=DailyBar(symbol=symbol,session=day,open=candles[0][1],high=max(v[2] for v in candles),
                            low=min(v[3] for v in candles),close=candles[-1][4],volume=sum(v[5] for v in candles))
                        history=[h for h in history if h.session!=day]+[complete]
                else:
                    out['gaps'].append(f'{day}: daily close context incomplete');daily_close=False
            try:
                result=decide_exits(campaign,state,history,as_of_ms=closes if daily_close else received,
                    observed_price=b[4],daily_close=daily_close,pending_qty=sum(p['qty'] for p in pending),dte=contract.dte(day) if contract else None)
                out['gaps'].extend(w for w in result['warnings'] if 'exit is pending' not in w)
                if result['decisions']:
                    pending=[{**d,'decisionAt':received} for d in result['decisions']]
                    out['decisions'].append({'at':received,'priceMinute':ts,'underlying':b[4],'exits':pending})
            except ValueError as exc:
                out['gaps'].append(str(exc))
        fill_pending(received)
        if usable_quote(last_quote,received,instrument=instrument):
            mark=proceeds-exit_fees+state.remaining_qty*last_quote['bid']*multiplier-debit
            mae=min(mae,mark);mfe=max(mfe,mark)
    out.update(remainingQty=state.remaining_qty,fees=charge(qty)+exit_fees,spreadCost=spread_cost,
               executionAssumption='Displayed ask/bid with no additional market impact; spread cost is measured against quote midpoints.',
               activeStop=state.stop,breakeven=state.breakeven,
               pendingExits=pending,observedMaxAdversePnl=mae,observedMaxFavorablePnl=mfe)
    if state.remaining_qty:
        start_day=dt.datetime.fromtimestamp(signal['at']/1000,ET).date()
        end_day=dt.datetime.fromtimestamp(cutoff/1000,ET).date()
        from ...marketstructure.market_calendar import is_trading_day
        while start_day<=end_day:
            if is_trading_day(start_day):
                opens,closes=session_bounds(start_day.isoformat())
                verified=minute_set(known_proofs,symbol,cutoff)
                missing.update(t for t in range(max(opens,signal['at']),min(closes,cutoff//60000*60000),60000)
                               if t not in seen and t not in verified)
            start_day+=dt.timedelta(days=1)
    if missing: out['gaps'].append(f'{len(missing)} post-entry minute gaps were unresolved when later prices arrived.')
    sold=qty-state.remaining_qty;realized=proceeds-exit_fees-debit*sold/qty
    out['realizedNet']=realized
    if state.remaining_qty:
        if not usable_quote(last_quote,cutoff,instrument=instrument) or last_quote['bidSize']<state.remaining_qty:
            out['gaps'].append('No fresh size-qualified liquidation mark at the cutoff.')
        else: out['openNet']=state.remaining_qty*last_quote['bid']*multiplier-debit*state.remaining_qty/qty
    else:
        out['openNet']=0.;out['closedAt']=out['fills'][-1]['at']
    out['gaps']=list(dict.fromkeys(out['gaps']))
    if not out['gaps']:
        out['status']='closed' if not state.remaining_qty else 'open'
        out['netPnl']=realized+(out['openNet'] or 0)
    out['inputHash']=digest({'instrument':instrument,'symbol':symbol,'signal':signal,'entry':entry_observation,'campaign':campaign.model_dump(mode='json'),
        'decisionBars':decision_bars,'receipts':price_receipts,'quotes':quotes,'daily':daily,'cutoff':cutoff,'proofs':proofs or {}})
    return out
