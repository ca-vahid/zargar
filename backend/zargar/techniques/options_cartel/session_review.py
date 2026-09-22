"""Account-scoped as-of outcomes, distinct from signals and research."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from ...domain import now_ms
from ...marketstructure.sessions import ET, session_bounds
from ...models import (
    CartelOptionQuote,
    Event,
    Execution,
    ExecutionEvidence,
    ManagedPositionRow,
    Order,
    Portfolio,
    TechniqueArmed,
    TechniqueRun,
)
from .data_quality import evidence
from .preparation_attempts import attempt_page
from .review_ledger import summarize_fills


async def report(engine, portfolio_id, day):
    if dt.date.fromisoformat(day) > dt.datetime.now(ET).date():
        raise ValueError('Choose a completed or current session, not a future date')
    _, close = session_bounds(day)
    cutoff_ms = min(now_ms(), close)
    cutoff = dt.datetime.fromtimestamp(cutoff_ms/1000, dt.UTC)
    begins = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(), ET).astimezone(dt.UTC)
    async with engine.sf() as session:
        book = await session.get(Portfolio, portfolio_id)
        if book is None:
            raise ValueError('Review account not found')
        orders = (await session.scalars(select(Order).where(Order.portfolio_id == portfolio_id,
            Order.technique == 'options_cartel', Order.created_at <= cutoff))).all()
        fills = (await session.execute(select(Execution, Order).join(Order, Order.id == Execution.order_id).where(
            Order.portfolio_id == portfolio_id, Order.technique == 'options_cartel', Execution.ts <= cutoff))).all()
        arms = (await session.scalars(select(TechniqueArmed).where(TechniqueArmed.technique == 'options_cartel',
            TechniqueArmed.portfolio_id == portfolio_id))).all()
        managed = (await session.scalars(select(ManagedPositionRow).where(ManagedPositionRow.technique == 'options_cartel',
            ManagedPositionRow.portfolio_id == portfolio_id, ManagedPositionRow.created_at <= cutoff))).all()
        preparations = (await session.scalars(select(TechniqueRun).where(TechniqueRun.technique == 'options_cartel',
            TechniqueRun.mode == 'preparation', TechniqueRun.config['portfolioId'].as_string() == portfolio_id,
            TechniqueRun.config['session'].as_string() == day, TechniqueRun.created_at <= cutoff)
            .order_by(TechniqueRun.created_at.desc()))).all()
        fill_ids = [f.id for f, _ in fills if f.ts >= begins]
        receipts = (await session.scalars(select(ExecutionEvidence).where(
            ExecutionEvidence.execution_id.in_(fill_ids)))).all() if fill_ids else []
        plan_runs = (await session.execute(select(TechniqueRun.id, TechniqueRun.result['plan']['plan']).where(
            TechniqueRun.id.in_([a.run_id for a in arms])))).all()
        plans = dict(plan_runs)
        waits = (await session.scalars(select(Event).where(Event.type == 'SimFillWaiting',
            Event.portfolio_id == portfolio_id, Event.ts >= begins, Event.ts <= cutoff,
            Event.aggregate_id.in_([o.id for o in orders])).order_by(Event.ts))).all()
    async with engine.sf() as session:
        preflights = (await session.scalars(select(Event).where(
            Event.type == 'TechniqueCartelPreflight', Event.portfolio_id == portfolio_id,
            Event.ts >= begins, Event.ts <= cutoff).order_by(Event.ts, Event.id))).all()
    execution_checks = {}
    for event in preflights:
        body = event.payload or {}; read = body.get('report') or {}
        failures = [c for c in read.get('checks', []) if c.get('passed') is False]
        failures += [dict(c, reason=c.get('detail') or c.get('name'))
                     for c in (read.get('risk') or {}).get('checks', []) if c.get('passed') is False]
        execution_checks.setdefault(body.get('runId'), []).append({
            'at': int(event.ts.timestamp()*1000), 'passed': read.get('passed'),
            'reasons': [c.get('reason') or c.get('name') for c in failures],
            'checks': failures, 'expression': read.get('expression'), 'eventId': event.id})
    ownership = {a.state.get('orderId'): a.run_id for a in arms if a.state.get('orderId')}
    arm_orders = {a.run_id: a.state.get('orderId') for a in arms if a.state.get('orderId')}
    for p in managed:
        plan_id = (p.config or {}).get('runId')
        for item in [*p.legs, *p.state.get('exits', [])]:
            oid = item.get('entryOrderId') or item.get('orderId')
            if oid and plan_id:
                ownership[oid] = plan_id
        for order in orders:
            if any(tag.startswith(f'managed_exit:{p.id}:') for tag in (order.tags or [])):
                ownership[order.id] = plan_id
    assets, issues = summarize_fills(fills, begins, cutoff, ownership)
    attempts = await attempt_page(engine, portfolio_id, day, cutoff_ms)
    accounting_complete = not issues
    if any(a['planId'] is None for a in assets):
        issues.append('Some executions have no campaign link; account totals include them but campaign counts cannot attribute them')
    async with engine.sf() as session:
        for asset in assets:
            asset.update(mark=None, unrealizedNet=None)
            if not asset['remainingQty']:
                asset['unrealizedNet'] = 0.
                continue
            quote = await session.scalar(select(CartelOptionQuote).where(
                CartelOptionQuote.contract == asset['symbol'], CartelOptionQuote.available_at <= cutoff_ms,
                CartelOptionQuote.run_id.in_([a.run_id for a in arms]))
                .order_by(CartelOptionQuote.available_at.desc(), CartelOptionQuote.id.desc()).limit(1))
            if quote and quote.source_at and 0 <= cutoff_ms-quote.source_at <= 15_000 and not quote.delayed and not quote.halted and 0 < quote.bid <= quote.ask:
                asset['mark'] = {'bid': quote.bid, 'source': quote.source, 'sourceAt': quote.source_at, 'availableAt': quote.available_at}
                asset['unrealizedNet'] = asset['remainingQty']*quote.bid*(100 if asset['secType'] == 'OPT' else 1)-asset['remainingCost']-asset['openEntryFees']
            else:
                issues.append(f"{asset['symbol']}: no source-qualified mark at the review cutoff")
    rows = []
    for arm in arms:
        owned_positions = [p for p in managed if (p.config or {}).get('runId') == arm.run_id]
        related = [a for a in assets if a['planId'] == arm.run_id]
        if arm.state.get('day') != day and not related:
            continue
        trace = [d for d in arm.state.get('decisionHistory', []) if d.get('at', 0) <= cutoff_ms]
        kinds = {d.get('decision') for d in trace}
        from .opportunity_status import opportunity_status
        from .plans import CartelPlan
        from .review_attribution import attribute, category_from
        checks = execution_checks.get(arm.run_id, [])
        latest_check = checks[-1] if checks else None
        plan_model = CartelPlan.model_validate(plans[arm.run_id]) if plans.get(arm.run_id) else None
        opportunity = opportunity_status(plan_model, arm.state, day, cutoff_ms) if plan_model else None
        if plan_model:
            # F1 (2026-09-21): the category follows the first KNOWN blocker; a prior data refusal no
            # longer hides a measured confirmation refusal, and unknown windows stay unknown.
            entry_orders = [{'id': o.id, 'qty': o.qty, 'filledQty': o.filled_qty or 0., 'status': o.status, 'createdAt': int(o.created_at.timestamp()*1000) if o.created_at else None}
                            for o in orders if o.side == 'BUY' and ownership.get(o.id) == arm.run_id]
            attribution = attribute(plan_model, arm.state, day, cutoff_ms, checks=checks, assets=related, opportunity=opportunity,
                                    entry_orders=entry_orders)
            category = category_from(attribution, opportunity, kinds, related)
        else:
            attribution = None
            category = ('open' if related and any(a['remainingQty'] for a in related) else 'closed' if related else
                'invalidated' if 'invalidated' in kinds else 'signalled' if 'triggered' in kinds or 0 < (arm.state.get('signal') or {}).get('at', 0) <= cutoff_ms else
                'data_limited' if kinds & {'unsupported_volume_period', 'untrusted_confirmation', 'missing_bucket'} else
                'strategy_rejected' if 'watch_only' in kinds else 'no_trigger')
            last_signal_at = max((d.get('at', 0) for d in trace if d.get('decision') == 'triggered'), default=0)
            if not related and latest_check and latest_check['passed'] is False and latest_check['at'] >= last_signal_at:
                category = 'execution_rejected'
        actual_exit_ids = {f.order_id for f,o in fills if o.side == 'SELL'}
        exit_reasons = [e.get('reason') or e.get('kind') for p in owned_positions
            for e in p.state.get('exits', []) if e.get('orderId') in actual_exit_ids]
        from .cadence import control_summary
        cadence = {'executing': (plans.get(arm.run_id) or {}).get('cadence_version') or (arm.config.get('cadence') or {}).get('executing'),
                   'executingTimeframeMinutes': plan_model.entry.timeframe_minutes if plan_model else None,
                   'control': control_summary(arm.config.get('cadence'), arm.state.get('control'), cutoff_ms),
                   'executingSignalAt': (arm.state.get('signal') or {}).get('at') if 0 < (arm.state.get('signal') or {}).get('at', 0) <= cutoff_ms else None}
        rows.append({'planId': arm.run_id, 'symbol': arm.symbol, 'status': category, 'category': category,
            'opportunity': opportunity, 'attribution': attribution, 'cadence': cadence,
            'executionChecks': checks, 'latestExecutionCheck': latest_check,
            'decisions': trace, 'assets': related, 'exitReasons': exit_reasons,
            'dataEvidence': evidence({k:v for k,v in arm.state.get('minutes', {}).items() if int(k) < cutoff_ms}),
            'lastObservedMinute': min(arm.state.get('lastMinute') or 0, cutoff_ms),
            'recoveries': [r for r in arm.state.get('observationRecoveries', []) if r.get('day') == day and r.get('at', 0) <= cutoff_ms],
            'executionPolicy': arm.config.get('execution', {}),
            'campaigns': [p.config.get('policy', {}).get('cartel', {}).get('campaign') for p in owned_positions]})
    prep = preparations[0] if preparations else None
    candidates = []
    if prep:
        if prep.result.get('updatedAt', 0) > cutoff_ms:
            issues.append('Preparation projection was updated after this cutoff; timestamped attempts are the historical evidence')
        for item in [*prep.result.get('shortlist', []), *prep.result.get('rows', [])]:
            if item.get('status') in ('plan_blocked', 'data_error', 'awaiting_contract', 'market_blocked', 'expired'):
                candidates.append({**item, 'status': 'expired' if cutoff_ms >= close and item.get('status') == 'awaiting_contract' else item.get('status')})
    daily_orders = [o for o in orders if o.created_at >= begins]
    daily_fills = [(f,o) for f,o in fills if f.ts >= begins]
    currencies = {'CAD' if a['symbol'].endswith(('.TO', '.V')) else 'USD' for a in assets}
    if currencies and currencies != {book.base_currency}:
        issues.append('Native-currency outcomes are not converted; no historical FX evidence supplied')
    totals = {key: sum(a[key] for a in assets) for key in ('grossRealized', 'realizedFees', 'netRealized', 'feesPaidToday')}
    controls = [r['cadence']['control'] for r in rows if r['cadence'].get('control')]
    cadence_comparison = {'executing': {}, 'placesOrders': False,
        'note': 'Actual fills and after-cost results belong to the executing cadence only; the matched control has no orders, fills or modeled P&L.'}
    for r in rows:
        label = r['cadence'].get('executing') or 'unlabelled'
        bucket = cadence_comparison['executing'].setdefault(label, {'plans': 0, 'signals': 0, 'entryOrders': 0, 'filledEntries': 0, 'netRealized': 0.})
        bucket['plans'] += 1
        bucket['signals'] += 1 if r['cadence'].get('executingSignalAt') else 0
        bucket['entryOrders'] += 1 if arm_orders.get(r['planId']) else 0
        bucket['filledEntries'] += 1 if any(a.get('entryOrders') for a in r['assets']) else 0
        bucket['netRealized'] += sum(a.get('netRealized', 0) for a in r['assets'])
    if controls:
        cadence_comparison['control'] = {'cadence': controls[0]['control'], 'plans': len(controls),
            'signals': sum(c['controlSignals'] for c in controls), 'plansWithSignal': sum(1 for c in controls if c['controlSignals']),
            'entryOrders': 0, 'filledEntries': 0, 'netRealized': None, 'basis': 'observation only'}
    return {'schemaVersion': 2, 'session': day, 'asOfMs': cutoff_ms, 'portfolioId': portfolio_id, 'cadenceComparison': cadence_comparison,
        'account': book.name, 'baseCurrency': book.base_currency, 'rows': rows, 'assets': assets,
        'totals': totals if accounting_complete and (not currencies or currencies == {book.base_currency}) else None,
        'closedCampaigns': sum(r['category'] == 'closed' for r in rows),
        'openInstruments': sum(a['remainingQty'] > 0 for a in assets),
        'orderCount': len(daily_orders), 'filledOrders': len({f.order_id for f,_ in daily_fills}),
        'entryOrders': len({f.order_id for f,o in daily_fills if o.side == 'BUY'}),
        'exitOrders': len({f.order_id for f,o in daily_fills if o.side == 'SELL'}),
        'rejectedOrders': [{'orderId':o.id, 'symbol':o.symbol, 'reason':o.reject_reason} for o in daily_orders if o.reject_reason],
        'candidates': candidates, 'preparationId': prep.id if prep else None,
        'attempts': attempts['rows'], 'attemptCount': attempts['total'], 'attemptCursor': attempts['nextCursor'],
        'fillEvidence': [{'executionId':e.execution_id, **e.evidence} for e in receipts],
        'missingFillEvidence': len(fill_ids)-len(receipts), 'issues':issues, 'placesOrders':False,
        'fillWaits': [{'orderId': e.aggregate_id, 'at': int(e.ts.timestamp()*1000), **e.payload,
                      'subsequentlyFilled': any(f.order_id == e.aggregate_id for f,_ in fills)} for e in waits],
        'note':'Actual executions and recorded fees. Open marks require source-qualified cutoff evidence; recovered bars do not prove timely delivery.'}
