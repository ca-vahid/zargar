"""Reserve timeout and fenced ambiguity boundaries; scripted, no paid calls."""
import asyncio
import pytest
from zargar.domain import new_id
from zargar.signals.extraction import _parse_result_json
from zargar.techniques.tip import analyst
from .test_tip_analyst_loop import rig, _Block, _Resp, _json_opinion, _mk_run


async def test_optional_call_timeout_spends_reserve_on_final_answer(rig, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(analyst, "_loop_now", lambda: clock["t"])
    class Client:
        def __init__(self): self.messages = self; self.kw = []
        async def create(self, **kw):
            self.kw.append(kw)
            if len(self.kw) == 1:
                clock["t"] = 100.0
                raise asyncio.TimeoutError("optional-call allowance exhausted")
            return _Resp([_Block(type="text", text=_json_opinion())])
    client = Client()
    run_id = new_id()
    await _mk_run(rig, run_id)
    state = analyst._arm_deadline({}, rig, timeout_s=120)
    text = await analyst.run_agent_loop(rig, client, model="m", system="s", header="h",
        rec=analyst._Recorder(rig, run_id), run_id=run_id, max_tools=4,
        tool_ctx={"stage": "appraise"}, tools_used=[], state=state)
    assert text and '"verdict"' in text
    assert len(client.kw) == 2 and client.kw[-1].get("tool_choice") == {"type": "none"}
    assert state["usage"]["partial"] and state["usage"]["unknownCalls"] == 1


@pytest.mark.parametrize("kind", ["extraction", "analyst", "review"])
def test_conflicting_object_after_closing_fence_is_not_discarded(kind):
    if kind == "extraction":
        first = '{"signals": [], "source_type": "other"}'
        second = '{"signals": [], "source_type": "trade_alert"}'
        parse = _parse_result_json
    elif kind == "analyst":
        first = _json_opinion()
        second = first.replace('"skip"', '"take"')
        parse = analyst._parse_opinion
    else:
        first = '{"headline":"first","details":"","watch":[],"missed_tip":null,"confidence":0.4}'
        second = first.replace("first", "correction")
        parse = lambda raw: analyst.parse_single_object(raw, analyst.ReviewOpinion)
    parse(first)
    parse(second)
    with pytest.raises(ValueError, match="ambiguity"):
        parse("```json\n" + first + "\n```\nCorrection:\n" + second)
