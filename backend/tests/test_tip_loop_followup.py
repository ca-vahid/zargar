"""Independent finding-4 boundaries; run via scripts/test-codex.ps1 only.

Expected failures identify remaining work in v0.7.20. Provider I/O is scripted.
"""
import asyncio
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from zargar.domain import new_id
from zargar.models import TipAnalystRun
from zargar.signals.schemas import TradeSignal
from zargar.techniques.tip import analyst

from .test_tip_analyst_loop import _Block, _json_opinion, _mk_run, _Resp, _Scripted
from .test_tip_analyst_loop import rig as rig  # noqa: PLC0414 -- pytest fixture re-export


def signal_row():
    signal = TradeSignal(ticker="TEST", direction="long", instrument="shares",
        confidence="explicit_call", is_actionable=True, thesis_summary="offline",
        evidence_quotes=["TEST offline"])
    return NS(**signal.model_dump(), id=new_id(), source_name="OfflineAudit",
              status="verified", extraction={}, created_at=dt.datetime.now(dt.UTC))


async def appraise(eng, client, row):
    return await analyst.analyze_tip(eng, row, {"passed": True, "checks": []},
        NS(budget_per_tip=500, dte_min=3, dte_max=45), client=client)


async def test_appraisal_repair_retains_real_caller_tool_evidence(rig, monkeypatch):
    monkeypatch.setattr(analyst, "_run_tool", AsyncMock(return_value={"evidence": "retained-marker"}))
    client = _Scripted([
        _Resp([_Block(type="tool_use", id="evidence", name="get_quote", input={"symbol": "TEST"})]),
        _Resp([_Block(type="text", text="partial invalid answer")], stop="max_tokens"),
        _Resp([_Block(type="text", text=_json_opinion())]),
    ])
    result = await appraise(rig, client, signal_row())
    assert result and result["verdict"] == "skip"
    assert result["usage"]["calls"] == 3
    assert "retained-marker" in str(client.requests[-1])
    assert "partial invalid answer" in str(client.requests[-1])


async def test_failed_appraisal_persists_consumed_usage(rig):
    row = signal_row()
    client = _Scripted([_Resp([_Block(type="text", text="not JSON")]) for _ in range(2)])
    assert await appraise(rig, client, row) is None
    async with rig.sf() as session:
        saved = (await session.execute(select(TipAnalystRun).where(
            TipAnalystRun.signal_id == row.id))).scalar_one()
    assert saved.status == "failed"
    assert (saved.opinion.get("usage") or {}).get("calls") == 2, saved.opinion


async def test_successful_intake_review_persists_usage(rig):
    intake = analyst.IntakeRun(rig)
    await intake.start(source="OfflineAudit", chars=12, has_image=False)
    client = _Scripted([_Resp([_Block(type="text", text='{"headline":"offline review"}')])])
    await intake.review(source="OfflineAudit", message_text="offline note", outcomes=[], client=client)
    async with rig.sf() as session:
        saved = await session.get(TipAnalystRun, intake.id)
    assert saved.status == "done"
    assert (saved.opinion.get("usage") or {}).get("calls") == 1, saved.opinion


async def test_cancelled_intake_review_is_terminal(rig):
    intake = analyst.IntakeRun(rig)
    await intake.start(source="OfflineAudit", chars=12, has_image=False)
    client = NS(messages=NS(create=AsyncMock(side_effect=asyncio.CancelledError())))
    with pytest.raises(asyncio.CancelledError):
        await intake.review(source="OfflineAudit", message_text="offline note", outcomes=[], client=client)
    # A restart within six minutes does not reconcile it either; no wait is needed.
    await analyst.reconcile_stale_runs(rig)
    async with rig.sf() as session:
        saved = await session.get(TipAnalystRun, intake.id)
    assert saved.status == "failed" and saved.finished_at is not None, saved.status


async def test_declined_disarm_is_not_counted_as_completed_side_effect(rig, monkeypatch):
    # Real tool dispatch, fake runner reporting that no disarm was performed.
    monkeypatch.setattr(rig, "tip_runner",
        NS(get=lambda rid: NS(technique="tip", trades={}, symbol="TEST"),
           disarm=AsyncMock(return_value=False)), raising=False)
    rid = new_id()
    await _mk_run(rig, rid)
    rec = analyst._Recorder(rig, rid)
    ctx = {}
    client = _Scripted([
        _Resp([_Block(type="tool_use", id="disarm", name="disarm_plan",
                     input={"run_id": "offline-plan", "reason": "test"})]),
        _Resp([_Block(type="text", text=_json_opinion())]),
    ])
    await analyst.run_agent_loop(rig, client, model="offline", system="s", header="h",
        rec=rec, run_id=rid, max_tools=4, tool_ctx=ctx, tools_used=[], state={})
    assert rig.tip_runner.disarm.await_count == 1
    assert not ctx.get("receipts"), ctx.get("receipts")
