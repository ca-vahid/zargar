"""Delivery B (2026-09-15): optional LLM entry evidence over FROZEN decisions is evidence only. Frozen input is
hash-stable and excludes outcomes; a hanging, failing, absent or budget-skipped model is an evidence outcome; the
evidence modules carry no order/arm/settings-write capability. No DB, no paid calls."""
import asyncio
import inspect
from types import SimpleNamespace

import zargar.technique.entry_evidence as ee
import zargar.tools.em_entry_evidence as cli
from zargar.technique.entry_evidence import AUTHORITY, EvidenceResult, evidence_key, frozen_input, isolated_analysis, run_evidence

DECISION = {"runId": "run", "symbol": "X", "trigger": "b1", "kind": "bounce", "direction": "long", "window": "prime_open", "decisionId": "d1",
            "fireAttemptId": "a1", "decisionMode": "deterministic", "decisionVersion": "deterministic-entry-v1", "verdict": "allow",
            "reasonCodes": [], "inputHash": "h1", "checks": [], "signalBarStart": 1_789_479_300_000, "signalBarClose": 1_789_479_360_000,
            "orderId": "should-not-leak", "avgFill": 1.23, "realizedPnl": 99.0}
TRIGGER = {"id": "b1", "kind": "bounce", "direction": "long", "entry": {"price": 100.0, "basis": "at_level"}, "stop": {"price": 99.0},
           "targets": [{"price": 101.0, "basis": "next_resistance"}], "levelPrice": 100.0, "level": {"price": 100.0, "touches": 3, "sources": ["T1.2"]},
           "setupType": "support_bounce", "confidence": 0.6}


def test_frozen_input_is_hash_stable_and_excludes_fills_and_outcomes():
    a = frozen_input(DECISION, TRIGGER); b = frozen_input(dict(DECISION), dict(TRIGGER))
    assert a == b and a["evidenceInputHash"] == b["evidenceInputHash"] and a["frozenAt"] == DECISION["signalBarClose"]
    assert "orderId" not in a and "avgFill" not in a and "realizedPnl" not in a
    assert frozen_input({**DECISION, "verdict": "refuse"}, TRIGGER)["evidenceInputHash"] != a["evidenceInputHash"]
    assert evidence_key(a, prompt_hash="p1", model="m") != evidence_key(a, prompt_hash="p2", model="m")


def test_isolated_analysis_is_a_fresh_object_built_from_the_frozen_trigger():
    fi = frozen_input(DECISION, TRIGGER)
    a1, a2 = isolated_analysis(fi), isolated_analysis(fi)
    assert a1 is not a2 and a1.verdict == "setup" and a1.symbol == "X"
    a1.verdict = "no_setup"
    assert a2.verdict == "setup" and DECISION["verdict"] == "allow"          # mutating the copy touches nothing else


class _HangingStream:
    async def __aenter__(self):
        await asyncio.Event().wait()                 # never yields a first event

    async def __aexit__(self, *a):
        return False


class Hanging:
    """Mimics the real client's `messages.stream(**params)` context manager and never answers."""
    def __init__(self):
        self.messages = SimpleNamespace(stream=lambda **kw: _HangingStream())


def test_hanging_failing_absent_and_skipped_models_are_evidence_outcomes_only():
    fi = frozen_input(DECISION, TRIGGER)
    from zargar.technique.llm import LLMConfig
    from zargar.technique.rulebook import Thresholds
    llm = LLMConfig(api_key="test-key", model="test-model")
    r = asyncio.run(run_evidence(fi, client=Hanging(), llm=llm, thresholds=Thresholds(), images={}, facts_txt="", timeout_s=0.05))
    assert r.review_outcome == "timed_out" and r.model_opinion is None

    class Boom:
        def __init__(self):
            def _raise(**kw):
                raise RuntimeError("provider down")
            self.messages = SimpleNamespace(stream=_raise)
    r2 = asyncio.run(run_evidence(fi, client=Boom(), llm=llm, thresholds=Thresholds(), images={}, facts_txt="", timeout_s=1.0))
    assert r2.review_outcome == "failed" and "provider down" in r2.error
    r3 = asyncio.run(run_evidence(fi, client=None, llm=SimpleNamespace(available=False), thresholds=Thresholds(), images={}, facts_txt="", timeout_s=1.0))
    assert r3.review_outcome == "unavailable"
    rec = EvidenceResult("budget_skipped", error="budget").to_record(fi, prompt_hash="p", model="m", enqueued_at=1, started_at=1, completed_at=2)
    assert rec["authority"] == AUTHORITY and rec["reviewOutcome"] == "budget_skipped" and rec["decisionId"] == "d1" and rec["disagreement"] is None
    done = EvidenceResult("completed", model_opinion="no_setup", model_confidence=0.1, critic={"kill": True, "summary": "s", "violations": ["R3.2"]})
    rec2 = done.to_record(fi, prompt_hash="p", model="m", enqueued_at=1, started_at=1, completed_at=2)
    assert rec2["disagreement"] == "model_would_refuse" and rec2["appVerdict"] == "allow" and rec2["citedEvidence"] == ["R3.2"]


def test_evidence_modules_import_no_trading_capability():
    for mod in (ee, cli):
        src = inspect.getsource(mod)
        for forbidden in ("orders.place", "OrderManager", "arm(", ".pause(", "settings.set", "set_many", "engage_halt", "disarm", "PlanArmer", "Engine("):
            assert forbidden not in src, f"{mod.__name__} must not carry {forbidden!r}"
