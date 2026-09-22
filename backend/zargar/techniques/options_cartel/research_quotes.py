"""Read-only research option observations, never orders or executable sizing."""
from __future__ import annotations

import hashlib
import json
import math

from .contracts import SelectionEconomics, SelectionRequest, call_selector, rank_candidates


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def snapshot_quote(engine, contract, clock):
    at = clock()
    quote = engine.quotes.get(contract)
    result = {'contract': contract, 'observedAt': at, 'availableAt': at,
              'status': 'unavailable', 'sourceAt': None, 'source': None,
              'bid': None, 'ask': None, 'placesOrders': False}
    if quote is None:
        return {**result, 'reason': 'No cached quote at observation time'}
    result.update(sourceAt=quote.source_ts or None, confirmedAt=quote.ts, source=quote.source,
                  bid=quote.bid if finite(quote.bid) else None, ask=quote.ask if finite(quote.ask) else None,
                  bidSize=quote.bid_size if finite(quote.bid_size) else None,
                  askSize=quote.ask_size if finite(quote.ask_size) else None, delayed=quote.delayed, halted=quote.halted)
    reason = None
    if quote.source not in ('opra', 'ibkr'):
        reason = 'A real option source is required for this research cohort'
    elif not finite(quote.source_ts) or not 0 < quote.source_ts <= at or at-quote.source_ts > 10_000:
        reason = 'Missing, stale or future source timestamp'
    elif not finite(quote.ts) or not 0 < quote.ts <= at or at-quote.ts > 10_000:
        reason = 'Missing, stale or future receipt timestamp'
    elif quote.delayed or quote.halted:
        reason = 'Delayed or halted option quote'
    elif not finite(quote.bid) or not finite(quote.ask) or not 0 < quote.bid <= quote.ask:
        reason = 'Missing or crossed bid/ask'
    elif not finite(quote.ask_size) or not finite(quote.bid_size) or quote.ask_size <= 0 or quote.bid_size <= 0:
        reason = 'Displayed two-sided size is unavailable'
    result.update(status='observed' if reason is None else 'unavailable', reason=reason)
    identity = {k: v for k, v in result.items() if k not in ('observedAt', 'availableAt', 'confirmedAt', 'status', 'reason')}
    result['evidenceSha256'] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return result


async def observe_contract(engine, plan, policy, clock, *, choose=None, preferred=None, deadline_ms=None):
    """Select against unchanged limits; capture unknowns instead of inventing fills.

    Quantity is an isolated cash/fee estimate, not a reservation. Shared account
    exposure, pending orders and final execution checks still own actual sizing.
    ``preferred`` is a reviewed contract that gets first refresh consideration under
    ``diverse_liquidity_v1``; ``deadline_ms`` bounds the search (never extended).
    """
    out = {'status': 'unavailable', 'observedAt': clock(), 'selected': None,
           'selection': None, 'quote': None, 'funding': None, 'affordabilityOnly': False,
           'placesOrders': False, 'automaticPermissionChanged': False, 'selectionErrors': []}
    book = engine.positions.portfolio(policy.portfolio_id)
    if policy.workspace != 'practice' or not book or book.get('kind') != 'sim' or book.get('archived'):
        return {**out, 'selectionErrors': ['An active Cartel Practice book is required']}
    equity = await engine.positions.equity(policy.portfolio_id)
    currency = book.get('baseCurrency', 'USD')
    fx = engine.positions.fx.rate('USD', currency)
    cash = book.get('cash')
    fee = engine.settings.get('options.fee_per_contract', .99)
    regulatory = engine.settings.get('sim.reg_fee_per_contract', .05)
    stock_fee = engine.settings.get('sim.stock_commission', 0.)
    if not all(finite(v) for v in (equity, fx, cash, fee, regulatory, stock_fee)) or equity <= 0 or fx <= 0 \
            or min(fee, regulatory, stock_fee) < 0:
        return {**out, 'selectionErrors': ['Account value, FX or modeled fee schedule unavailable']}
    unit_fee = fee+regulatory
    cap = max(0., min(cash, policy.budget, equity*policy.risk_pct/100))
    funding = {'quantity': None, 'quantityBasis': 'current_funding_estimate', 'budgetCurrency': currency,
               'cashCap': cap, 'cashCapUsd': cap/fx, 'equity': equity, 'cash': cash, 'usdToAccountFx': fx,
               'optionFeePerContractUsd': unit_fee, 'stockFeePerOrder': stock_fee,
               'feesCurrency': 'USD',
               'feesBasis': 'Frozen Practice simulator settings; estimated, not executed fees',
               'reserved': False, 'executionPermission': False, 'asOfMs': clock()}
    out['funding'] = funding
    max_ask = min(policy.contract_policy.max_ask, (cap/fx-unit_fee)/100)
    if max_ask <= 0:
        return {**out, 'status': 'budget_unavailable', 'selectionErrors': ['No positive cash capacity after entry fees']}
    selection_policy = policy.contract_policy.model_copy(update={'max_ask': max_ask})
    funding.update(maxAskUsd=max_ask, maxSpreadPct=selection_policy.max_spread_pct,
                   maxContracts=policy.max_contracts)
    economics = SelectionEconomics(cash_cap_usd=cap/fx, max_units=policy.max_contracts,
                                   entry_fee_per_contract_usd=unit_fee, exit_fee_per_contract_usd=unit_fee)
    request = SelectionRequest(preferred_contract=preferred, deadline_ms=deadline_ms, economics=economics,
                               plan_id=getattr(plan, 'id', None), portfolio_id=policy.portfolio_id, clock=clock)
    selected = await call_selector(choose, engine, plan, selection_policy, request)
    at = clock()
    # Refresh elapsed-time checks without issuing another chain request. Unrefreshed rows carry
    # no quote and are kept as they were reported (never ranked as if they had been observed).
    observed_rows = [c for c in selected.get('candidates', []) if c.get('refreshed', True)]
    refreshed = rank_candidates(plan, selection_policy, observed_rows, at, economics=economics)
    refreshed['candidates'] = refreshed['candidates']+[c for c in selected.get('candidates', []) if not c.get('refreshed', True)]
    selection = {**selected, **refreshed}
    out.update(observedAt=at, selection=selection)
    chosen = selection.get('selected')
    if chosen is None:
        # Only a demonstrably otherwise-eligible inspected contract can support
        # the affordability comparison. A combined premium/spread error alone
        # is not sufficient evidence, and incomplete search remains disclosed.
        otherwise = [c for c in selection.get('candidates', [])
            if c.get('reasons') == ['premium or spread exceeds reviewed limit']
            and finite(c.get('spreadPct')) and c['spreadPct'] <= selection_policy.max_spread_pct
            and finite(c.get('ask')) and c['ask'] > max_ask and c.get('quoteSource') == 'opra'
            and snapshot_quote(engine, c['symbol'], clock)['status'] == 'observed']
        return {**out, 'status': 'awaiting_contract', 'affordabilityOnly': bool(otherwise),
                'affordabilityScope': 'Inspected contracts only; not proof of an exhaustive option chain',
                'selectionErrors': selection.get('warnings', []),
                'affordabilityCandidates': [c['symbol'] for c in otherwise]}
    quote = snapshot_quote(engine, chosen['symbol'], clock)
    out.update(selected=chosen, quote=quote, observedAt=quote['observedAt'])
    if quote['status'] != 'observed':
        return {**out, 'status': 'quote_unavailable', 'selectionErrors': [quote['reason']]}
    spread = (quote['ask']-quote['bid'])/((quote['ask']+quote['bid'])/2)*100
    if quote['ask'] > max_ask or spread > selection_policy.max_spread_pct:
        return {**out, 'status': 'quote_changed', 'selectionErrors': ['Current ask or spread no longer fits the saved selection limits']}
    unit_cost = (quote['ask']*100+unit_fee)*fx
    quantity = min(policy.max_contracts, math.floor(cap/unit_cost), math.floor(quote['askSize']))
    funding.update(quantity=quantity, contract=chosen['symbol'], estimatedDebit=quantity*unit_cost,
                   optionAsk=quote['ask'], displayedAskSize=quote['askSize'])
    return {**out, 'status': 'observed' if quantity >= 1 else 'budget_unavailable',
            'selectionErrors': [] if quantity >= 1 else ['No whole contract fits cash, fees and displayed size']}
