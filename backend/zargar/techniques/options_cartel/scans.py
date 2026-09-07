"""Bounded, source-dated focus-list collection; research only."""
from __future__ import annotations

import asyncio
import datetime as dt
import re
from typing import Literal

import httpx
from pydantic import Field, model_validator
from sqlalchemy import select

from ... import events as ev
from ...domain import new_id
from ...models import TechniqueRun
from .collect import CollectInput, collect_inputs
from .rules import ScreenProfile
from .service import TECHNIQUE, FactsInput, WireModel


class ScanRequest(WireModel):
    industry_snapshot_id: str | None = Field(default=None, max_length=64)
    symbols: list[str] = Field(min_length=1, max_length=20)
    profile: ScreenProfile = "september_2026"
    direction: Literal["long", "short"] = "long"
    as_of_ms: int | None = Field(default=None, ge=0)
    facts: dict[str, FactsInput] = Field(default_factory=dict)
    fundamentals_snapshot_ids: dict[str, str] = Field(default_factory=dict, max_length=20)
    membership_snapshot_ids: dict[str, str] = Field(default_factory=dict, max_length=20)

    @model_validator(mode="after")
    def universe(self):
        self.symbols = [s.strip().upper() for s in self.symbols]
        if len(set(self.symbols)) != len(self.symbols) or any(
                not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", s) for s in self.symbols):
            raise ValueError("scan symbols must be unique supported US equity symbols")
        if set(self.facts)-set(self.symbols) or any(k != f.symbol.upper() for k, f in self.facts.items()):
            raise ValueError("fundamental evidence must match a symbol in this scan")
        if set(self.fundamentals_snapshot_ids)-set(self.symbols) or any(
                not value.strip() or len(value) > 64 for value in self.fundamentals_snapshot_ids.values()):
            raise ValueError('fundamentals capture IDs must match scan symbols and contain 1 to 64 characters')
        if set(self.membership_snapshot_ids)-set(self.symbols) or any(
                not value.strip() or len(value) > 64 for value in self.membership_snapshot_ids.values()):
            raise ValueError('membership capture IDs must match scan symbols and contain 1 to 64 characters')
        return self


async def retry_scan(service, run_id, *, collect=collect_inputs, now_ms=None, on_started=None):
    previous = await service._load(run_id)
    if previous.mode != 'scan' or previous.status == 'running':
        raise ValueError('retry requires a finished or interrupted Cartel scan')
    rows = previous.result['rows']
    if not any(row['status'] in ('pending', 'data_error') for row in rows):
        raise ValueError('this scan has no unresolved symbols')
    body = ScanRequest.model_validate({**previous.config['request'], 'as_of_ms': previous.as_of})
    seeds = [dict(row, reused=True) if row['status'] not in ('pending', 'data_error') else
             {'symbol': row['symbol'], 'status': 'pending'} for row in rows]
    return await scan_focus_list(service, body, collect=collect, now_ms=now_ms,
                                 seed_rows=seeds, parent_run_id=previous.id, on_started=on_started)


async def scan_focus_list(service, body: ScanRequest, *, collect=collect_inputs, now_ms=None,
                          seed_rows=None, parent_run_id=None, on_started=None):
    active = getattr(service.engine, '_cartel_scan_tasks', None)
    if active is None:
        active = service.engine._cartel_scan_tasks = {}
    run_id = new_id()
    active[run_id] = asyncio.current_task()
    try:
        return await _scan_focus_list(service, body, collect=collect, now_ms=now_ms, run_id=run_id,
                                     seed_rows=seed_rows, parent_run_id=parent_run_id, on_started=on_started)
    finally:
        active.pop(run_id, None)


async def _scan_focus_list(service, body, *, collect, now_ms, run_id, seed_rows, parent_run_id, on_started):
    now = now_ms if now_ms is not None else int(dt.datetime.now(dt.UTC).timestamp()*1000)
    at = body.as_of_ms if body.as_of_ms is not None else now
    if at > now:
        raise ValueError("scan cutoff cannot be in the future")
    slots = asyncio.Semaphore(2)
    initial = seed_rows if seed_rows is not None else [{'symbol': symbol, 'status': 'pending'} for symbol in body.symbols]
    parent = TechniqueRun(id=run_id, technique=TECHNIQUE, symbol='MULTI', as_of=at,
        parent_run_id=parent_run_id,
        primary_tf='1d', mode='scan', trigger='manual', status='running', verdict='running', tags=['cartel:scan'],
        config={'request': body.model_dump(mode='json'), 'asOfMs': at,
                'dataSource': 'User-selected universe; shared market history and separately supplied fundamental evidence.'},
        result={'placesOrders': False, 'rows': initial,
                'summary': {'requested': len(body.symbols), 'qualified': sum(r['status'] == 'setup' for r in initial),
                            'dataErrors': 0, 'completed': sum(r['status'] != 'pending' for r in initial)},
                'warnings': ['This is a selected-symbol scan, not a complete market universe.',
                             'Missing fundamentals or industry ranks remain unknown. Review an analysis before preparing a plan.']})
    async with service.engine.sf() as session:
        session.add(parent)
        await session.commit()
    await service.engine.journal.append(ev.TECHNIQUE_RUN_STARTED,
        {'runId': parent.id, 'symbol': 'MULTI', 'technique': TECHNIQUE, 'mode': 'scan'},
        aggregate_type='technique_run', aggregate_id=parent.id)
    if on_started is not None:
        on_started(service._view(parent, detail=True))

    async def checkpoint(result=None, *, terminal=False, error=None):
        async with service.engine.sf() as session:
            row = await session.scalar(select(TechniqueRun).where(TechniqueRun.id == parent.id,
                TechniqueRun.technique == TECHNIQUE).with_for_update())
            if row.status != 'running':
                raise ValueError('completed scan cannot be rewritten')
            rows = [result if result and r['symbol'] == result['symbol'] else r for r in row.result['rows']]
            errors = sum(r['status'] == 'data_error' for r in rows)
            row.result = {**row.result, 'rows': rows, 'summary': {'requested': len(rows),
                'qualified': sum(r['status'] == 'setup' for r in rows), 'dataErrors': errors,
                'completed': sum(r['status'] != 'pending' for r in rows)}}
            if terminal:
                row.status = 'failed' if error else 'done'
                row.verdict = 'interrupted' if error else 'data_error' if errors == len(rows) else 'partial' if errors else 'complete'
                row.error = error
                row.finished_at = dt.datetime.now(dt.UTC)
            await session.commit()
            return service._view(row, detail=True)

    async def one(symbol):
        async with slots:
            try:
                inputs, provenance = await collect(CollectInput(symbol=symbol, as_of_ms=at,
                    membership_snapshot_id=body.membership_snapshot_ids.get(symbol),
                    fundamentals_snapshot_id=body.fundamentals_snapshot_ids.get(symbol),
                    industry_snapshot_id=body.industry_snapshot_id,
                    profile=body.profile, direction=body.direction, facts=body.facts.get(symbol)), now_ms=now)
                saved = await service.analyze(inputs, collection=provenance, parent_run_id=parent.id)
            except (KeyError, ValueError, httpx.HTTPError, OSError) as exc:
                # No invented inputs or automatic reattempts. Successful siblings
                # remain available and failures are explicit in the parent record.
                result = {"symbol": symbol, "status": "data_error", "error": str(exc)[:1000]}
                await checkpoint(result)
                return result
            result = saved["result"]
            result = {"symbol": symbol, "status": saved["verdict"], "runId": saved["runId"],
                    "screen": result["screen"], "candidates": result["analysis"]["candidates"],
                    "warnings": provenance.get("warnings", [])}
            await checkpoint(result)
            return result

    tasks = [asyncio.create_task(one(row['symbol'])) for row in initial if row['status'] == 'pending']
    try:
        await asyncio.gather(*tasks)
    except BaseException as exc:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        error = f'{type(exc).__name__}: scan interrupted'
        await checkpoint(terminal=True, error=error)
        await service.engine.journal.append(ev.TECHNIQUE_RUN_FAILED,
            {'runId': parent.id, 'symbol': 'MULTI', 'technique': TECHNIQUE, 'error': error},
            aggregate_type='technique_run', aggregate_id=parent.id)
        raise
    saved = await checkpoint(terminal=True)
    await service.engine.journal.append(ev.TECHNIQUE_RUN_COMPLETED,
        {'runId': parent.id, 'symbol': 'MULTI', 'technique': TECHNIQUE, 'mode': 'scan', 'verdict': saved['verdict']},
        aggregate_type='technique_run', aggregate_id=parent.id)
    return saved
