"""EM optional LLM entry evidence over FROZEN deterministic decisions (Delivery B, 2026-09-15). Evidence only.

The evidence worker consumes a serialized immutable decision snapshot (the journaled `TechniqueEntryDecision` payload
plus the plan's saved trigger), never live `ArmedPlan` / `Trade` / `TriggerTracker` objects and never bars after the
signal bar's close. Its analysis object is an ISOLATED copy built from the frozen trigger; the critic may mutate that
copy freely - nothing here can reach an order, an arm, a setup row, a stop, a cooldown or a settings write (this
module imports none of them, and the command that runs it opens no trading service). Output = a `TechniqueEntryEvidence`
record keyed by (decisionId, inputHash, policyVersion, promptHash, model): `authority = evidence_only`.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass

EVIDENCE_VERSION = "entry-evidence-v1"
AUTHORITY = "evidence_only"
OUTCOMES = ("completed", "unavailable", "timed_out", "budget_skipped", "invalid", "failed")


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def frozen_input(decision_payload: dict, trigger: dict) -> dict:
    """The immutable evidence input: the decision record (minus anything that arrived after it) plus the SAVED plan
    trigger (geometry, level provenance). Later price path, fills and outcomes are excluded by construction."""
    keep = ("runId", "symbol", "trigger", "kind", "direction", "window", "decisionId", "fireAttemptId", "decisionMode", "decisionVersion",
            "ruleVersion", "thresholdsHash", "planId", "planVersion", "triggerId", "triggerFamily", "confirmationVariant", "signalBarStart",
            "signalBarClose", "sourceTime", "receivedTime", "verdict", "reasonCodes", "inputHash", "checks", "notEncoded")
    d = {k: decision_payload.get(k) for k in keep if k in decision_payload}
    d["trigger"] = decision_payload.get("trigger") or decision_payload.get("triggerId")
    t = trigger or {}
    d["plannedTrigger"] = {"id": t.get("id"), "kind": t.get("kind"), "direction": t.get("direction"), "entry": t.get("entry"), "stop": t.get("stop"),
                           "targets": t.get("targets"), "levelPrice": t.get("levelPrice"), "level": t.get("level"), "setupType": t.get("setupType"),
                           "assessment": t.get("assessment"), "conditions": t.get("conditions"), "confidence": t.get("confidence")}
    d["frozenAt"] = d.get("signalBarClose")
    d["evidenceInputHash"] = hashlib.sha256(_canonical({k: v for k, v in d.items() if k != "evidenceInputHash"}).encode("utf-8")).hexdigest()
    return d


def isolated_analysis(frozen: dict):
    """An independent `TechniqueAnalysis` built from the FROZEN trigger (never the execution-owned object)."""
    from .plans import analysis_from_trigger
    t = dict(frozen.get("plannedTrigger") or {})
    if not t.get("levelPrice") and isinstance(t.get("level"), dict):
        t["levelPrice"] = t["level"].get("price")
    t.setdefault("entry", {"price": t.get("levelPrice"), "basis": "at_level"})
    t.setdefault("stop", {"price": t.get("levelPrice")})
    t.setdefault("targets", [])
    t.setdefault("id", frozen.get("trigger"))
    return analysis_from_trigger(t, str(frozen.get("symbol") or "?"), session_window=str(frozen.get("window") or "unknown"))


def evidence_key(frozen: dict, *, prompt_hash: str, model: str) -> str:
    return hashlib.sha256(f"{frozen.get('decisionId')}:{frozen.get('inputHash')}:{frozen.get('decisionVersion')}:{prompt_hash}:{model}".encode("utf-8")).hexdigest()[:32]


@dataclass
class EvidenceResult:
    review_outcome: str
    model_opinion: str | None = None            # setup | no_setup | None
    model_confidence: float | None = None
    critic: dict | None = None
    error: str | None = None
    elapsed_ms: int = 0
    usage: dict | None = None

    def to_record(self, frozen: dict, *, prompt_hash: str, model: str, enqueued_at: int, started_at: int, completed_at: int) -> dict:
        disagreement = None
        if self.review_outcome == "completed" and self.model_opinion is not None:
            app = frozen.get("verdict")
            model_allows = self.model_opinion == "setup"
            disagreement = ("agree" if (app == "allow") == model_allows else ("model_would_refuse" if app == "allow" else "model_would_allow"))
        return {"runId": frozen.get("runId"), "symbol": frozen.get("symbol"), "trigger": frozen.get("trigger"), "decisionId": frozen.get("decisionId"),
                "inputHash": frozen.get("inputHash"), "evidenceInputHash": frozen.get("evidenceInputHash"), "policyVersion": frozen.get("decisionVersion"),
                "evidenceVersion": EVIDENCE_VERSION, "evidenceKey": evidence_key(frozen, prompt_hash=prompt_hash, model=model),
                "model": model, "promptHash": prompt_hash, "asOf": frozen.get("frozenAt"), "enqueuedAt": enqueued_at, "startedAt": started_at,
                "completedAt": completed_at, "reviewOutcome": self.review_outcome, "modelOpinion": self.model_opinion,
                "modelConfidence": self.model_confidence, "citedEvidence": (self.critic or {}).get("violations"), "summary": (self.critic or {}).get("summary"),
                "usage": self.usage, "error": self.error, "elapsedMs": self.elapsed_ms, "disagreement": disagreement,
                "appVerdict": frozen.get("verdict"), "appReasonCodes": frozen.get("reasonCodes"), "authority": AUTHORITY}


async def run_evidence(frozen: dict, *, client, llm, thresholds, images: dict | None, facts_txt: str, timeout_s: float) -> EvidenceResult:
    """One bounded critic evaluation over the isolated analysis copy. The prompt is the existing critic prompt; the
    context text must be built by the caller from bars at or before the frozen signal bar close only."""
    import asyncio
    from .vision import VisionPipeline
    t0 = time.perf_counter()
    if client is None or llm is None or not getattr(llm, "available", True):
        return EvidenceResult("unavailable", error="no model client / key")
    a = isolated_analysis(frozen)
    vp = VisionPipeline(client, llm, thresholds=thresholds, max_passes=1, trace=[])
    try:
        critic = await asyncio.wait_for(vp.run_critic(a, images or {}, facts_txt), timeout_s)
    except asyncio.TimeoutError:
        return EvidenceResult("timed_out", error=f"no answer within {timeout_s:g}s", elapsed_ms=int((time.perf_counter() - t0) * 1000))
    except Exception as exc:  # noqa: BLE001 - an evidence failure is an evidence outcome
        return EvidenceResult("failed", error=f"{type(exc).__name__}: {exc}", elapsed_ms=int((time.perf_counter() - t0) * 1000))
    if critic is None:
        return EvidenceResult("invalid", error="critic returned no structured verdict", elapsed_ms=int((time.perf_counter() - t0) * 1000))
    return EvidenceResult("completed", model_opinion=("no_setup" if critic.get("kill") else "setup"),
                          model_confidence=float(getattr(a, "confidence", 0.0) or 0.0),
                          critic={k: critic.get(k) for k in ("kill", "summary", "violations")}, elapsed_ms=int((time.perf_counter() - t0) * 1000),
                          usage=critic.get("usage") if isinstance(critic.get("usage"), dict) else None)
