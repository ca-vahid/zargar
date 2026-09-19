"""Visible observation continuity and bounded, context-only recovery."""
from __future__ import annotations

import datetime as dt

from ...marketstructure.aggregate import bar_session
from ...marketstructure.market_calendar import is_trading_day
from ...marketstructure.sessions import session_bounds, session_date
from .data_quality import evidence, merge
from .preparation_readiness import load_session_context


def coverage(state, now, *, day=None, use_verified=False):
    day = day or state.get('day') or session_date(now)
    opens, closes = session_bounds(day)
    end = min(closes, now//60_000*60_000)
    signal_at = (state.get('signal') or {}).get('at')
    if signal_at and opens <= signal_at <= closes:
        end = min(end, signal_at)
    elif (state.get('observation') or {}).get('status') == 'invalidated' and state.get('lastMinute'):
        end = min(end, state['lastMinute']+60000)
    if not is_trading_day(dt.date.fromisoformat(day)):
        end = opens
    expected = max(0, (end-opens)//60_000)
    from .nonemission import minute_set
    verified = minute_set(state.get('verifiedIntervals',{}), state.get('verifiedIntervalSymbol',''), now) if use_verified else set()
    verified = {t for t in verified if opens <= t < end and not
                (len(state.get('minutes',{}).get(str(t),[])) > 6 and state['minutes'][str(t)][6] == 'exchange')}
    present = {int(k) for k in state.get('minutes', {}) if opens <= int(k) < end} | verified
    recoveries = [r for r in state.get('observationRecoveries', []) if r.get('day') == day and r.get('inSession')]
    quality = evidence({k:v for k,v in state.get('minutes', {}).items() if int(k) in present})
    degraded = sum(1 for k,v in state.get('minutes',{}).items() if int(k) in present and int(k) not in verified and (len(v)<7 or v[6]!='exchange'))
    return {'dataEvidence': quality, 'verifiedNonemissionMinutes': len(verified), 'untrustedMinutes': degraded, 'session': day, 'expectedMinutes': expected, 'recordedMinutes': len(present),
            'missingMinutes': max(0, expected-len(present)),
            'overdueMissingMinutes': sum(t not in present for t in range(opens, min(end, now//60000*60000-120000), 60000)), 'recoveries': len(recoveries),
            'lastRecovery': recoveries[-1] if recoveries else None,
            'lastObservedMinute': state.get('lastMinute'), 'repairError': state.get('gapRepairError'),
            'note': 'Recovered history restores context; it does not prove uninterrupted observation or replay missed entries.'}


def recovery_record(state, *, now, reason, added):
    return [*state.get('observationRecoveries', []), {'at': now, 'day': session_date(now),
        'inSession': bar_session(now) == 'rth', 'reason': reason, 'addedMinutes': added,
        'previousObservedMinute': state.get('lastMinute')}][-100:]


def plan_coverage(plan, state, now, *, use_verified=False):
    """A future plan owes no minutes from the day it happened to be armed."""
    first, last = plan.first_session.isoformat(), plan.last_session.isoformat()
    day = session_date(now) if state.get('phase') == 'waiting' else state.get('day') or session_date(now)
    day = min(last, max(first, day))
    return coverage(state, now, day=day, use_verified=use_verified)


def repair_cutoff(plan, state, now, *, use_verified=False):
    """Practice: exclude every already-closed bucket, allow the next fresh close.

    Arming, restart and pause boundaries remain unchanged. A data repair inside
    an open bucket must not unnecessarily discard that bucket's *future* close.
    """
    cutoff=now
    if use_verified:
        opens,_=session_bounds(session_date(now))
        step=plan.entry.timeframe_minutes*60000
        cutoff=opens+max(0,(now-opens)//step)*step
    return max(state.get('observeAfter',state['armedAt']),cutoff)


async def repair_gaps(runtime, *, load=load_session_context):
    """One owned task, five plans/pass. Verified Practice: 1min; other paths: 5min."""
    now = runtime.clock()
    if bar_session(now) != 'rth':
        return
    attempted = 0
    for rid, cached in list(runtime.rows.items()):
        if runtime.stopping or attempted >= 5:
            break
        if cached['status'] != 'armed' or cached['state']['phase'] != 'waiting':
            continue
        plan = runtime.plans[rid]
        if not plan.first_session.isoformat() <= session_date(now) <= plan.last_session.isoformat():
            continue
        from .nonemission import VERSION, enabled
        verified_enabled=enabled(runtime.engine,cached)
        health = plan_coverage(plan, cached['state'], now, use_verified=verified_enabled)
        first_verification = verified_enabled and cached['state'].get('providerIntervalVersion') != VERSION
        retry_interval=60_000 if verified_enabled else 300_000
        if not (health['overdueMissingMinutes'] or (runtime.plans[rid].entry.require_exchange_bars and health['untrustedMinutes'])) or (not first_verification and now-cached['state'].get('lastGapRepairAt', 0) < retry_interval):
            continue
        attempted += 1
        async with runtime.engine.sf() as session, session.begin():
            row = await runtime.repository._locked(session, rid)
            if row.status != 'armed' or row.state['phase'] != 'waiting':
                continue
            row.state = {**row.state, 'lastGapRepairAt': now}
            if enabled(runtime.engine,cached):
                row.state = {**row.state,'providerIntervalVersion':VERSION}
        try:
            bars = await load(runtime.engine, runtime.plans[rid], now)
            from .nonemission import effective, enabled, minute_set, verify
            proofs = {}
            proof_error = None
            attempted_intervals = []
            if enabled(runtime.engine, cached):
                import asyncio
                covered = minute_set(effective(runtime.engine,cached),cached['symbol'],now)
                opens, closes = session_bounds(session_date(now))
                tape = dict(cached['state'].get('minutes',{}))
                for b in bars:
                    if b.symbol==cached['symbol'] and b.tf=='1m' and b.ts+60000<=now:
                        merge(tape,b)  # do not probe intervals whose native bars just arrived
                candidates = [t for t in range(opens,min(closes,now//60000*60000),60000)
                              if t not in covered and (str(t) not in tape or len(tape[str(t)])<7 or tape[str(t)][6]!='exchange')]
                counts = cached['state'].get('providerIntervalAttempts',{})
                attempted_intervals = sorted((t for t in candidates if t+180000<=now),key=lambda t:(counts.get(str(t),0),t))[:8]
                try:
                    async with asyncio.timeout(20):
                        proofs = await verify(runtime.engine.config,cached['symbol'],attempted_intervals,runtime.clock)
                except Exception as exc:  # optional verification must not discard successful ordinary recovery
                    proof_error = f'Provider interval verification failed: {type(exc).__name__}; ordinary history repair continued'
            async with runtime.engine.sf() as session, session.begin():
                row = await runtime.repository._locked(session, rid)
                if runtime.stopping or row.status != 'armed' or row.state['phase'] != 'waiting':
                    continue
                state = row.state
                minutes = dict(state.get('minutes', {}))
                changed = 0
                for b in bars:
                    if b.symbol == row.symbol and b.tf == '1m' and b.ts+60_000 <= now:
                        changed += int(merge(minutes, b))
                added = changed
                recovered_at = runtime.clock()
                attempts = dict(state.get('providerIntervalAttempts',{}))
                for t in attempted_intervals:
                    attempts[str(t)] = attempts.get(str(t),0)+1
                row.state = {**state, 'minutes': minutes, 'gapRepairError': proof_error,
                             'providerIntervalAttempts':attempts}
                if proofs:
                    row.state = {**row.state,'verifiedIntervals':{**state.get('verifiedIntervals',{}),**proofs},
                                 'verifiedIntervalSymbol':row.symbol}
                if added or proofs:
                    row.state = {**row.state, 'observeAfter': repair_cutoff(plan,state,recovered_at,use_verified=enabled(runtime.engine,runtime.repository.view(row))),
                        'observationRecoveries': recovery_record(state, now=recovered_at, reason='missing_minute_repair', added=added)}
                    row.state['observationRecoveries'][-1]['verifiedIntervalsAdded'] = len(proofs)
                snapshot = runtime.repository.view(row)
            runtime.rows[rid] = snapshot
            if added or proofs:
                await runtime.repository._journal(snapshot, 'history_gap_repaired')
            runtime._publish(rid)
        except Exception as exc:  # noqa: BLE001 - report data-service failures without interrupting exits
            async with runtime.engine.sf() as session, session.begin():
                row = await runtime.repository._locked(session, rid)
                if runtime.stopping or row.status != 'armed' or row.state['phase'] != 'waiting':
                    continue
                row.state = {**row.state, 'gapRepairError': f'Historical gap repair failed: {type(exc).__name__}'}
                snapshot = runtime.repository.view(row)
            runtime.rows[rid] = snapshot
            runtime._publish(rid)
