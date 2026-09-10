"""Visible observation continuity and bounded, context-only recovery."""
from __future__ import annotations

import datetime as dt

from ...marketstructure.aggregate import bar_session
from ...marketstructure.market_calendar import is_trading_day
from ...marketstructure.sessions import session_bounds, session_date
from .preparation_readiness import load_session_context


def coverage(state, now, *, day=None):
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
    present = {int(k) for k in state.get('minutes', {}) if opens <= int(k) < end}
    recoveries = [r for r in state.get('observationRecoveries', []) if r.get('day') == day and r.get('inSession')]
    return {'session': day, 'expectedMinutes': expected, 'recordedMinutes': len(present),
            'missingMinutes': max(0, expected-len(present)),
            'overdueMissingMinutes': sum(t not in present for t in range(opens, min(end, now//60000*60000-120000), 60000)), 'recoveries': len(recoveries),
            'lastRecovery': recoveries[-1] if recoveries else None,
            'lastObservedMinute': state.get('lastMinute'), 'repairError': state.get('gapRepairError'),
            'note': 'Recovered history restores context; it does not prove uninterrupted observation or replay missed entries.'}


def recovery_record(state, *, now, reason, added):
    return [*state.get('observationRecoveries', []), {'at': now, 'day': session_date(now),
        'inSession': bar_session(now) == 'rth', 'reason': reason, 'addedMinutes': added,
        'previousObservedMinute': state.get('lastMinute')}][-100:]


async def repair_gaps(runtime, *, load=load_session_context):
    """One owned task, at most five plans per pass, at most once/5min per plan."""
    now = runtime.clock()
    if bar_session(now) != 'rth':
        return
    attempted = 0
    for rid, cached in list(runtime.rows.items()):
        if runtime.stopping or attempted >= 5:
            break
        if cached['status'] != 'armed' or cached['state']['phase'] != 'waiting':
            continue
        health = coverage(cached['state'], now, day=session_date(now))
        if not health['overdueMissingMinutes'] or now-cached['state'].get('lastGapRepairAt', 0) < 300_000:
            continue
        attempted += 1
        async with runtime.engine.sf() as session, session.begin():
            row = await runtime.repository._locked(session, rid)
            if row.status != 'armed' or row.state['phase'] != 'waiting':
                continue
            row.state = {**row.state, 'lastGapRepairAt': now}
        try:
            bars = await load(runtime.engine, runtime.plans[rid], now)
            async with runtime.engine.sf() as session, session.begin():
                row = await runtime.repository._locked(session, rid)
                if runtime.stopping or row.status != 'armed' or row.state['phase'] != 'waiting':
                    continue
                state = row.state
                minutes = dict(state.get('minutes', {}))
                before = len(minutes)
                for b in bars:
                    if b.symbol == row.symbol and b.tf == '1m' and b.ts+60_000 <= now:
                        minutes.setdefault(str(b.ts), b.to_row())
                added = len(minutes)-before
                recovered_at = runtime.clock()
                row.state = {**state, 'minutes': minutes, 'gapRepairError': None}
                if added:
                    row.state = {**row.state, 'observeAfter': max(state.get('observeAfter', state['armedAt']), recovered_at),
                        'observationRecoveries': recovery_record(state, now=recovered_at, reason='missing_minute_repair', added=added)}
                snapshot = runtime.repository.view(row)
            runtime.rows[rid] = snapshot
            if added:
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
