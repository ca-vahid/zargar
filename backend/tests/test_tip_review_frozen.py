"""Frozen evaluation of intake reviews (2026-09-19): a captured review replays on another model with NO side effect -
a management tool is a recorded proposal, reads come from the case, the budget is mandatory and enforced."""
import json
from types import SimpleNamespace as NS

import pytest

from zargar.techniques.tip import review_frozen as rf
from zargar.techniques.tip.frozen import ReplayBudget

RATE = {"in": 2.0, "out": 10.0, "cacheRead": 0.2, "cacheWrite": 2.5}


def _run(*, captured=True, mgmt=True):
    trace = [{"kind": "start", "text": "x"}]
    if captured:
        trace.append({"kind": "context", "reviewManifest": rf.review_manifest(
            header="MESSAGE: trimmed SBLK, stop to 31", system="SYS", model="claude-opus-5", max_tools=4, source="src")})
    trace += [{"kind": "tool_call", "tool": "get_positions", "args": {}},
              {"kind": "tool_result", "tool": "get_positions", "result": {"positions": [{"symbol": "SBLK", "qty": 62}]}}]
    used = [{"tool": "get_positions", "args": {}}]
    if mgmt:
        used.append({"tool": "update_exit_plan", "args": {"symbol": "SBLK", "stop": 31.0}})
    return {"id": "run-1", "source": "src", "model": "claude-opus-5", "created_at": None, "trace": trace,
            "opinion": {"toolsUsed": used, "missedTip": None, "watch": ["SBLK"], "model": "claude-opus-5"}}


def _tool(name, args, i):
    return NS(type="tool_use", name=name, input=args, id=f"t{i}")


class _Client:
    """Scripted provider: each entry is a list of content blocks."""
    def __init__(self, script):
        self.script, self.sent = list(script), []
        self.messages = NS(create=self._create)

    async def _create(self, **kw):
        self.sent.append({**kw, "messages": list(kw["messages"])})          # the list keeps growing - snapshot it
        return NS(content=self.script.pop(0), usage=NS(input_tokens=1000, output_tokens=100, cache_read_input_tokens=0,
                                                        cache_creation_input_tokens=0), stop_reason="end_turn")


def _final(missed=None):
    return [NS(type="text", text=json.dumps({"headline": "SBLK trimmed", "details": "", "watch": ["SBLK"],
                                              "missed_tip": missed, "confidence": 0.6}))]


def test_an_uncaptured_review_is_not_replayable_and_says_why():
    case = rf.build_case(_run(captured=False))
    assert case["replayable"] is False and "not captured" in case["gaps"][0]
    assert case["baseline"]["actions"] == ["update_exit_plan:SBLK"]


async def test_replay_serves_reads_from_the_case_and_never_executes_management():
    case = rf.build_case(_run())
    client = _Client([[_tool("get_positions", {}, 1)], [_tool("update_exit_plan", {"symbol": "SBLK", "stop": 31.2}, 2)], _final()])
    rep = await rf.replay_review(case, client=client, model="claude-sonnet-5", budget=ReplayBudget(5.0, RATE, model="claude-sonnet-5"))
    assert client.sent[0]["system"] == "SYS" and client.sent[0]["messages"][0]["content"] == case["manifest"]["header"]
    served = json.loads(client.sent[1]["messages"][-1]["content"][0]["content"])
    assert served == {"positions": [{"symbol": "SBLK", "qty": 62}]}                       # the recorded read, not today's book
    ack = json.loads(client.sent[2]["messages"][-1]["content"][0]["content"])
    assert ack["frozen"] is True                                                           # nothing was changed
    assert rep["actions"] == ["update_exit_plan:SBLK"] and rep["compare"]["agree"] is True
    assert rep["budget"]["spentUsd"] > 0 and rep["budget"]["attempts"] == 3


async def test_a_missed_management_action_is_reported_never_netted():
    case = rf.build_case(_run())
    rep = await rf.replay_review(case, client=_Client([_final(missed="GS 900C")]), model="claude-haiku-4-5",
                                 budget=ReplayBudget(5.0, RATE, model="claude-haiku-4-5"))
    c = rep["compare"]
    assert c["agree"] is False and c["missedActions"] == ["update_exit_plan:SBLK"] and c["extraActions"] == []
    assert c["missedEntryFlag"] == {"baseline": False, "candidate": True, "same": False}
    s = rf.summarize([rep])
    assert s["missedManagement"] == 1 and s["missedEntryFlagDiffers"] == 1 and s["agree"] == 0


async def test_the_budget_is_mandatory_and_refuses_before_the_call():
    case = rf.build_case(_run())
    with pytest.raises(ValueError):
        await rf.replay_review(case, client=_Client([]), model="m", budget=None)
    client = _Client([_final()])
    rep = await rf.replay_review(case, client=client, model="m", budget=ReplayBudget(0.0001, RATE, model="m"))
    assert client.sent == [] and rep["valid"] is False and "budget" in rep["error"]
    assert rep["compare"]["missedActions"] == ["update_exit_plan:SBLK"]                    # an invalid reply misses the action
