"""Reviewer boundaries: no paid calls, no runtime; disposable DB via test-codex."""
import datetime as dt
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from zargar import scheduler
from zargar.db import make_engine, make_session_factory
from zargar.models import TipNote
from zargar.signals.service import SignalService
from zargar.techniques.tip import lifecycle, retro, rule_audit, runner

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


async def test_default_weekly_audit_is_reachable_on_saturday(monkeypatch):
    class Saturday(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            t = cls(2026, 9, 12, 22, tzinfo=dt.UTC)
            return t.astimezone(tz) if tz else t.replace(tzinfo=None)

    clock = NS(datetime=Saturday, timezone=dt.timezone, timedelta=dt.timedelta)
    monkeypatch.setattr(scheduler, "dt", clock)
    monkeypatch.setattr(rule_audit, "dt", clock)
    fake_runner = NS(restore=AsyncMock(return_value=0), shadow_arm_open_tips=AsyncMock())
    monkeypatch.setattr(runner, "TipRunner", lambda eng: fake_runner)
    monkeypatch.setattr(lifecycle, "resume_pending_adoptions", AsyncMock())
    for name in ("run_tip_retros", "run_unfilled_retros", "grade_lanes"):
        monkeypatch.setattr(retro, name, AsyncMock(return_value={}))
    audit = AsyncMock(return_value={})
    monkeypatch.setattr(rule_audit, "run_rule_audit", audit)
    monkeypatch.setattr(rule_audit, "run_knowledge_audit", AsyncMock(return_value={}))
    eng = NS(settings={}, journal=NS(append=AsyncMock()),
             signals_service=NS(morning_triage=AsyncMock()))
    eng.scheduler = scheduler.Scheduler(eng)
    eng.scheduler._journaled_last_day = AsyncMock(return_value="")
    await runner.attach_tip_runner(eng)
    assert rule_audit.audit_due_today(eng.settings)
    await eng.scheduler._tick()
    assert audit.await_count == 1, "Saturday audit is due but weekday-only parent never runs"


async def test_audit_cannot_merge_away_its_own_contradiction(svc):
    a = await svc.add_tip_note("rule", "Always permit action A.")
    b = await svc.add_tip_note("rule", "Never permit action A.")
    await svc.add_tip_note("rule", "Unrelated third rule.")
    opinion = {"merges": [{"supersedes": [a["id"], b["id"]], "new_rule": "Permit A."}],
               "contradictions": [{"ids": [a["id"], b["id"]], "why": "Direct conflict"}]}
    client = NS(messages=NS(create=AsyncMock(return_value=NS(
        content=[NS(type="text", text=json.dumps(opinion))], usage=None, stop_reason="end_turn"))))
    out = await rule_audit.run_rule_audit(svc.engine, client=client)
    assert out["contradictions"] == 2 and out["merged"] == 0, out
    async with svc.engine.sf() as session:
        for nid in (a["id"], b["id"]):
            row = await session.get(TipNote, nid)
            assert row.needs_human and row.superseded_by is None


async def test_historical_read_cannot_see_later_in_place_edit(svc):
    note = await svc.add_tip_note("general", "Original statement available in May.")
    async with svc.engine.sf() as session:
        row = await session.get(TipNote, note["id"])
        row.created_at = dt.datetime(2026, 5, 1, tzinfo=dt.UTC)
        await session.commit()
    await svc.update_tip_note(note["id"], text="Future September outcome now known.")
    historical = await svc.notes_for_tip("X", "Src", as_of=dt.datetime(2026, 6, 1, tzinfo=dt.UTC))
    assert not any(n["text"] == "Future September outcome now known." for n in historical)


async def test_shared_write_boundary_rejects_empty_entity_scope(svc):
    with pytest.raises(ValueError):
        await svc.add_tip_note("ticker:", "An orphan that no ticker query can retrieve.")
