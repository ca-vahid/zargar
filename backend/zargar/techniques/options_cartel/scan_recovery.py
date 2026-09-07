"""Startup reconciliation for this single-engine runtime's interrupted scans."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from ... import events as ev
from ...models import TechniqueRun
from .service import TECHNIQUE


async def recover_interrupted_scans(engine):
    recovered = []
    active = getattr(engine, '_cartel_scan_tasks', {})
    async with engine.sf() as session:
        parents = (await session.scalars(select(TechniqueRun).where(TechniqueRun.technique == TECHNIQUE,
            TechniqueRun.mode == 'scan', TechniqueRun.status == 'running').with_for_update())).all()
        for parent in parents:
            task = active.get(parent.id)
            if task is not None and not task.done():
                continue
            children = (await session.scalars(select(TechniqueRun).where(
                TechniqueRun.technique == TECHNIQUE, TechniqueRun.parent_run_id == parent.id,
                TechniqueRun.mode == 'analysis', TechniqueRun.status == 'done',
                TechniqueRun.as_of == parent.as_of))).all()
            rows = []
            for old in parent.result['rows']:
                matches = [child for child in children if child.symbol == old['symbol']]
                if old['status'] == 'pending' and len(matches) == 1:
                    child = matches[0]
                    rows.append({'symbol': child.symbol, 'status': child.verdict, 'runId': child.id,
                        'screen': child.result['screen'], 'candidates': child.result['analysis']['candidates'],
                        'warnings': (child.result.get('collection') or {}).get('warnings', [])})
                else:
                    rows.append(old)
            errors = sum(r['status'] == 'data_error' for r in rows)
            pending = sum(r['status'] == 'pending' for r in rows)
            parent.result = {**parent.result, 'rows': rows, 'summary': {'requested': len(rows),
                'completed': len(rows)-pending, 'dataErrors': errors,
                'qualified': sum(r['status'] == 'setup' for r in rows)},
                'startupRecovery': {'pending': pending, 'fetchedMarketData': False}}
            parent.status = 'failed' if pending else 'done'
            parent.verdict = 'interrupted' if pending else 'data_error' if errors == len(rows) else 'partial' if errors else 'complete'
            parent.error = 'Scan process ended before all symbols completed.' if pending else None
            parent.finished_at = dt.datetime.now(dt.UTC)
            recovered.append({'runId': parent.id, 'symbol': 'MULTI', 'technique': TECHNIQUE,
                              'verdict': parent.verdict, 'pending': pending, 'error': parent.error})
        await session.commit()
    for result in recovered:
        await engine.journal.append(ev.TECHNIQUE_RUN_FAILED if result['pending'] else ev.TECHNIQUE_RUN_COMPLETED,
            result, aggregate_type='technique_run', aggregate_id=result['runId'])
    return recovered
