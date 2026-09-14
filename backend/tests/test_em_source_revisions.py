"""Delivery B first PR (2026-09-14): source revisions, fenced jobs, idempotent artifacts, the backfill
dry-run/apply and the order-free arm boundary. Real Postgres (repository fresh_db), no Engine start, no
LLM, no gateway. The two implementation contracts from the closure review are the acceptance here."""
from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from tests.conftest import TEST_DB_URL
from zargar.db import make_engine, make_session_factory
from zargar.execution.planrunner import PlanRunner
from zargar.models import TechniqueMethodNote, TechniqueSourceArtifact, TechniqueSourceJob, TechniqueSourceRevision
from zargar.technique import source_revisions as srcrev
from zargar.technique.ingest import MethodIngestService
from zargar.tools import em_source_backfill as backfill

pytestmark = pytest.mark.usefixtures("fresh_db")

T0 = "2026-09-14T13:00:00+00:00"
T1 = "2026-09-14T13:05:00+00:00"
T2 = "2026-09-14T13:10:00+00:00"
MSG = {"id": "700001", "channelId": "em1", "channelName": "em-alerts", "author": "EnhancedMarket", "authorId": "42",
       "text": "AMZN two-sided: over 230 calls, under 226 puts", "images": ["https://cdn/x/a.png"], "postedAt": T0}


async def _note(sf, mid="700001", **over):
    async with sf() as session:
        fields = dict(id=f"note-{mid}", message_id=mid, channel_id="em1", channel_name="em-alerts",
                      author="EnhancedMarket", kind="post", status="new", text=MSG["text"],
                      images=list(MSG["images"]), posted_at=srcrev.parse_ts(T0))
        n = TechniqueMethodNote(**{**fields, **over})
        session.add(n)
        await session.commit()
        return n.id


async def _deliver(sf, note_id, payload, kind="create", seq=None):
    async with sf() as session:
        out = await srcrev.record_delivery(session, note_id=note_id, payload=payload, kind=kind, gateway_seq=seq)
        await session.commit()
        return out


async def _revs(sf, note_id):
    async with sf() as session:
        return await srcrev.revisions_for(session, note_id)


def _db():
    db = make_engine(TEST_DB_URL)
    return db, make_session_factory(db)


# ----------------------------------------------------------------- contract 1: ordering + partial merge
def test_revision_per_distinct_state_and_redelivery_is_a_receipt():
    async def scenario():
        db, sf = _db()
        try:
            nid = await _note(sf)
            first = await _deliver(sf, nid, MSG, seq=10)
            assert first["outcome"] == "recorded" and first["revision"] == 1 and first["kind"] == "create"
            again = await _deliver(sf, nid, MSG, seq=11)
            assert again["outcome"] == "redelivery" and again["revision"] == 1, "identical transport redelivery is not a revision"
            edit = await _deliver(sf, nid, {**MSG, "text": MSG["text"] + " (edit)", "editedAt": T1}, kind="update", seq=12)
            assert edit["outcome"] == "recorded" and edit["revision"] == 2 and edit["kind"] == "edit"
            back = await _deliver(sf, nid, {**MSG, "editedAt": T2}, kind="update", seq=13)
            assert back["outcome"] == "recorded" and back["revision"] == 3, "A -> B -> A is a genuine third state"
            revs = await _revs(sf, nid)
            assert [r["revision"] for r in revs] == [1, 2, 3]
            assert revs[2]["supersedes"] == revs[1]["id"] and revs[1]["supersedes"] == revs[0]["id"]
            assert revs[0]["contentHash"] == revs[2]["contentHash"] != revs[1]["contentHash"]
            assert revs[0]["authorId"] == "42"
        finally:
            await db.dispose()
    asyncio.run(scenario())


def test_older_delivery_never_replaces_the_newer_accepted_state():
    async def scenario():
        db, sf = _db()
        try:
            nid = await _note(sf)
            await _deliver(sf, nid, MSG, seq=1)
            newer = await _deliver(sf, nid, {**MSG, "text": "newer text", "editedAt": T2}, kind="update", seq=3)
            assert newer["revision"] == 2
            late = await _deliver(sf, nid, {**MSG, "text": "older edit arriving late", "editedAt": T1}, kind="update", seq=4)
            assert late["outcome"] == "stale" and late["revision"] == 2 and "older" in late["why"]
            # no edit timestamp at all: the gateway sequence orders it
            seq_late = await _deliver(sf, nid, {**MSG, "text": "seq-late", "editedAt": None}, kind="update", seq=2)
            assert seq_late["outcome"] == "stale"
            revs = await _revs(sf, nid)
            assert len(revs) == 2
            async with sf() as session:
                cur = await srcrev.current_revision(session, nid)
                assert cur.text == "newer text"
        finally:
            await db.dispose()
    asyncio.run(scenario())


def test_partial_delivery_keeps_the_accepted_values_for_absent_fields():
    async def scenario():
        db, sf = _db()
        try:
            nid = await _note(sf)
            await _deliver(sf, nid, MSG)
            # text-only edit: images absent (None) = "not in this payload", never "cleared"
            out = await _deliver(sf, nid, {"id": "700001", "text": "text changed", "images": None, "editedAt": T1}, kind="update")
            assert out["outcome"] == "recorded" and out["revision"] == 2
            async with sf() as session:
                cur = await srcrev.current_revision(session, nid)
                assert cur.text == "text changed" and cur.attachments == MSG["images"]
                assert cur.author_id == "42" and cur.channel_name == "em-alerts", "identity fields carry forward"
            # an images-only change with text absent keeps the accepted text
            out = await _deliver(sf, nid, {"id": "700001", "text": None, "images": [], "editedAt": T2}, kind="update")
            assert out["revision"] == 3
            async with sf() as session:
                cur = await srcrev.current_revision(session, nid)
                assert cur.text == "text changed" and cur.attachments == []
        finally:
            await db.dispose()
    asyncio.run(scenario())


def test_delete_and_restore_are_revisions_and_dependents_are_not_rewritten():
    async def scenario():
        db, sf = _db()
        try:
            nid = await _note(sf)
            await _deliver(sf, nid, MSG)
            gone = await _deliver(sf, nid, {"id": "700001", "editedAt": T1}, kind="delete")
            assert gone["outcome"] == "recorded" and gone["kind"] == "delete" and gone["revision"] == 2
            assert (await _deliver(sf, nid, {"id": "700001", "editedAt": T1}, kind="delete"))["outcome"] == "redelivery"
            restored = await _deliver(sf, nid, {**MSG, "editedAt": T2}, kind="update")
            assert restored["kind"] == "restore" and restored["revision"] == 3
            revs = await _revs(sf, nid)
            assert [r["kind"] for r in revs] == ["create", "delete", "restore"]
            assert revs[1]["deleted"] is True and revs[2]["deleted"] is False
            # revision 1 is untouched by everything after it (immutable observation)
            async with sf() as session:
                r1 = await session.get(TechniqueSourceRevision, revs[0]["id"])
                assert r1.text == MSG["text"] and r1.kind == "create" and r1.supersedes is None
        finally:
            await db.dispose()
    asyncio.run(scenario())


# ----------------------------------------------------------------- contract 2: fencing + atomic output/checkpoint
def test_expired_lease_is_resumed_under_a_new_fence_and_the_stale_worker_is_refused():
    async def scenario():
        db, sf = _db()
        try:
            nid = await _note(sf)
            await _deliver(sf, nid, MSG)
            t = srcrev.utcnow()
            async with sf() as session:
                a = await srcrev.resume_unfinished(session, owner="worker-A", now=t, lease_seconds=60)
                await session.commit()
            assert len(a) == 1 and a[0]["stage"] == "received" and a[0]["fenceToken"] == 1
            job_id, fence_a = a[0]["id"], a[0]["fenceToken"]
            async with sf() as session:            # the lease is live: nobody else gets it
                assert await srcrev.resume_unfinished(session, owner="worker-B", now=t + dt.timedelta(seconds=30)) == []
            async with sf() as session:            # the lease expired: B takes over at the recorded stage, new fence
                b = await srcrev.resume_unfinished(session, owner="worker-B", now=t + dt.timedelta(seconds=61))
                await session.commit()
            assert len(b) == 1 and b[0]["fenceToken"] == 2 and b[0]["leaseOwner"] == "worker-B"
            # A comes back from its stall and tries to checkpoint: refused, nothing written
            async with sf() as session:
                with pytest.raises(srcrev.FenceMismatch):
                    await srcrev.checkpoint(session, job_id=job_id, fence_token=fence_a, item_key="transcript",
                                            artifact={"kind": "transcript", "inputHash": "m1", "configHash": "whisper-small",
                                                      "payload": {"text": "A's transcript"}}, stage="transcribed")
                await session.rollback()
            async with sf() as session:
                assert (await session.execute(select(TechniqueSourceArtifact))).scalars().all() == []
                job = await session.get(TechniqueSourceJob, job_id)
                assert job.checkpoint == [] and job.stage == "received" and job.fence_token == 2
            # B checkpoints under its fence: artifact + checkpoint land together
            async with sf() as session:
                out = await srcrev.checkpoint(session, job_id=job_id, fence_token=2, item_key="transcript",
                                              artifact={"kind": "transcript", "inputHash": "m1", "configHash": "whisper-small",
                                                        "payload": {"text": "B's transcript"}}, stage="transcribed")
                await session.commit()
            assert out["artifactReused"] is False
            async with sf() as session:
                job = await session.get(TechniqueSourceJob, job_id)
                arts = (await session.execute(select(TechniqueSourceArtifact))).scalars().all()
                assert job.checkpoint == ["transcript"] and job.stage == "transcribed"
                assert len(arts) == 1 and arts[0].payload["text"] == "B's transcript" and arts[0].completed_at is not None
        finally:
            await db.dispose()
    asyncio.run(scenario())


def test_crash_between_output_and_checkpoint_recovers_by_the_same_output_key():
    async def scenario():
        db, sf = _db()
        try:
            nid = await _note(sf)
            await _deliver(sf, nid, MSG)
            async with sf() as session:
                j = (await srcrev.resume_unfinished(session, owner="w", lease_seconds=600))[0]
                await session.commit()
            # a worker produced the output and died before the checkpoint could commit with it: the artifact
            # row exists (say, from an out-of-band write), the checkpoint does not
            async with sf() as session:
                key = srcrev.artifact_key(j["revisionId"], "extraction", "t1", "prompt-v9")
                session.add(TechniqueSourceArtifact(id=key, revision_id=j["revisionId"], note_id=nid, kind="extraction",
                                                    version=1, config_hash="prompt-v9", input_hash="t1",
                                                    payload={"board": ["AMZN"]}, completed_at=srcrev.utcnow()))
                await session.commit()
            # recovery re-derives the SAME key: the existing row is reused, no duplicate, checkpoint completes
            async with sf() as session:
                out = await srcrev.checkpoint(session, job_id=j["id"], fence_token=j["fenceToken"], item_key="extraction",
                                              artifact={"kind": "extraction", "inputHash": "t1", "configHash": "prompt-v9",
                                                        "payload": {"board": ["AMZN"]}}, stage="extracted", outcome="done")
                await session.commit()
            assert out["artifactReused"] is True and out["artifactId"] == key
            async with sf() as session:
                arts = (await session.execute(select(TechniqueSourceArtifact).where(TechniqueSourceArtifact.revision_id == j["revisionId"]))).scalars().all()
                assert len(arts) == 1
                job = await session.get(TechniqueSourceJob, j["id"])
                assert job.outcome == "done" and job.checkpoint == ["extraction"] and job.lease_owner is None
                assert await srcrev.resume_unfinished(session, owner="w2") == [], "a done job is never resumed"
        finally:
            await db.dispose()
    asyncio.run(scenario())


def test_checkpoint_and_artifact_are_one_commit():
    async def scenario():
        db, sf = _db()
        try:
            nid = await _note(sf)
            await _deliver(sf, nid, MSG)
            async with sf() as session:
                j = (await srcrev.resume_unfinished(session, owner="w", lease_seconds=600))[0]
                await session.commit()
            async with sf() as session:
                await srcrev.checkpoint(session, job_id=j["id"], fence_token=j["fenceToken"], item_key="transcript",
                                        artifact={"kind": "transcript", "inputHash": "m", "configHash": "c", "payload": {"text": "x"}},
                                        stage="transcribed")
                await session.rollback()               # the process died before the commit
            async with sf() as session:
                assert (await session.execute(select(TechniqueSourceArtifact))).scalars().all() == []
                job = await session.get(TechniqueSourceJob, j["id"])
                assert job.checkpoint == [] and job.stage == "received", "no output without its checkpoint, no checkpoint without its output"
        finally:
            await db.dispose()
    asyncio.run(scenario())


# ----------------------------------------------------------------- the ingest service writes revisions with the note
def test_store_message_writes_revision_one_with_the_note_and_edits_become_revisions():
    async def scenario():
        db, sf = _db()
        try:
            eng = SimpleNamespace(sf=sf, settings=SimpleNamespace(get=lambda k, d=None: d), bus=SimpleNamespace(publish=Mock()))
            ing = MethodIngestService(eng, SimpleNamespace())
            ing._spawn = Mock()                        # no extraction task in this test
            d = await ing.store_message({**MSG, "gatewaySeq": 5})
            assert d["revision"] == 1 and d["duplicate"] is False
            revs = await _revs(sf, d["id"])
            assert len(revs) == 1 and revs[0]["gatewaySeq"] == 5 and revs[0]["authorId"] == "42"
            dup = await ing.store_message(MSG)
            assert dup["duplicate"] is True and len(await _revs(sf, d["id"])) == 1
            e = await ing.store_revision({"id": "700001", "kind": "update", "text": "edited text", "images": None,
                                          "editedAt": T1, "gatewaySeq": 6})
            assert e["ok"] and e["outcome"] == "recorded" and e["revision"] == 2
            async with sf() as session:
                note = await session.get(TechniqueMethodNote, d["id"])
                assert note.text == "edited text" and note.images == MSG["images"], "the note shows the latest accepted state"
                assert note.meta["revision"] == 2 and note.meta["revisionKind"] == "edit"
            stale = await ing.store_revision({"id": "700001", "kind": "update", "text": "late", "editedAt": T0})
            assert stale["outcome"] == "stale"
            unknown = await ing.store_revision({"id": "nope", "kind": "update", "text": "?"})
            assert unknown["ok"] is False
            jobs = await ing.resume_unfinished(owner="test")
            assert [j["revisionId"] for j in jobs] == [r["id"] for r in await _revs(sf, d["id"])]
        finally:
            await db.dispose()
    asyncio.run(scenario())


# ----------------------------------------------------------------- backfill: dry run + one-transaction apply, idempotent
def test_backfill_dry_run_and_apply_are_idempotent_and_never_derive_availability():
    async def scenario():
        db, sf = _db()
        try:
            a = await _note(sf, mid="800001", status="checked", transcript="the transcript", extraction={"material": "setups_brief"})
            b = await _note(sf, mid="800002", status="new")
            c = await _note(sf, mid="800003")
            await _deliver(sf, c, {**MSG, "id": "800003"})       # already revisioned: the backfill leaves it alone
            m = await backfill.build_manifest(sf)
            assert {i["noteId"] for i in m["items"]} == {a, b} and m["alreadyRevisioned"] == [c]
            ia = next(i for i in m["items"] if i["noteId"] == a)
            assert ia["authorId"] is None and ia["publishedAt"] == srcrev.parse_ts(T0).isoformat()
            assert sorted(x["kind"] for x in ia["artifacts"]) == ["extraction", "transcript"]
            assert all(x["availability"] == "unknown" for x in ia["artifacts"])
            assert await backfill.apply(sf, m) == 2
            assert await backfill.apply(sf, m) == 0, "a second apply of the same manifest writes nothing"
            async with sf() as session:
                revs = (await session.execute(select(TechniqueSourceRevision))).scalars().all()
                assert sorted((r.note_id, r.revision) for r in revs) == sorted([(a, 1), (b, 1), (c, 1)])
                arts = (await session.execute(select(TechniqueSourceArtifact).where(TechniqueSourceArtifact.note_id == a))).scalars().all()
                assert len(arts) == 2 and all(x.completed_at is None and x.payload["availability"] == "unknown" for x in arts)
                jobs = {j.note_id: j for j in (await session.execute(select(TechniqueSourceJob))).scalars().all()}
                assert jobs[a].outcome == "done" and jobs[a].stage == "board_checked" and sorted(jobs[a].checkpoint) == ["extraction", "transcript"]
                assert jobs[b].outcome == "retryable" and jobs[b].stage == "received"
            # a note edited after the dry run refuses the whole apply (re-run the dry run)
            d = await _note(sf, mid="800004")
            m2 = await backfill.build_manifest(sf)
            async with sf() as session:
                n = await session.get(TechniqueMethodNote, d)
                n.text = "changed after the dry run"
                await session.commit()
            assert await backfill.apply(sf, m2) == 0
        finally:
            await db.dispose()
    asyncio.run(scenario())


# ----------------------------------------------------------------- the order-free boundary in the ONE arm path
def test_scenario_candidates_are_refused_from_every_arm_path_and_journaled():
    journal = SimpleNamespace(append=AsyncMock())
    engine = SimpleNamespace(settings={}, journal=journal, positions=SimpleNamespace(equity=AsyncMock(return_value=1.0)),
                             quotes={}, options=None)
    r = PlanRunner(engine)
    r.load_plan = AsyncMock(return_value={"id": "run-scn", "symbol": "AMZN", "mode": "plan", "tags": ["ingest"],
                                         "config": {"origin": "scenario:abc123"}, "result": {"plan": {"triggers": []}}})
    for restored in (False, True):
        with pytest.raises(ValueError, match="order-free scenario candidate"):
            asyncio.run(r.arm("run-scn", {"portfolioId": "p", "mode": "auto"}, restored=restored))
    assert journal.append.await_count == 2
    kind, payload = journal.append.await_args.args[0], journal.append.await_args.args[1]
    assert kind == "TechniqueArmRefused" and payload["origin"] == "scenario:abc123" and payload["restored"] is True
    assert "run-scn" not in r._armed
    # a tag is enough - the boundary does not depend on config alone, nor on any setting
    r.load_plan = AsyncMock(return_value={"id": "run-tag", "symbol": "AMZN", "mode": "plan", "tags": ["scenario:zzz"],
                                         "config": {}, "result": {"plan": {"triggers": []}}})
    with pytest.raises(ValueError, match="order-free"):
        asyncio.run(r.arm("run-tag", {"portfolioId": "p", "mode": "auto"}))
