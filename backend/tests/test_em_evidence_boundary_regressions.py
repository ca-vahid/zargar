"""Delivery B boundary reproductions at 758ccfb. No DB, paid calls or trading services.

The normal CLI body is exercised with read/journal boundaries replaced by in-memory
fakes. Run sequentially with the reviewer's other tests in the isolated checkout.
"""
import asyncio
import copy
from types import SimpleNamespace

from zargar.technique.entry_evidence import (
    EvidenceResult, evidence_key, frozen_input, run_evidence,
)


DECISION = {
    "runId": "run", "symbol": "X", "trigger": "b1", "kind": "bounce",
    "direction": "long", "window": "prime_open", "decisionId": "d1",
    "fireAttemptId": "a1", "decisionMode": "deterministic",
    "decisionVersion": "deterministic-entry-v1", "verdict": "allow",
    "reasonCodes": [], "inputHash": "h1", "checks": [],
    "signalBarStart": 1_789_479_300_000, "signalBarClose": 1_789_479_360_000,
}
TRIGGER = {
    "id": "b1", "kind": "bounce", "direction": "long",
    "entry": {"price": 100.0, "basis": "at_level"}, "stop": {"price": 99.0},
    "targets": [{"price": 101.0, "basis": "next_resistance"}],
    "levelPrice": 100.0, "level": {"price": 100.0, "touches": 3, "sources": ["T1.2"]},
    "setupType": "support_bounce", "confidence": 0.6,
}


def test_frozen_evidence_is_detached_from_mutable_plan_and_decision():
    decision, trigger = copy.deepcopy(DECISION), copy.deepcopy(TRIGGER)
    frozen = frozen_input(decision, trigger)
    expected = copy.deepcopy(frozen)
    trigger["entry"]["price"] = 120.0
    trigger["targets"][0]["price"] = 140.0
    decision["checks"].append({"name": "later_state"})
    assert frozen == expected, "An evidence payload changed without its saved hash changing"


def test_evidence_identity_changes_when_the_review_input_changes():
    first = frozen_input(copy.deepcopy(DECISION), copy.deepcopy(TRIGGER))
    changed = copy.deepcopy(TRIGGER)
    changed["targets"][0]["price"] = 110.0
    second = frozen_input(copy.deepcopy(DECISION), changed)
    assert first["evidenceInputHash"] != second["evidenceInputHash"]
    assert evidence_key(first, prompt_hash="prompt", model="model") != evidence_key(
        second, prompt_hash="prompt", model="model"
    ), "Different actual evidence inputs must not share the completion/deduplication key"


def test_after_close_cli_processes_a_real_eligible_row_without_import_abort(monkeypatch):
    import zargar.tools.em_entry_evidence as cli
    import zargar.technique.entry_evidence as evidence
    import zargar.technique.llm as llm_module

    rows = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def scalars(self, query):
            return SimpleNamespace(all=lambda: [])

    async def dispose():
        pass

    async def append(kind, payload, **kwargs):
        rows.append((kind, payload))

    async def open_fake():
        return (
            SimpleNamespace(anthropic_api_key="fake-no-network"),
            SimpleNamespace(dispose=dispose), Session,
            {"techniques.enhanced_market.fire_evidence_mode": "after_close"},
            SimpleNamespace(append=append),
        )

    async def decisions(*args):
        return [{**copy.deepcopy(DECISION), "_have": set()}]

    async def trigger(*args):
        return copy.deepcopy(TRIGGER)

    async def no_paid_call(*args, **kwargs):
        return EvidenceResult("unavailable", error="fake model boundary")

    monkeypatch.setattr(cli, "_open", open_fake)
    monkeypatch.setattr(cli, "_decisions", decisions)
    monkeypatch.setattr(cli, "_trigger_for", trigger)
    monkeypatch.setattr(llm_module, "make_client", lambda cfg: object())
    monkeypatch.setattr(evidence, "run_evidence", no_paid_call)
    result = asyncio.run(cli.run("2026-09-14", max_calls=1, timeout_s=1, dry_run=False, force=False))
    assert result["evaluated"] == 1
    assert len(rows) == 1 and rows[0][1]["authority"] == "evidence_only"


def test_successful_real_critic_return_preserves_usage(monkeypatch):
    from zargar.technique.llm import LLMConfig
    from zargar.technique.rulebook import Thresholds
    from zargar.technique.vision import VisionPipeline

    usage = {"input": 111, "output": 17, "cacheRead": 3, "cacheWrite": 0}

    async def critic(self, analysis, images, facts_txt):
        # VisionPipeline.run_critic returns usage inside its actual PassRecord shape.
        return {"kill": False, "summary": "ok", "violations": [],
                "passRecord": {"name": "critic", "usage": usage, "seconds": 0.1}}

    monkeypatch.setattr(VisionPipeline, "run_critic", critic)
    result = asyncio.run(run_evidence(
        frozen_input(copy.deepcopy(DECISION), copy.deepcopy(TRIGGER)),
        client=object(), llm=LLMConfig(api_key="fake-no-network"),
        thresholds=Thresholds(), images={}, facts_txt="frozen", timeout_s=1,
    ))
    assert result.review_outcome == "completed"
    assert result.usage == usage


def test_missing_required_snapshot_becomes_invalid_evidence_not_batch_abort():
    from zargar.technique.llm import LLMConfig
    from zargar.technique.rulebook import Thresholds

    result = asyncio.run(run_evidence(
        frozen_input(copy.deepcopy(DECISION), {}), client=object(),
        llm=LLMConfig(api_key="fake-no-network"), thresholds=Thresholds(),
        images={}, facts_txt="", timeout_s=1,
    ))
    assert result.review_outcome == "invalid"
    assert result.model_opinion is None
