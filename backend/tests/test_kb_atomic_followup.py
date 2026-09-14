"""Independent KB closure boundaries; disposable test DB only, no paid calls."""
import datetime as dt
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from zargar.db import make_engine, make_session_factory
from zargar.models import TipNote
from zargar.signals.service import SignalService
from zargar.techniques.tip import rule_audit

from .conftest import TEST_DB_URL


@pytest.fixture
async def svc(fresh_db):
    db = make_engine(TEST_DB_URL)
    eng = NS(sf=make_session_factory(db), settings={},
             config=NS(anthropic_api_key="", extraction_model="offline"),
             journal=NS(append=AsyncMock()))
    eng.signals_service = SignalService(eng, None)
    yield eng.signals_service
    await db.dispose()


async def _pair(svc):
    return (await svc.add_tip_note("rule", "Original allowance from evidence A."),
            await svc.add_tip_note("rule", "Similar allowance from evidence B."))


async def test_note_commit_before_batch_receipt_can_be_retried(svc):
    a, b = await _pair(svc)
    args = {"scope": "rule", "merges": [{"supersedes": [a["id"], b["id"]],
                                        "new_rule": "Canonical allowance."}],
            "expires": [], "contradictions": [], "author": "review", "run_id": "review-run",
            "live_ids": {a["id"], b["id"]}, "batch_id": "stable-review-batch"}
    svc.engine.journal.append = AsyncMock(side_effect=OSError("journal unavailable"))
    with pytest.raises(OSError, match="journal unavailable"):
        await svc.apply_knowledge_batch(**args)
    svc.engine.journal.append = AsyncMock()
    # Either the original transaction rolled back or its receipt was durable.
    # Both permit replay; a superseded-row error strands the committed batch.
    await svc.apply_knowledge_batch(**args)
    async with svc.engine.sf() as session:
        replacements = (await session.execute(select(TipNote).where(
            TipNote.text == "Canonical allowance."))).scalars().all()
        assert len(replacements) == 1
        for nid in (a["id"], b["id"]):
            assert (await session.get(TipNote, nid)).superseded_by == replacements[0].id


async def test_audit_cannot_apply_to_a_note_edited_after_its_read(svc):
    a, b = await _pair(svc)
    await svc.add_tip_note("rule", "An unrelated third rule.")

    async def judge(**kwargs):
        assert "Original allowance from evidence A." in kwargs["messages"][0]["content"]
        await svc.update_tip_note(a["id"], text="Human decision: forbid the allowance.")
        return NS(content=[NS(type="text", text=json.dumps({
            "merges": [{"supersedes": [a["id"], b["id"]],
                        "new_rule": "The stale audit still permits the allowance."}]
        }))], usage=None, stop_reason="end_turn")

    client = NS(messages=NS(create=AsyncMock(side_effect=judge)))
    out = await rule_audit.run_rule_audit(svc.engine, client=client)
    async with svc.engine.sf() as session:
        row = await session.get(TipNote, a["id"])
        assert row.superseded_by is None, "stale audit superseded a newer human edit"
        assert row.text == "Human decision: forbid the allowance."
    assert out is None, "revision mismatch must abort and re-read, not apply stale judgment"


async def test_unversioned_legacy_text_is_not_backdated(svc):
    async with svc.engine.sf() as session:
        session.add(TipNote(id="legacy-edited-note", scope="general",
                            text="September outcome edited into an old May note.",
                            author="legacy", revision_no=1, revised_at=None,
                            created_at=dt.datetime(2026, 5, 1, tzinfo=dt.UTC)))
        await session.commit()
    historical = await svc.tip_notes(as_of=dt.datetime(2026, 6, 1, tzinfo=dt.UTC))
    assert not any(n["id"] == "legacy-edited-note" for n in historical), (
        "absence of a known-from boundary must not turn legacy current text into June knowledge")
    assert svc._last_as_of_unavailable >= 1


async def test_existing_dispute_survives_a_later_audit_without_rediscovery(svc):
    a, b = await _pair(svc)
    await svc.flag_tip_notes([a["id"], b["id"]], needs_human=True)
    result = await svc.apply_knowledge_batch(
        scope="rule", merges=[{"supersedes": [a["id"], b["id"]],
                               "new_rule": "Only one side of the unresolved dispute."}],
        expires=[], contradictions=[], author="review", run_id="next-audit",
        live_ids={a["id"], b["id"]}, batch_id="next-audit-rule")
    async with svc.engine.sf() as session:
        for nid in (a["id"], b["id"]):
            row = await session.get(TipNote, nid)
            assert row.needs_human and row.superseded_by is None, (
                "an unresolved human dispute must stay active until explicitly resolved")
    assert result["merged"] == 0
