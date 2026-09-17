"""Additional deadline, ambiguous JSON and model-pricing boundaries."""
import json
from unittest.mock import AsyncMock
import pytest
from zargar.domain import new_id
from zargar.techniques.tip import analyst
from zargar.models import TipAnalystRun
from zargar.tools.tip_llm_cost import load_runs
from zargar.signals.extraction import _parse_result_json
from .test_tip_analyst_loop import _Block, _Resp, _json_opinion, _mk_run
from .test_tip_analyst_loop import rig  # noqa: F401


async def test_tool_returning_inside_reserve_cannot_execute_mutation(rig, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(analyst, "_loop_now", lambda: clock["t"])
    spy = AsyncMock(return_value={"saved": True})
    monkeypatch.setattr(analyst, "_run_tool", spy)
    class Client:
        def __init__(self): self.messages=self; self.n=0
        async def create(self, **kwargs):
            self.n+=1
            if self.n==1:
                clock["t"]=105.0  # provider returns inside the 20s reserve
                return _Resp([_Block(type="tool_use",id="save",name="save_note",input={"scope":"general","text":"late"})])
            return _Resp([_Block(type="text",text=_json_opinion())])
    run_id=new_id(); await _mk_run(rig,run_id)
    state=analyst._arm_deadline({},rig,timeout_s=120)
    await analyst.run_agent_loop(rig,Client(),model="review-model",system="s",header="h",
        rec=analyst._Recorder(rig,run_id),run_id=run_id,max_tools=4,tool_ctx={"stage":"appraise"},tools_used=[],state=state)
    assert spy.await_count == 0, "late provider response executed optional mutation inside final-answer reserve"


def test_conflicting_valid_extraction_objects_are_not_silently_accepted():
    first=json.dumps({"signals":[],"source_type":"other"})
    second=json.dumps({"signals":[{"ticker":"AAPL","direction":"long","instrument":"shares",
        "entry_price":100,"thesis_summary":"fresh buy","confidence":"explicit_call",
        "evidence_quotes":["BTO AAPL at100"],"is_actionable":True}],"source_type":"trade_alert"})
    assert len(_parse_result_json(first).signals)==0
    assert len(_parse_result_json(second).signals)==1
    with pytest.raises(ValueError):
        _parse_result_json(first+"\nCorrection:\n"+second)


async def test_cost_uses_model_that_generated_usage(rig):
    import datetime as dt
    run_id=new_id(); await _mk_run(rig,run_id)
    async with rig.sf() as session:
        r=await session.get(TipAnalystRun,run_id)
        r.kind="intake";r.status="done"
        r.opinion={"model":"extraction-model", "usage":{"model":"review-model","in":1000,"out":100,"calls":1}}
        r.created_at=dt.datetime(2026,9,17,15,tzinfo=dt.timezone.utc)
        await session.commit()
    rows=await load_runs(rig.sf,since="2026-09-17",until="2026-09-17")
    row=next(r for r in rows if r["id"]==run_id)
    assert row["model"]=="review-model", "review tokens were attributed to the extractor's rate card"
