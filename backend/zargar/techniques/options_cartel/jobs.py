"""Cartel-owned scheduled research and completed-history recovery."""
from __future__ import annotations

import datetime as dt
from typing import Literal

import httpx
from pydantic import Field, model_validator
from sqlalchemy import select

from ...marketstructure.history import UA, fetch_window
from ...marketstructure.market_calendar import is_trading_day
from ...marketstructure.sessions import ET
from ...models import Event
from ...scheduler import SCHEDULED_JOB_FAILED, SCHEDULED_JOB_RAN
from .collect import normalize_daily
from .rules import ScreenProfile
from .scans import ScanRequest, scan_focus_list
from .service import CartelService, WireModel

PREFIX = 'techniques.options_cartel.'
JOB_NAMES = ('options_cartel_preopen_recovery', 'options_cartel_close_recovery', 'options_cartel_nightly_scan')


def stopping(engine):
    return bool(getattr(getattr(engine, 'cartel_observer', None), 'stopping', False))


class ScheduleInput(WireModel):
    scan_enabled: bool = False
    scan_symbols: list[str] = Field(default_factory=list, max_length=20)
    scan_profile: ScreenProfile = 'september_2026'
    scan_direction: Literal['long', 'short'] = 'long'
    recovery_enabled: bool = False

    @model_validator(mode='after')
    def valid_universe(self):
        if self.scan_symbols or self.scan_enabled:
            self.scan_symbols = ScanRequest(symbols=self.scan_symbols).symbols
        return self


async def schedule_status(engine):
    jobs = [j for j in engine.scheduler.status() if j['name'].startswith('options_cartel_')]
    async with engine.sf() as session:
        for job in jobs:
            event = await session.scalar(select(Event).where(
                Event.type.in_((SCHEDULED_JOB_RAN, SCHEDULED_JOB_FAILED)),
                Event.payload['job'].as_string() == job['name']).order_by(Event.ts.desc(), Event.id.desc()).limit(1))
            job['lastOutcome'] = None if event is None else {
                'at': event.ts.isoformat(), 'day': event.payload.get('date'),
                'status': 'failed' if event.type == SCHEDULED_JOB_FAILED else 'finished',
                'result': event.payload.get('result'), 'error': event.payload.get('error')}
    return {'configuration': ScheduleInput.model_validate({
        key: engine.settings.get(PREFIX+key) for key in ScheduleInput.model_fields}).model_dump(by_alias=True),
        'jobs': jobs}


async def nightly_scan(engine, *, now_ms=None, scan=scan_focus_list):
    if stopping(engine):
        return {'status': 'stopping'}
    if not engine.settings.get(PREFIX+'scan_enabled', False):
        return {'status': 'disabled'}
    now = now_ms if now_ms is not None else int(dt.datetime.now(dt.UTC).timestamp()*1000)
    if not is_trading_day(dt.datetime.fromtimestamp(now/1000, ET).date()):
        return {'status': 'non_trading_day'}
    symbols = engine.settings.get(PREFIX+'scan_symbols', [])
    if not symbols:
        return {'status': 'empty_universe'}
    request = ScanRequest(symbols=symbols, as_of_ms=now,
        profile=engine.settings.get(PREFIX+'scan_profile', 'september_2026'),
        direction=engine.settings.get(PREFIX+'scan_direction', 'long'))
    result = await scan(CartelService(engine), request, now_ms=now)
    return {'status': result['verdict'], 'runId': result['runId'], **result['result']['summary']}


async def recover_positions(engine, *, now_ms=None, fetch=fetch_window):
    if stopping(engine):
        return {'status': 'stopping'}
    if not engine.settings.get(PREFIX+'recovery_enabled', False):
        return {'status': 'disabled'}
    manager = engine.position_manager
    now = now_ms if now_ms is not None else manager.now_ms()
    rows = []
    cached = {}
    async with httpx.AsyncClient(headers={'User-Agent': UA}, timeout=25.) as client:
        for summary in manager.positions():
            p = manager.get(summary['id'])
            if p is None or p.technique != 'options_cartel' or not p.open_legs \
                    or p.policy.get('adapter') != 'options_cartel' or p.policy['cartel'].get('residualOf'):
                continue
            adapter = manager._policy_adapter(p)
            if adapter is None:
                rows.append({'positionId': p.id, 'status': 'unavailable', 'reason': 'Position adapter unavailable'})
                continue
            try:
                if p.symbol not in cached:
                    bars = await fetch(p.symbol, '1d', now-550*86_400_000, now, client=client)
                    cached[p.symbol] = normalize_daily(bars, p.symbol, now)
                if stopping(engine):
                    return {'status': 'stopping', 'positions': rows}
                result = await adapter.recover_daily(manager, p, cached[p.symbol],
                    source='Scheduled shared-provider completed daily history', as_of_ms=now)
                rows.append({'positionId': p.id, 'status': 'recovered',
                    'addedSessions': result['addedSessions'], 'missedCloses': result['missedCloses'],
                    'catchupStatus': (result.get('catchupReview') or {}).get('status')})
            except (ValueError, httpx.HTTPError, OSError) as exc:
                rows.append({'positionId': p.id, 'status': 'unavailable', 'reason': str(exc)[:1000]})
    return {'status': 'partial' if any(r['status'] == 'unavailable' for r in rows) else 'complete',
            'positions': rows, 'recoveryMayTriggerManagedExits': True}


def register_jobs(engine):
    # Register once at runtime attachment. Shared scheduler provides persistent
    # daily execution markers and failure journaling; no other jobs are replaced.
    engine.scheduler.register('options_cartel_preopen_recovery', '09:05', lambda: recover_positions(engine))
    engine.scheduler.register('options_cartel_close_recovery', '20:10', lambda: recover_positions(engine))
    engine.scheduler.register('options_cartel_nightly_scan', '20:15', lambda: nightly_scan(engine))


def unregister_jobs(engine):
    scheduler = getattr(engine, 'scheduler', None)
    if scheduler is not None:
        for name in JOB_NAMES:
            scheduler.unregister(name)
