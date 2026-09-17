"""E17-03 (2026-09-17): model identity on intake records, knob-gated prompt caching of the stable
prefix, and an operating-cost rollup that never infers a dollar bill without a rate. Scripted only."""
from zargar.domain import new_id
from zargar.models import TipAnalystRun
from zargar.techniques.tip.analyst import IntakeRun, _Recorder, cacheable_request, run_agent_loop
from zargar.tools.tip_llm_cost import price, rollup

from .test_tip_analyst_loop import _Block, _Resp, _Scripted, _json_opinion, _mk_run
from .test_tip_analyst_loop import rig as rig  # noqa: PLC0414 - fixture re-export


def test_cacheable_request_marks_the_stable_prefix_only_when_enabled():
    tools = [{"name": "a", "input_schema": {}}, {"name": "b", "input_schema": {}}]
    sys_p, tools_p = cacheable_request("SYSTEM", tools, enabled=False)
    assert sys_p == "SYSTEM" and tools_p is tools and "cache_control" not in tools[-1]
    sys_c, tools_c = cacheable_request("SYSTEM", tools, enabled=True)
    assert sys_c == [{"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}]
    assert tools_c[-1]["cache_control"] == {"type": "ephemeral"} and "cache_control" not in tools_c[0]
    assert "cache_control" not in tools[-1], "the caller's tool list is never mutated"


async def test_prompt_cache_knob_shapes_the_request_and_is_recorded_on_usage(rig):
    eng = rig
    run_id = new_id()
    await _mk_run(eng, run_id)
    # OFF (default): plain system string
    client = _Scripted([_Resp([_Block(type="text", text=_json_opinion())])])
    state: dict = {}
    await run_agent_loop(eng, client, model="m", system="SYS", header="h", rec=_Recorder(eng, run_id), run_id=run_id,
                         max_tools=4, tool_ctx={"stage": "appraise"}, tools_used=[], state=state)
    assert state["usage"]["promptCache"] is False and state["usage"]["model"] == "m"
    # ON: system as a cache-marked block, last tool marked - the dynamic header stays a plain user message
    await eng.settings.set("techniques.tip.prompt_cache", True, journal=False)
    client2 = _CapturingScripted([_Resp([_Block(type="text", text=_json_opinion())])])
    state2: dict = {}
    await run_agent_loop(eng, client2, model="m", system="SYS", header="h", rec=_Recorder(eng, run_id), run_id=run_id,
                         max_tools=4, tool_ctx={"stage": "appraise"}, tools_used=[], state=state2)
    kw = client2.kwargs[-1]
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"} and kw["tools"][-1].get("cache_control")
    assert kw["messages"][0] == {"role": "user", "content": "h"}
    assert state2["usage"]["promptCache"] is True
    await eng.settings.set("techniques.tip.prompt_cache", False, journal=False)


class _CapturingScripted(_Scripted):
    def __init__(self, responses):
        super().__init__(responses)
        self.kwargs: list[dict] = []

    async def create(self, **kw):
        self.kwargs.append(kw)
        return await super().create(**kw)


async def test_intake_finish_carries_the_extraction_model_identity(rig):
    intake = IntakeRun(rig)
    await intake.start(source="OfflineAudit", chars=5, has_image=False)
    intake.model = "claude-test-model"
    await intake.finish("no signals", "Done — no trade signals in this message.")
    async with rig.sf() as session:
        saved = await session.get(TipAnalystRun, intake.id)
    assert saved.status == "done" and saved.opinion.get("model") == "claude-test-model"


def test_cost_rollup_prices_only_known_models_and_labels_lower_bounds():
    runs = [
        {"id": "a", "kind": "appraise", "status": "done", "day": "2026-09-17", "model": "m1",
         "usage": {"calls": 2, "in": 1_000_000, "out": 100_000, "cacheRead": 0, "cacheWrite": 0, "unknownCalls": 0, "partial": False}},
        {"id": "b", "kind": "appraise", "status": "failed", "day": "2026-09-17", "model": "m1",
         "usage": {"calls": 1, "in": 500_000, "out": 0, "unknownCalls": 1, "partial": True}},
        {"id": "c", "kind": "intake", "status": "done", "day": "2026-09-17", "model": None, "usage": {}},
        {"id": "d", "kind": "intake", "status": "done", "day": "2026-09-17", "model": "m2",
         "usage": {"calls": 1, "in": 200_000, "out": 10_000, "cacheRead": 50_000, "cacheWrite": 0}},
    ]
    rates = {"m1": {"in": 10.0, "out": 50.0, "cacheRead": 1.0, "cacheWrite": 12.5}}
    rep = rollup(runs, rates)
    by = {(g["kind"], g["model"]): g for g in rep["groups"]}
    a = by[("appraise", "m1")]
    assert a["runs"] == 2 and a["calls"] == 3 and a["in"] == 1_500_000 and a["failed"] == 1
    assert a["priced"] is True and a["usd"] == round(1.5 * 10.0 + 0.1 * 50.0, 4) and a["lowerBound"] is True   # one cut call
    assert by[("intake", "unknown-model")]["priced"] is False and by[("intake", "unknown-model")]["runsWithoutUsage"] == 1
    assert by[("intake", "m2")]["priced"] is False and "unpriced" in by[("intake", "m2")]["note"]
    assert rep["unpricedGroups"] == 2 and rep["lowerBound"] is True and rep["totalPricedUsd"] == a["usd"]
    assert price({"in": 1_000_000}, {"in": 3.0, "out": 15.0}) == {"usd": 3.0, "priced": True}
    assert price({"in": 1, "cacheRead": 5}, {"in": 3.0, "out": 15.0})["priced"] is False   # rate card lacks cacheRead
    assert price({"in": 1}, None)["priced"] is False
