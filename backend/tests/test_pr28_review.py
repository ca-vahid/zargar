"""Independent PR28 metrics and real fill-time boundaries."""
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from zargar.domain import new_id
from zargar.models import Execution, Order
from zargar.research import llm_stats
from zargar.signals.extraction import Extractor
from zargar.techniques.tip import analyst

from .test_llm_measurement import rig as rig  # noqa: PLC0414
from .test_tip_analyst_loop import _Block, _json_opinion, _Resp, _Scripted


@pytest.fixture(autouse=True)
def clean_metrics(monkeypatch):
    monkeypatch.setattr(llm_stats, "_ACC", {})


async def test_failed_journal_flush_preserves_metrics_for_retry():
    llm_stats.record("extraction", input_tokens=10)
    eng = NS(journal=NS(append=AsyncMock(side_effect=RuntimeError("offline"))))
    assert await llm_stats.flush(eng) == 0
    eng.journal.append = AsyncMock()
    assert await llm_stats.flush(eng) == 1, "Failed journal write must not lose the batch"


async def test_invalid_output_annotation_does_not_add_a_request():
    extractor = Extractor("offline", "offline")
    extractor._client = _Scripted([_Resp([_Block(type="text", text="not JSON")]) for _ in range(2)])
    result = await extractor.extract("offline")
    assert result.outcome == "invalid_output"
    stats = next(iter(llm_stats._ACC.values()))["extraction"]
    assert stats["requests"] == 1 and stats["retries"] == 1, stats


async def test_normal_tool_turn_is_not_a_provider_retry(monkeypatch):
    monkeypatch.setattr(analyst, "_persist_run", AsyncMock())
    monkeypatch.setattr(analyst, "_run_tool", AsyncMock(return_value={"price": 10}))
    client = _Scripted([
        _Resp([_Block(type="tool_use", id="quote", name="get_quote", input={"symbol": "TEST"})]),
        _Resp([_Block(type="text", text=_json_opinion())]),
    ])
    await analyst.run_agent_loop(NS(), client, model="offline", system="s", header="h",
        rec=NS(step=lambda *args, **kw: None), run_id="offline", max_tools=4,
        tool_ctx={}, tools_used=[], state={})
    stats = next(iter(llm_stats._ACC.values()))["appraise"]
    assert stats["retries"] == 0, stats


async def test_intake_review_is_not_counted_as_appraisal(rig):
    intake = analyst.IntakeRun(rig)
    await intake.start(source="offline", chars=12, has_image=False)
    client = _Scripted([_Resp([_Block(type="text", text='{"headline":"offline"}')])])
    await intake.review(source="offline", message_text="offline", outcomes=[], client=client)
    stages = next(iter(llm_stats._ACC.values()))
    assert "review" in stages and "appraise" not in stages, stages


async def test_old_order_filled_today_does_not_count_as_aged(rig, monkeypatch):
    source = "ActualFillAge"
    shadow = await rig.signals_service.shadow_portfolio(source, "immediate")
    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=10)
    fresh = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=30)
    oid = new_id()
    async with rig.sf() as session:
        session.add(Order(id=oid, portfolio_id=shadow["id"], symbol="EP", sec_type="STK",
            side="BUY", qty=10, filled_qty=10, order_type="LMT", limit_price=10,
            status="FILLED", created_at=old, updated_at=fresh))
        await session.flush()
        session.add(Execution(id=new_id(), order_id=oid, portfolio_id=shadow["id"],
            symbol="EP", side="BUY", qty=10, price=10, ts=fresh))
        await session.commit()
    monkeypatch.setattr(rig.positions, "positions_list", lambda pid: [
        {"symbol": "EP", "qty": 10, "avgCost": 10, "last": 12}])
    trust = await rig.signals_service.source_trust(source)
    assert trust["shadowImmediate"] == {"graded": 0, "hits": 0}, trust
