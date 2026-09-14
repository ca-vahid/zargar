"""Delivery B boundaries on real, disposable Codex PostgreSQL.

Run sequentially via scripts/test-codex.ps1 with the reviewed backend on
PYTHONPATH. Refuses all databases except loopback:5433/zargar_test_codex.
Resets only the four source-table contents in that disposable database.
No Engine, feed, paid extraction, runtime endpoint, or production apply is used.
"""

import asyncio
import datetime as dt
import os
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

from zargar.api.routes_technique import build_technique_routes
from zargar.db import make_engine, make_session_factory
from zargar.models import (
    Base, TechniqueMethodNote, TechniqueSourceArtifact, TechniqueSourceJob, TechniqueSourceRevision,
)
from zargar.technique import source_revisions as src
from zargar.technique.ingest import MethodIngestService
from zargar.tools import em_source_backfill


T0 = "2026-09-14T13:00:00+00:00"
T1 = "2026-09-14T13:05:00+00:00"
T2 = "2026-09-14T13:10:00+00:00"
ORIGINAL = "AAPL long above 336.22"


def _url():
    raw = os.environ.get("ZARGAR_TEST_DATABASE_URL")
    assert raw, "Use scripts/test-codex.ps1; no default database is permitted"
    value = make_url(raw)
    assert value.drivername == "postgresql+asyncpg"
    assert value.host in {"127.0.0.1", "localhost", "::1"}
    assert value.port == 5433 and value.database == "zargar_test_codex"
    return raw


async def _clear(sf):
    async with sf() as session:
        for cls in (TechniqueSourceArtifact, TechniqueSourceJob,
                    TechniqueSourceRevision, TechniqueMethodNote):
            await session.execute(delete(cls))
        await session.commit()


@asynccontextmanager
async def _case(*, legacy=False):
    db = make_engine(_url())
    sf = make_session_factory(db)
    try:
        async with db.begin() as conn:
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[
                TechniqueMethodNote.__table__, TechniqueSourceRevision.__table__,
                TechniqueSourceArtifact.__table__, TechniqueSourceJob.__table__,
            ]))
        await _clear(sf)
        eng = SimpleNamespace(sf=sf, chat=None,
                              settings=SimpleNamespace(get=lambda key, default=None:
                                                       False if key.endswith("ingest.auto_extract") else default),
                              bus=SimpleNamespace(publish=lambda *a, **kw: None))
        eng.technique = SimpleNamespace()
        ing = MethodIngestService(eng, eng.technique)
        eng.technique.ingest = ing
        msg_id = uuid.uuid4().hex
        payload = {"id": msg_id, "channelId": "review-em", "channelName": "em-alerts",
                   "author": "EnhancedMarket", "authorId": "42", "text": ORIGINAL,
                   "images": ["https://example.invalid/chart.png"], "postedAt": T0, "gatewaySeq": 1}
        if legacy:
            note_id = "review-note-" + msg_id
            async with sf() as session:
                session.add(TechniqueMethodNote(
                    id=note_id, message_id=msg_id, technique="enhanced_market",
                    channel_id="review-em", channel_name="em-alerts", author="EnhancedMarket",
                    kind="video", status="checked", text=ORIGINAL, images=[],
                    transcript="old transcript", extraction={"version": "old extraction"},
                    posted_at=src.parse_ts(T0),
                ))
                await session.commit()
        else:
            note_id = (await ing.store_message(payload))["id"]
        yield SimpleNamespace(db=db, sf=sf, eng=eng, ing=ing,
                              note_id=note_id, msg_id=msg_id, payload=payload)
    finally:
        await _clear(sf)
        await db.dispose()


async def _edit(c, *, text=None, edited=T1, seq=2, kind="update"):
    return await c.ing.store_revision({"id": c.msg_id, "kind": kind,
                                       "text": text, "images": None,
                                       "editedAt": edited, "gatewaySeq": seq})


async def _current(c):
    async with c.sf() as session:
        row = await src.current_revision(session, c.note_id)
        return {"text": row.text, "deleted": row.deleted, "revision": row.revision}


def test_equal_edit_timestamp_uses_gateway_sequence_tie_break():
    async def scenario():
        async with _case() as c:
            await _edit(c, text="newer accepted text", edited=T1, seq=20)
            older = await _edit(c, text="older same-timestamp text", edited=T1, seq=19)
            assert older["outcome"] == "stale"
            assert (await _current(c))["text"] == "newer accepted text"
    asyncio.run(scenario())


def test_delete_without_edit_timestamp_does_not_reset_ordering_watermark():
    async def scenario():
        async with _case() as c:
            await _edit(c, text="latest text", edited=T2, seq=3)
            await _edit(c, edited=None, seq=4, kind="delete")
            older = await _edit(c, text="delayed earlier edit", edited=T1, seq=2)
            assert older["outcome"] == "stale", "A delayed edit must not resurrect a newer tombstone"
            assert (await _current(c))["deleted"] is True
    asyncio.run(scenario())


def test_same_content_newer_delivery_retains_its_ordering_watermark():
    async def scenario():
        async with _case() as c:
            same = await _edit(c, text=ORIGINAL, edited=T2, seq=3)
            assert same["outcome"] == "redelivery", "Same content need not create another immutable state"
            older = await _edit(c, text="earlier different text", edited=T1, seq=2)
            assert older["outcome"] == "stale", (
                "The newer accepted source observation must still advance ordering metadata"
            )
            assert (await _current(c))["text"] == ORIGINAL
    asyncio.run(scenario())


@pytest.mark.parametrize("text_field", ["omitted", "null"])
def test_api_images_only_edit_preserves_omitted_text(text_field):
    async def scenario():
        async with _case() as c:
            async def auth():
                return None
            app = FastAPI()
            build_technique_routes(app, c.eng, Depends(auth), SimpleNamespace())
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://review.invalid") as client:
                payload = {
                    "id": c.msg_id, "kind": "update", "editedAt": T1,
                    "gatewaySeq": 2, "images": [],
                }
                if text_field == "null":
                    payload["text"] = None  # The actual gateway uses null for an absent content field.
                response = await client.post("/api/technique/ingest/message", json=payload)
            assert response.status_code == 200, response.text
            assert (await _current(c))["text"] == ORIGINAL, (
                "Production request-model defaults must preserve absence; omitted text is not an empty edit"
            )
    asyncio.run(scenario())


def test_ready_job_is_not_starved_by_an_earlier_leased_job_at_limit():
    async def scenario():
        async with _case() as c:
            second = await c.ing.store_message({**c.payload, "id": uuid.uuid4().hex, "text": "second note"})
            now = src.utcnow()
            async with c.sf() as session:
                first_claim = await src.resume_unfinished(session, owner="worker-A", now=now,
                                                         lease_seconds=600, limit=1)
                await session.commit()
            assert len(first_claim) == 1 and first_claim[0]["noteId"] == c.note_id
            async with c.sf() as session:
                second_claim = await src.resume_unfinished(session, owner="worker-B", now=now, limit=1)
                await session.commit()
            assert [j["noteId"] for j in second_claim] == [second["id"]], (
                "Apply eligibility before LIMIT, or leased/backoff jobs indefinitely hide later ready jobs"
            )
    asyncio.run(scenario())


def test_expired_lease_cannot_checkpoint_even_before_another_claim():
    async def scenario():
        async with _case() as c:
            now = src.utcnow()
            async with c.sf() as session:
                job = (await src.resume_unfinished(session, owner="worker-A", now=now, lease_seconds=1))[0]
                await session.commit()
            async with c.sf() as session:
                with pytest.raises(src.FenceMismatch):
                    await src.checkpoint(
                        session, job_id=job["id"], fence_token=job["fenceToken"],
                        item_key="transcript", stage="transcribed", now=now + dt.timedelta(seconds=2),
                        artifact={"kind": "transcript", "inputHash": "media", "configHash": "cfg",
                                  "payload": {"text": "expired worker output"}},
                    )
                    await session.commit()
    asyncio.run(scenario())


def test_backfill_refuses_changed_artifact_inputs_after_dry_run():
    async def scenario():
        async with _case(legacy=True) as c:
            manifest = await em_source_backfill.build_manifest(c.sf)
            assert len(manifest["items"]) == 1
            async with c.sf() as session:
                note = await session.get(TechniqueMethodNote, c.note_id)
                note.transcript = "new transcript after the dry run"
                note.extraction = {"version": "new extraction after the dry run"}
                await session.commit()
            applied = await em_source_backfill.apply(c.sf, manifest)
            assert applied == 0, (
                "Unchanged caption does not make changed transcript/extraction the reviewed artifact; "
                "do not combine an old inputHash with current payload"
            )
            async with c.sf() as session:
                artifacts = (await session.execute(select(TechniqueSourceArtifact))).scalars().all()
                assert artifacts == []
    asyncio.run(scenario())
