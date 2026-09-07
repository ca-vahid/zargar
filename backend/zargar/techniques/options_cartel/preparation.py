"""Daily market discovery -> reviewed plans -> automatic Practice arming."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import math

import httpx
from sqlalchemy import select

from ... import events as ev
from ...domain import new_id, now_ms
from ...marketstructure.history import UA, fetch_window
from ...marketstructure.market_calendar import is_trading_day
from ...marketstructure.sessions import ET, next_session_date, session_bounds
from ...models import ManagedPositionRow, Portfolio, TechniqueArmed, TechniqueRun
from .automatic_plans import PreparationPolicy, automatic_review, planning_contract
from .collect import normalize_daily
from .discovery import discover_market
from .execution import ExecutionInput
from .industry import save_snapshot
from .industry_feed import capture_industries
from .plans import CartelPlan
from .prepare import build_volume_baseline
from .rules import CartelRules
from .screen import market_regime
from .service import CartelService, FactsInput, MinuteInput, ResearchInput

SETTING = 'techniques.options_cartel.preparation'


async def affordable_contract_policy(engine, portfolio_id, policy):
    book = engine.positions.portfolio(portfolio_id)
    if not book:
        raise ValueError('Practice account valuation is unavailable')
    equity = float(await engine.positions.equity(portfolio_id))
    fx = engine.positions.fx.rate('USD', book.get('baseCurrency', 'USD'))
    if not math.isfinite(equity) or equity <= 0 or fx is None or not math.isfinite(fx) or fx <= 0:
        raise ValueError('Practice equity or currency conversion is unavailable')
    limit = min(policy.contract_policy.max_ask, policy.budget/(100*fx), equity*policy.risk_pct/100/(100*fx))
    return policy.contract_policy.model_copy(update={'max_ask': limit})


async def practice_portfolio(engine, requested=None):
    async with engine.sf() as session:
        if requested:
            row = await session.get(Portfolio, requested)
            if row is None or row.kind != 'sim':
                raise ValueError('Automatic Cartel preparation can arm only a Practice (sim) portfolio')
            return row.id
        rows = (await session.scalars(select(Portfolio).where(Portfolio.kind == 'sim').order_by(Portfolio.id))).all()
    if len(rows) != 1:
        raise ValueError('Choose the Practice portfolio for automatic preparation')
    return rows[0].id


async def run_preparation(engine, policy: PreparationPolicy, *, clock=now_ms, discover=discover_market,
                          industries=capture_industries, fetch=fetch_window, choose=planning_contract, on_started=None):
    started = clock()
    if not policy.enabled:
        raise ValueError('Enable automatic Practice preparation before starting a run')
    day = dt.datetime.fromtimestamp(started/1000, ET).date()
    opens, closes = session_bounds(day.isoformat())
    if is_trading_day(day) and opens <= started < closes:
        raise ValueError('Daily preparation runs before the open or after the close, using completed sessions')
    portfolio_id = await practice_portfolio(engine, policy.portfolio_id)
    runtime = getattr(engine, 'cartel_observer', None)
    if runtime is None or runtime.stopping:
        raise ValueError('Cartel runtime is unavailable')
    service = CartelService(engine)
    target_session = next_session_date(started)
    run_id = new_id()
    result = {'phase': 'discovering', 'session': target_session, 'portfolioId': portfolio_id,
              'mode': 'auto', 'practiceOnly': True, 'rows': [], 'shortlist': [], 'warnings': [],
              'discovered': 0, 'evaluated': 0, 'qualifying': 0, 'armed': 0}
    record = TechniqueRun(id=run_id, technique='options_cartel', symbol='MULTI', mode='preparation',
        primary_tf='1d', trigger='automatic', status='running', verdict='running', as_of=started,
        config={'policy': policy.model_dump(mode='json'), 'session': target_session, 'portfolioId': portfolio_id},
        result=result, tags=['cartel:preparation'])
    async with engine.sf() as session:
        session.add(record); await session.commit()
    if on_started:
        on_started(service._view(record, detail=True))

    async def checkpoint(phase, *, terminal=False, error=None):
        result['phase'] = phase
        async with engine.sf() as session:
            row = await session.get(TechniqueRun, run_id)
            row.result = json.loads(json.dumps(result))
            if terminal:
                row.status = 'failed' if error else 'done'
                row.verdict = 'failed' if error else 'prepared' if result['shortlist'] else 'no_setups'
                row.error = error
                row.finished_at = dt.datetime.now(dt.UTC)
            await session.commit()
            view = service._view(row, detail=True)
        if terminal:
            await engine.journal.append(ev.TECHNIQUE_RUN_FAILED if error else ev.TECHNIQUE_RUN_COMPLETED,
                {'runId': run_id, 'technique': 'options_cartel', 'mode': 'preparation',
                 'phase': phase, 'armed': result['armed'], 'error': error},
                aggregate_type='technique_run', aggregate_id=run_id)
        return view

    try:
        await engine.journal.append(ev.TECHNIQUE_RUN_STARTED,
            {'runId': run_id, 'technique': 'options_cartel', 'mode': 'preparation',
             'portfolioId': portfolio_id, 'session': target_session},
            aggregate_type='technique_run', aggregate_id=run_id)
        # Refresh only unused automatic arms. Paused plans express user intent;
        # working entries and held positions retain their existing protection.
        result['replacedPlans'] = []
        for old_id in list(runtime.rows):
            async with runtime.controller._guard(old_id):
                old = runtime.rows[old_id]
                if old['portfolioId'] != portfolio_id or not old.get('config', {}).get('preparation') \
                        or old['status'] != 'armed' or old['state'].get('attemptTag'):
                    continue
                if runtime._positions(old_id):
                    continue
                await runtime.disarm(old_id, reason='daily preparation refresh')
                result['replacedPlans'].append(old_id)
        await checkpoint('discovering')
        rules = CartelRules.for_profile(policy.profile)
        universe = await discover(rules, clock=clock)
        result['discovered'] = len(universe['rows'])
        result['discovery'] = {k: universe[k] for k in ('providerTotal', 'received', 'complete', 'excluded', 'observedAt', 'inputSha256')}
        industry, industry_raw = await industries(clock=clock)
        captured = await save_snapshot(service, industry, now_ms=clock())
        result['industrySnapshotId'] = captured['runId']
        at = clock()
        async with engine.sf() as session:
            row = await session.get(TechniqueRun, run_id)
            row.as_of = at
            row.config = {**row.config, 'discoverySnapshot': universe, 'industryPublication': industry_raw}
            await session.commit()
        await checkpoint('market_context')
        async with httpx.AsyncClient(headers={'User-Agent': UA}, timeout=30.) as client:
            indices = {}
            for symbol in ('SPY', 'QQQ'):
                indices[symbol] = normalize_daily(await fetch(symbol, '1d', at-550*86_400_000, at, client=client), symbol, at)
            regime = market_regime(indices, rules, at)
            result['market'] = regime
            direction = regime['direction']
            if direction not in ('long', 'short'):
                result['warnings'].append('SPY and QQQ do not establish an aligned trend; no new plans armed.')
                return await checkpoint('no_market_alignment', terminal=True)
            eligible = [r for r in universe['rows'] if rules.volume_basis != 'last_session' or
                        r['dailyVolume'] is not None and r['dailyVolume'] > rules.min_volume]
            result['liquidityCandidates'] = len(eligible)
            result['notEvaluated'] = max(0, len(eligible)-policy.history_limit)
            if result['notEvaluated']:
                result['warnings'].append(f"History budget evaluates the first {policy.history_limit} volume-ranked listings; {result['notEvaluated']} remain outside this run.")
            pool = []
            for listing in eligible[:policy.history_limit]:
                if runtime.stopping:
                    raise asyncio.CancelledError()
                symbol = listing['symbol']
                try:
                    history = normalize_daily(await fetch(symbol, '1d', at-550*86_400_000, at, client=client), symbol, at)
                    facts = FactsInput(symbol=symbol, observed_at=listing['observedAt'], source=listing['source'],
                        market_cap=listing['marketCap'], cap_observed_at=listing['observedAt'],
                        cap_data_as_of_ms=listing['sourceBarOpenAt'], fundamentals_snapshot_id=run_id, industry=listing['industry'],
                        membership_observed_at=listing['observedAt'], membership_source='TradingView primary listing classification')
                    research = ResearchInput(history=history, indices=indices, facts=facts, rules=rules,
                        parameters=policy.setups, as_of_ms=at, direction=direction, data_source=listing['source'],
                        industry_snapshot_id=captured['runId'])
                    saved = await service.analyze(research, parent_run_id=run_id)
                    review = automatic_review(saved['config']['inputs'], saved['result']['analysis'], policy)
                    entry = {'symbol': symbol, 'analysisId': saved['runId'], 'status': 'candidate' if review else 'filtered',
                             'reasons': [g['label'] for g in saved['result']['screen']['gates'] if g['status'] != 'pass']}
                    if review:
                        result['qualifying'] += 1
                        pool.append((saved, review))
                except (ValueError, httpx.HTTPError, OSError) as exc:
                    entry = {'symbol': symbol, 'status': 'data_error', 'reason': str(exc)[:600]}
                result['rows'].append(entry); result['evaluated'] += 1
                await checkpoint('evaluating')
            # Discovery volume order is retained; choose one measured setup per name.
            for saved, review in pool:
                if len(result['shortlist']) >= policy.focus_count:
                    break
                symbol = saved['symbol']
                async with engine.sf() as session:
                    existing = await session.scalar(select(TechniqueArmed).where(
                        TechniqueArmed.technique == 'options_cartel', TechniqueArmed.portfolio_id == portfolio_id,
                        TechniqueArmed.symbol == symbol, TechniqueArmed.status.in_(('armed', 'paused', 'closing'))))
                    held = await session.scalar(select(ManagedPositionRow).where(ManagedPositionRow.technique == 'options_cartel',
                        ManagedPositionRow.portfolio_id == portfolio_id, ManagedPositionRow.symbol == symbol,
                        ManagedPositionRow.status != 'closed'))
                if existing or held:
                    result['shortlist'].append({'symbol': symbol, 'status': 'already_managed', 'planId': existing.run_id if existing else held.run_id})
                    continue
                try:
                    minutes = await fetch(symbol, '1m', at-19*86_400_000, at, client=client)
                    baseline = build_volume_baseline(minutes, symbol, review.entry_policy.timeframe_minutes, at)
                    if not baseline['baselines']:
                        raise ValueError('No supported same-time volume baseline; plan cannot be armed')
                    inputs = ResearchInput.model_validate(saved['config']['inputs']).model_copy(update={
                        'minute_history': [MinuteInput(symbol=b.symbol, ts=b.ts, open=b.open, high=b.high,
                            low=b.low, close=b.close, volume=b.volume) for b in minutes if b.ts+60_000 <= at]})
                    enriched = await service.analyze(inputs, parent_run_id=run_id)
                    key = hashlib.sha256(f'{target_session}:{portfolio_id}:{symbol}:{at}'.encode()).hexdigest()[:32]
                    plan_record = await service.prepare(enriched['runId'], review, plan_id=key,
                        preparation={'runId': run_id, 'session': target_session, 'portfolioId': portfolio_id, 'reviewer': 'automatic_rules'})
                    plan = CartelPlan.model_validate(plan_record['result']['plan']['plan'])
                    selected = await choose(engine, plan, await affordable_contract_policy(engine, portfolio_id, policy))
                    row = {'symbol': symbol, 'planId': plan.id, 'setup': plan.setup, 'trigger': plan.trigger,
                           'invalidation': plan.invalidation, 'targets': list(plan.targets), 'selection': selected,
                           'status': 'awaiting_contract'}
                    if selected['selected']:
                        current = PreparationPolicy.model_validate(engine.settings.get(SETTING, {}))
                        if current != policy or not current.enabled:
                            raise ValueError('Preparation configuration changed before arming; rerun with current settings')
                        await practice_portfolio(engine, portfolio_id)  # recheck identity immediately before arming
                        spec = ExecutionInput(portfolio_id=portfolio_id, mode='auto', instrument='options',
                            contract_symbol=selected['selected']['symbol'], budget=policy.budget, risk_pct=policy.risk_pct,
                            max_units=policy.max_contracts, overnight_ack=True, allow_live=False)
                        await runtime.arm(plan.id, {'mode': 'auto', 'portfolioId': portfolio_id, 'execution': spec.model_dump(),
                            'clientKind': 'desktop', 'preparation': {'runId': run_id, 'practiceOnly': True,
                                'validUntil': min(at+86_400_000, session_bounds(plan.last_session.isoformat())[1])}})
                        row['status'] = 'armed'; result['armed'] += 1
                    result['shortlist'].append(row)
                except (ValueError, httpx.HTTPError, OSError) as exc:
                    result['rows'].append({'symbol': symbol, 'status': 'plan_blocked', 'reason': str(exc)[:600]})
                await checkpoint('preparing_plans')
        return await checkpoint('complete', terminal=True)
    except BaseException as exc:
        result['warnings'].append(f'{type(exc).__name__}: preparation interrupted; saved plans and execution are preserved.')
        await checkpoint('interrupted', terminal=True, error=f'{type(exc).__name__}: preparation interrupted')
        raise


async def preparation_status(engine):
    policy = PreparationPolicy.model_validate(engine.settings.get(SETTING, {}))
    async with engine.sf() as session:
        row = await session.scalar(select(TechniqueRun).where(TechniqueRun.technique == 'options_cartel',
            TechniqueRun.mode == 'preparation').order_by(TechniqueRun.created_at.desc()).limit(1))
    latest = None if row is None else {**CartelService._view(row), 'error': row.error,
                                     'result': json.loads(json.dumps(row.result))}
    if latest:
        ids = [r['planId'] for r in latest['result'].get('shortlist', []) if r.get('planId')]
        async with engine.sf() as session:
            arms = (await session.scalars(select(TechniqueArmed).where(TechniqueArmed.run_id.in_(ids),
                TechniqueArmed.technique == 'options_cartel'))).all() if ids else []
        states = {a.run_id: a.status for a in arms}
        for item in latest['result'].get('shortlist', []):
            if item.get('planId') in states:
                item['status'] = states[item['planId']]
        latest['result']['armed'] = sum(r['status'] == 'armed' for r in latest['result'].get('shortlist', []))
    return {'configuration': policy.model_dump(mode='json', by_alias=True), 'latest': latest,
            'quoteRefresh': getattr(getattr(engine, 'cartel_observer', None), 'preparation_quote_status', {}),
            'activation': getattr(engine, '_cartel_preparation_activation', {})}


async def activate_pending(engine, *, clock=now_ms, choose=planning_contract):
    now = clock()
    day = dt.datetime.fromtimestamp(now/1000, ET).date()
    opens, closes = session_bounds(day.isoformat())
    if not is_trading_day(day) or not opens-45*60_000 <= now < closes:
        return
    running = getattr(engine, '_cartel_preparation_task', None)
    if running is not None and not running.done():
        return
    policy = PreparationPolicy.model_validate(engine.settings.get(SETTING, {}))
    if not policy.enabled:
        return
    runtime = getattr(engine, 'cartel_observer', None)
    if runtime is None or runtime.stopping:
        return
    async with engine.sf() as session:
        row = await session.scalar(select(TechniqueRun).where(TechniqueRun.technique == 'options_cartel',
            TechniqueRun.mode == 'preparation', TechniqueRun.status == 'done').order_by(TechniqueRun.created_at.desc()).limit(1))
    if row is None or row.config.get('policy') != policy.model_dump(mode='json'):
        return
    service = CartelService(engine)
    portfolio_id = await practice_portfolio(engine, row.config['portfolioId'])
    statuses = {}
    for item in row.result.get('shortlist', []):
        if item.get('status') != 'awaiting_contract' or not item.get('planId'):
            continue
        async with engine.sf() as session:
            existing = await session.scalar(select(TechniqueArmed).where(TechniqueArmed.technique == 'options_cartel',
                TechniqueArmed.portfolio_id == portfolio_id, TechniqueArmed.symbol == item['symbol'],
                TechniqueArmed.status.in_(('armed', 'paused', 'closing'))))
            held = await session.scalar(select(ManagedPositionRow).where(
                ManagedPositionRow.technique == 'options_cartel', ManagedPositionRow.portfolio_id == portfolio_id,
                ManagedPositionRow.symbol == item['symbol'], ManagedPositionRow.status != 'closed'))
        if existing or held:
            continue
        try:
            record = await service._load(item['planId'])
            plan = CartelPlan.model_validate(record.result['plan']['plan'])
            valid_until = min(row.as_of+86_400_000, session_bounds(plan.last_session.isoformat())[1])
            if now >= valid_until:
                statuses[plan.id] = 'Preparation evidence expired; next preparation run must rebuild the plan'
                continue
            selection = await choose(engine, plan, await affordable_contract_policy(engine, portfolio_id, policy))
            if not selection['selected']:
                statuses[plan.id] = 'Waiting for an option contract meeting the configured DTE, delta, liquidity and premium limits'
                continue
            current = PreparationPolicy.model_validate(engine.settings.get(SETTING, {}))
            if not current.enabled or current != policy or runtime.stopping:
                break
            await practice_portfolio(engine, portfolio_id)
            spec = ExecutionInput(portfolio_id=portfolio_id, mode='auto', instrument='options',
                contract_symbol=selection['selected']['symbol'], budget=policy.budget, risk_pct=policy.risk_pct,
                max_units=policy.max_contracts, overnight_ack=True, allow_live=False)
            await runtime.arm(plan.id, {'mode': 'auto', 'portfolioId': portfolio_id, 'execution': spec.model_dump(),
                'clientKind': 'desktop', 'preparation': {'runId': row.id, 'practiceOnly': True, 'validUntil': valid_until}})
            statuses[plan.id] = 'armed'
        except Exception as exc:  # noqa: BLE001 - expose retry state without interrupting execution
            statuses[item['planId']] = f'{type(exc).__name__}: option preparation remains pending'
    engine._cartel_preparation_activation = {'at': now, 'plans': statuses}


async def submit_preparation(engine, *, scheduled=False, **kwargs):
    lock = getattr(engine, '_cartel_preparation_submit_lock', None)
    if lock is None:
        lock = engine._cartel_preparation_submit_lock = asyncio.Lock()
    async with lock:
        return await _submit_preparation(engine, scheduled=scheduled, **kwargs)


async def _submit_preparation(engine, *, scheduled=False, **kwargs):
    if getattr(getattr(engine, 'cartel_observer', None), 'stopping', False):
        return {'status': 'stopping'}
    running = getattr(engine, '_cartel_preparation_task', None)
    if running is not None and not running.done():
        return await asyncio.shield(engine._cartel_preparation_ready)
    policy = PreparationPolicy.model_validate(engine.settings.get(SETTING, {}))
    if not policy.enabled:
        if scheduled:
            return {'status': 'disabled'}
        raise ValueError('Automatic Practice preparation is disabled')
    await practice_portfolio(engine, policy.portfolio_id)
    if scheduled:
        now = kwargs.get('clock', now_ms)()
        if not is_trading_day(dt.datetime.fromtimestamp(now/1000, ET).date()):
            return {'status': 'non_trading_day'}
        async with engine.sf() as session:
            latest = await session.scalar(select(TechniqueRun).where(TechniqueRun.technique == 'options_cartel',
                TechniqueRun.mode == 'preparation', TechniqueRun.status == 'done').order_by(TechniqueRun.created_at.desc()).limit(1))
        if latest and latest.config.get('session') == next_session_date(now) and 0 <= now-latest.as_of < 12*3_600_000:
            return {'status': 'already_prepared', 'runId': latest.id}
    ready = asyncio.get_running_loop().create_future()
    ready.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
    engine._cartel_preparation_ready = ready
    def started(row):
        if not ready.done():
            ready.set_result(row)
    task = asyncio.create_task(run_preparation(engine, policy, on_started=started, **kwargs), name='cartel-daily-preparation')
    engine._cartel_preparation_task = task
    def done(worker):
        if worker.cancelled():
            if not ready.done(): ready.cancel()
        else:
            error = worker.exception()
            if error and not ready.done(): ready.set_exception(error)
    task.add_done_callback(done)
    return await asyncio.shield(ready)


async def stop_preparation(engine):
    task = getattr(engine, '_cartel_preparation_task', None)
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    runtime = getattr(engine, 'cartel_observer', None)
    activation = getattr(runtime, 'preparation_activation_task', None)
    if activation is not None and not activation.done() and activation is not asyncio.current_task():
        activation.cancel()
        await asyncio.gather(activation, return_exceptions=True)


async def recover_interrupted_preparations(engine):
    active = getattr(engine, '_cartel_preparation_task', None)
    if active is not None and not active.done():
        return
    async with engine.sf() as session, session.begin():
        rows = (await session.scalars(select(TechniqueRun).where(TechniqueRun.technique == 'options_cartel',
            TechniqueRun.mode == 'preparation', TechniqueRun.status == 'running'))).all()
        for row in rows:
            row.status, row.verdict = 'failed', 'interrupted'
            row.error = 'Runtime restarted during preparation; published plans remain preserved'
            row.finished_at = dt.datetime.now(dt.UTC)
            row.result = {**row.result, 'phase': 'interrupted'}
