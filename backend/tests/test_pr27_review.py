"""PR27 historical isolation and reproducible rule snapshot boundaries."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.techniques.tip import analyst

from .test_knowledge_governance import rig as rig  # noqa: PLC0414
from .test_tip_analyst_loop import _Block, _json_opinion, _Resp, _Scripted
from .test_tip_loop_followup import signal_row


async def test_historical_mode_cannot_close_current_position():
    close = AsyncMock(return_value={"status": "closed"})
    p = NS(id="current", technique="tip", status="open", portfolio_id="practice")
    eng = NS(settings={}, position_manager=NS(get=lambda _: p, close=close),
             positions=NS(portfolio=lambda _: {"kind": "sim"}))
    result = await analyst._run_tool(eng, "close_position", {"position_id": "current", "reason": "offline"},
                                    ctx={"experiment": "x", "asOfMs": 1750000000000})
    assert close.await_count == 0 and result.get("error"), result


async def test_historical_mode_without_timestamp_never_fetches_current_bars(monkeypatch):
    from zargar.marketstructure import history
    recent = AsyncMock(return_value=[])
    monkeypatch.setattr(history, "fetch_recent", recent)
    result = await analyst._run_tool(NS(), "get_bars", {"symbol": "TEST"}, ctx={"experiment": "x"})
    assert recent.await_count == 0 and result.get("error"), result


async def test_rule_snapshot_changes_when_same_rule_is_edited():
    note = {"id": "rule-unchanged-id", "createdAt": "2026-09-09", "text": "old policy"}
    service = NS(tip_notes=AsyncMock(side_effect=[[note], [{**note, "text": "opposite policy"}]]))
    eng = NS(signals_service=service)
    await analyst._rules_text(eng)
    old_hash = analyst._rules_text.last_snapshot["rulesHash"]
    await analyst._rules_text(eng)
    assert analyst._rules_text.last_snapshot["rulesHash"] != old_hash


async def test_historical_appraisal_does_not_receive_future_rules(rig):
    await rig.signals_service.add_tip_note("rule", "AFTER_EVENT_SECRET: outcome learned after June")
    row = signal_row()
    row.extraction = {"statedAt": "2026-06-01T14:00:00+00:00"}
    client = _Scripted([_Resp([_Block(type="text", text=_json_opinion())])])
    result = await analyst.analyze_tip(rig, row, {"passed": True, "checks": []},
        NS(budget_per_tip=500, dte_min=3, dte_max=45), client=client, experiment="offline-history")
    assert result is not None
    assert "AFTER_EVENT_SECRET" not in str(client.requests)
