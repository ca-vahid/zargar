"""WI-01..05 additional boundary coverage (worker wiring review, 2026-09-14). Real Postgres/API rig from
tests.test_em_source_wiring; no Engine start, no network, no paid LLM."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.test_em_source_wiring import CH, T1, T2, msg, run
from zargar.technique import source_revisions as srcrev
from zargar.tools.em_ingest import media_cache_name, worker_identity

pytestmark = pytest.mark.usefixtures("fresh_db")


async def _pending(rig, owner):
    return (await rig.client.get("/api/technique/ingest/pending", params={"owner": owner})).json()["notes"]


# ----------------------------------------------------------------- WI-01: two worker instances, one job
def test_two_worker_instances_only_the_claimant_can_renew_or_complete():
    async def scenario(rig):
        await rig.deliver("create", msg(video=True), seq=1)
        n = await rig.note("123")
        a = next(p for p in await _pending(rig, "em-ingest:hostA:100") if p["id"] == n.id)
        assert a["owner"] == "em-ingest:hostA:100" and a["fenceToken"] == 1
        # instance B polls while A holds the lease: the note is not handed out
        assert all(p["id"] != n.id for p in await _pending(rig, "em-ingest:hostB:200"))
        # A polls again: renewed, same fence (no self-invalidation)
        a2 = next(p for p in await _pending(rig, "em-ingest:hostA:100") if p["id"] == n.id)
        assert a2["fenceToken"] == a["fenceToken"] and a2["jobId"] == a["jobId"]
        # B guesses A's job id with its own (wrong) fence: refused, nothing written
        r = await rig.client.post("/api/technique/ingest/transcript", json={
            "noteId": n.id, "jobId": a["jobId"], "fenceToken": a["fenceToken"] + 1, "transcript": "B's guess", "model": "small"})
        assert r.status_code == 409 and await rig.artifacts(n.id) == [] and (await rig.note("123")).transcript is None
        # A completes under its lease
        r = await rig.client.post("/api/technique/ingest/transcript", json={
            "noteId": n.id, "jobId": a["jobId"], "fenceToken": a["fenceToken"], "transcript": "A's transcript", "model": "small"})
        assert r.status_code == 200 and (await rig.note("123")).transcript == "A's transcript"
        assert len(await rig.artifacts(n.id)) == 1
        assert worker_identity().startswith("em-ingest:") and len(worker_identity()) <= 64
    run(scenario)


# ----------------------------------------------------------------- WI-02: media identity per revision
def test_unchanged_media_with_edited_caption_reuses_the_transcript_and_extracts_with_the_caption():
    async def scenario(rig):
        await rig.deliver("create", msg(video=True), seq=1)
        n = await rig.note("123")
        lease = next(p for p in await _pending(rig, "w") if p["id"] == n.id)
        r = await rig.client.post("/api/technique/ingest/transcript", json={
            "noteId": n.id, "jobId": lease["jobId"], "fenceToken": lease["fenceToken"], "transcript": "the spoken words", "model": "small"})
        assert r.status_code == 200 and r.json()["applied"] is True
        # caption edited, SAME media link: no re-transcription, the transcript stays, the new revision is next
        await rig.deliver("update", {"id": "123", "channel_id": CH, "guild_id": "guild",
                                     "content": "edited caption https://x.com/i/broadcasts/1abc123", "edited_timestamp": T1}, seq=2)
        note = await rig.note("123")
        assert note.status == "transcribed" and note.transcript == "the spoken words" and note.media_url.endswith("1abc123")
        assert all(p["id"] != n.id for p in await _pending(rig, "w"))
        seen = {}

        async def model(source, body):
            seen["body"] = body
            return {"material": "other", "summary": "s", "stance": "neutral", "symbols": [], "board": [], "claims": [], "vetoes": []}
        rig.ing._llm_extract = model
        d = await rig.ing.extract(n.id)
        assert "the spoken words" in seen["body"] and "edited caption" in seen["body"], "transcript + CURRENT caption"
        assert d["revisionId"] == (await rig.revs(n.id))[-1]["id"]
        # replacement media: the transcript no longer applies and the note is pending again for its own media
        await rig.deliver("update", {"id": "123", "channel_id": CH, "guild_id": "guild",
                                     "content": "new video https://x.com/i/broadcasts/9zzz", "edited_timestamp": T2}, seq=3)
        note = await rig.note("123")
        assert note.status == "pending_transcript" and note.transcript is None and note.media_url.endswith("9zzz")
        lease2 = next(p for p in await _pending(rig, "w") if p["id"] == n.id)
        assert lease2["mediaUrl"].endswith("9zzz") and lease2["revisionId"] == (await rig.revs(n.id))[-1]["id"]
        assert media_cache_name(n.id, lease["mediaUrl"]) != media_cache_name(n.id, lease2["mediaUrl"]), "cache identity follows the media"
    run(scenario)


def test_duplicate_completion_of_a_replacement_media_job_is_exactly_once():
    async def scenario(rig):
        await rig.deliver("create", msg(video=True), seq=1)
        n = await rig.note("123")
        lease = next(p for p in await _pending(rig, "w") if p["id"] == n.id)
        body = {"noteId": n.id, "jobId": lease["jobId"], "fenceToken": lease["fenceToken"], "transcript": "once", "model": "small"}
        assert (await rig.client.post("/api/technique/ingest/transcript", json=body)).status_code == 200
        second = await rig.client.post("/api/technique/ingest/transcript", json=body)
        assert second.status_code in (200, 409)
        arts = await rig.artifacts(n.id)
        assert len(arts) == 1 and arts[0].payload["text"] == "once"
        assert (await rig.note("123")).transcript == "once"
    run(scenario)


# ----------------------------------------------------------------- WI-03: source changes at the planning boundary
@pytest.mark.parametrize("change", ["edit", "delete"])
def test_source_change_during_planning_arms_nothing_and_completes_no_newer_job(change):
    async def scenario(rig):
        rig.settings["techniques.enhanced_market.ingest.auto_arm"] = True
        await rig.deliver("create", msg(content="TEST and ZZZZ are conditional longs at the morning level"), seq=1)
        n = await rig.note("123")
        rig.ing._llm_extract = AsyncMock(return_value={"material": "setups_brief", "summary": "s", "stance": "neutral",
                                                        "symbols": ["TEST", "ZZZZ"], "board": [], "claims": [], "vetoes": []})
        valid_run = {"id": "run-1", "result": {"plan": {"triggers": [{"id": "b1", "kind": "bounce", "valid": True,
                                                                     "assessment": {"grade": "A", "score": 9}, "riskReward": 4.0}]}}}

        async def analyze(sym, **kw):
            # the source changes while the FIRST symbol is being planned
            if sym == "TEST":
                update = {"id": "123", "channel_id": CH, "guild_id": "guild"}
                if change == "edit":
                    update.update(content="changed while planning", edited_timestamp=T1)
                await rig.deliver("update" if change == "edit" else "delete", update, seq=2)
            return valid_run
        rig.technique.analyze = AsyncMock(side_effect=analyze)
        await rig.ing._extract_and_check(n.id)
        assert rig.technique.arm_plan.await_count == 0, "no arm after the source changed"
        assert rig.technique.analyze.await_count == 1, "planning stopped at the boundary"
        jobs = {j.revision_id: j for j in await rig.jobs(n.id)}
        revs = await rig.revs(n.id)
        assert jobs[revs[0]["id"]].outcome == "superseded" and jobs[revs[-1]["id"]].outcome != "done"
        note = await rig.note("123")
        assert note.status != "checked" and not note.board_check, "the old board was not published"
        assert len(revs) == 2 and rig.armer.disarm.await_count == rig.armer.flatten.await_count == 0
    run(scenario)


# ----------------------------------------------------------------- WI-04: an old attempt's failure after a newer success
def test_old_attempt_failure_does_not_overwrite_a_newer_revisions_success():
    async def scenario(rig):
        await rig.deliver("create", msg(content="first version of a post long enough to extract"), seq=1)
        n = await rig.note("123")
        async with rig.sf() as s:                          # the old attempt's own context (revision 1's job)
            old_job = await srcrev.claim_for_note(s, n.id, owner="engine")
            await s.commit()
        await rig.deliver("update", {"id": "123", "channel_id": CH, "guild_id": "guild",
                                     "content": "second version of the post long enough to extract", "edited_timestamp": T1}, seq=2)
        rig.ing._llm_extract = AsyncMock(return_value={"material": "other", "summary": "ok", "stance": "neutral",
                                                        "symbols": [], "board": [], "claims": [], "vetoes": []})
        d = await rig.ing.extract(n.id)                    # the newer revision succeeds
        assert d["status"] == "extracted" and not d.get("superseded")
        await rig.ing._fail(n.id, "old attempt blew up", job=old_job)
        note = await rig.note("123")
        assert note.status == "extracted" and note.error is None, "the newer success is intact"
        jobs = {j.revision_id: j for j in await rig.jobs(n.id)}
        revs = await rig.revs(n.id)
        assert jobs[revs[0]["id"]].outcome == "permanent" and "blew up" in jobs[revs[0]["id"]].error
        assert jobs[revs[1]["id"]].stage == "extracted"
        # no context at all: nothing is mutated
        await rig.ing._fail(n.id, "orphan failure")
        assert (await rig.note("123")).status == "extracted"
    run(scenario)


# ----------------------------------------------------------------- WI-05: the board consumes the selected artifact
def test_board_input_references_the_persisted_extraction_artifact():
    async def scenario(rig):
        await rig.deliver("create", msg(content="TEST is a conditional long at the morning level, enough text"), seq=1)
        n = await rig.note("123")
        one = {"material": "setups_brief", "summary": "first", "stance": "neutral", "symbols": ["TEST"], "board": [], "claims": [], "vetoes": []}
        two = {**one, "summary": "second answer, same inputs"}
        rig.ing._llm_extract = AsyncMock(side_effect=[one, two])
        d1 = await rig.ing.extract(n.id)
        d2 = await rig.ing.extract(n.id)
        assert d2["artifactReused"] is True and d2["extraction"]["summary"] == "first"
        arts = [a for a in await rig.artifacts(n.id) if a.kind == "extraction"]
        assert len(arts) == 1 and (await rig.note("123")).extraction["artifactId"] == arts[0].id
        # a deliberate reprocess has its own identity and persists before it is shown
        rig.ing._llm_extract = AsyncMock(return_value=two)
        d3 = await rig.ing.extract(n.id, reprocess=True)
        arts = [a for a in await rig.artifacts(n.id) if a.kind == "extraction"]
        assert d3["artifactReused"] is False and len(arts) == 2 and d3["extraction"]["summary"] == "second answer, same inputs"
        assert (await rig.note("123")).extraction["artifactId"] in {a.id for a in arts}
        b = await rig.ing.board_check(n.id)
        assert b["boardCheck"]["revisionId"] == d1["revisionId"] and b["status"] == "checked"
    run(scenario)
