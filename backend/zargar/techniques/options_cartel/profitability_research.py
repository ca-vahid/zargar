"""Prospective Practice research. These records can never be armed or submitted."""
from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as dt
import functools
import hashlib
import json
import math

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ...domain import Bar
from ...marketstructure.history import UA, fetch_window
from ...marketstructure.market_calendar import is_trading_day
from ...marketstructure.sessions import ET, session_bounds
from ...models import BarRow, TechniqueRun
from .automatic_plans import PreparationPolicy, automatic_review
from .data import DailyBar
from .data_quality import evidence, pack, unpack
from .exits import ExitCampaign
from .intraday_research import STEP, market_observation
from .leader_context import leader_evidence
from .plans import CartelPlan
from .preparation_io import PreparationHistory
from .preparation_readiness import baseline_coverage
from .preparation_scope import read_policy
from .prepare import build_volume_baseline
from .quality import ranking_evidence
from .screen import screen_listing
from .service import ResearchInput
from .setups import analyze_setups

# D4 (2026-09-18): one worker for the collector's CPU-bound studies. This bounds *concurrent*
# study work to a single thread and keeps it off the event loop; it does not make research
# fully bounded: a study already running when its awaiting task times out keeps running to
# completion (thread work cannot be cancelled), and queued studies wait behind it. Callers keep
# their existing timeout/retry lifecycle; the queue depth per tick is the candidate count.
_STUDY_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='cartel-research-study')


async def _study(fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_STUDY_EXECUTOR, functools.partial(fn, *args, **kwargs))

SETTING = 'techniques.options_cartel.profitability_research'
VERSION = 'cartel-profitability-v1'
BEARISH_VERSION = 'engineering-structural-short-proxy-v1'
BEARISH_SOURCE = 'https://x.com/SRxTrades/status/1906420174246510756'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def identity(preparation_id, suffix):
    return digest([VERSION, preparation_id, suffix])[:32]


def settings(engine):
    return {'enabled': bool(engine.settings.get(SETTING, True)),
        'candidateCap': max(1, min(100, int(engine.settings.get(SETTING+'.candidate_cap', 50)))),
        'bearishEnabled': bool(engine.settings.get(SETTING+'.bearish_enabled', True))}


def weak_environment(saved_market, direction):
    """A mixed index makes Moderate context weak; missing reference stays unknown."""
    reads = [saved_market.get('indices', {}).get(symbol, {}) for symbol in ('SPY', 'QQQ')]
    if any(r.get('direction') not in ('long', 'short', 'mixed') or any(
            not isinstance(r.get('emas', {}).get(str(p)), (int, float))
            or isinstance(r['emas'][str(p)], bool) or not math.isfinite(r['emas'][str(p)])
            or r['emas'][str(p)]<=0 for p in (8, 21, 50)) for r in reads):
        return None
    return any(r['direction'] != direction for r in reads)


def candidate_from_analysis(saved, policy, cohort, *, short=False):
    """Re-use immutable daily inputs; this function performs no I/O."""
    body = ResearchInput.model_validate(saved['config']['inputs'])
    if short:
        body = body.model_copy(update={'direction': 'short'})
        screen = screen_listing(body.history, body.facts, body.indices, body.rules, body.as_of_ms, direction='short')
        analysis = analyze_setups(body.history, body.indices.get('SPY', []), screen, body.parameters,
            body.as_of_ms, direction='short')
        saved = {**saved, 'config': {**saved['config'], 'inputs': body.model_dump(mode='json')},
            'result': {**saved['result'], 'screen': screen, 'analysis': analysis}}
    review = automatic_review(body.model_dump(mode='json'), saved['result']['analysis'], policy, research_only=True)
    if review is None:
        return None
    setup = next(c for c in saved['result']['analysis']['candidates'] if c['setup'] == review.setup)
    return {'analysisId': saved['runId'], 'symbol': saved['symbol'], 'direction': body.direction,
        'cohort': cohort, 'setup': review.setup, 'trigger': setup['trigger'], 'invalidation': setup['invalidation'],
        'targets': list(review.reviewed_targets), 'ranking': ranking_evidence(saved, review),
        'leaderEvidence': leader_evidence(saved), 'rules': body.rules.model_dump(mode='json'),
        'entryPolicy': review.entry_policy.model_dump(mode='json'),
        'exitCampaign': review.exit_campaign.model_dump(mode='json'),
        'daily': [b.model_dump(mode='json') for b in body.history], 'sourceAt': body.as_of_ms}


async def _insert(engine, key, mode, prep, at, result, config):
    from ... import __version__
    async with engine.sf() as session, session.begin():
        await session.execute(insert(TechniqueRun).values(id=key, technique='options_cartel', symbol='MULTI',
            mode=mode, status='done', verdict='research_only', as_of=at, parent_run_id=prep.id,
            config={'workspace': 'practice', 'portfolioId': prep.config['portfolioId'],
                'session': prep.config['session'], 'researchVersion': VERSION, 'codeVersion': __version__, **config},
            result={**result, 'researchOnly': True, 'placesOrders': False, 'automaticPermissionChanged': False})
            .on_conflict_do_nothing(index_elements=['id']))


async def freeze_preparation(engine, prep_id, policy, result, *, clock, report=None):
    """Freeze the qualified denominator before the session, independent of arm slots."""
    from .research_economics import compare_rankings
    config = settings(engine)
    if not config['enabled'] or policy.workspace != 'practice':
        return {'status': 'disabled', 'placesOrders': False}
    async with engine.sf() as session:
        prep = await session.get(TechniqueRun, prep_id)
        existing = await session.get(TechniqueRun, identity(prep_id, 'context'))
    if existing:
        return {'status': 'frozen', 'contextId': existing.id, 'placesOrders': False}
    opens, _ = session_bounds(prep.config['session'])
    if clock() >= opens or prep.as_of >= opens:
        return {'status': 'pre_session_required', 'placesOrders': False}
    ids = list(dict.fromkeys(r['analysisId'] for r in result.get('rows', []) if r.get('analysisId')))
    candidates, errors = [], []
    groups = {g['industry']: g for g in result.get('leaderContext', {}).get('groups', [])}
    for offset in range(0, len(ids), 25):
        if not settings(engine)['enabled'] or clock() >= opens:
            return {'status': 'pre_session_required', 'placesOrders': False}
        async with engine.sf() as session:
            rows = (await session.scalars(select(TechniqueRun).where(TechniqueRun.id.in_(ids[offset:offset+25]),
                TechniqueRun.technique == 'options_cartel', TechniqueRun.mode == 'analysis'))).all()
        saved = [{'runId': row.id, 'symbol': row.symbol, 'config': row.config, 'result': row.result}
            for row in rows if row.as_of == prep.as_of]

        def evaluate_batch():
            found, failures = [], []
            for row in saved:
                for cohort, short in [('primary', False), *([('bearish', True)] if config['bearishEnabled']
                        and row['config']['inputs']['direction'] != 'short' else [])]:
                    try:
                        candidate = candidate_from_analysis(row, policy, cohort, short=short)
                        if candidate:
                            found.append(candidate)
                    except (KeyError, ValueError, TypeError) as exc:
                        failures.append({'symbol': row['symbol'], 'cohort': cohort, 'reason': str(exc)[:250]})
            return found, failures

        found, failures = await _study(evaluate_batch)
        candidates.extend(found); errors.extend(failures)
        if report:
            await report(message=f'Freezing profitability research: {min(offset+25, len(ids))}/{len(ids)} saved analyses')
    rankings = {}
    for cohort in ('primary', 'bearish'):
        cohort_rows = [c for c in candidates if c['cohort'] == cohort]
        for c in cohort_rows:
            c['id'] = identity(prep.id, cohort+':'+c['analysisId'])
            group = groups.get((c.get('leaderEvidence') or {}).get('industry'), {})
            median = group.get('medianRelativeStrength')
            # Prepared group medians are directional to the primary cohort.
            c['themeEvidence'] = {'strengthKnown': group.get('strengthKnown', 0),
                'medianRelativeStrength': -median if cohort == 'bearish' and median is not None else median}
        rankings[cohort] = compare_rankings([{k: c.get(k) for k in ('id','analysisId','symbol','direction',
            'ranking','leaderEvidence','themeEvidence','daily','sourceAt','trigger')} for c in cohort_rows], execution_slots=policy.focus_count)
    # Interleave both frozen rankings/cohorts so the bounded sample does not
    # silently equate research capacity with the five execution slots.
    by_id = {c['id']: c for c in candidates}
    orders = [[c['id'] for c in sorted(r['candidates'], key=lambda c: c[rank])]
        for r in rankings.values() for rank in ('baselineRank', 'leaderRank')]
    orders.extend(r['opportunityComparisons'][key] for r in rankings.values()
                  for key in ('nearestUnbrokenIds','liquidFirstIds'))
    selected = []
    for i in range(max((len(order) for order in orders), default=0)):
        for order in orders:
            if i < len(order) and order[i] not in selected and len(selected) < config['candidateCap']:
                selected.append(order[i])
    rank_rows = {r['id']: r for ranking in rankings.values() for r in ranking['candidates']}
    for cid in selected:
        by_id[cid].update({k: rank_rows[cid].get(k) for k in ('baselineRank', 'leaderRank', 'baselineSelected', 'leaderSelected')})
        by_id[cid].update(baselineStatus='pending', baselineAttempts=0, nextBaselineAt=0)
        by_id[cid]['weakEnvironment'] = weak_environment(result.get('market', {}), by_id[cid]['direction'])
    if clock() >= opens or settings(engine) != config or read_policy(engine, 'practice') != policy:
        return {'status': 'pre_session_required', 'placesOrders': False}
    key = identity(prep.id, 'context')
    await _insert(engine, key, 'profit_context', prep, clock(), {
        'phase': 'collecting', 'frozenAt': clock(), 'candidates': [by_id[cid] for cid in selected],
        'rankings': rankings, 'errors': errors, 'market': result.get('market', {}),
        'denominator': {'discovered': result.get('discovered', 0), 'evaluated': result.get('evaluated', 0),
            'eligible': len(candidates), 'boundedLimit': config['candidateCap'], 'omitted': len(candidates)-len(selected),
            'primaryEligible': sum(c['cohort']=='primary' for c in candidates),
            'bearishEligible': sum(c['cohort']=='bearish' for c in candidates)},
        'omittedIds': [c['id'] for c in candidates if c['id'] not in selected],
        'protocol': {'version': VERSION, 'bearishVersion': BEARISH_VERSION, 'sourceRefs': [BEARISH_SOURCE],
            'policySha256': digest(policy.model_dump(mode='json')), 'sourcePreparationId': prep.id,
            'sourceAsOf': prep.as_of, 'settings': config, 'costs': None,
            'weakEnvironmentDefinition': 'At least one index lacked strict directional daily 8/21/50 alignment, including Moderate mixed context. Missing references are unknown. Frozen before the session, never inferred from losses.',
            'bearishDefinition': {'kind': 'engineering_structural_short_proxy', 'sourceEquivalent': False,
                'sourceInspiration': BEARISH_SOURCE, 'stockRules': 'Existing frozen neutral listing gates; stock below its selected EMAs; directional structural checks.',
                'sourceDifferences': 'Does not claim the March source scanner price/capitalization/relative-volume/negative-change thresholds. Those source-specific fields remain unverified.'},
            'note': 'Source-inspired directional research and a theme-proxy ranking; no strategy promotion or trading authority.'}},
        {'policy': policy.model_dump(mode='json')})
    return {'status': 'frozen', 'contextId': key, 'eligible': len(candidates), 'observedLimit': len(selected), 'placesOrders': False}


def directional_market(saved, bars, boundary, at, direction, previous=None):
    base = market_observation(saved, bars, boundary, at, previous if direction == 'long' else None)
    if direction == 'short':
        aligned = base['status'] != 'unavailable' and all(all(r['close'] < r['dailyEmas'][str(p)]
            for p in (8, 21, 50)) for r in base['indices'].values())
        consecutive = bool(aligned and previous and previous.get('boundary') == boundary-STEP
            and previous.get('aligned') and previous.get('direction') == direction)
        base.update(aligned=aligned, sustained=consecutive,
            improvedSince=(previous.get('improvedSince') or at) if consecutive else None,
            status='sustained_improvement' if consecutive else 'improvement_observed' if aligned else
                'unavailable' if base['status']=='unavailable' else 'not_aligned')
    return {**base, 'direction': direction}


def make_plan(candidate, day, baseline):
    return CartelPlan(id=candidate['id'], symbol=candidate['symbol'], direction=candidate['direction'],
        setup=candidate['setup'], created_at=candidate['sourceAt'], first_session=dt.date.fromisoformat(day),
        last_session=dt.date.fromisoformat(day), trigger=candidate['trigger'], invalidation=candidate['invalidation'],
        targets=tuple(candidate['targets']), source_refs=(candidate['analysisId'],),
        rationale='Frozen profitability research only; never executable', rules=candidate['rules'],
        entry={**candidate['entryPolicy'], 'require_exchange_bars': True, 'allow_simulated_bars': False},
        volume_baseline=baseline['baselines'], baseline_as_of=candidate['sourceAt'])


async def _update_context(engine, key, changes, candidate_id=None):
    async with engine.sf() as session, session.begin():
        row = await session.get(TechniqueRun, key, with_for_update=True)
        result = json.loads(json.dumps(row.result))
        if candidate_id:
            next(c for c in result['candidates'] if c['id']==candidate_id).update(changes)
        else:
            result.update(changes)
        row.result = result
    return row


async def _warm_baselines(runtime, context, policy, *, fetch=fetch_window, attempt_limit=None):
    async def report(**kwargs):
        runtime._profitability_status = {'phase': 'collecting', 'message': kwargs.get('message')}
    reader = PreparationHistory(runtime.engine, fetch, report, policy, runtime.clock)
    attempted = 0
    # Scheduling order is separate from the frozen candidate/ranking order.
    # Persisted attempt counts keep retries fair across passes and restarts.
    due = [c for c in context.result['candidates'] if c['baselineStatus'] != 'ready'
           and runtime.clock() >= c.get('nextBaselineAt', 0)
           and (attempt_limit is None or c.get('baselineAttempts', 0) < attempt_limit)]
    due.sort(key=lambda c: (c.get('baselineAttempts', 0), c.get('nextBaselineAt', 0)))
    async with httpx.AsyncClient(timeout=18, headers={'User-Agent': UA}) as client:
        for candidate in due:
            if runtime.stopping or attempted >= 2 or not settings(runtime.engine)['enabled']:
                break
            if candidate['baselineStatus']=='ready' or runtime.clock() < candidate.get('nextBaselineAt', 0):
                continue
            attempted += 1
            update = {'baselineAttempts': candidate.get('baselineAttempts', 0)+1,
                'nextBaselineAt': runtime.clock()+300_000}
            try:
                if candidate['entryPolicy']['timeframe_minutes'] != 15:
                    raise ValueError('Research v1 requires the saved 15-minute entry policy; other timeframes remain unscored')
                if fetch is fetch_window and getattr(getattr(runtime.engine, 'config', None), 'quote_source', None) == 'sim':
                    raise ValueError('Exchange-history research is unavailable on the synthetic quote source')
                bars = await asyncio.wait_for(reader.baseline(candidate['symbol'], candidate['sourceAt'], client), 20)
                baseline = build_volume_baseline(bars, candidate['symbol'], 15, candidate['sourceAt'], require_exchange=True)
                plan = make_plan(candidate, context.config['session'], baseline)
                coverage = baseline_coverage(plan); slots = coverage['usableEntryPeriods']
                ready = coverage['ready'] and not (policy.coverage_policy=='full_session' and coverage['available']!=coverage['expected'])
                ready = ready and not (policy.coverage_policy=='opening_and_broad' and
                    (not all(i in slots for i in range(4)) or len(slots)<math.ceil((coverage['expected']-1)*.8)))
                update.update(baseline=baseline, coverage=coverage, baselineStatus='ready' if ready else 'data_unavailable',
                    baselineReason=None if ready else 'Historical baseline does not meet the unchanged coverage policy')
                if ready:
                    update['baselineReadyAt'] = runtime.clock()
            except (ValueError, OSError, httpx.HTTPError, TimeoutError) as exc:
                update.update(baselineStatus='data_unavailable', baselineReason=f'{type(exc).__name__}: {str(exc)[:200]}')
            if runtime.stopping or not settings(runtime.engine)['enabled'] or read_policy(runtime.engine, 'practice') != policy:
                break
            # Every completed attempt survives cancellation or the outer task timeout.
            context = await _update_context(runtime.engine, context.id, update, candidate['id'])
    return context


async def _pending_quotes(runtime, context, policy, observer=None):
    from .research_quotes import observe_contract
    from .research_economics import compare_entry_variants
    observer = observer or observe_contract
    requested = 0
    for candidate in context.result['candidates']:
        signal = candidate.get('researchEntry') or candidate.get('targetRoomProbe')
        previous_option = candidate.get('optionObservation') or {}
        if not signal or previous_option.get('signalAt') == signal['at']:
            continue
        if requested >= 2 or runtime.stopping or not settings(runtime.engine)['enabled']:
            break
        requested += 1
        at = runtime.clock()
        if at-signal['at'] > 120_000:
            observed = {'status': 'unmeasured', 'observedAt': at, 'quantity': None,
                'signalAt': signal['at'], 'reason': 'No option observation inside the two-minute stock-confirmation window', 'placesOrders': False}
        else:
            context = await _update_context(runtime.engine, context.id, {'optionAttemptAt': at}, candidate['id'])
            try:
                observed = await asyncio.wait_for(observer(runtime.engine,
                    make_plan(candidate, context.config['session'], candidate['baseline']), policy, runtime.clock), 25)
                observed = {**observed, 'signalAt': signal['at'],
                    'timely': 0 <= observed.get('observedAt', runtime.clock())-signal['at'] <= 120_000}
            except (ValueError, OSError, httpx.HTTPError, TimeoutError) as exc:
                observed = {'status': 'unavailable', 'observedAt': runtime.clock(), 'quantity': None,
                    'signalAt': signal['at'], 'reason': f'{type(exc).__name__}: option research observation unavailable', 'placesOrders': False}
        if runtime.stopping or not settings(runtime.engine)['enabled'] or read_policy(runtime.engine, 'practice') != policy:
            break
        changes = {'optionObservation': observed}
        quantity = (observed.get('funding') or {}).get('quantity') if observed.get('timely') else None
        if quantity and candidate.get('targetRoomProbe') and not candidate.get('campaignEntry') and candidate['targetRoomProbe']['at']==signal['at']:
            plan = make_plan(candidate, context.config['session'], candidate['baseline'])
            comparison = compare_entry_variants(plan, ExitCampaign.model_validate(candidate['exitCampaign']),
                [unpack(candidate['symbol'], b) for b in candidate['decisionBars']], as_of_ms=signal['at'],
                quantity=quantity, signal_after=candidate.get('studyEntryAfter'))
            changes['fundedEntryComparison'] = comparison
            challenge = comparison['campaignAware'].get('signal')
            if challenge and challenge['at']==signal['at']:
                changes.update(campaignEntry=challenge, campaignEntryObservedAt=observed['observedAt'],
                    campaignOptionObservation=observed, campaignDecisionBars=candidate['decisionBars'])
        context = await _update_context(runtime.engine, context.id, changes, candidate['id'])
        selected = observed.get('selected')
        if selected and observed.get('timely'):
            contract = selected['symbol'] if isinstance(selected, dict) else selected
            targets = getattr(runtime, '_profitability_targets', {})
            targets[candidate['id']+':'+contract] = {'contextId': context.id, 'candidateId': candidate['id'],
                'contract': contract, 'preparationId': context.parent_run_id, 'day': context.config['session']}
            runtime._profitability_targets = targets
            track = getattr(getattr(runtime.engine, 'options', None), 'track', None)
            if track:
                try:
                    await asyncio.wait_for(track(contract), 10)
                except (ValueError, OSError, httpx.HTTPError, TimeoutError):
                    pass  # the durable selection remains; subsequent gaps stay explicit
    return context


async def capture_quotes(runtime):
    """Bounded single-flight sampler called by the existing quote-watch loop."""
    from .research_quotes import snapshot_quote
    if runtime.stopping or not settings(runtime.engine)['enabled']:
        return
    now = runtime.clock(); day = dt.datetime.fromtimestamp(now/1000, ET).date().isoformat()
    opens, closes = session_bounds(day)
    if not opens <= now <= closes+120000:
        return
    targets = list(getattr(runtime, '_profitability_targets', {}).values())[:100]
    signatures = getattr(runtime, '_profitability_quote_signatures', {})
    for target in targets:
        if runtime.stopping or not settings(runtime.engine)['enabled'] or target['day'] != day:
            continue
        quote = snapshot_quote(runtime.engine, target['contract'], runtime.clock)
        owner = target['candidateId']+':'+target['contract']
        signature = digest([quote.get('evidenceSha256'), quote['status'], quote.get('reason')])
        if signatures.get(owner) == signature:
            continue
        key = identity(target['contextId'], owner+':quote:'+signature+':'+str(quote['observedAt']))
        async with runtime.engine.sf() as session:
            prep = await session.get(TechniqueRun, target['preparationId'])
        if prep:
            await _insert(runtime.engine, key, 'profit_quote', prep, quote['observedAt'],
                {'candidateId': target['candidateId'], 'quote': quote},
                {'contextId': target['contextId'], 'candidateId': target['candidateId']})
            signatures[owner] = signature
    runtime._profitability_quote_signatures = signatures


async def _premium_evidence(engine, context, candidate, at, *, campaign=False):
    observed = candidate.get('campaignOptionObservation' if campaign else 'optionObservation') or {}
    selected = observed.get('selected')
    if not selected or not observed.get('timely'):
        return None
    contract = selected['symbol'] if isinstance(selected, dict) else selected
    async with engine.sf() as session:
        rows = (await session.scalars(select(TechniqueRun).where(TechniqueRun.technique=='options_cartel',
            TechniqueRun.mode=='profit_quote', TechniqueRun.config['contextId'].as_string()==context.id,
            TechniqueRun.config['candidateId'].as_string()==candidate['id'], TechniqueRun.as_of<=at)
            .order_by(TechniqueRun.as_of).limit(10000))).all()
    quotes = [observed['quote']] if observed.get('quote') else []
    quotes.extend(row.result['quote'] for row in rows)
    usable = {q['observedAt']: q for q in quotes if q.get('contract')==contract and q.get('observedAt', at+1)<=at}
    fee = (observed.get('funding') or {}).get('optionFeePerContractUsd')
    return {'contract_symbol': contract, 'source': 'Prospectively recorded research quotes; modeled fills, not broker executions',
        **({'fee_per_contract': fee} if fee is not None else {}),
        'quotes': [{'source_at': q.get('sourceAt') if q['status']=='observed' else None,
            'available_at': q['observedAt'], 'bid': q['bid'] if q['status']=='observed' else 0,
            'ask': q['ask'] if q['status']=='observed' else 0,
            'delayed': q.get('delayed', False) or q['status']!='observed', 'halted': q.get('halted', False)} for q in usable.values()]}


async def prewarm_next_session(runtime, *, fetch=fetch_window):
    """Prepare research history outside RTH; never subscribe, signal or order."""
    from ...marketstructure.market_calendar import next_trading_day
    now = runtime.clock(); today = dt.datetime.fromtimestamp(now/1000, ET).date()
    opens, closes = session_bounds(today.isoformat())
    if is_trading_day(today) and opens <= now <= closes+120_000:
        return
    target = today if is_trading_day(today) and now < opens else next_trading_day(today)
    policy = read_policy(runtime.engine, 'practice')
    if runtime.stopping or not settings(runtime.engine)['enabled'] or not policy.enabled:
        return
    async with runtime.engine.sf() as session:
        context = await session.scalar(select(TechniqueRun).where(
            TechniqueRun.technique=='options_cartel', TechniqueRun.mode=='profit_context',
            TechniqueRun.config['workspace'].as_string()=='practice',
            TechniqueRun.config['portfolioId'].as_string()==policy.portfolio_id,
            TechniqueRun.config['session'].as_string()==target.isoformat())
            .order_by(TechniqueRun.created_at.desc()).limit(1))
    if context is None or PreparationPolicy.model_validate(context.config['policy']) != policy:
        return
    if context.as_of > now or context.result['frozenAt'] > now or context.result['frozenAt'] >= session_bounds(target.isoformat())[0]:
        return
    context = await _warm_baselines(runtime, context, policy, fetch=fetch, attempt_limit=3)
    runtime._profitability_status = {'phase': 'preparing_next_session', 'session': target.isoformat(),
        'baselineReady': sum(c['baselineStatus']=='ready' for c in context.result['candidates']),
        'candidates': len(context.result['candidates'])}


async def collect(runtime, *, fetch=fetch_window, quote_observer=None):
    from .research_economics import compare_entry_variants, evaluate_exit_variants, shares_vs_skip, entry_policy_study, entry_study_plans
    engine = runtime.engine; now = runtime.clock()
    if not settings(engine)['enabled'] or runtime.stopping:
        runtime._profitability_started = None
        return
    day = dt.datetime.fromtimestamp(now/1000, ET).date(); opens, closes = session_bounds(day.isoformat())
    if not is_trading_day(day) or not opens-45*60_000 <= now <= closes+120_000:
        await prewarm_next_session(runtime, fetch=fetch)
        return
    policy = read_policy(engine, 'practice')
    async with engine.sf() as session:
        context = await session.scalar(select(TechniqueRun).where(TechniqueRun.technique=='options_cartel',
            TechniqueRun.mode=='profit_context', TechniqueRun.config['session'].as_string()==day.isoformat(),
            TechniqueRun.config['portfolioId'].as_string()==policy.portfolio_id).order_by(TechniqueRun.created_at.desc()).limit(1))
        prep = await session.get(TechniqueRun, context.parent_run_id) if context else None
    if context is None or prep is None or context.result['frozenAt'] >= opens:
        runtime._profitability_status = {'phase': 'awaiting_preparation'}
        return
    if PreparationPolicy.model_validate(context.config['policy']) != policy:
        runtime._profitability_status = {'phase': 'fresh_preparation_required'}
        return
    if getattr(runtime, '_profitability_started', None) is None or getattr(runtime, '_profitability_context_id', None) != context.id:
        runtime._profitability_started = now
        runtime._profitability_context_id = context.id
    runtime._profitability_targets = {c['id']+':'+option['selected']['symbol']: {'contextId': context.id, 'candidateId': c['id'],
        'contract': option['selected']['symbol'], 'preparationId': context.parent_run_id,
        'day': day.isoformat()} for c in context.result['candidates']
        for option in [c.get('optionObservation') or {}, c.get('campaignOptionObservation') or {}]
        if option.get('selected') and option.get('timely')}
    tracked = getattr(runtime, '_profitability_tracked', set())
    track = getattr(getattr(engine, 'options', None), 'track', None)
    pending_tracks = [t['contract'] for t in runtime._profitability_targets.values() if t['contract'] not in tracked]
    for contract in pending_tracks[:3] if track else []:
        try:
            await asyncio.wait_for(track(contract), 5)
            tracked.add(contract)
        except (ValueError, OSError, httpx.HTTPError, TimeoutError):
            pass
    runtime._profitability_tracked = tracked
    watched = runtime._intraday_research_watched
    for symbol in ['SPY', 'QQQ', *[c['symbol'] for c in context.result['candidates']]]:
        if symbol not in watched:
            await engine.feed.watch(symbol); watched.add(symbol)
    context = await _warm_baselines(runtime, context, policy, fetch=fetch)
    now = runtime.clock(); boundary = min(closes, opens+max(0, (now-opens)//STEP)*STEP)
    if boundary < opens+STEP or now-boundary < 60_000:
        return
    key = identity(context.id, str(boundary))
    async with engine.sf() as session:
        already_observed = await session.get(TechniqueRun, key)
        if already_observed:
            await _pending_quotes(runtime, context, policy, quote_observer)
            return
        previous = await session.get(TechniqueRun, identity(context.id, str(boundary-STEP)))
        symbols = ['SPY', 'QQQ', *[c['symbol'] for c in context.result['candidates']]]
        stored = (await session.scalars(select(BarRow).where(BarRow.tf=='1m', BarRow.symbol.in_(symbols),
            BarRow.ts>=opens, BarRow.ts<boundary))).all()
    bars = [Bar(b.symbol, b.tf, b.ts, b.open, b.high, b.low, b.close, b.volume, source=b.source) for b in stored]
    market_observed_at = runtime.clock()
    markets = {d: directional_market(context.result['market'], bars, boundary, market_observed_at, d,
        previous.result.get('markets', {}).get(d) if previous else None) for d in ('long', 'short')}
    observations = []
    for candidate in context.result['candidates']:
        await asyncio.sleep(0)  # D4 (2026-09-18): yield between candidates so research never monopolises the loop
        market = markets[candidate['direction']]
        tape = [b for b in bars if b.symbol==candidate['symbol']]
        item = {'id': candidate['id'], 'symbol': candidate['symbol'], 'direction': candidate['direction'],
            'cohort': candidate['cohort'], 'status': 'waiting_market', 'reasons': [], 'entry': candidate.get('researchEntry'),
            'optionEligibility': 'not_evaluated', 'optionObservation': candidate.get('optionObservation'),
            'experiments': None, 'sourceEvidence': evidence({str(b.ts): pack(b) for b in tape}),
            'sourceBars': [pack(b) for b in tape if b.ts>=boundary-STEP]}
        if candidate['baselineStatus'] != 'ready':
            item.update(status='data_unavailable', reasons=[candidate.get('baselineReason') or 'Historical baseline warming'])
        else:
            plan = make_plan(candidate, day.isoformat(), candidate['baseline'])
            # Separate diagnostic cohort: market eligibility is recorded, not bypassed for trading.
            diagnostic_after = max(candidate['baselineReadyAt'], runtime._profitability_started)
            try:
                study = await _study(entry_policy_study, plan, tape, as_of_ms=boundary, entry_after=diagnostic_after)
                observed_at = runtime.clock()
                study.update(observedAt=observed_at, marketEligible=market['sustained'])
                saved_signals = dict(candidate.get('entryPolicySignals') or {})
                changed = False
                for alternative in study['rows']:
                    name = alternative['variant']; signal = alternative.get('signal')
                    if (name not in saved_signals and signal and signal['at']==boundary
                            and 0 <= observed_at-boundary <= 120000):
                        saved_signals[name] = {'signal': signal, 'observedAt': observed_at,
                            'entryAfter': diagnostic_after, 'decisionBars': [pack(b) for b in tape],
                            'marketEligible': market['sustained']}
                        changed = True
                    captured = saved_signals.get(name)
                    alternative['prospectiveConfirmation'] = captured is not None
                    alternative['observedSignalAt'] = captured['signal']['at'] if captured else None
                    if captured:
                        frozen = {b[0]: unpack(candidate['symbol'], b) for b in captured['decisionBars']}
                        evaluation = sorted([*frozen.values(), *[b for b in tape if b.ts not in frozen]], key=lambda b: b.ts)
                        outcome = evaluate_exit_variants(entry_study_plans(plan)[name],
                            ExitCampaign.model_validate(candidate['exitCampaign']), evaluation,
                            [DailyBar.model_validate(b) for b in candidate['daily']], signal=captured['signal'],
                            quantity=None, as_of_ms=boundary, entry_after=captured['observedAt'],
                            signal_after=captured['entryAfter'], costs=None)
                        alternative['outcome'] = outcome
                        alternative['marketEligibleAtSignal'] = captured['marketEligible']
                if changed and not runtime.stopping and settings(engine)['enabled'] and read_policy(engine, 'practice')==policy:
                    context = await _update_context(engine, context.id, {'entryPolicySignals': saved_signals}, candidate['id'])
                item['entryPolicyStudy'] = study
            except ValueError as exc:
                item['entryPolicyStudy'] = {'status': 'data_unavailable', 'reason': str(exc), 'placesOrders': False}
            if not item['entry'] and market['sustained']:
                after = max(market['improvedSince'], candidate['baselineReadyAt'], runtime._profitability_started)
                try:
                    if {b.ts for b in tape} != set(range(opens, boundary, 60000)):
                        raise ValueError('Current-session minute context is incomplete')
                    comparison = await _study(compare_entry_variants, plan, ExitCampaign.model_validate(candidate['exitCampaign']),
                        tape, as_of_ms=boundary, signal_after=after)
                    decision_at = runtime.clock()
                    read = comparison['baseline']
                    timely = 0 <= decision_at-boundary <= 120000
                    item.update(status=read['status'], entryRead=read, entryAfter=after, entryComparison=comparison,
                        observedAt=decision_at)
                    if read.get('signal') and read['signal']['at']==boundary and timely:
                        item['entry'] = read['signal']; item['status'] = 'research_confirmation'
                        item['decisionBars'] = [pack(b) for b in tape]
                        context = await _update_context(engine, context.id,
                            {'researchEntry': read['signal'], 'entryObservedAt': decision_at,
                             'decisionBars': item['decisionBars'], 'studyEntryAfter': after}, candidate['id'])
                    elif not candidate.get('targetRoomProbe') and timely:
                        # Only remove the target-R veto to identify a price
                        # confirmation for funded campaign diagnostics. This
                        # never becomes the baseline research entry or an arm.
                        probe = comparison['targetOnlyProbe']
                        if probe.get('signal') and probe['signal']['at']==boundary:
                            item['targetRoomProbe'] = probe['signal']
                            context = await _update_context(engine, context.id, {'targetRoomProbe': probe['signal'],
                                'probeObservedAt': decision_at, 'probeDefinition': 'target_room_only_v1',
                                'probeBaselineRejected': True, 'studyEntryAfter': after,
                                'decisionBars': [pack(b) for b in tape]}, candidate['id'])
                    if not timely and (read.get('signal') or comparison['targetOnlyProbe'].get('signal')):
                        item.update(status='stale_confirmation', reasons=['Confirmation was no longer timely when research evaluation completed'])
                except ValueError as exc:
                    item.update(status='data_unavailable', reasons=[str(exc)])
            if item['entry']:
                item['status'] = 'research_confirmed'
                option = candidate.get('optionObservation') or {}
                funding = option.get('funding') or {}
                quantity = funding.get('quantity') if option.get('timely') and option.get('signalAt')==item['entry']['at'] else None
                try:
                    frozen = {b[0]: unpack(candidate['symbol'], b) for b in candidate.get('decisionBars', [])}
                    evaluation = sorted([*frozen.values(), *[b for b in tape if b.ts not in frozen]], key=lambda b: b.ts)
                    item['evaluationBars'] = [pack(b) for b in evaluation]
                    premium = await _premium_evidence(engine, context, candidate, boundary)
                    item['experiments'] = await _study(evaluate_exit_variants, plan, ExitCampaign.model_validate(candidate['exitCampaign']),
                        evaluation, [DailyBar.model_validate(b) for b in candidate['daily']], signal=item['entry'],
                        quantity=quantity, as_of_ms=boundary, costs=None,
                        entry_after=max(candidate.get('entryObservedAt', item.get('observedAt', runtime.clock())), option.get('observedAt', 0)),
                        signal_after=candidate.get('studyEntryAfter'), quantity_basis='current_funding_estimate',
                        funding=funding if quantity is not None else None,
                        weak_environment=candidate.get('weakEnvironment'),
                        weak_environment_at=context.result['frozenAt'],
                        premium_input=premium)
                    if option.get('affordabilityOnly') and option.get('timely') and funding.get('cashCapUsd', 0)>0:
                        item['sharesComparison'] = await _study(shares_vs_skip, plan, ExitCampaign.model_validate(candidate['exitCampaign']),
                            evaluation, [DailyBar.model_validate(b) for b in candidate['daily']], signal=item['entry'],
                            as_of_ms=boundary, cash_budget=funding['cashCapUsd'], option_failures=['affordability'],
                            other_checks_passed=True, entry_after=max(candidate.get('entryObservedAt', item.get('observedAt', runtime.clock())), option['observedAt']),
                            signal_after=candidate.get('studyEntryAfter'),
                            costs={'fee_per_unit': 0, 'fee_per_order': funding['stockFeePerOrder']})
                except ValueError as exc:
                    item['experiments'] = {'status': 'unscorable', 'warnings': [str(exc)], 'placesOrders': False}
                # Option economics stay unknown until genuine contemporaneous
                # selection/quotes are captured. No price-only path becomes P&L.
                item['optionEligibility'] = option.get('status', 'quote_evidence_pending')
            if candidate.get('campaignEntry'):
                option = candidate.get('campaignOptionObservation') or {}; funding = option.get('funding') or {}
                try:
                    frozen = {b[0]: unpack(candidate['symbol'], b) for b in candidate.get('campaignDecisionBars', [])}
                    evaluation = sorted([*frozen.values(), *[b for b in tape if b.ts not in frozen]], key=lambda b: b.ts)
                    item['campaignEvaluationBars'] = [pack(b) for b in evaluation]
                    premium = await _premium_evidence(engine, context, candidate, boundary, campaign=True)
                    item['campaignExperiments'] = await _study(evaluate_exit_variants, plan, ExitCampaign.model_validate(candidate['exitCampaign']),
                        evaluation, [DailyBar.model_validate(b) for b in candidate['daily']], signal=candidate['campaignEntry'],
                        quantity=funding.get('quantity'), as_of_ms=boundary, costs=None,
                        entry_after=candidate['campaignEntryObservedAt'], signal_after=candidate.get('studyEntryAfter'),
                        entry_variant='campaign_static_target_v1', quantity_basis='current_funding_estimate',
                        funding=funding,
                        weak_environment=candidate.get('weakEnvironment'),
                        weak_environment_at=context.result['frozenAt'],
                        premium_input=premium)
                except ValueError as exc:
                    item['campaignExperiments'] = {'status': 'unscorable', 'warnings': [str(exc)], 'placesOrders': False}
            selected = (candidate.get('optionObservation') or {}).get('selected')
            if selected:
                from .research_quotes import snapshot_quote
                contract = selected.get('symbol') if isinstance(selected, dict) else selected
                item['optionQuote'] = snapshot_quote(engine, contract, runtime.clock)
        observations.append(item)
    if runtime.stopping or not settings(engine)['enabled'] or read_policy(engine, 'practice') != policy:
        return
    await _insert(engine, key, 'profit_watch', prep, runtime.clock(),
        {'boundary': boundary, 'contextId': context.id, 'markets': markets, 'candidates': observations,
         'phase': 'complete' if boundary==closes else 'observing'}, {'contextId': context.id})
    await _update_context(engine, context.id, {'latestObservationId': key, 'phase': 'complete' if boundary==closes else 'observing'})
    runtime._profitability_status = {'phase': 'complete' if boundary==closes else 'observing', 'lastObservedAt': now}
    await _pending_quotes(runtime, context, policy, quote_observer)


async def status(engine, day, portfolio_id=None):
    """Read-only public projection; no evaluation, subscription or recovery effects."""
    from .research_economics import DEFINITIONS
    config = settings(engine)
    out = {'day': day, 'session': day, 'workspace': 'practice', 'researchOnly': True, 'placesOrders': False,
        'enabled': config['enabled'], 'version': VERSION, 'status': 'awaiting_preparation' if config['enabled'] else 'disabled',
        'asOfMs': None, 'contextId': None, 'preparationId': None,
        'denominator': {'discovered': 0, 'evaluated': 0, 'eligible': 0, 'observed': 0, 'boundedLimit': config['candidateCap'],
            'omitted': 0, 'primaryEligible': 0, 'bearishEligible': 0, 'baselineReady': 0},
        'rankings': {}, 'candidates': [], 'bearish': {'status': 'awaiting_preparation', 'eligible': 0, 'observed': 0, 'rows': []},
        'experiments': list(DEFINITIONS), 'gaps': [], 'protocol': {'version': VERSION}, 'contexts': []}
    if not portfolio_id:
        out.update(phase=out['status'], rows=[])
        out['gaps'] = [{'kind': 'account', 'count': 1, 'reason': 'No configured Practice account'}]
        return out
    async with engine.sf() as session:
        query = select(TechniqueRun).where(TechniqueRun.technique=='options_cartel', TechniqueRun.mode=='profit_context',
            TechniqueRun.config['session'].as_string()==day, TechniqueRun.config['workspace'].as_string()=='practice')
        if portfolio_id:
            query = query.where(TechniqueRun.config['portfolioId'].as_string()==portfolio_id)
        context = await session.scalar(query.order_by(TechniqueRun.created_at.desc()).limit(1))
        last = await session.get(TechniqueRun, context.result.get('latestObservationId')) if context and context.result.get('latestObservationId') else None
    if context:
        observed = {c['id']: c for c in last.result['candidates']} if last else {}
        rows = [{**{k: c.get(k) for k in ('id','symbol','direction','cohort','baselineRank','leaderRank','baselineSelected','leaderSelected')},
            'status': observed.get(c['id'], {}).get('status', c['baselineStatus']),
            'reasons': observed.get(c['id'], {}).get('reasons') or ([c['baselineReason']] if c.get('baselineReason') else []),
            'entryPolicyStudy': observed.get(c['id'], {}).get('entryPolicyStudy'),
            'entry': observed.get(c['id'], {}).get('entry'), 'experiments': observed.get(c['id'], {}).get('experiments'),
            'campaignExperiments': observed.get(c['id'], {}).get('campaignExperiments'),
            'sharesComparison': observed.get(c['id'], {}).get('sharesComparison'),
            'entryComparison': c.get('fundedEntryComparison') or observed.get(c['id'], {}).get('entryComparison'),
            'optionObservation': c.get('optionObservation'), 'optionQuote': observed.get(c['id'], {}).get('optionQuote'),
            'targetRoomProbe': c.get('targetRoomProbe'), 'gaps': [], 'baselineStatus': c['baselineStatus'],
            'baselineAttempts': c.get('baselineAttempts', 0), 'nextBaselineAt': c.get('nextBaselineAt')} for c in context.result['candidates']]
        bearish = [r for r in rows if r['cohort']=='bearish']
        out.update(status=context.result['phase'], phase=context.result['phase'], asOfMs=last.as_of if last else context.as_of,
            contextId=context.id, preparationId=context.parent_run_id, protocol=context.result['protocol'],
            rankings=context.result['rankings'], candidates=rows, rows=rows,
            denominator={**context.result['denominator'], 'observed': len(observed),
                'baselineReady': sum(c['baselineStatus']=='ready' for c in context.result['candidates'])},
            bearish={'status': context.result['phase'], 'eligible': context.result['denominator']['bearishEligible'],
                'observed': sum(r['id'] in observed for r in bearish), 'rows': bearish},
            contexts=[{'id': context.id, 'preparationId': context.parent_run_id, 'frozenAt': context.result['frozenAt']}])
        out['gaps'] = [{'kind': 'baseline', 'count': sum(c['baselineStatus']!='ready' for c in context.result['candidates']),
            'reason': 'Historical coverage remains pending or insufficient; entry thresholds are unchanged'},
            {'kind': 'capacity', 'count': context.result['denominator']['omitted'], 'reason': 'Qualified candidates outside the explicit research cap'},
            {'kind': 'option_economics', 'count': sum(bool(r['entry']) for r in rows),
                'reason': 'Option funding, fills and costs are not established by stock confirmation'}]
    out.setdefault('phase', out['status']); out.setdefault('rows', out['candidates'])
    return out
