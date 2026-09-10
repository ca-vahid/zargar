"""Daily market discovery -> reviewed plans -> workspace-scoped automatic arming."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import math
import time

import httpx
from sqlalchemy import select

from ... import events as ev
from ...domain import new_id, now_ms
from ...marketstructure.history import UA, fetch_window
from ...marketstructure.market_calendar import is_trading_day
from ...marketstructure.sessions import ET, next_session_date, session_bounds
from ...models import ManagedPositionRow, Portfolio, TechniqueArmed, TechniqueRun
from .accounts import default_practice_book, is_archived, validate_account
from .automatic_plans import PreparationPolicy, automatic_review, planning_contract
from .breadth import read_breadth
from .discovery import discover_market
from .execution import ExecutionInput
from .industry import IndustrySnapshot, read_industry, save_snapshot
from .industry_feed import capture_industries
from .plans import CartelPlan
from .preparation_io import DATA_ERRORS, PreparationHistory, observed_work, rate_limited
from .preparation_readiness import baseline_coverage, entry_readiness, load_session_context
from .preparation_scope import SETTING as SETTING  # noqa: PLC0414 - preserve the existing public constant
from .preparation_scope import (
    read_policy,
    require_execution_scope,
    workspace_filter,
)
from .prepare import build_volume_baseline
from .quality import quality_key, ranking_evidence, target_room
from .rules import CartelRules
from .screen import market_regime
from .service import CartelService, FactsInput, MinuteInput, ResearchInput


async def affordable_contract_policy(engine, portfolio_id, policy):
    book = engine.positions.portfolio(portfolio_id)
    if not book:
        raise ValueError('Account valuation is unavailable')
    equity = float(await engine.positions.equity(portfolio_id))
    fx = engine.positions.fx.rate('USD', book.get('baseCurrency', 'USD'))
    if not math.isfinite(equity) or equity <= 0 or fx is None or not math.isfinite(fx) or fx <= 0:
        raise ValueError('Account equity or currency conversion is unavailable')
    limit = min(policy.contract_policy.max_ask, policy.budget/(100*fx), equity*policy.risk_pct/100/(100*fx))
    return policy.contract_policy.model_copy(update={'max_ask': limit})


async def preparation_portfolio(engine, requested=None, workspace='practice'):
    dedicated = default_practice_book(engine) if workspace == 'practice' else ''
    if dedicated:
        if requested and requested != dedicated:
            raise ValueError('Cartel must use its configured dedicated Practice book')
        requested = dedicated
    kinds = ('sim',) if workspace == 'practice' else ('live', 'paper')
    async with engine.sf() as session:
        if requested:
            row = await session.get(Portfolio, requested)
            if row is None or row.kind not in kinds:
                raise ValueError(f'Choose a {workspace.title()} account for this preparation workspace')
            validate_account(engine, row)
            return row.id
        rows = (await session.scalars(select(Portfolio).where(Portfolio.kind.in_(kinds)).order_by(Portfolio.id))).all()
        rows = [r for r in rows if not is_archived(engine, r)]
    if workspace == 'live' or len(rows) != 1:
        raise ValueError(f'Choose the {workspace.title()} account explicitly for automatic preparation')
    return rows[0].id


async def practice_portfolio(engine, requested=None):
    return await preparation_portfolio(engine, requested, 'practice')


def resumable(row, policy, now):
    return bool(row.technique == 'options_cartel' and row.mode == 'preparation'
        and row.config.get('coverageVersion') == 4
        and row.status in ('done', 'failed') and row.result.get('resumeReady')
        and (row.status == 'failed' or row.result.get('dataErrors', 0) > 0 or row.result.get('planErrors', 0) > 0)
        and row.config.get('workspace', 'practice') == policy.workspace
        and PreparationPolicy.model_validate(row.config.get('policy', {})) == policy
        and 0 <= now-row.as_of < 86_400_000 and row.config.get('session') == next_session_date(now))


def evaluation_row(saved, review, policy=None):
    checks = [*saved['result']['screen']['gates'], *saved['result']['analysis'].get('checks', [])]
    reasons = list(dict.fromkeys(g.get('label') or g.get('name') or 'Unspecified check' for g in checks if g['status'] != 'pass'))
    if not review and policy:
        for c in saved['result']['analysis'].get('candidates', []):
            if c.get('targets') and (c.get('contextPassed') or c.get('researchContextPassed')):
                room = target_room(c['trigger'], c['invalidation'], c['targets'][0])
                if room['firstTargetPct'] < policy.min_target_distance_pct:
                    reasons.append(f"{c['setup']}: first target distance {room['firstTargetPct']:.3f}% is below the configured {policy.min_target_distance_pct:g}% minimum; nearby resistance retained.")
    if not review and not reasons:
        reasons = ['No qualifying measured setup with valid targets and sufficient configured target distance']
    return {'symbol': saved['symbol'], 'analysisId': saved['runId'],
            'status': 'candidate' if review else 'filtered', 'reasons': reasons}


async def run_preparation(engine, policy: PreparationPolicy, *, clock=now_ms, discover=discover_market,
                          industries=capture_industries, fetch=fetch_window, choose=planning_contract, on_started=None, resume_run_id=None):
    started = clock()
    if not policy.enabled:
        raise ValueError('Enable automatic preparation before starting a run')
    require_execution_scope(engine, policy)
    day = dt.datetime.fromtimestamp(started/1000, ET).date()
    opens, closes = session_bounds(day.isoformat())
    if is_trading_day(day) and opens <= started < closes:
        raise ValueError('Daily preparation runs before the open or after the close, using completed sessions')
    portfolio_id = await preparation_portfolio(engine, policy.portfolio_id, policy.workspace)
    runtime = getattr(engine, 'cartel_observer', None)
    if runtime is None or runtime.stopping:
        raise ValueError('Cartel runtime is unavailable')
    service = CartelService(engine)
    target_session = next_session_date(started)
    prior = await service._load(resume_run_id) if resume_run_id else None
    if prior and not resumable(prior, policy, started):
        raise ValueError('This preparation cannot be resumed with current settings or expired evidence; start a fresh run')
    run_id = new_id()
    result = {'phase': 'discovering', 'session': target_session, 'portfolioId': portfolio_id,
              'mode': 'auto', 'workspace': policy.workspace, 'practiceOnly': policy.workspace == 'practice', 'rows': [], 'shortlist': [], 'warnings': [],
              'discovered': 0, 'evaluated': 0, 'qualifying': 0, 'armed': 0, 'processed': 0, 'dataErrors': 0,
              'startedAt': started, 'updatedAt': started, 'message': 'Starting market discovery', 'currentSymbol': None,
              'cacheHits': 0, 'historyRequests': 0, 'resumedFrom': resume_run_id, 'resumedAnalyses': 0, 'prefiltered': 0, 'planErrors': 0}
    record = TechniqueRun(id=run_id, technique='options_cartel', symbol='MULTI', mode='preparation',
        parent_run_id=resume_run_id, primary_tf='1d', trigger='automatic', status='running', verdict='running', as_of=started,
        config={'coverageVersion': 4, 'workspace': policy.workspace, 'policy': policy.model_dump(mode='json'), 'session': target_session, 'portfolioId': portfolio_id},
        result=result, tags=['cartel:preparation'])
    async with engine.sf() as session:
        session.add(record); await session.commit()
    if on_started:
        on_started(service._view(record, detail=True))

    last_persisted = 0.
    checkpoint_lock = asyncio.Lock()
    async def _checkpoint(phase, *, terminal=False, error=None, force=False):
        nonlocal last_persisted
        result['phase'] = phase
        result['updatedAt'] = clock()
        result['cacheHits'] = history_reader.cache_hits
        result['historyRequests'] = history_reader.requests
        result['activeHistoryRequests'] = history_reader.active_requests
        result['prefetchedHistories'] = history_reader.prefetched
        result['historyConcurrency'] = policy.history_concurrency
        result['historyBatchSize'] = policy.history_batch_size
        if terminal:
            result['finishedAt'] = clock()
        if not terminal and not force and time.monotonic()-last_persisted < 1:
            return None
        last_persisted = time.monotonic()
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
                {'runId': run_id, 'symbol': 'MULTI', 'technique': 'options_cartel', 'mode': 'preparation',
                 'phase': phase, 'armed': result['armed'], 'error': error},
                aggregate_type='technique_run', aggregate_id=run_id)
        return view

    async def checkpoint(phase, **kwargs):
        async with checkpoint_lock:
            return await _checkpoint(phase, **kwargs)

    async def report(*, symbol=None, message=None, phase=None):
        if symbol is not None:
            result['currentSymbol'] = symbol
        if message:
            result['message'] = message
        await checkpoint(phase or result['phase'])

    history_reader = PreparationHistory(engine, fetch, report, policy, clock)
    try:
        await engine.journal.append(ev.TECHNIQUE_RUN_STARTED,
            {'runId': run_id, 'symbol': 'MULTI', 'technique': 'options_cartel', 'mode': 'preparation',
             'portfolioId': portfolio_id, 'session': target_session},
            aggregate_type='technique_run', aggregate_id=run_id)
        # Refresh only unused automatic arms. Paused plans express user intent;
        # working entries and held positions retain their existing protection.
        result['replacedPlans'] = []
        for old_id in ([] if prior else list(runtime.rows)):
            async with runtime.controller._guard(old_id):
                require_execution_scope(engine, policy)
                old = runtime.rows[old_id]
                if old['portfolioId'] != portfolio_id or not old.get('config', {}).get('preparation') \
                        or old['status'] != 'armed' or old['state'].get('attemptTag'):
                    continue
                if runtime._positions(old_id):
                    continue
                await runtime.disarm(old_id, reason='daily preparation refresh')
                result['replacedPlans'].append(old_id)
        rules = CartelRules.for_profile(policy.profile, market_alignment=policy.market_alignment, require_industry_rank=policy.industry_policy == 'strict', reviewed_etfs=policy.reviewed_etfs)
        async def discovery_progress(update):
            result['discoveryProgress'] = update
            await report(message=update['message'], phase='discovering')
        if prior:
            universe = prior.config['discoverySnapshot']
            captured = {'runId': prior.result['industrySnapshotId']}
            industry_record = await service._load(captured['runId'])
            industry = IndustrySnapshot.model_validate(industry_record.config['inputs'])
            industry_raw = prior.config['industryPublication']
            at = prior.as_of
        else:
            await checkpoint('discovering', force=True)
            args = {'clock': clock}
            if discover is discover_market:
                args['on_progress'] = discovery_progress
            universe = await observed_work(discover(rules, **args), report, message='Discovering market listings', timeout=600)
            result['discovered'] = len(universe['rows'])
            await report(message='Capturing published weekly and monthly industry ranks', phase='industry_context')
            industry, industry_raw = await observed_work(industries(clock=clock), report, message='Loading industry publication')
            captured = await save_snapshot(service, industry, now_ms=clock())
            at = clock()
        result['discovered'] = len(universe['rows'])
        result['discovery'] = {k: universe[k] for k in ('providerTotal', 'received', 'complete', 'excluded', 'observedAt', 'inputSha256')}
        result['industrySnapshotId'] = captured['runId']
        result['resumeReady'] = True
        async with engine.sf() as session:
            row = await session.get(TechniqueRun, run_id)
            row.as_of = at
            row.config = {**row.config, 'discoverySnapshot': universe, 'industryPublication': industry_raw}
            await session.commit()
        await checkpoint('market_context', force=True)
        async with httpx.AsyncClient(headers={'User-Agent': UA}, timeout=30.) as client:
            indices = {}
            for symbol in ('SPY', 'QQQ'):
                indices[symbol], _ = await history_reader.daily(symbol, at, client)
            regime = market_regime(indices, rules, at)
            result['market'] = regime
            breadth_histories = dict(indices)
            breadth_errors = {}
            for benchmark in ('RSP', 'QQQE'):
                try:
                    breadth_histories[benchmark], _ = await history_reader.daily(benchmark, at, client)
                except Exception as exc:  # noqa: BLE001 - optional context remains explicitly unavailable
                    breadth_errors[benchmark] = type(exc).__name__
            result['breadthContext'] = {**read_breadth(breadth_histories, at), 'errors': breadth_errors}

            market_blocked = regime['direction'] not in ('long', 'short')
            direction = policy.research_direction if market_blocked else regime['direction']
            result['armingBlocked'] = market_blocked
            result['researchDirection'] = direction
            result['researchCandidates'] = 0
            if market_blocked:
                result['warnings'].append('Market alignment blocks automatic arming. Stock research continues; candidates require fresh aligned preparation before execution.')
                await report(message=f'Market alignment blocked; evaluating {direction} research candidates', phase='evaluating')
            def review_saved(saved):
                args = (saved['config']['inputs'], saved['result']['analysis'], policy)
                return automatic_review(*args, research_only=True) if market_blocked else automatic_review(*args)
            eligible = universe['rows']
            selected_listings = eligible if policy.scan_all else eligible[:policy.history_limit]
            result['eligible'] = len(eligible)
            result['evaluationTotal'] = len(selected_listings)
            result['notEvaluated'] = len(eligible)
            if len(selected_listings) < len(eligible):
                result['warnings'].append(f"Optional cap limits this run to {len(selected_listings)} of {len(eligible)} eligible listings.")
            reused = {}
            if prior:
                reused = {r['symbol']: r['analysisId'] for r in prior.result.get('rows', []) if r.get('analysisId') and r['status'] in ('candidate', 'filtered', 'research_only')}
                # Child analyses survive a crash between their commit and the next progress checkpoint.
                async with engine.sf() as session:
                    children = (await session.execute(select(TechniqueRun.symbol, TechniqueRun.id).where(TechniqueRun.parent_run_id == prior.id,
                        TechniqueRun.mode == 'analysis', TechniqueRun.result['collection']['historyCacheVersion'].as_integer() == 1))).all()
                reused.update({r.symbol: r.id for r in children})
            pool = []
            consecutive_transport_errors = 0
            industry_reads = {}
            await report(message='Evaluating all eligible listings' if policy.scan_all else 'Evaluating the explicitly capped universe', phase='evaluating')
            for listing in selected_listings:
                group = listing.get('industry') or ''
                if group not in industry_reads:
                    industry_reads[group] = read_industry(industry, group, at=at, direction=direction,
                        top_n=rules.industry_top_n, max_age_days=rules.max_metadata_age_days)
            def skip_history(listing):
                return listing['symbol'] in reused or (rules.require_industry_rank and listing.get('securityType') != 'etf'
                    and industry_reads[listing.get('industry') or '']['status'] == 'fail')
            async with history_reader.prefetch(selected_listings, at, client, skip=skip_history) as histories:
                async for listing, prefetched_history in histories:
                    if runtime.stopping:
                        raise asyncio.CancelledError()
                    symbol = listing['symbol']
                    result['currentSymbol'] = symbol
                    try:
                        group = listing.get('industry') or ''
                        if group not in industry_reads:
                            industry_reads[group] = read_industry(industry, group, at=at, direction=direction,
                                top_n=rules.industry_top_n, max_age_days=rules.max_metadata_age_days)
                        if rules.require_industry_rank and listing.get('securityType') != 'etf' and industry_reads[group]['status'] == 'fail':
                            result['rows'].append({'symbol': symbol, 'status': 'prefiltered',
                                'reasons': ['Industry fails the required weekly/monthly ranking gate; history is unnecessary'],
                                'industrySnapshotId': captured['runId'], 'industryContext': industry_reads[group]})
                            result['prefiltered'] += 1; result['processed'] += 1
                            result['notEvaluated'] = len(eligible)-result['processed']
                            await checkpoint('evaluating')
                            continue
                        if symbol in reused:
                            saved = service._view(await service._load(reused[symbol]), detail=True)
                            if saved['config']['inputs']['as_of_ms'] != at:
                                raise ValueError('Resumed analysis cutoff differs from the saved preparation')
                            review = review_saved(saved)
                            result['resumedAnalyses'] += 1
                            entry = evaluation_row(saved, review, policy)
                            if market_blocked and review:
                                entry.update(status='research_only', reasons=['Stock/setup checks pass; market alignment blocks arming.'])
                            if review:
                                result['researchCandidates' if market_blocked else 'qualifying'] += 1
                                pool.append((saved['runId'], review))
                            result['rows'].append(entry); result['evaluated'] += 1; result['processed'] += 1
                            result['notEvaluated'] = len(eligible)-result['processed']
                            await checkpoint('evaluating')
                            continue
                        if isinstance(prefetched_history, Exception):
                            raise prefetched_history
                        history, provenance = prefetched_history
                        facts = FactsInput(symbol=symbol, observed_at=listing['observedAt'], source=listing['source'],
                            market_cap=listing['marketCap'], security_type=listing.get('securityType', 'stock'), cap_observed_at=listing['observedAt'],
                            cap_data_as_of_ms=listing['sourceBarOpenAt'], fundamentals_snapshot_id=run_id, industry=listing['industry'],
                            membership_observed_at=listing['observedAt'], membership_source='TradingView primary listing classification')
                        research = ResearchInput(history=history, indices=indices, facts=facts, rules=rules,
                            parameters=policy.setups, as_of_ms=at, direction=direction, data_source=listing['source'],
                            industry_snapshot_id=captured['runId'])
                        saved = await service.analyze(research, collection=provenance, parent_run_id=run_id)
                        review = review_saved(saved)
                        entry = evaluation_row(saved, review, policy)
                        if market_blocked and review:
                            entry.update(status='research_only', reasons=['Stock/setup checks pass; market alignment blocks arming.'])
                        if review:
                            result['researchCandidates' if market_blocked else 'qualifying'] += 1
                            pool.append((saved['runId'], review))
                        result['evaluated'] += 1
                        consecutive_transport_errors = 0
                    except (*DATA_ERRORS, httpx.HTTPError) as exc:
                        result['dataErrors'] += 1
                        if rate_limited(exc):
                            result['message'] = 'Provider rate limit reached after bounded retries. Resume to continue saved work.'
                            raise
                        transport_error = isinstance(exc, (TimeoutError, httpx.TimeoutException, httpx.NetworkError)) or 'HTTP 5' in str(exc)
                        consecutive_transport_errors = consecutive_transport_errors+1 if transport_error else 0
                        if consecutive_transport_errors >= 3:
                            result['message'] = 'Provider unavailable after three consecutive transport failures. Saved work can be resumed.'
                            raise
                        entry = {'symbol': symbol, 'status': 'data_error', 'reason': str(exc)[:600]}
                    entry['industryContext'] = industry_reads[group]
                    entry['industryPolicy'] = policy.industry_policy
                    result['rows'].append(entry); result['processed'] += 1
                    result['notEvaluated'] = len(eligible)-result['processed']
                    result['cacheHits'] = history_reader.cache_hits
                    result['historyRequests'] = history_reader.requests
                    await checkpoint('evaluating')
            evaluated_by_symbol = {r['symbol']: r for r in result['rows']}
            result['watchlistComparison'] = {'source': policy.comparison_source, 'rows': [
                {'symbol': sym, **evaluated_by_symbol.get(sym, {'status': 'outside_universe', 'reasons': ['Not returned by the eligible discovery universe; not assumed to fail setup checks.']})}
                for sym in policy.comparison_symbols]}
            rank_evidence = {}
            for saved_id, review in pool:
                saved = service._view(await service._load(saved_id), detail=True)
                rank_evidence[saved_id] = ranking_evidence(saved, review)
            if policy.shortlist_ranking == 'quality':
                pool.sort(key=lambda item: quality_key(rank_evidence[item[0]], rank_evidence[item[0]]['symbol']))
            result['shortlistRanking'] = policy.shortlist_ranking
            # Ranking affects new candidates only, never existing positions.
            for saved_id, review in pool:
                saved = service._view(await service._load(saved_id), detail=True)
                await report(symbol=saved['symbol'], message=f"Preparing {saved['symbol']} plan and option expression", phase='preparing_plans')
                if len(result['shortlist']) >= policy.focus_count:
                    break
                symbol = saved['symbol']
                if market_blocked:
                    candidate = next(c for c in saved['result']['analysis']['candidates'] if c['setup'] == review.setup)
                    result['shortlist'].append({'symbol': symbol, 'analysisId': saved['runId'], 'status': 'market_blocked',
                        'ranking': rank_evidence[saved_id], 'setup': review.setup, 'direction': direction, 'trigger': candidate['trigger'],
                        'invalidation': candidate['invalidation'], 'targets': list(review.reviewed_targets or []),
                        'reason': 'Research only. Market alignment prevents arming; prepare again with fresh aligned evidence.'})
                    await checkpoint('saving_research')
                    continue
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
                    minutes = await history_reader.window(symbol, '1m', at-19*86_400_000, at, client)
                    baseline = build_volume_baseline(minutes, symbol, review.entry_policy.timeframe_minutes, at)
                    if not baseline['baselines']:
                        raise ValueError('No supported same-time volume baseline; plan cannot be armed')
                    inputs = ResearchInput.model_validate(saved['config']['inputs']).model_copy(update={
                        'minute_history': [MinuteInput(symbol=b.symbol, ts=b.ts, open=b.open, high=b.high,
                            low=b.low, close=b.close, volume=b.volume) for b in minutes if b.ts+60_000 <= at]})
                    enriched = await service.analyze(inputs, parent_run_id=run_id)
                    key = hashlib.sha256(f'{target_session}:{portfolio_id}:{symbol}:{at}'.encode()).hexdigest()[:32]
                    async with engine.sf() as session:
                        existing_plan = await session.get(TechniqueRun, key)
                    if existing_plan:
                        if existing_plan.technique != 'options_cartel' or existing_plan.mode != 'plan' or existing_plan.config.get('preparation', {}).get('portfolioId') != portfolio_id:
                            raise ValueError('Existing plan identity does not match this preparation')
                        plan_record = service._view(existing_plan, detail=True)
                    else:
                        plan_record = await service.prepare(enriched['runId'], review, plan_id=key,
                            preparation={'runId': run_id, 'workspace': policy.workspace, 'session': target_session, 'portfolioId': portfolio_id, 'reviewer': 'automatic_rules'})
                    plan = CartelPlan.model_validate(plan_record['result']['plan']['plan'])
                    coverage = baseline_coverage(plan)
                    if not coverage['ready']:
                        raise ValueError(f"Volume baseline covers {coverage['available']}/{coverage['expected']} periods; plan saved but not armed. Rebuild with complete history.")
                    selection_policy = await affordable_contract_policy(engine, portfolio_id, policy)
                    selected = await observed_work(choose(engine, plan, selection_policy), report, message=f'Selecting {symbol} option contract')
                    row = {'symbol': symbol, 'planId': plan.id, 'setup': plan.setup, 'trigger': plan.trigger,
                           'invalidation': plan.invalidation, 'targets': list(plan.targets), 'selection': selected,
                           'status': 'awaiting_contract', 'ranking': rank_evidence[saved_id]}
                    if selected['selected']:
                        current = read_policy(engine, policy.workspace)
                        if current != policy or not current.enabled:
                            raise ValueError('Preparation configuration changed before arming; rerun with current settings')
                        await preparation_portfolio(engine, portfolio_id, policy.workspace)
                        require_execution_scope(engine, policy)  # recheck identity immediately before arming
                        spec = ExecutionInput(portfolio_id=portfolio_id, mode='auto', instrument='options',
                            contract_symbol=selected['selected']['symbol'], budget=policy.budget, risk_pct=policy.risk_pct,
                            max_units=policy.max_contracts, overnight_ack=policy.workspace == 'practice' or policy.overnight_ack, allow_live=policy.workspace == 'live' and policy.allow_live)
                        await runtime.arm(plan.id, {'mode': 'auto', 'portfolioId': portfolio_id, 'execution': spec.model_dump(),
                            'clientKind': 'desktop', 'preparation': {'runId': run_id, 'workspace': policy.workspace, 'practiceOnly': policy.workspace == 'practice',
                                'validUntil': min(at+86_400_000, session_bounds(plan.last_session.isoformat())[1])}})
                        row['status'] = 'armed'; result['armed'] += 1
                    result['shortlist'].append(row)
                except (*DATA_ERRORS, httpx.HTTPError) as exc:
                    result['planErrors'] += 1
                    result['rows'].append({'symbol': symbol, 'status': 'plan_blocked', 'reason': str(exc)[:600]})
                await checkpoint('preparing_plans')
        result['coverageComplete'] = result.get('notEvaluated', 0) == 0 and result['dataErrors'] == 0
        result['currentSymbol'] = None
        complete = result['coverageComplete'] and result['planErrors'] == 0
        result['message'] = ('Research finished; automatic arming blocked by market alignment' if result.get('armingBlocked') else 'Preparation finished') if complete else 'Preparation finished with coverage gaps or blocked plans; review exclusions'
        return await checkpoint('complete' if complete else 'partial', terminal=True)
    except BaseException as exc:
        if not rate_limited(exc):
            result['message'] = 'Preparation interrupted; completed work is saved'
        result['warnings'].append(f'{type(exc).__name__}: preparation interrupted; saved plans and execution are preserved.')
        await checkpoint('interrupted', terminal=True, error=f'{type(exc).__name__}: {str(exc)[:500] or "Preparation interrupted"}')
        raise


async def preparation_status(engine, workspace=None):
    policy = read_policy(engine, workspace)
    async with engine.sf() as session:
        query = select(TechniqueRun).where(TechniqueRun.technique == 'options_cartel',
            TechniqueRun.mode == 'preparation', workspace_filter(policy.workspace))
        if policy.portfolio_id:
            query = query.where(TechniqueRun.config['portfolioId'].as_string() == policy.portfolio_id)
        row = await session.scalar(query.order_by(TechniqueRun.created_at.desc()).limit(1))
    latest = None if row is None else {**CartelService._view(row), 'error': row.error,
                                     'result': json.loads(json.dumps(row.result))}
    arms = []
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
    refresh = getattr(getattr(engine, 'cartel_observer', None), 'preparation_quote_status', {})
    contracts = {a.config.get('execution', {}).get('contract_symbol') for a in arms}
    return {'configuration': policy.model_dump(mode='json', by_alias=True), 'latest': latest, 'liveAutoAllowed': bool(engine.settings.get('techniques.options_cartel.allow_live_auto', False)),
            'canResume': bool(row and resumable(row, policy, now_ms())), 'serverNow': now_ms(),
            'quoteRefresh': {**refresh, 'errors': {k: v for k, v in refresh.get('errors', {}).items() if k in contracts}},
            'activation': getattr(engine, '_cartel_preparation_activations', {}).get(policy.workspace, {})}


async def activate_pending(engine, *, clock=now_ms, choose=planning_contract):
    now = clock()
    day = dt.datetime.fromtimestamp(now/1000, ET).date()
    opens, closes = session_bounds(day.isoformat())
    if not is_trading_day(day) or not opens-45*60_000 <= now < closes:
        return
    running = getattr(engine, '_cartel_preparation_task', None)
    if running is not None and not running.done():
        return
    policy = read_policy(engine)
    if not policy.enabled:
        return
    runtime = getattr(engine, 'cartel_observer', None)
    if runtime is None or runtime.stopping:
        return
    async with engine.sf() as session:
        row = await session.scalar(select(TechniqueRun).where(TechniqueRun.technique == 'options_cartel',
            TechniqueRun.mode == 'preparation', TechniqueRun.status == 'done', workspace_filter(policy.workspace)).order_by(TechniqueRun.created_at.desc()).limit(1))
    if row is None or row.result.get('armingBlocked') or PreparationPolicy.model_validate(row.config.get('policy', {})) != policy:
        return
    service = CartelService(engine)
    portfolio_id = await preparation_portfolio(engine, row.config['portfolioId'], policy.workspace)
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
            context = await load_session_context(engine, plan, now)
            readiness = entry_readiness(plan, context, now)
            if not readiness['ready']:
                statuses[plan.id] = '; '.join(readiness['reasons'])
                continue
            selection = await choose(engine, plan, await affordable_contract_policy(engine, portfolio_id, policy))
            if not selection['selected']:
                statuses[plan.id] = 'Waiting for an option contract meeting the configured DTE, delta, liquidity and premium limits'
                continue
            current = read_policy(engine, policy.workspace)
            if not current.enabled or current != policy or runtime.stopping:
                break
            await preparation_portfolio(engine, portfolio_id, policy.workspace)
            require_execution_scope(engine, policy)
            spec = ExecutionInput(portfolio_id=portfolio_id, mode='auto', instrument='options',
                contract_symbol=selection['selected']['symbol'], budget=policy.budget, risk_pct=policy.risk_pct,
                max_units=policy.max_contracts, overnight_ack=policy.workspace == 'practice' or policy.overnight_ack, allow_live=policy.workspace == 'live' and policy.allow_live)
            await runtime.arm(plan.id, {'mode': 'auto', 'portfolioId': portfolio_id, 'execution': spec.model_dump(),
                'clientKind': 'desktop', 'preparation': {'runId': row.id, 'workspace': policy.workspace, 'practiceOnly': policy.workspace == 'practice', 'validUntil': valid_until,
                    'contextMinutes': [b.to_row() for b in context]}})
            statuses[plan.id] = 'armed'
        except Exception as exc:  # noqa: BLE001 - expose retry state without interrupting execution
            statuses[item['planId']] = f'{type(exc).__name__}: option preparation remains pending'
    if not hasattr(engine, '_cartel_preparation_activations'):
        engine._cartel_preparation_activations = {}
    engine._cartel_preparation_activations[policy.workspace] = {'at': now, 'plans': statuses}


async def submit_preparation(engine, *, scheduled=False, **kwargs):
    lock = getattr(engine, '_cartel_preparation_submit_lock', None)
    if lock is None:
        lock = engine._cartel_preparation_submit_lock = asyncio.Lock()
    async with lock:
        return await _submit_preparation(engine, scheduled=scheduled, **kwargs)


async def _submit_preparation(engine, *, scheduled=False, workspace=None, **kwargs):
    policy = read_policy(engine, workspace)
    if getattr(getattr(engine, 'cartel_observer', None), 'stopping', False):
        return {'status': 'stopping'}
    running = getattr(engine, '_cartel_preparation_task', None)
    if running is not None and not running.done():
        if getattr(engine, '_cartel_preparation_workspace', 'practice') != policy.workspace:
            raise ValueError('Preparation is already running in the other workspace')
        return await asyncio.shield(engine._cartel_preparation_ready)
    if not policy.enabled:
        if scheduled:
            return {'status': 'disabled'}
        raise ValueError(f'Automatic {policy.workspace.title()} preparation is disabled')
    await preparation_portfolio(engine, policy.portfolio_id, policy.workspace)
    require_execution_scope(engine, policy)
    if scheduled:
        now = kwargs.get('clock', now_ms)()
        if not is_trading_day(dt.datetime.fromtimestamp(now/1000, ET).date()):
            return {'status': 'non_trading_day'}
        async with engine.sf() as session:
            latest = await session.scalar(select(TechniqueRun).where(TechniqueRun.technique == 'options_cartel',
                TechniqueRun.mode == 'preparation', TechniqueRun.status == 'done', workspace_filter(policy.workspace)).order_by(TechniqueRun.created_at.desc()).limit(1))
        if latest and PreparationPolicy.model_validate(latest.config.get('policy', {})) == policy and latest.config.get('session') == next_session_date(now) and 0 <= now-latest.as_of < 12*3_600_000:
            return {'status': 'already_prepared', 'runId': latest.id}
    ready = asyncio.get_running_loop().create_future()
    ready.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
    engine._cartel_preparation_ready = ready
    def started(row):
        if not ready.done():
            ready.set_result(row)
    engine._cartel_preparation_workspace = policy.workspace
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


async def stop_preparation(engine, workspace=None):
    task = getattr(engine, '_cartel_preparation_task', None)
    if task is not None and not task.done() and (workspace is None or getattr(engine, '_cartel_preparation_workspace', 'practice') == workspace):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    runtime = getattr(engine, 'cartel_observer', None)
    activation = getattr(runtime, 'preparation_activation_task', None)
    if activation is not None and not activation.done() and activation is not asyncio.current_task() and (workspace is None or getattr(runtime, 'preparation_activation_workspace', None) == workspace):
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
            row.result = {**row.result, 'phase': 'interrupted', 'updatedAt': now_ms(), 'finishedAt': now_ms(),
                          'message': 'Runtime restarted; completed work is saved'}
