"""WF-01..03 additional ownership and manual-API coverage (worker rereview, 2026-09-14). Real Postgres/API rig
from tests.test_em_source_wiring; no Engine start, no network, no paid LLM; arms are observed calls."""
from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock

import pytest

from tests.test_em_source_wiring import CH, T1, msg, run
from zargar.technique import source_revisions as srcrev
from zargar.technique.ingest import StaleWorker

pytestmark = pytest.mark.usefixtures("fresh_db")

EX = {"material": "setups_brief", "summary": "old", "stance": "neutral", "symbols": ["OLD"], "board": [], "claims": [], "vetoes": []}
VALID = {"id": "run-1", "result": {"plan": {"triggers": [{"id": "b1", "kind": "bounce", "valid": True,
                                                        "assessment": {"grade": "A", "score": 9}, "riskReward": 4.0}]}}}


async def _expire_lease(rig, note_id):
    async with rig.sf() as s:
        job = await srcrev.job_for_note(s, note_id)
        job.lease_until = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
        await s.commit()


# ----------------------------------------------------------------- WF-01: the manual API route
def test_manual_board_route_refuses_a_superseded_extraction_and_accepts_a_current_one():
    async def scenario(rig):
        await rig.deliver("create", msg(content="OLD is a conditional long setup at a morning level"), seq=1)
        n = await rig.note("123")
        rig.ing._llm_extract = AsyncMock(return_value=dict(EX))
        await rig.ing.extract(n.id)
        await rig.deliver("update", {"id": "123", "channel_id": CH, "guild_id": "guild",
                                     "content": "NEW replaces the old setup", "edited_timestamp": T1}, seq=2)
        r = await rig.client.post(f"/api/technique/ingest/notes/{n.id}/board-check")
        assert r.status_code == 409 and "re-extract" in r.json()["detail"]
        assert rig.technique.analyze.await_count == 0
        jobs = {j.revision_id: j for j in await rig.jobs(n.id)}
        revs = await rig.revs(n.id)
        assert jobs[revs[-1]["id"]].outcome != "done" and (await rig.note("123")).status != "checked"
        # re-extract the current revision, then the manual board is accepted and consumes THAT artifact
        rig.ing._llm_extract = AsyncMock(return_value={**EX, "symbols": ["NEW"], "summary": "new"})
        d = await rig.ing.extract(n.id)
        r = await rig.client.post(f"/api/technique/ingest/notes/{n.id}/board-check")
        assert r.status_code == 200 and r.json()["status"] == "checked"
        assert r.json()["boardCheck"]["artifactId"] == d["extraction"]["artifactId"]
        assert r.json()["boardCheck"]["revisionId"] == revs[-1]["id"]
        assert [c.args[0] for c in rig.technique.analyze.await_args_list] == ["NEW"]
        # the old artifact is still history
        assert len([a for a in await rig.artifacts(n.id) if a.kind == "extraction"]) == 2
    run(scenario)


# ----------------------------------------------------------------- WF-02: reassignment / fence change during planning
def test_reassigned_lease_during_planning_stops_before_arming():
    async def scenario(rig):
        rig.settings["techniques.enhanced_market.ingest.auto_arm"] = True
        await rig.deliver("create", msg(content="OLD is a conditional long setup at a morning level"), seq=1)
        n = await rig.note("123")
        rig.ing._llm_extract = AsyncMock(return_value=dict(EX))
        await rig.ing.extract(n.id)

        async def analyze(*a, **kw):
            await _expire_lease(rig, n.id)                # the planning attempt stalls ...
            async with rig.sf() as s:                     # ... and another attempt takes the job (fence changes)
                other = await srcrev.claim_for_note(s, n.id, owner="board:other", retry=True)
                await s.commit()
            assert other is not None
            return VALID
        rig.technique.analyze = AsyncMock(side_effect=analyze)
        with pytest.raises(StaleWorker):
            await rig.ing.board_check(n.id)
        assert rig.technique.arm_plan.await_count == 0
        job = (await rig.jobs(n.id))[0]
        assert job.lease_owner == "board:other" and job.outcome == "in_progress", "the other attempt's lease is untouched"
        assert (await rig.note("123")).status != "checked"
    run(scenario)


def test_lease_or_source_loss_during_the_awaited_arm_is_refused_at_the_mutation_boundary():
    async def scenario(rig):
        rig.settings["techniques.enhanced_market.ingest.auto_arm"] = True
        await rig.deliver("create", msg(content="OLD is a conditional long setup at a morning level"), seq=1)
        n = await rig.note("123")
        rig.ing._llm_extract = AsyncMock(return_value=dict(EX))
        await rig.ing.extract(n.id)
        rig.technique.analyze = AsyncMock(return_value=VALID)
        mutated = []

        async def arm_plan(run_id, config, *, authorize=None):
            # the arm's awaited preparation: the source is edited meanwhile
            await rig.deliver("update", {"id": "123", "channel_id": CH, "guild_id": "guild",
                                         "content": "edited during the arm", "edited_timestamp": T1}, seq=2)
            await authorize()                         # the runner's mutation boundary
            mutated.append(run_id)                    # never reached
            return {"runId": run_id}
        rig.technique.arm_plan = AsyncMock(side_effect=arm_plan)
        with pytest.raises(StaleWorker):
            await rig.ing.board_check(n.id)
        assert rig.technique.arm_plan.await_count == 1 and mutated == [], "the arm mutation itself was refused"
        assert (await rig.note("123")).status != "checked"
        assert rig.armer.disarm.await_count == rig.armer.flatten.await_count == 0
        # the same boundary refuses a lease loss during the arm (no source change)
        await rig.deliver("create", msg(mid="124", content="OLD is a conditional long setup at a morning level"), seq=3)
        n2 = await rig.note("124")
        await rig.ing.extract(n2.id)
        mutated.clear()

        async def arm_plan2(run_id, config, *, authorize=None):
            await _expire_lease(rig, n2.id)
            await authorize()
            mutated.append(run_id)
            return {"runId": run_id}
        rig.technique.arm_plan = AsyncMock(side_effect=arm_plan2)
        with pytest.raises(StaleWorker):
            await rig.ing.board_check(n2.id)
        assert mutated == []
    run(scenario)


# ----------------------------------------------------------------- WF-03: the full board exception path after a takeover
def test_board_failure_after_another_attempt_took_over_records_nothing_and_the_newer_success_stands():
    async def scenario(rig):
        await rig.deliver("create", msg(content="OLD is a conditional long setup at a morning level"), seq=1)
        n = await rig.note("123")
        rig.ing._llm_extract = AsyncMock(return_value=dict(EX))
        await rig.ing.extract(n.id)
        takeover = {}

        async def analyze_then_blow_up(*a, **kw):
            await _expire_lease(rig, n.id)
            # another attempt on the SAME source revision takes over and succeeds
            real = rig.technique.analyze
            rig.technique.analyze = AsyncMock(return_value={"id": "run-2", "result": {"plan": {"triggers": []}}})
            takeover["result"] = await rig.ing.board_check(n.id)
            rig.technique.analyze = real
            raise RuntimeError("planning blew up in the stale attempt")
        rig.technique.analyze = AsyncMock(side_effect=analyze_then_blow_up)
        with pytest.raises(RuntimeError):
            await rig.ing.board_check(n.id)
        assert takeover["result"]["status"] == "checked"
        note = await rig.note("123")
        assert note.status == "checked" and note.error is None, "the newer attempt's success stands; the stale failure wrote nothing"
        job = (await rig.jobs(n.id))[0]
        assert job.outcome == "done" and job.error is None
    run(scenario)
