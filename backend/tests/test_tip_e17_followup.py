"""E17-F1/F2/F3 (Codex follow-up, 2026-09-17): the reserve is re-checked after every await and
before every tool/retry; a second schema-valid object is ambiguous, not "first wins"; tokens are
priced under the model that consumed them. Scripted clients and a fake clock only."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from zargar.domain import new_id
from zargar.signals.extraction import _parse_result_json
from zargar.techniques.tip import analyst
from zargar.techniques.tip.analyst import AnalystOpinion, ReviewOpinion, parse_single_object
from zargar.tools.tip_llm_cost import normalize_usage, rollup, usage_model

from .test_tip_analyst_loop import _Block, _Resp, _json_opinion, _mk_run
from .test_tip_analyst_loop import rig as rig  # noqa: PLC0414 - fixture re-export


def _tool(id_, name="save_note", **inp):
    return _Block(type="tool_use", id=id_, name=name, input=inp or {"scope": "general", "text": id_})


async def test_two_tools_in_one_reply_first_consumes_the_reserve_second_is_stubbed(rig, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(analyst, "_loop_now", lambda: clock["t"])
    seen = []

    async def slow_tool(eng, name, args, *, ctx):
        seen.append(name)
        clock["t"] += 30.0                         # the first tool eats into the reserve
        return {"saved": True}
    monkeypatch.setattr(analyst, "_run_tool", slow_tool)

    class Client:
        def __init__(self): self.messages = self; self.n = 0; self.kw = []
        async def create(self, **kw):
            self.kw.append(kw); self.n += 1
            if self.n == 1:
                clock["t"] = 80.0                  # 40 s left, reserve 20: optional work still allowed
                return _Resp([_tool("first"), _tool("second")])
            return _Resp([_Block(type="text", text=_json_opinion())])
    run_id = new_id(); await _mk_run(rig, run_id)
    state = analyst._arm_deadline({}, rig, timeout_s=120)
    client = Client()
    text = await analyst.run_agent_loop(rig, client, model="m", system="s", header="h", rec=analyst._Recorder(rig, run_id),
                                        run_id=run_id, max_tools=4, tool_ctx={"stage": "appraise"}, tools_used=[], state=state)
    assert seen == ["save_note"], "only the first tool ran; the second arrived inside the reserve"
    assert text and '"verdict"' in text and client.kw[-1].get("tool_choice") == {"type": "none"}


async def test_retry_backoff_that_reaches_the_reserve_switches_to_the_final_call(rig, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(analyst, "_loop_now", lambda: clock["t"])
    # the backoff seam, never asyncio.sleep globally (a global mock stalls wait_for / engine loops)
    async def _fake_backoff(d):
        clock["t"] += 25.0
    monkeypatch.setattr(analyst, "_backoff_sleep", _fake_backoff)

    class Overloaded(Exception):
        status_code = 529

    class Client:
        def __init__(self): self.messages = self; self.n = 0; self.kw = []
        async def create(self, **kw):
            self.kw.append(kw); self.n += 1
            if self.n == 1:
                clock["t"] = 90.0                  # 30 s left before the first failure
                raise Overloaded("overloaded")
            return _Resp([_Block(type="text", text=_json_opinion())])
    run_id = new_id(); await _mk_run(rig, run_id)
    state = analyst._arm_deadline({}, rig, timeout_s=120)
    client = Client()
    text = await analyst.run_agent_loop(rig, client, model="m", system="s", header="h", rec=analyst._Recorder(rig, run_id),
                                        run_id=run_id, max_tools=4, tool_ctx={"stage": "appraise"}, tools_used=[], state=state)
    assert text and '"verdict"' in text
    # after the backoff the optional budget was gone: the second request is the FINAL one, tools off
    assert client.kw[-1].get("tool_choice") == {"type": "none"} and state["forceFinal"] is True
    assert state["usage"]["calls"] == 1 and state["usage"]["retries"] == 0 and any(e.get("error") for e in state["usage"]["perCall"])


async def test_terminal_answer_control_still_completes_with_time_to_spare(rig, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(analyst, "_loop_now", lambda: clock["t"])
    spy = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(analyst, "_run_tool", spy)

    class Client:
        def __init__(self): self.messages = self; self.n = 0
        async def create(self, **kw):
            self.n += 1
            clock["t"] += 10.0
            if self.n == 1:
                return _Resp([_tool("t1", name="get_quote", symbol="TEST")])
            return _Resp([_Block(type="text", text=_json_opinion())])
    run_id = new_id(); await _mk_run(rig, run_id)
    state = analyst._arm_deadline({}, rig, timeout_s=120)
    text = await analyst.run_agent_loop(rig, Client(), model="m", system="s", header="h", rec=analyst._Recorder(rig, run_id),
                                        run_id=run_id, max_tools=4, tool_ctx={"stage": "appraise"}, tools_used=[], state=state)
    assert text and '"verdict"' in text and spy.await_count == 1 and state.get("forceFinal") is not True


def test_ambiguity_reversed_order_and_harmless_trailing_json_and_prose():
    valid = {"signals": [], "source_type": "other"}
    actionable = {"signals": [{"ticker": "AAPL", "direction": "long", "instrument": "shares", "entry_price": 100,
                               "thesis_summary": "fresh buy", "confidence": "explicit_call",
                               "evidence_quotes": ["BTO AAPL at 100"], "is_actionable": True}], "source_type": "trade_alert"}
    with pytest.raises(ValueError, match="ambiguity"):
        _parse_result_json(json.dumps(actionable) + "\nCorrection: nothing tradable after all\n" + json.dumps(valid))
    assert _parse_result_json(json.dumps(valid) + " thanks, that is all.").source_type == "other"
    assert len(_parse_result_json(json.dumps(actionable) + ' {"x": 1} and {"note": "unrelated"}').signals) == 1
    # the analyst / review parsers follow the same rule
    op = '{"verdict": "skip", "rationale": "a", "confidence": 0.5, "invalidation": "n/a"}'
    assert parse_single_object(op + " (final)", AnalystOpinion, what="analyst reply").verdict == "skip"
    with pytest.raises(ValueError, match="ambiguity"):
        parse_single_object(op + "\nactually:\n" + op.replace('"skip"', '"take"'), AnalystOpinion, what="analyst reply")
    rv = '{"headline": "h", "details": "", "watch": [], "missed_tip": null, "confidence": 0.4}'
    assert parse_single_object("```json\n" + rv + "\n```", ReviewOpinion, what="review reply").headline == "h"
    with pytest.raises(ValueError, match="ambiguity"):
        parse_single_object(rv + "\n" + rv.replace('"h"', '"other"'), ReviewOpinion, what="review reply")


def test_cost_attribution_separates_extraction_identity_and_handles_legacy_usage():
    # a review run recorded under an intake record: tokens belong to the REVIEW model
    used, extraction = usage_model({"model": "extractor", "usage": {"model": "reviewer", "in": 10, "out": 1, "calls": 1}})
    assert (used, extraction) == ("reviewer", "extractor")
    # no usage model on an intake record -> unpriced, never the extractor's card
    assert usage_model({"model": "extractor", "usage": {"in": 5, "out": 1, "calls": 1}}) == (None, "extractor")
    # legacy list-shaped usage is summed and flagged, not assumed to be a dict
    legacy = normalize_usage([{"inputTokens": 100, "outputTokens": 10}, {"inputTokens": None, "outputTokens": None}])
    assert legacy["legacy"] is True and legacy["calls"] == 2 and legacy["in"] == 100 and legacy["unknownCalls"] == 1 and legacy["partial"] is True
    assert normalize_usage("garbage") == {} and normalize_usage(None) == {}
    rates = {"extractor": {"in": 1.0, "out": 5.0, "cacheRead": 0.1, "cacheWrite": 1.25},
             "reviewer": {"in": 15.0, "out": 75.0, "cacheRead": 1.5, "cacheWrite": 18.75}}
    runs = [{"id": "r", "kind": "intake", "status": "done", "day": "2026-09-17", "model": "reviewer", "extractionModel": "extractor",
             "usage": {"calls": 1, "in": 1_000_000, "out": 0}},
            {"id": "x", "kind": "intake", "status": "done", "day": "2026-09-17", "model": None, "extractionModel": "extractor",
             "usage": {"calls": 1, "in": 1_000_000, "out": 0}}]
    rep = rollup(runs, rates)
    by = {g["model"]: g for g in rep["groups"]}
    assert by["reviewer"]["usd"] == 15.0 and by["reviewer"]["priced"] is True
    assert by["unknown-model"]["priced"] is False, "an intake record without a usage model is never priced at the extractor's rate"
