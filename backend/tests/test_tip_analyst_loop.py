"""Codex audit finding 4: repair keeps its evidence, the tool budget forces a
final answer, usage/stop reasons are recorded, receipts capture side effects,
and interrupted runs reconcile to a terminal state."""
import datetime as dt

from zargar.domain import new_id
from zargar.engine import Engine
from zargar.models import TipAnalystRun
from zargar.signals.service import attach_signal_layer
from zargar.techniques.tip.analyst import (_Recorder, reconcile_stale_runs,
                                           run_agent_loop)

from .conftest import make_test_config


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, content, stop="end_turn", usage=(100, 50)):
        self.content = content
        self.stop_reason = stop
        self.usage = _Block(input_tokens=usage[0], output_tokens=usage[1])


def _json_opinion():
    return ('{"verdict": "skip", "rationale": "test", "confidence": 0.5,'
            ' "invalidation": "n/a"}')


class _Scripted:
    """messages.create returns the scripted responses in order and records
    every request's messages list for transcript assertions."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests: list[list] = []
        self.messages = self

    async def create(self, **kw):
        self.requests.append([dict(m) if isinstance(m, dict) else m
                              for m in kw["messages"]])
        return self._responses.pop(0)


import pytest


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


async def _mk_run(eng, run_id):
    async with eng.sf() as session:
        session.add(TipAnalystRun(id=run_id, ticker="TEST", status="running"))
        await session.commit()


async def test_budget_exhaustion_forces_a_final_answer(rig):
    """Four tools used + a fifth request no longer returns unserviced text:
    the request is stubbed, the model is told to answer, and it does."""
    eng = rig
    run_id = new_id()
    await _mk_run(eng, run_id)
    client = _Scripted([
        _Resp([_Block(type="tool_use", id="t1", name="get_quote",
                      input={"symbol": "TEST"})]),      # budget already full
        _Resp([_Block(type="text", text=_json_opinion())]),
    ])
    rec = _Recorder(eng, run_id)
    state: dict = {}
    tools_used = [{"tool": "x", "args": {}}] * 4        # budget (4) consumed
    text = await run_agent_loop(
        eng, client, model="m", system="s", header="h", rec=rec, run_id=run_id,
        max_tools=4, tool_ctx={}, tools_used=tools_used, state=state)
    assert text and '"verdict"' in text
    # the over-budget call was SERVICED with a stub + a JSON-now instruction
    last_req = client.requests[-1]
    assert any(isinstance(m, dict) and m.get("role") == "user"
               and "ONLY the JSON" in str(m.get("content")) for m in last_req)
    assert state["usage"]["calls"] == 2 and state["usage"]["in"] == 200
    assert state["usage"]["stops"] == ["end_turn", "end_turn"]


async def test_state_carries_the_transcript_for_same_conversation_repair(rig):
    """The repair pass continues the SAME messages list — the first attempt's
    tool results stay in evidence (the old repair rebuilt from the header)."""
    eng = rig
    run_id = new_id()
    await _mk_run(eng, run_id)
    client = _Scripted([
        _Resp([_Block(type="tool_use", id="t1", name="get_quote",
                      input={"symbol": "TEST"})]),
        _Resp([_Block(type="text", text="not JSON at all")]),
        _Resp([_Block(type="text", text=_json_opinion())]),
    ])
    rec = _Recorder(eng, run_id)
    state: dict = {}
    text = await run_agent_loop(eng, client, model="m", system="s", header="h",
                                rec=rec, run_id=run_id, max_tools=4,
                                tool_ctx={}, tools_used=[], state=state)
    assert text == "not JSON at all"
    # caller-side repair: append the failure exchange, continue the same state
    state["messages"].append({"role": "assistant", "content": text})
    state["messages"].append({"role": "user", "content": "Reply with ONLY the JSON opinion object now."})
    text2 = await run_agent_loop(eng, client, model="m", system="s", header="h",
                                 rec=rec, run_id=run_id, max_tools=4,
                                 tool_ctx={}, tools_used=[], state=state)
    assert text2 and '"verdict"' in text2
    last_req = client.requests[-1]
    kinds = [str(m) for m in last_req]
    assert any("tool_result" in k for k in kinds), "tool evidence must be retained"
    assert any("not JSON at all" in k for k in kinds), "partial answer must be retained"


async def test_mutating_tools_leave_receipts(rig, monkeypatch):
    eng = rig
    run_id = new_id()
    await _mk_run(eng, run_id)

    async def fake_tool(eng_, name, args, ctx=None):
        return {"ok": True}
    import zargar.techniques.tip.analyst as an
    monkeypatch.setattr(an, "_run_tool", fake_tool)
    client = _Scripted([
        _Resp([_Block(type="tool_use", id="t1", name="save_note",
                      input={"scope": "general", "text": "x"})]),
        _Resp([_Block(type="text", text=_json_opinion())]),
    ])
    rec = _Recorder(eng, run_id)
    ctx: dict = {}
    await run_agent_loop(eng, client, model="m", system="s", header="h",
                         rec=rec, run_id=run_id, max_tools=4,
                         tool_ctx=ctx, tools_used=[], state={})
    assert ctx.get("receipts") and ctx["receipts"][0]["tool"] == "save_note"
    assert any(s.get("kind") == "receipt" for s in rec.trace)


async def test_stale_running_runs_reconcile_at_boot(rig):
    eng = rig
    old_id, fresh_id = new_id(), new_id()
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
    async with eng.sf() as session:
        session.add(TipAnalystRun(id=old_id, ticker="OLD", status="running",
                                  created_at=old))
        session.add(TipAnalystRun(id=fresh_id, ticker="NEW", status="running"))
        await session.commit()
    n = await reconcile_stale_runs(eng)
    assert n == 1
    async with eng.sf() as session:
        stale = await session.get(TipAnalystRun, old_id)
        fresh = await session.get(TipAnalystRun, fresh_id)
    assert stale.status == "failed" and "reconciled at boot" in stale.error
    assert stale.finished_at is not None
    assert fresh.status == "running"        # in-flight work is left alone
