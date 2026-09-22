"""One bounded alternative search for a spread-only refusal on automatic Practice arms."""
from __future__ import annotations

import asyncio
import httpx

from .contracts import SelectionRequest, call_selector, rank_candidates, select_contract, selection_economics
from .execution import ExecutionInput

SETTING = 'techniques.options_cartel.reselect_wide_contract'


async def reselect_for_spread(controller, run_id, row, plan, spec, report, *, choose=None):
    engine = controller.engine
    failures = {c['name'] for c in report.get('checks', []) if c.get('passed') is False}
    book = engine.positions.portfolio(spec.portfolio_id)
    if (failures != {'entry_contract_spread'} or not (report.get('risk') or {}).get('passed')
            or not engine.settings.get(SETTING, True) or row['mode'] != 'auto'
            or spec.instrument != 'options' or spec.contract_policy is None
            or not book or book.get('kind') != 'sim' or book.get('archived')
            or row.get('config', {}).get('preparation', {}).get('workspace', 'practice') != 'practice'
            or not row.get('config', {}).get('preparation')):
        return None
    signal = row['state'].get('signal') or {}
    async with engine.sf() as session, session.begin():
        locked = await controller.repository._locked(session, run_id)
        latest = controller.repository.view(locked)
        controller._entry_conditions(latest, plan, spec)
        if (locked.state.get('attemptTag') or locked.state.get('orderId')
                or (locked.state.get('signal') or {}).get('id') != signal.get('id')
                or (locked.state.get('contractReselection') or {}).get('signalId') == signal.get('id')):
            return None
        claim = {'signalId': signal['id'], 'startedAt': controller.clock(),
                 'oldContract': spec.contract_symbol, 'status': 'searching',
                 'policy': spec.contract_policy.model_dump(mode='json'),
                 'selectionVersion': spec.contract_policy.selection_version,
                 'rankingVersion': spec.contract_policy.ranking_version}
        locked.state = {**locked.state, 'contractReselection': claim}
    # No widened premium/delta limits, extra expiry range, or extra refresh budget.
    cap = min(spec.contract_policy.max_ask, spec.max_premium or spec.contract_policy.max_ask)
    search_policy = spec.contract_policy.model_copy(update={'max_ask': cap,
        'min_abs_delta': max(spec.min_abs_delta, spec.contract_policy.min_abs_delta)})
    deadline = signal['at']+120000
    remaining = (deadline-controller.clock())/1000
    if remaining <= 0:
        return None
    try:
        # The saved contract gets first refresh consideration (F2 item 1), never unconditional
        # selection; the signal deadline bounds the whole search and is never extended.
        request = SelectionRequest(preferred_contract=spec.contract_symbol, deadline_ms=deadline,
            economics=await selection_economics(engine, spec.portfolio_id, budget=spec.budget,
                                                risk_pct=spec.risk_pct, max_units=spec.max_units),
            plan_id=plan.id, portfolio_id=spec.portfolio_id, clock=controller.clock)
        selection = await asyncio.wait_for(call_selector(choose or select_contract, engine, plan, search_policy, request), min(20., remaining))
        candidate = selection.get('selected')
        accepted = rank_candidates(plan, search_policy, [candidate] if candidate else [], controller.clock(),
                                   economics=request.economics)['selected']
        reason = 'No inspected alternative satisfies the saved contract limits.'
    except (ValueError, OSError, TimeoutError, httpx.HTTPError) as exc:
        selection, accepted = {'error': type(exc).__name__}, None
        reason = f'Bounded alternative search unavailable ({type(exc).__name__}).'
    async with engine.sf() as session, session.begin():
        locked = await controller.repository._locked(session, run_id)
        latest = controller.repository.view(locked)
        controller._entry_conditions(latest, plan, spec)
        if (not engine.settings.get(SETTING, True) or locked.state.get('attemptTag') or locked.state.get('orderId')
                or (locked.state.get('signal') or {}).get('id') != signal['id']):
            return None
        updated = spec.model_copy(update={'contract_symbol': accepted['symbol']}) if accepted else None
        if updated:
            # Only the contract identity changes; full preflight follows in the controller.
            locked.config = {**locked.config, 'execution': updated.model_dump(mode='json')}
            reason = f"Rechecked {spec.contract_symbol}; selected {updated.contract_symbol} within the same saved limits. Full entry checks remain required."
        locked.state = {**locked.state, 'contractReselection': {**claim, 'finishedAt': controller.clock(),
            'status': 'selected' if updated else 'unavailable', 'selection': selection,
            'newContract': updated.contract_symbol if updated else None},
            'decisionHistory': [*locked.state.get('decisionHistory', []), {'at': controller.clock(),
                'rule': 'CONTRACT', 'decision': 'contract_reselected' if updated else 'contract_search_unavailable',
                'reason': reason}][-200:]}
        snapshot = controller.repository.view(locked)
    # Preserve any concurrently updated pause/signal state in the live cache.
    runtime = getattr(engine, 'cartel_observer', None)
    cached = getattr(runtime, 'rows', {}).get(run_id)
    if updated and cached and ExecutionInput.model_validate(cached['config'].get('execution') or {}) == spec:
        runtime.rows[run_id] = {**cached, 'config': snapshot['config']}
    await controller.repository._journal(snapshot, 'contract_reselection')
    return (snapshot, updated) if updated else None
