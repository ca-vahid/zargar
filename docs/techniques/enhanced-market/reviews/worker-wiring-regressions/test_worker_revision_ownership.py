"""Worker wiring ownership checks; copy to backend/tests and use test-codex.ps1.

Uses the team's real PostgreSQL/API rig, no Engine.start(), network or paid LLM.
"""
from unittest.mock import AsyncMock

import pytest

from tests.test_em_source_wiring import CH, T1, msg, run
from zargar.technique import source_revisions as src

pytestmark = pytest.mark.usefixtures("fresh_db")


def test_transcript_job_cannot_write_a_different_note():
    async def scenario(rig):
        await rig.deliver("create", msg(mid="one", video=True), seq=1)
        await rig.deliver("create", msg(mid="two", video=True), seq=2)
        first, second = await rig.note("one"), await rig.note("two")
        pending = (await rig.client.get("/api/technique/ingest/pending")).json()["notes"]
        lease = next(p for p in pending if p["id"] == first.id)
        response = await rig.client.post("/api/technique/ingest/transcript", json={
            "noteId": second.id, "jobId": lease["jobId"], "fenceToken": lease["fenceToken"],
            "transcript": "Output for another note must not be accepted", "model": "small",
        })
        assert response.status_code == 409, "Validate job.note_id against the requested note before any write"
        assert (await rig.note("two")).transcript is None
        assert await rig.artifacts(first.id) == [] and await rig.artifacts(second.id) == []
    run(scenario)


def test_changed_video_still_needs_its_own_transcription_after_old_worker_finishes():
    async def scenario(rig):
        await rig.deliver("create", msg(video=True), seq=1)
        note = await rig.note("123")
        pending = (await rig.client.get("/api/technique/ingest/pending")).json()["notes"]
        lease = next(p for p in pending if p["id"] == note.id)
        replacement = "https://x.com/i/broadcasts/1newvideo"
        await rig.deliver("update", {
            "id": "123", "channel_id": CH, "guild_id": "guild", "edited_timestamp": T1,
            "content": "Replacement video " + replacement,
        }, seq=2)
        current_revision = (await rig.revs(note.id))[-1]["id"]
        response = await rig.client.post("/api/technique/ingest/transcript", json={
            "noteId": note.id, "jobId": lease["jobId"], "fenceToken": lease["fenceToken"],
            "transcript": "Transcript of the superseded video", "model": "small",
        })
        assert response.status_code in (200, 409)
        pending = (await rig.client.get("/api/technique/ingest/pending")).json()["notes"]
        current_work = [p for p in pending if p["id"] == note.id and p["revisionId"] == current_revision]
        assert current_work and current_work[0]["mediaUrl"] == replacement, (
            "Completing an old media revision must not suppress the replacement media's work"
        )
    run(scenario)


@pytest.mark.parametrize("change", ["edit", "delete"])
def test_old_extraction_does_not_drive_the_current_board_after_source_changes(change):
    async def scenario(rig):
        await rig.deliver("create", msg(content="OLD is a conditional long setup at the morning level"), seq=1)
        note = await rig.note("123")

        async def model(source, body):
            assert "OLD" in body
            update = {"id": "123", "channel_id": CH, "guild_id": "guild"}
            if change == "edit":
                update.update(content="NEW replaces the earlier setup", edited_timestamp=T1)
            await rig.deliver("update" if change == "edit" else "delete", update, seq=2)
            return {"material": "setups_brief", "summary": "old source result", "stance": "neutral",
                    "symbols": ["OLD"], "board": [], "claims": [], "vetoes": []}

        rig.ing._llm_extract = model
        await rig.ing._extract_and_check(note.id)
        assert rig.technique.analyze.await_count == 0, (
            "A superseded/deleted source may be archived, but must not create a current board plan"
        )
        jobs = {j.revision_id: j for j in await rig.jobs(note.id)}
        latest = (await rig.revs(note.id))[-1]["id"]
        assert jobs[latest].outcome != "done", "Old extraction cannot complete the newer revision's job"
    run(scenario)


def test_stale_worker_conflict_cannot_mark_another_workers_note_failed():
    async def scenario(rig):
        await rig.deliver("create", msg(content="A source post long enough to be extracted by a worker"), seq=1)
        note = await rig.note("123")
        async with rig.sf() as session:
            lease = await src.claim_for_note(session, note.id, owner="other-worker")
            await session.commit()
        rig.ing._llm_extract = AsyncMock()
        await rig.ing._extract_and_check(note.id)
        assert rig.ing._llm_extract.await_count == 0
        current = await rig.note("123")
        assert current.status != "failed" and current.error is None, (
            "A lease conflict is not authority to overwrite the current note with a failure"
        )
        job = (await rig.jobs(note.id))[0]
        assert job.lease_owner == "other-worker" and job.fence_token == lease["fenceToken"]
    run(scenario)


def test_repeated_extraction_projection_has_a_matching_immutable_artifact():
    async def scenario(rig):
        await rig.deliver("create", msg(content="A source post with enough detail for a model extraction"), seq=1)
        note = await rig.note("123")
        one = {"material": "other", "summary": "first", "stance": "neutral", "symbols": [],
               "board": [], "claims": [], "vetoes": []}
        two = {**one, "summary": "different answer on the same inputs"}
        rig.ing._llm_extract = AsyncMock(side_effect=[one, two])
        await rig.ing.extract(note.id)
        await rig.ing.extract(note.id)
        current = await rig.note("123")
        payloads = [a.payload for a in await rig.artifacts(note.id) if a.kind == "extraction"]
        assert current.extraction in payloads, (
            "Reusing an output key cannot leave a newer legacy projection with no matching immutable output"
        )
    run(scenario)
