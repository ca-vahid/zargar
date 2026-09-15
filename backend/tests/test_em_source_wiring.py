"""Delivery B next PR (2026-09-14): the REAL path - Discord gateway envelope -> /api/technique/ingest/* ->
ingest service -> source ledger -> transcription/extraction workers through immutable artifacts and fenced
checkpoints. Real Postgres (repository fresh_db), a real FastAPI app over ASGI, the real Gateway envelope
worker with its HTTP client pointed at that app; no Engine start, no LLM (stubbed), no Discord.

Covers: create/edit/delete through the envelope (with receipt sequences and a gateway sequence reset),
duplicate delivery, changed source after a claim, worker crash (expired lease) and retry, stale-worker
refusal, exactly-once outputs, known vs unknown availability, and the tombstone contract: a deletion is a
journaled source fact that never disarms, flattens or re-owns anything."""
from __future__ import annotations

import asyncio
import datetime as dt
import pathlib
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import select

from tests.conftest import TEST_DB_URL
from zargar.api.routes_technique import build_technique_routes
from zargar.db import make_engine, make_session_factory
from zargar.models import TechniqueMethodNote, TechniqueSourceArtifact, TechniqueSourceJob, TechniqueSourceRevision
from zargar.technique import source_revisions as srcrev
from zargar.technique.ingest import MethodIngestService, StaleWorker
from zargar.tools.discord_gateway import Gateway

pytestmark = pytest.mark.usefixtures("fresh_db")

CH = "em-channel"
T0, T1, T2 = "2026-09-14T13:20:00Z", "2026-09-14T13:21:00Z", "2026-09-14T13:22:00Z"


class Rig:
    """A real ingest service + real API + real gateway envelope worker, wired end to end."""

    def __init__(self, sf):
        self.sf = sf
        self.settings = {"techniques.enhanced_market.ingest.auto_extract": False,
                         "techniques.enhanced_market.ingest.auto_transcribe": True,
                         "techniques.enhanced_market.ingest.transcribe_max_attempts": 2}
        self.journal = SimpleNamespace(append=AsyncMock())
        self.armer = SimpleNamespace(armed=lambda slim=True: [], disarm=AsyncMock(), stop_all=AsyncMock(), flatten=AsyncMock())
        self.technique = SimpleNamespace(armer=self.armer, arm_plan=AsyncMock(), analyze=AsyncMock(return_value={"id": "r", "result": {"plan": {"triggers": []}}}),
                                         llm_config=lambda: SimpleNamespace(model="fake-model", available=True))
        self.eng = SimpleNamespace(sf=sf, settings=SimpleNamespace(get=lambda k, d=None: self.settings.get(k, d)),
                                   bus=SimpleNamespace(publish=Mock()), journal=self.journal, chat=None, technique=self.technique)
        self.ing = MethodIngestService(self.eng, self.technique)
        self.ing._spawn = Mock()
        self.technique.ingest = self.ing
        app = FastAPI()

        async def auth():
            return None
        build_technique_routes(app, self.eng, Depends(auth), SimpleNamespace())
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://em.invalid")
        rig = self

        class Http:                                   # the gateway's HTTP client, routed into the ASGI app
            async def post(self, url, headers=None, json=None, timeout=None):
                return await rig.client.post(url.replace("http://em.invalid", ""), json=json)
        self.http = Http()
        self.gw = Gateway("tok", "http://em.invalid", "sess", pathlib.Path(tempfile.mkdtemp()) / "gateway.jsonl", ingest=True, dump=False, bots_only=False, author_id="", channel_id="")
        self.gw._em = {CH: {"channelId": CH, "label": "EM source"}}
        self.gw._watch = {}
        self.gw._queue = asyncio.Queue(50)
        self.gw._mirror = AsyncMock(return_value=True)

    async def deliver(self, kind, msg, seq):
        """One Discord event -> envelope -> the worker half -> the API (the real path)."""
        self.gw._seq = seq
        self.gw._enqueue(kind, msg)
        if self.gw._queue.empty():
            return None                               # the ledger already holds this key (in flight): a receipt
        env = self.gw._queue.get_nowait()
        assert await self.gw._deliver(self.http, {}, env), "delivery must be acknowledged"
        return env

    async def note(self, mid):
        async with self.sf() as s:
            return (await s.execute(select(TechniqueMethodNote).where(TechniqueMethodNote.message_id == mid))).scalar_one()

    async def revs(self, note_id):
        async with self.sf() as s:
            return await srcrev.revisions_for(s, note_id)

    async def artifacts(self, note_id):
        async with self.sf() as s:
            return (await s.execute(select(TechniqueSourceArtifact).where(TechniqueSourceArtifact.note_id == note_id)
                                    .order_by(TechniqueSourceArtifact.created_at))).scalars().all()

    async def jobs(self, note_id):
        async with self.sf() as s:
            return (await s.execute(select(TechniqueSourceJob).where(TechniqueSourceJob.note_id == note_id))).scalars().all()

    async def close(self):
        await self.client.aclose()


def msg(mid="123", content="MSFT long above 498.97", edited=None, video=False, **extra):
    d = {"id": mid, "channel_id": CH, "guild_id": "guild", "timestamp": T0,
         "author": {"id": "author", "username": "EM"}, "attachments": [], "embeds": []}
    if content is not None:
        # one broadcast link per message id: the ingest dedupes a re-posted link within a day as ONE video
        d["content"] = content + (f" https://x.com/i/broadcasts/1abc{mid}" if video else "")
    if edited:
        d["edited_timestamp"] = edited
    d.update(extra)
    return d


def run(coro):
    async def wrapped():
        db = make_engine(TEST_DB_URL)
        rig = Rig(make_session_factory(db))
        try:
            return await coro(rig)
        finally:
            await rig.close()
            await db.dispose()
    return asyncio.run(wrapped())


# ----------------------------------------------------------------- ordering through the real path
def test_create_edit_and_sequence_reset_through_the_real_envelope_path():
    async def scenario(rig):
        env = await rig.deliver("create", msg(), seq=40)
        assert env["em"] and env["emDone"] and env["seq"] == 40
        n = await rig.note("123")
        revs = await rig.revs(n.id)
        assert len(revs) == 1 and revs[0]["gatewaySeq"] == 40
        # duplicate delivery of the same create: a receipt, still one revision
        await rig.deliver("create", msg(), seq=41)
        assert len(await rig.revs(n.id)) == 1
        # an edit (partial: Discord omits attachments) -> revision 2, receipt sequence 42
        await rig.deliver("update", {"id": "123", "channel_id": CH, "guild_id": "guild", "content": "MSFT long above 499.10",
                                     "edited_timestamp": T1}, seq=42)
        revs = await rig.revs(n.id)
        assert [r["revision"] for r in revs] == [1, 2] and revs[1]["gatewaySeq"] == 42
        assert revs[1]["attachments"] == [] and (await rig.note("123")).text == "MSFT long above 499.10"
        # gateway sequence RESET (reconnect): a newer edit with a LOWER sequence is accepted on its event time ...
        await rig.deliver("update", {"id": "123", "channel_id": CH, "guild_id": "guild", "content": "MSFT long above 499.50",
                                     "edited_timestamp": T2}, seq=3)
        # ... and its own later same-time update (seq 4) is not discarded (P2 pair contract)
        await rig.deliver("update", {"id": "123", "channel_id": CH, "guild_id": "guild", "content": "MSFT long above 499.55",
                                     "edited_timestamp": T2}, seq=4)
        revs = await rig.revs(n.id)
        assert [r["revision"] for r in revs] == [1, 2, 3, 4]
        assert (await rig.note("123")).text == "MSFT long above 499.55"
        # a delayed OLDER edit after the reset is stale
        await rig.deliver("update", {"id": "123", "channel_id": CH, "guild_id": "guild", "content": "late", "edited_timestamp": T1}, seq=5)
        assert len(await rig.revs(n.id)) == 4 and (await rig.note("123")).text == "MSFT long above 499.55"
        # the tips path never saw any of it (EM-only channel)
        assert rig.gw._mirror.await_count == 0
    run(scenario)


def test_delete_is_a_journaled_tombstone_that_never_touches_positions_or_arms():
    async def scenario(rig):
        await rig.deliver("create", msg(), seq=1)
        n = await rig.note("123")
        env = await rig.deliver("delete", {"id": "123", "channel_id": CH, "guild_id": "guild"}, seq=2)
        assert env["kind"] == "delete" and env["em"] and env["emDone"]
        revs = await rig.revs(n.id)
        assert [r["kind"] for r in revs] == ["create", "delete"] and revs[1]["deleted"] is True
        assert revs[0]["contentHash"] != revs[1]["contentHash"], "history kept: revision 1 is untouched"
        note = await rig.note("123")
        assert note.meta["deleted"] is True and note.text == "MSFT long above 498.97", "the tombstone keeps the last accepted text"
        kinds = [c.args[0] for c in rig.journal.append.await_args_list]
        assert "TechniqueSourceRevised" in kinds
        payload = [c.args[1] for c in rig.journal.append.await_args_list if c.args[0] == "TechniqueSourceRevised"][-1]
        assert payload["kind"] == "delete" and payload["outcome"] == "recorded" and payload["deleted"] is True
        # nothing was disarmed, flattened, stopped or re-owned
        assert rig.armer.disarm.await_count == rig.armer.stop_all.await_count == rig.armer.flatten.await_count == 0
        assert rig.technique.arm_plan.await_count == 0
        # a restore after the tombstone is a third revision; a duplicate delete is a receipt
        await rig.deliver("delete", {"id": "123", "channel_id": CH, "guild_id": "guild"}, seq=3)
        assert len(await rig.revs(n.id)) == 2
        await rig.deliver("update", {"id": "123", "channel_id": CH, "guild_id": "guild", "content": "MSFT long above 498.97", "edited_timestamp": T2}, seq=4)
        assert [r["kind"] for r in await rig.revs(n.id)] == ["create", "delete", "restore"]
        assert rig.gw._mirror.await_count == 0
    run(scenario)


# ----------------------------------------------------------------- the worker path: lease -> output -> checkpoint
def test_worker_lease_transcript_artifact_exactly_once_and_stale_worker_refused():
    async def scenario(rig):
        await rig.deliver("create", msg(video=True), seq=1)
        n = await rig.note("123")
        assert n.status == "pending_transcript"
        pend = (await rig.client.get("/api/technique/ingest/pending")).json()["notes"]
        job = next(p for p in pend if p["id"] == n.id)
        assert job["jobId"] and job["fenceToken"] == 1 and job["revisionId"] == (await rig.revs(n.id))[0]["id"]
        # the same worker polling again RENEWS its lease and keeps its fence (no self-invalidation)
        pend2 = (await rig.client.get("/api/technique/ingest/pending")).json()["notes"]
        assert next(p for p in pend2 if p["id"] == n.id)["fenceToken"] == job["fenceToken"]
        body = {"noteId": n.id, "transcript": "[0:01] MSFT looks good above the level", "model": "small",
                "durationSeconds": 61.0, "jobId": job["jobId"], "fenceToken": job["fenceToken"]}
        r = await rig.client.post("/api/technique/ingest/transcript", json=body)
        assert r.status_code == 200 and r.json()["status"] == "transcribed"
        arts = await rig.artifacts(n.id)
        assert len(arts) == 1 and arts[0].kind == "transcript" and arts[0].payload["text"].startswith("[0:01]")
        assert arts[0].completed_at is not None, "a worker-produced artifact has KNOWN availability"
        assert arts[0].config_hash == "small"
        jobs = await rig.jobs(n.id)
        assert jobs[0].stage == "transcribed" and jobs[0].checkpoint == ["transcript"]
        # the worker retries the same post (crash after the app committed): the artifact is reused, not duplicated
        r = await rig.client.post("/api/technique/ingest/transcript", json=body)
        assert r.status_code in (200, 409)
        assert len(await rig.artifacts(n.id)) == 1
        # another owner claims the job (e.g. the extraction path): the old fence is stale -> 409, nothing written
        async with rig.sf() as s:
            newer = await srcrev.claim_for_note(s, n.id, owner="extract", retry=True)
            await s.commit()
        assert newer["fenceToken"] > job["fenceToken"]
        r = await rig.client.post("/api/technique/ingest/transcript", json={**body, "transcript": "a different transcript from a stale worker"})
        assert r.status_code == 409 and "stale" in r.json()["detail"]
        assert (await rig.note("123")).transcript.startswith("[0:01]")
        assert len(await rig.artifacts(n.id)) == 1
    run(scenario)


def test_worker_crash_expired_lease_resume_and_retry():
    async def scenario(rig):
        await rig.deliver("create", msg(video=True), seq=1)
        n = await rig.note("123")
        # worker A takes the lease and dies; simulate the lease expiring
        async with rig.sf() as s:
            a = await srcrev.claim_for_note(s, n.id, owner="worker-A", lease_seconds=1)
            await s.commit()
        async with rig.sf() as s:
            j = await s.get(TechniqueSourceJob, a["id"])
            j.lease_until = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=5)
            await s.commit()
        # A's late result is refused (expired lease)
        with pytest.raises(StaleWorker):
            await rig.ing.store_transcript(n.id, transcript="A's late output", meta={"model": "small"},
                                           job_id=a["id"], fence_token=a["fenceToken"])
        assert (await rig.note("123")).transcript is None and await rig.artifacts(n.id) == []
        # the worker poll re-leases it under a new fence (resume at the recorded stage) and B completes it
        pend = (await rig.client.get("/api/technique/ingest/pending")).json()["notes"]
        job = next(p for p in pend if p["id"] == n.id)
        assert job["fenceToken"] > a["fenceToken"]
        r = await rig.client.post("/api/technique/ingest/transcript", json={"noteId": n.id, "transcript": "B's transcript", "model": "small",
                                                                            "jobId": job["jobId"], "fenceToken": job["fenceToken"]})
        assert r.status_code == 200
        arts = await rig.artifacts(n.id)
        assert len(arts) == 1 and arts[0].payload["text"] == "B's transcript"
        # a transcription failure is a retryable job (lease released, due now); the second failure is permanent
        await rig.deliver("create", msg(mid="124", video=True), seq=2)
        n2 = await rig.note("124")
        pend = (await rig.client.get("/api/technique/ingest/pending")).json()["notes"]
        job2 = next(p for p in pend if p["id"] == n2.id)
        r = await rig.client.post("/api/technique/ingest/transcript", json={"noteId": n2.id, "error": "download failed", "jobId": job2["jobId"], "fenceToken": job2["fenceToken"]})
        assert r.status_code == 200 and r.json()["status"] == "pending_transcript"
        jobs = await rig.jobs(n2.id)
        assert jobs[0].outcome == "retryable" and jobs[0].lease_owner is None and jobs[0].error == "download failed"
        pend = (await rig.client.get("/api/technique/ingest/pending")).json()["notes"]
        job2b = next(p for p in pend if p["id"] == n2.id)
        assert job2b["fenceToken"] > job2["fenceToken"]
        r = await rig.client.post("/api/technique/ingest/transcript", json={"noteId": n2.id, "error": "download failed again", "jobId": job2b["jobId"], "fenceToken": job2b["fenceToken"]})
        assert r.json()["status"] == "failed"
        jobs = await rig.jobs(n2.id)
        assert jobs[0].outcome == "permanent" and await rig.artifacts(n2.id) == []
    run(scenario)


def test_changed_source_after_a_claim_binds_the_output_to_the_old_revision_and_opens_a_new_job():
    async def scenario(rig):
        await rig.deliver("create", msg(video=True), seq=1)
        n = await rig.note("123")
        pend = (await rig.client.get("/api/technique/ingest/pending")).json()["notes"]
        job = next(p for p in pend if p["id"] == n.id)
        rev1 = job["revisionId"]
        # the source is edited while the worker transcribes
        await rig.deliver("update", {"id": "123", "channel_id": CH, "guild_id": "guild", "content": "edited caption https://x.com/i/broadcasts/1abc",
                                     "edited_timestamp": T1}, seq=2)
        revs = await rig.revs(n.id)
        assert len(revs) == 2 and revs[0]["id"] == rev1
        # the worker's output lands on the revision it was leased for (history), the note shows the latest text
        r = await rig.client.post("/api/technique/ingest/transcript", json={"noteId": n.id, "transcript": "transcript of the original", "model": "small",
                                                                            "jobId": job["jobId"], "fenceToken": job["fenceToken"]})
        assert r.status_code == 200
        arts = await rig.artifacts(n.id)
        assert len(arts) == 1 and arts[0].revision_id == rev1
        assert (await rig.note("123")).text.startswith("edited caption")
        # revision 2 has its own job, still at 'received': the media hash is unchanged, so the transcript is
        # reusable (reviewer answer 1) and the note - transcribed for the UI - is not handed out for a second
        # transcription; the edited caption's own extraction is the next stage
        jobs = {j.revision_id: j for j in await rig.jobs(n.id)}
        assert jobs[rev1].stage == "transcribed" and jobs[revs[1]["id"]].stage == "received"
        assert (await rig.note("123")).status == "transcribed"
        pend = (await rig.client.get("/api/technique/ingest/pending")).json()["notes"]
        assert all(p["id"] != n.id for p in pend)
        async with rig.sf() as s:                     # the current job is claimable by the next stage, fenced
            j2 = await srcrev.claim_for_note(s, n.id, owner="engine")
            assert j2 and j2["revisionId"] == revs[1]["id"] and j2["fenceToken"] == 1
    run(scenario)


def test_extraction_and_board_checkpoint_with_known_availability():
    async def scenario(rig):
        await rig.deliver("create", msg(content="TEST holds the level, watch 216.21 - a long post with enough substance to extract"), seq=1)
        n = await rig.note("123")
        rig.ing._llm_extract = AsyncMock(return_value={"summary": "s", "stance": "cautious", "symbols": ["TEST"], "board": [], "claims": [], "vetoes": []})
        d = await rig.ing.extract(n.id)
        assert d["status"] == "extracted"
        arts = await rig.artifacts(n.id)
        assert [a.kind for a in arts] == ["extraction"] and arts[0].completed_at is not None and arts[0].payload["symbols"] == ["TEST"]
        jobs = await rig.jobs(n.id)
        assert jobs[0].stage == "extracted" and jobs[0].checkpoint == ["extraction"]
        # a second extraction with the same input and model is the SAME output key: no duplicate artifact
        await rig.ing.extract(n.id)
        assert len(await rig.artifacts(n.id)) == 1
        b = await rig.ing.board_check(n.id)
        assert b["status"] == "checked"
        jobs = await rig.jobs(n.id)
        assert jobs[0].stage == "board_checked" and jobs[0].outcome == "done" and jobs[0].lease_owner is None
        assert sorted(jobs[0].checkpoint) == ["board_check", "extraction"]
        # an extraction failure surfaces as a permanent job outcome with the error, same commit as the note
        await rig.deliver("create", msg(mid="125", content="another post with enough substance to be extracted by the model"), seq=2)
        n2 = await rig.note("125")
        rig.ing._llm_extract = AsyncMock(side_effect=RuntimeError("LLM down"))
        await rig.ing._extract_and_check(n2.id)
        assert (await rig.note("125")).status == "failed"
        j2 = (await rig.jobs(n2.id))[0]
        assert j2.outcome == "permanent" and "LLM down" in j2.error
    run(scenario)
