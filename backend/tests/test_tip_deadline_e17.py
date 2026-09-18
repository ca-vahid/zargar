"""E17-02 (2026-09-17): the analyst loop keeps time for a final answer, records TYPED failures
(timeout / deadline / validation / error) with stage + elapsed/remaining, marks usage partial when a
call is cut, repairs on the same deadline with tools off, and the intake parser takes the first
complete JSON object. Scripted clients only - no provider, no network."""
import asyncio

from zargar.domain import new_id
from zargar.models import TipAnalystRun
from zargar.signals.extraction import _parse_result_json
from zargar.techniques.tip import analyst
from zargar.techniques.tip.analyst import (AnalystDeadline, IntakeRun, _Recorder, _arm_deadline,
                                           _fail_meta, run_agent_loop)

from .test_tip_analyst_loop import _Block, _Resp, _json_opinion, _mk_run
from .test_tip_analyst_loop import rig as rig  # noqa: PLC0414 - fixture re-export


class _SlowScripted:
    """Scripted responses, each delivered after its own delay; records every request's kwargs."""

    def __init__(self, items):
        self._items = list(items)          # (delay_s, response) or (delay_s, Exception)
        self.requests: list[dict] = []
        self.messages = self

    async def create(self, **kw):
        self.requests.append({k: (list(v) if k == "messages" else v) for k, v in kw.items()})
        delay, item = self._items.pop(0)
        await asyncio.sleep(delay)
        if isinstance(item, BaseException):
            raise item
        return item


def _tool_use(i):
    return _Resp([_Block(type="tool_use", id=f"t{i}", name="get_quote", input={"symbol": "TEST"})])


async def test_reserve_forces_a_terminal_answer_before_the_deadline(rig, monkeypatch):
    """A scripted near-deadline tool chain on a FAKE monotonic clock: once the remaining budget drops
    inside the reserve the loop stops tool work, tells the model to answer with tools off, and a
    verdict lands. Deterministic - no real sleeps."""
    eng = rig
    run_id = new_id()
    await _mk_run(eng, run_id)
    clock = {"t": 0.0}
    monkeypatch.setattr(analyst, "_loop_now", lambda: clock["t"])

    class Client:
        def __init__(self): self.messages = self; self.n = 0; self.requests = []
        async def create(self, **kw):
            self.requests.append(kw); self.n += 1
            if self.n == 1:
                clock["t"] = 60.0                      # 60 s left of 120, reserve 20: optional work allowed
                return _tool_use(1)
            if self.n == 2:
                clock["t"] = 105.0                     # reply lands inside the reserve -> its tool is stubbed
                return _tool_use(2)
            return _Resp([_Block(type="text", text=_json_opinion())])
    client = Client()
    state = _arm_deadline({}, eng, timeout_s=120.0)
    rec = _Recorder(eng, run_id)
    text = await run_agent_loop(eng, client, model="m", system="s", header="h", rec=rec, run_id=run_id,
                                max_tools=6, tool_ctx={"stage": "appraise"}, tools_used=[], state=state)
    assert text and '"verdict"' in text
    last = client.requests[-1]
    assert last.get("tool_choice") == {"type": "none"}, "tools must be off inside the reserve"
    assert any(m.get("role") == "user" and "ONLY the JSON" in str(m.get("content")) for m in last["messages"] if isinstance(m, dict))
    assert state["forceFinal"] is True and state.get("failure") is None
    assert state["usage"]["calls"] == 3 and state["usage"]["unknownCalls"] == 0 and state["usage"]["partial"] is False
    # the second tool request arrived inside the reserve: it was STUBBED, not executed
    assert any(s.get("kind") == "note" and "reserve" in str(s.get("text", "")).lower() for s in rec.trace)
    assert not any(s.get("kind") == "tool_result" and s.get("tool") == "get_quote" and "t2" in str(s) for s in rec.trace)


async def test_provider_call_that_outlives_the_deadline_is_a_typed_timeout_with_partial_usage(rig):
    eng = rig
    run_id = new_id()
    await _mk_run(eng, run_id)
    client = _SlowScripted([(5.0, _Resp([_Block(type="text", text=_json_opinion())]))])
    state = _arm_deadline({}, eng, timeout_s=1.2)
    state["reserveS"] = 0.2
    rec = _Recorder(eng, run_id)
    try:
        await run_agent_loop(eng, client, model="m", system="s", header="h", rec=rec, run_id=run_id,
                             max_tools=4, tool_ctx={"stage": "appraise"}, tools_used=[], state=state)
        raise AssertionError("expected AnalystDeadline")
    except AnalystDeadline:
        pass
    f = state["failure"]
    assert f["kind"] == "timeout" and f["stage"] == "appraise" and f["detail"]
    assert f["elapsedS"] is not None and f["remainingS"] is not None and f["remainingS"] <= 0.5
    u = state["usage"]
    assert u["calls"] == 0 and u["unknownCalls"] == 1 and u["partial"] is True
    assert any("timeout" in (e.get("error") or "") for e in u["perCall"])
    meta = _fail_meta(state, {"stage": "appraise"}, exc=asyncio.TimeoutError(), stage="appraise")
    assert meta["failure"]["kind"] == "timeout" and meta["usage"]["partial"] is True


async def test_an_exhausted_deadline_before_any_call_is_typed_not_silent(rig):
    eng = rig
    run_id = new_id()
    await _mk_run(eng, run_id)
    client = _SlowScripted([(0.0, _Resp([_Block(type="text", text=_json_opinion())]))])
    state = _arm_deadline({}, eng, timeout_s=0.1)
    await asyncio.sleep(0.15)
    try:
        await run_agent_loop(eng, client, model="m", system="s", header="h", rec=_Recorder(eng, run_id), run_id=run_id,
                             max_tools=4, tool_ctx={"stage": "appraise"}, tools_used=[], state=state)
        raise AssertionError("expected AnalystDeadline")
    except AnalystDeadline as exc:
        assert "deadline" in str(exc)
    assert state["failure"]["kind"] == "deadline" and client.requests == []


def test_empty_exception_strings_still_yield_a_typed_error():
    state = _arm_deadline({}, None, timeout_s=10.0)
    meta = _fail_meta(state, {"stage": "review"}, exc=RuntimeError(""), stage="review")
    assert meta["failure"]["kind"] == "error" and meta["failure"]["detail"] == "RuntimeError"
    meta2 = _fail_meta(_arm_deadline({}, None), None, exc=asyncio.TimeoutError(), stage="appraise")
    assert meta2["failure"] == {**meta2["failure"], "kind": "timeout", "detail": "TimeoutError"}
    meta3 = _fail_meta({}, None, exc=ValueError("no JSON object in analyst reply"), stage="appraise")
    assert meta3["failure"]["kind"] == "validation" and meta3["failure"]["elapsedS"] is None


async def test_intake_review_failing_after_a_note_keeps_one_receipt_and_a_typed_failure(rig, monkeypatch):
    """The reviewer's failed-after-note case under the deadline: the note's receipt survives once,
    the provider call that outlives the deadline is typed, usage is partial, the error is not empty."""
    # 4 s budget, reserve clamps to 2 s: the note's tool call runs with time to spare (E17-F1 bounds
    # optional work to remaining - reserve), the second call sleeps past that optional budget
    monkeypatch.setattr(analyst, "TIMEOUT_S", 4.0)
    intake = IntakeRun(rig)
    await intake.start(source="OfflineAudit", chars=12, has_image=False)
    client = _SlowScripted([
        (0.0, _Resp([_Block(type="tool_use", id="save", name="save_note",
                            input={"scope": "general", "text": "Offline deadline note"})])),
        (6.0, _Resp([_Block(type="text", text="never arrives in time")])),      # optional call cut at the reserve
        (6.0, _Resp([_Block(type="text", text="the final call is cut too")])),  # F1-R2: final call also outlives the deadline
    ])
    result = await intake.review(source="OfflineAudit", message_text="offline note", outcomes=[], client=client)
    assert result is None
    async with rig.sf() as session:
        saved = await session.get(TipAnalystRun, intake.id)
    assert saved.status == "failed" and saved.error and "timeout" in saved.error
    op = saved.opinion or {}
    assert op.get("failure", {}).get("kind") == "timeout" and op["failure"]["stage"] == "review"
    assert len(op.get("receipts") or []) == 1, "the note was saved once and stays on the record"
    # one or two cut calls depending on where the reserve boundary fell (the second call may already
    # have been the final one): partial usage either way, never zero unknown calls
    assert (op.get("usage") or {}).get("partial") is True and op["usage"]["unknownCalls"] in (1, 2)
    assert sum(1 for s in saved.trace if s.get("kind") == "receipt") == 1


def test_extraction_parser_takes_the_first_complete_object_and_types_validation_errors():
    ok = _parse_result_json('Here you go: {"signals": [], "source_type": "other"} trailing junk {"x": 1}')
    assert ok.signals == [] and ok.source_type == "other"
    fenced = _parse_result_json('```json\n{"signals": [], "source_type": "other"}\n```\nthanks')
    assert fenced.source_type == "other"
    try:
        _parse_result_json('{"signals": [], "source_type": "other"')
        raise AssertionError("expected a typed validation error")
    except ValueError as exc:
        assert str(exc).startswith("validation:")
    try:
        _parse_result_json("no object here")
        raise AssertionError("expected a typed validation error")
    except ValueError as exc:
        assert str(exc).startswith("validation:")
