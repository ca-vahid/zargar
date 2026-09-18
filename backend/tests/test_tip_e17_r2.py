"""E17 F1-R2 / F2-R2 companions: the FINAL call's timeout stays terminal, fenced single objects with
harmless prose still parse, and the backoff seam is what tests replace. Scripted only."""
import asyncio

import pytest

from zargar.domain import new_id
from zargar.signals.extraction import _parse_result_json
from zargar.techniques.tip import analyst
from zargar.techniques.tip.analyst import AnalystDeadline, AnalystOpinion, ReviewOpinion, parse_single_object

from .test_tip_analyst_loop import _Block, _Resp, _json_opinion, _mk_run
from .test_tip_analyst_loop import rig as rig  # noqa: PLC0414 - fixture re-export


async def test_final_call_timeout_remains_terminal_and_typed(rig, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(analyst, "_loop_now", lambda: clock["t"])

    class Client:
        def __init__(self): self.messages = self; self.kw = []
        async def create(self, **kw):
            self.kw.append(kw)
            clock["t"] = 119.5
            raise asyncio.TimeoutError("final call cut")
    run_id = new_id(); await _mk_run(rig, run_id)
    state = analyst._arm_deadline({}, rig, timeout_s=120)
    state["forceFinal"] = True                          # already inside the reserve: this IS the final call
    client = Client()
    with pytest.raises(AnalystDeadline):
        await analyst.run_agent_loop(rig, client, model="m", system="s", header="h", rec=analyst._Recorder(rig, run_id),
                                     run_id=run_id, max_tools=4, tool_ctx={"stage": "appraise"}, tools_used=[], state=state)
    assert len(client.kw) == 1 and client.kw[0].get("tool_choice") == {"type": "none"}
    assert state["failure"]["kind"] == "timeout" and "final" in state["failure"]["detail"]
    assert state["usage"]["partial"] is True and state["usage"]["unknownCalls"] == 1


async def test_optional_timeout_then_final_answer_leaves_no_failure_on_a_successful_run(rig, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(analyst, "_loop_now", lambda: clock["t"])

    class Client:
        def __init__(self): self.messages = self; self.kw = []
        async def create(self, **kw):
            self.kw.append(kw)
            if len(self.kw) == 1:
                clock["t"] = 100.0
                raise asyncio.TimeoutError("optional cut")
            return _Resp([_Block(type="text", text=_json_opinion())])
    run_id = new_id(); await _mk_run(rig, run_id)
    state = analyst._arm_deadline({}, rig, timeout_s=120)
    text = await analyst.run_agent_loop(rig, Client(), model="m", system="s", header="h", rec=analyst._Recorder(rig, run_id),
                                        run_id=run_id, max_tools=4, tool_ctx={"stage": "appraise"}, tools_used=[], state=state)
    assert text and '"verdict"' in text
    assert state.get("failure") is None, "a run that reached a verdict carries no failure"
    assert state["usage"]["partial"] is True and state["usage"]["unknownCalls"] == 1 and state["usage"]["calls"] == 1


def test_fenced_single_objects_with_harmless_prose_still_parse_everywhere():
    op = _json_opinion()
    assert parse_single_object("```json\n" + op + "\n```\nThat is my read.", AnalystOpinion).verdict == "skip"
    assert parse_single_object("Here:\n```\n" + op + "\n```", AnalystOpinion).verdict == "skip"
    rv = '{"headline":"h","details":"","watch":[],"missed_tip":null,"confidence":0.4}'
    assert parse_single_object("```json\n" + rv + "\n``` thanks", ReviewOpinion).headline == "h"
    ex = '{"signals": [], "source_type": "other"}'
    assert _parse_result_json("```json\n" + ex + "\n```\nNo trades here.").source_type == "other"
    # unrelated JSON after the fence stays harmless; a competing valid object after it does not
    assert _parse_result_json("```json\n" + ex + '\n```\n{"x": 1}').source_type == "other"
    with pytest.raises(ValueError, match="ambiguity"):
        _parse_result_json("```json\n" + ex + "\n```\nCorrection:\n```json\n" + ex.replace("other", "trade_alert") + "\n```")


async def test_backoff_seam_is_used_for_provider_retries(rig, monkeypatch):
    slept = []

    async def fake_backoff(d):
        slept.append(d)
    monkeypatch.setattr(analyst, "_backoff_sleep", fake_backoff)

    class Overloaded(Exception):
        status_code = 529

    class Client:
        def __init__(self): self.messages = self; self.n = 0
        async def create(self, **kw):
            self.n += 1
            if self.n == 1:
                raise Overloaded("overloaded")
            return _Resp([_Block(type="text", text=_json_opinion())])
    run_id = new_id(); await _mk_run(rig, run_id)
    state = analyst._arm_deadline({}, rig, timeout_s=120)
    text = await analyst.run_agent_loop(rig, Client(), model="m", system="s", header="h", rec=analyst._Recorder(rig, run_id),
                                        run_id=run_id, max_tools=4, tool_ctx={"stage": "appraise"}, tools_used=[], state=state)
    assert text and '"verdict"' in text and slept == [analyst._API_RETRY_DELAYS[0]]
    assert state["usage"]["retries"] == 1 and state["usage"]["calls"] == 1
