"""KFIN-04 (2026-09-14): a running Tips run is judged by process ownership / heartbeat, never by age.

The first EOD-07 cut counted a RUNNING row as stale after two hours. A rule-audit cycle or a
long appraisal legitimately outlives that; a genuinely running long job must stay visible to
readiness, and a dead process's rows must be reconciled honestly, on the record."""
import asyncio
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.models import TipAnalystRun
from zargar.ops import readiness_from_state, restart_state
from zargar.runtime import runtime_id
from zargar.techniques.tip import analyst

from .test_tip_knowledge import app_client  # noqa: F401


def _row(rid, *, age_h=0.0, owner="me", beat_age_h=None, kind="appraise"):
    now = dt.datetime.now(dt.timezone.utc)
    return TipAnalystRun(id=rid, ticker="X", source="t", status="running", kind=kind, model="offline",
                         tools=[], trace=[], tip={}, opinion={}, created_at=now - dt.timedelta(hours=age_h),
                         owner=(runtime_id() if owner == "me" else owner),
                         heartbeat_at=(None if beat_age_h is None else now - dt.timedelta(hours=beat_age_h)))


async def test_old_run_with_a_live_task_stays_visible_and_a_lost_one_is_reconciled(app_client):  # noqa: F811
    _, eng = app_client
    eng.technique = NS(status=AsyncMock(return_value={"running": []}))
    gate = asyncio.Event()

    async def long_job():
        analyst.register_run(eng, "old-but-alive")     # what every recorder / rule-audit cycle does
        await gate.wait()

    async with eng.sf() as session:
        session.add_all([
            _row("old-but-alive", age_h=5, kind="rule_audit"),          # 5 h old, task alive -> RUNNING
            _row("ours-lost", age_h=5),                                   # ours, no task, silent 5 h -> lost
            _row("ours-fresh", age_h=0),                                  # ours, just created -> RUNNING
            _row("foreign-fresh", age_h=6, owner="other:1:x", beat_age_h=0.01),   # heartbeat fresh -> RUNNING
            _row("foreign-silent", age_h=6, owner="other:1:x", beat_age_h=3),    # heartbeat 3 h ago -> stale
        ])
        await session.commit()
    task = asyncio.create_task(long_job())
    await asyncio.sleep(0)
    await eng._tip_run_registry["old-but-alive"]["pending"]             # the registration heartbeat
    st = await restart_state(eng)
    assert sorted(st["tipRuns"]) == ["tip:appraise:foreign-fresh", "tip:appraise:ours-fresh",
                                     "tip:rule_audit:old-but-alive"]
    assert st["tipRunsStale"] == ["tip:appraise:foreign-silent"]
    assert st["tipRunsReconciled"] == ["tip:appraise:ours-lost"]
    assert st["inflightRuns"] == 3 and not readiness_from_state(st)["safe"]
    async with eng.sf() as session:
        lost = await session.get(TipAnalystRun, "ours-lost")
        assert lost.status == "failed" and "lost by its owner process" in lost.error and lost.finished_at is not None
        foreign = await session.get(TipAnalystRun, "foreign-silent")
        assert foreign.status == "running", "another runtime's row is reported, never rewritten here"
        alive = await session.get(TipAnalystRun, "old-but-alive")
        assert alive.status == "running" and alive.owner == runtime_id() and alive.heartbeat_at is not None
    # the job finishes -> released -> the desk is free to restart
    gate.set()
    await task
    analyst.release_run(eng, "old-but-alive")
    async with eng.sf() as session:
        (await session.get(TipAnalystRun, "old-but-alive")).status = "done"
        (await session.get(TipAnalystRun, "ours-fresh")).status = "done"
        (await session.get(TipAnalystRun, "foreign-fresh")).status = "done"
        await session.commit()
    st = await restart_state(eng)
    assert st["tipRuns"] == [] and st["tipRunsReconciled"] == [] and st["inflightRuns"] == 0


async def test_recorder_registers_heartbeats_and_releases_on_terminal_persist(app_client):  # noqa: F811
    _, eng = app_client
    async with eng.sf() as session:
        session.add(_row("rec-run", age_h=3))
        await session.commit()

    async def run():
        rec = analyst._Recorder(eng, "rec-run")
        assert "rec-run" in analyst.live_runs(eng)
        rec.step("note", "thinking")
        pending = eng._tip_run_registry["rec-run"]["pending"]
        if pending is not None:
            await pending
        async with eng.sf() as session:
            row = await session.get(TipAnalystRun, "rec-run")
            assert row.heartbeat_at is not None and row.owner == runtime_id()
        await analyst._persist_run(eng, "rec-run", status="done", rec=rec, opinion={"verdict": "skip"})
        assert "rec-run" not in analyst.live_runs(eng) and "rec-run" not in eng._tip_run_registry

    await asyncio.create_task(run())
    async with eng.sf() as session:
        assert (await session.get(TipAnalystRun, "rec-run")).status == "done"
