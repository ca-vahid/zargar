"""Failure boundary for the deployed rule-family dispute guard."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from zargar.db import make_engine, make_session_factory
from zargar.models import TipNote
from zargar.signals.service import SignalService

from .conftest import TEST_DB_URL


@pytest.fixture
async def svc(fresh_db):
    db = make_engine(TEST_DB_URL)
    eng = NS(sf=make_session_factory(db),
             settings={"techniques.tip.knowledge_apply_enabled": False},
             journal=NS(append=AsyncMock()))
    eng.signals_service = SignalService(eng, None)
    yield eng.signals_service
    await db.dispose()


async def test_failed_add_notification_cannot_publish_an_undisputed_replacement(svc):
    original = await svc.add_tip_note(
        "rule", "RULE (session stop — base): One fast stop pauses new adoptions.")
    await svc.flag_tip_notes([original["id"]], needs_human=True)
    replacement_text = "RULE (session stop — refinement): Continue after a fast stop."
    svc.engine.journal.append = AsyncMock(side_effect=OSError("notification unavailable"))
    with pytest.raises(OSError, match="notification unavailable"):
        await svc.add_tip_note("rule", replacement_text, author="analyst:followup")

    async with svc.engine.sf() as session:
        original_row = await session.get(TipNote, original["id"])
        assert original_row.needs_human and original_row.superseded_by is None
        new_rows = (await session.execute(select(TipNote).where(
            TipNote.text == replacement_text))).scalars().all()
        assert all(row.needs_human or row.superseded_by is not None for row in new_rows), (
            "new rule was committed active and undisputed before the guarded family transition; "
            "a failed notification left that intermediate state permanently visible")
