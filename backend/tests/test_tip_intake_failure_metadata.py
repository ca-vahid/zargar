"""v0.7.21 failure-finalization acceptance; isolated DB and scripted LLM only."""
from zargar.models import TipAnalystRun
from zargar.techniques.tip.analyst import IntakeRun

from .test_tip_analyst_loop import _Block, _Resp, _Scripted
from .test_tip_analyst_loop import rig as rig  # noqa: PLC0414 -- pytest fixture re-export


async def test_failed_intake_finish_preserves_usage_and_receipts(rig):
    intake = IntakeRun(rig)
    await intake.start(source="OfflineAudit", chars=12, has_image=False)
    client = _Scripted([
        _Resp([_Block(type="tool_use", id="save", name="save_note",
                     input={"scope": "general", "text": "Offline test note"})]),
        _Resp([_Block(type="text", text="invalid final JSON")]),
    ])
    result = await intake.review(source="OfflineAudit", message_text="offline note",
                                 outcomes=[], client=client)
    assert result is None
    async with rig.sf() as session:
        saved = await session.get(TipAnalystRun, intake.id)
    assert saved.status == "failed" and saved.finished_at is not None
    assert any(step.get("kind") == "receipt" for step in saved.trace)
    assert (saved.opinion.get("usage") or {}).get("calls") == 2, saved.opinion
    assert len(saved.opinion.get("receipts") or []) == 1, saved.opinion
