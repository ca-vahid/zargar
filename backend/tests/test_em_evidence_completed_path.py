"""Full decision capture -> after-close rendering -> fake critic transport, no DB/network.

The success case requires a completed review, not merely an unavailable outcome.
The integrity case modifies stored material without its hash and must spend no call.
"""
import asyncio
import copy
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("corrupt_bars", [False, True], ids=["completed-path", "hash-mismatch"])
def test_real_fire_snapshot_reaches_evidence_only_when_content_matches(monkeypatch, corrupt_bars):
    from tests.test_em_deterministic_entry_integration import DAY, rig, run_fire
    from zargar.domain import Bar
    from zargar.technique.vision import PassRecord, VisionPipeline
    import zargar.technique.llm as llm_module
    import zargar.tools.em_entry_evidence as cli

    runner, arm, tracker, signal, technique = rig({
        "techniques.enhanced_market.fire_decision_mode": "deterministic",
    })
    live_bars = [Bar(symbol="X", tf="1m", ts=DAY + i * 60_000,
                     open=101.0, high=101.3, low=100.7, close=101.0, volume=1000)
                 for i in range(24)] + [signal]
    runner.engine.bars.bars = lambda *args, **kwargs: live_bars
    run_fire(runner, arm, tracker, signal)
    record = next(c.args[1] for c in runner.engine.journal.append.await_args_list
                  if c.args[0] == "TechniqueEntryDecision")
    record = copy.deepcopy(record)
    assert record["snapshot"] and record["frozenBars"] and record["frozenBarsHash"]
    # Destroy current objects after capture: the CLI must not read them.
    tracker.trigger["entry"]["price"] = 999.0
    live_bars.clear()
    if corrupt_bars:
        record["frozenBars"][-1]["close"] += 50.0
    record["_have"] = set()
    appended, model_requests = [], []

    async def dispose():
        pass

    async def append(kind, payload, **kwargs):
        appended.append(payload)

    async def open_fake():
        return (SimpleNamespace(anthropic_api_key="fake-no-network"),
                SimpleNamespace(dispose=dispose), None,
                {"techniques.enhanced_market.fire_evidence_mode": "after_close"},
                SimpleNamespace(append=append))

    async def decisions(*args):
        return [record]

    async def forbid_current_lookup(*args, **kwargs):
        raise AssertionError("evidence must not query current plan or bars")

    async def fake_model_transport(self, name, user_blocks, output_format, **kwargs):
        model_requests.append(user_blocks)
        return PassRecord(name="critic", request_blocks=user_blocks, response_blocks=[],
                          parsed={"kill": False, "fakeout_risk": "low", "violations": [],
                                  "adjustments": [], "confidence_adjustment": 0.0, "summary": "frozen review"},
                          usage={"input": 11, "output": 7, "cacheRead": 0, "cacheWrite": 0}, seconds=0.01)

    monkeypatch.setattr(cli, "_open", open_fake)
    monkeypatch.setattr(cli, "_decisions", decisions)
    monkeypatch.setattr(cli, "_trigger_for", forbid_current_lookup)
    monkeypatch.setattr(llm_module, "make_client", lambda cfg: object())
    monkeypatch.setattr(VisionPipeline, "_call", fake_model_transport)
    report = asyncio.run(cli.run("2026-09-14", max_calls=1, timeout_s=1,
                                dry_run=False, force=False))
    assert report["evaluated"] == 1 and len(appended) == 1
    output = appended[0]
    if corrupt_bars:
        assert not model_requests, "A mismatched frozen-bars hash must refuse before buying an opinion"
        assert output["reviewOutcome"] == "invalid"
    else:
        assert len(model_requests) == 1
        assert any(b.get("type") == "image" for b in model_requests[0]), "Actual frozen-chart render must succeed"
        assert output["reviewOutcome"] == "completed" and output["authority"] == "evidence_only"
        assert output["usage"] == {"input": 11, "output": 7, "cacheRead": 0, "cacheWrite": 0}
        assert output["frozenSource"] == "decision_snapshot"
        assert output["frozenBarsHash"] == record["frozenBarsHash"]
        assert output["modelStartedAt"] >= output["startedAt"]
