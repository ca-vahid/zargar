"""Service shutdown must release startup transactions before the DB closes."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select, text

from zargar.models import TechniqueArmed
from zargar.technique.service import TechniqueService


async def test_stop_awaits_startup_and_sheet_tasks_and_releases_table_lock(engine, monkeypatch):
    service = TechniqueService(engine)
    service.armer = SimpleNamespace(start=lambda: None, stop=AsyncMock())
    entered, released = asyncio.Event(), asyncio.Event()
    owned = set()

    async def idle():
        owned.add(asyncio.current_task())
        await asyncio.Event().wait()

    async def restore():
        owned.add(asyncio.current_task())
        try:
            async with engine.sf() as session:
                await session.execute(select(TechniqueArmed))
                entered.set()
                await asyncio.Event().wait()
        finally:
            released.set()

    for name in ('_scan_loop', '_outcome_loop', '_sheet_loop', 'fail_orphaned_sweeps'):
        monkeypatch.setattr(service, name, idle)
    monkeypatch.setattr(service, '_restore_armed', restore)
    try:
        service.start()
        await asyncio.wait_for(entered.wait(), timeout=5)
        await asyncio.wait_for(service.stop(), timeout=5)
        assert released.is_set(), 'startup restore still owns its transaction after stop'
        assert all(task.done() for task in owned)
        async with engine.sf() as session:
            await session.execute(text("SET LOCAL lock_timeout = '300ms'"))
            await session.execute(text('LOCK TABLE technique_armed IN ACCESS EXCLUSIVE MODE'))
    finally:
        for task in owned:
            if not task.done():
                task.cancel()
        await asyncio.gather(*owned, return_exceptions=True)
