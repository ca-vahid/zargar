"""Knowledge lifecycle boundary checks; no provider or runtime calls."""
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

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


async def test_ordinary_rule_writer_cannot_supersede_an_unresolved_dispute(svc):
    original = await svc.add_tip_note(
        "rule", "RULE (session stop — base): One fast stop pauses new adoptions.")
    await svc.flag_tip_notes([original["id"]], needs_human=True)
    replacement = await svc.add_tip_note(
        "rule", "RULE (session stop — refinement): Continue after a fast stop.",
        author="analyst:followup")
    async with svc.engine.sf() as session:
        row = await session.get(TipNote, original["id"])
        assert row.needs_human and row.superseded_by is None, (
            "prose-family dedupe bypassed the persisted dispute lock outside the audit batch")
        new = await session.get(TipNote, replacement["id"])
        assert new.needs_human or new.superseded_by is not None, (
            "the conflicting replacement must not become undisputed live policy")


async def test_deleting_superseded_note_preserves_earlier_replacement_provenance(svc):
    original = await svc.add_tip_note("general", "Original source evidence.")
    replacement = await svc.add_tip_note("general", "Reviewed replacement evidence.")
    await svc.supersede_tip_notes([original["id"]], by=replacement["id"])
    observed_before_delete = dt.datetime.now(dt.UTC)
    await svc.delete_tip_note(original["id"])
    history = await svc.tip_notes(as_of=observed_before_delete,
                                  include_superseded=True, include_expired=True)
    old = next(n for n in history if n["id"] == original["id"])
    assert old["supersededBy"] == replacement["id"], (
        "delete overwrote the prior supersession pointer without a new revision")
    async with svc.engine.sf() as session:
        current = await session.get(TipNote, original["id"])
        assert current.revision_no == old["revisionNo"] + 1
