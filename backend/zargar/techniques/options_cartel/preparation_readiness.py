"""Causal preparation checks and durable entry explanations, without order effects."""
from __future__ import annotations

from ...domain import Bar
from ...marketstructure.sessions import session_bounds, session_date
from .data_quality import trusted


def baseline_coverage(plan):
    opens, closes = session_bounds(plan.first_session.isoformat())
    expected = (closes-opens)//(plan.entry.timeframe_minutes*60_000)
    missing = [i for i in range(expected) if plan.volume_baseline.get(i, 0) <= 0]
    usable = [i for i in range(max(0, expected-1)) if i not in missing]
    def clock_label(slot, offset=0):
        minutes = 9*60+30+(slot+offset)*plan.entry.timeframe_minutes
        return f'{minutes//60:02d}:{minutes%60:02d}'
    return {"expected": expected, "available": expected-len(missing), "missing": missing,
            "policy": plan.entry.baseline_policy, "limited": bool(missing), "usableEntryPeriods": usable,
            "entryWindows": [{'slot': i, 'startET': clock_label(i), 'confirmationET': clock_label(i, 1)} for i in usable],
            "ready": not missing if plan.entry.baseline_policy == 'full_session' else bool(usable)}



def entry_readiness(plan, minutes: list[Bar], now: int):
    coverage = baseline_coverage(plan)
    reasons = []
    terminal = False
    terminal_status = None
    if not coverage['ready']:
        reasons.append(f"Volume baseline covers {coverage['available']}/{coverage['expected']} periods; no usable entry window under {coverage['policy']} policy. Rebuild the plan.")
    if now >= session_bounds(plan.last_session.isoformat())[1]:
        reasons.append('Entry window expired; prepare a new plan.')
        terminal = True
        terminal_status = 'expired'
    opens, closes = session_bounds(session_date(now))
    if opens <= now < closes and plan.first_session.isoformat() <= session_date(now) <= plan.last_session.isoformat():
        if (plan.entry.baseline_policy == 'covered_periods' and session_date(now) == plan.last_session.isoformat()
                and not any(opens+i*plan.entry.timeframe_minutes*60000 >= now for i in coverage['usableEntryPeriods'])):
            reasons.append('No supported confirmation period remains for a newly armed plan today.')
        tape = {b.ts: b for b in minutes if b.symbol == plan.symbol and b.tf == '1m' and opens <= b.ts and b.ts+60_000 <= now}
        end = now//60_000*60_000
        missing = sum(t not in tape for t in range(opens, end, 60_000))
        untrusted = sum(not trusted(b, simulation=plan.entry.allow_simulated_bars) for b in tape.values()) if plan.entry.require_exchange_bars else 0
        if untrusted:
            reasons.append(f'{untrusted} session minutes lack verified provenance; recover history before arming.')
        if missing:
            reasons.append(f'Missing {missing} completed session minutes since the open; recover history before arming.')
        if end > opens and (not tape or max(tape) < end-120_000):
            reasons.append('No recent completed underlying bar; waiting for current market data.')
        sign = 1 if plan.direction == 'long' else -1
        step = plan.entry.timeframe_minutes*60000
        for start in range(opens, min(end, closes), step):
            bucket = [tape[t] for t in range(start, start+step, 60000) if t in tape]
            if (len(bucket) == plan.entry.timeframe_minutes and (not plan.entry.require_exchange_bars or all(trusted(b, simulation=plan.entry.allow_simulated_bars) for b in bucket))
                    and (bucket[-1].close-plan.invalidation)*sign <= 0):
                terminal = True
                terminal_status = 'invalidated'
                reasons.append('A completed confirmation already invalidated this plan; a rebound cannot revive it.')
                break
        if tape:
            close = tape[max(tape)].close
            sign = 1 if plan.direction == 'long' else -1
            if (close-plan.targets[0])*sign >= 0:
                reasons.append('First target already reached before arming; prepare a new setup instead of chasing.')
                if not terminal and (not plan.entry.require_exchange_bars or trusted(tape[max(tape)], simulation=plan.entry.allow_simulated_bars)):
                    terminal = True
                    terminal_status = 'target_passed'
            if (close-plan.invalidation)*sign <= 0:
                reasons.append('Reviewed invalidation already broken before arming.')
    return {'terminalStatus': terminal_status, 'terminal': terminal, 'ready': not reasons, 'reasons': reasons, 'baseline': coverage, 'checkedAt': now}


def retain_decisions(previous, observation):
    """Keep distinct causal decisions even when restart advances observation cutoff."""
    rows = { (r.get('at'), r.get('decision'), r.get('reason')): r for r in previous or [] }
    for row in observation.get('trace', []):
        rows[(row.get('at'), row.get('decision'), row.get('reason'))] = row
    return sorted(rows.values(), key=lambda r: r.get('at', 0))[-500:]


async def load_session_context(engine, plan, now, *, fetch=None):
    """Bounded read-only recovery; returned bars seed this plan, not another runner."""
    import asyncio

    import httpx
    from sqlalchemy import select

    from ...marketstructure.history import UA, fetch_window
    from ...models import BarRow
    from .history_cache import cached_bars, read_cache, write_cache
    opens, closes = session_bounds(session_date(now))
    if not opens <= now < closes:
        return []
    async with engine.sf() as session:
        rows = (await session.scalars(select(BarRow).where(BarRow.symbol == plan.symbol,
            BarRow.tf == '1m', BarRow.ts >= opens, BarRow.ts+60_000 <= now))).all()
    tape = {r.ts: Bar(r.symbol, '1m', r.ts, r.open, r.high, r.low, r.close, r.volume, source=r.source) for r in rows}
    cached = await read_cache(engine, plan.symbol, '1m', 'cartel-session-recovery:v1', now)
    if cached:
        for b in cached_bars(cached, plan.symbol, '1m'):
            if opens <= b.ts and b.ts+60000 <= now and (b.ts not in tape or trusted(b) and not trusted(tape[b.ts])):
                tape[b.ts] = b
    expected = range(opens, now//60_000*60_000, 60_000)
    simulated = getattr(getattr(engine, 'config', None), 'quote_source', None) == 'sim'
    if any(t not in tape or not trusted(tape[t]) for t in expected) and (fetch is not None or not simulated):
        async with httpx.AsyncClient(headers={'User-Agent': UA}, timeout=20.) as client:
            recovered = await asyncio.wait_for((fetch or fetch_window)(plan.symbol, '1m', opens, now, client=client), 25.)
        for b in recovered:
            if (b.symbol == plan.symbol and b.tf == '1m' and b.ts % 60_000 == 0 and opens <= b.ts and b.ts+60_000 <= now
                    and (b.ts not in tape or (trusted(b) and not trusted(tape[b.ts])))):
                tape[b.ts] = b
    result = sorted(tape.values(), key=lambda b: b.ts)
    await write_cache(engine, plan.symbol, '1m', 'cartel-session-recovery:v1', opens, now, now, result)
    return result


def automatic_valid_until(plan):
    """Automatic evidence survives weekends but ends with its intended entry session."""
    return session_bounds(plan.first_session.isoformat())[1]
