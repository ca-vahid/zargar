"""EM optional LLM entry evidence over FROZEN deterministic decisions (Delivery B, 2026-09-15; DE-04/DE-05). Evidence only.

The evidence worker consumes the serialized immutable decision record (the journaled `TechniqueEntryDecision` payload,
which carries the decision's own `snapshot`, `policy` and `frozenBars` captured at decision time), never live
`ArmedPlan` / `Trade` / `TriggerTracker` objects and never later bars, fills or outcomes. Its analysis object is an
ISOLATED copy built from the frozen trigger geometry; the critic may mutate that copy freely - nothing here can reach
an order, an arm, a setup row, a stop, a cooldown or a settings write. Output = a `TechniqueEntryEvidence` record keyed
by (decisionId, inputHash, evidenceInputHash, policyVersion, promptHash, model): `authority = evidence_only`.

Provenance rules: a decision without a frozen snapshot is `unavailable` (never rebuilt from mutable current rows); a
frozen input that fails validation is `invalid`; both keep the batch going. `frozenSource` labels the input as
`decision_snapshot` or `retrospective:<what>` when the caller deliberately supplies a later reconstruction.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import time
from dataclasses import dataclass

EVIDENCE_VERSION = "entry-evidence-v1"
AUTHORITY = "evidence_only"
OUTCOMES = ("completed", "unavailable", "timed_out", "budget_skipped", "invalid", "failed")


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def frozen_input(decision_payload: dict, trigger: dict | None = None) -> dict:
    """The immutable evidence input, DEEP-COPIED and hashed once. Prefers the decision's own frozen `snapshot` (saved
    geometry, the tracker transition, the policy actually used); the `trigger` argument is only used when the
    decision carries no snapshot and is then labelled retrospective. Later price path, fills and outcomes are excluded
    by construction (only the whitelisted decision fields are kept)."""
    src = copy.deepcopy(decision_payload or {})
    keep = ("runId", "symbol", "trigger", "kind", "direction", "window", "decisionId", "fireAttemptId", "decisionMode", "decisionVersion",
            "ruleVersion", "thresholdsHash", "planId", "planVersion", "triggerId", "triggerFamily", "confirmationVariant", "signalBarStart",
            "signalBarClose", "sourceTime", "receivedTime", "verdict", "reasonCodes", "inputHash", "checks", "notEncoded", "policy",
            "frozenBarsHash", "frozenBarsCount")
    d = {k: src.get(k) for k in keep if k in src}
    d["trigger"] = src.get("trigger") or src.get("triggerId")
    snap = src.get("snapshot") if isinstance(src.get("snapshot"), dict) else None
    if snap:
        d["snapshot"] = snap
        d["plannedTrigger"] = {"id": snap.get("trigger_id"), "kind": snap.get("family"), "direction": snap.get("direction"),
                               "entry": {"price": snap.get("entry"), "basis": "saved"}, "stop": {"price": snap.get("stop")},
                               "targets": [{"price": p} for p in (snap.get("targets") or [])], "levelPrice": snap.get("entry"),
                               "level": (snap.get("level_provenance") or {}), "observedEntry": snap.get("observed_entry"),
                               "firedEvent": snap.get("fired_event"), "confirmationVariant": src.get("confirmationVariant")}
        d["frozenSource"] = "decision_snapshot"
    else:
        t = copy.deepcopy(trigger or {})
        d["plannedTrigger"] = {"id": t.get("id"), "kind": t.get("kind"), "direction": t.get("direction"), "entry": t.get("entry"), "stop": t.get("stop"),
                               "targets": t.get("targets"), "levelPrice": t.get("levelPrice"), "level": t.get("level"), "setupType": t.get("setupType"),
                               "assessment": t.get("assessment"), "conditions": t.get("conditions"), "confidence": t.get("confidence")}
        d["frozenSource"] = "retrospective:supplied_trigger" if t else "missing"
    d["frozenAt"] = d.get("signalBarClose")
    d["evidenceInputHash"] = hashlib.sha256(_canonical({k: v for k, v in d.items() if k != "evidenceInputHash"}).encode("utf-8")).hexdigest()
    return copy.deepcopy(d)


def validate_frozen(frozen: dict) -> str | None:
    """The reason a frozen input cannot be reviewed (None = usable). Never fabricates a setup from missing data."""
    t = (frozen or {}).get("plannedTrigger") or {}
    if not t or not t.get("kind"):
        return "no frozen trigger snapshot"
    lp = t.get("levelPrice") if t.get("levelPrice") is not None else (t.get("level") or {}).get("price")
    entry = (t.get("entry") or {}).get("price") if isinstance(t.get("entry"), dict) else None
    stop = (t.get("stop") or {}).get("price") if isinstance(t.get("stop"), dict) else None
    if lp is None and entry is None:
        return "no level/entry price in the frozen trigger"
    if stop is None:
        return "no stop in the frozen trigger"
    if not frozen.get("decisionId") or not frozen.get("inputHash"):
        return "decision identity missing"
    return None


def isolated_analysis(frozen: dict):
    """An independent `TechniqueAnalysis` built from the FROZEN trigger (never the execution-owned object).
    Raises on an unusable input - `run_evidence` turns that into an `invalid` outcome."""
    from .plans import analysis_from_trigger
    t = copy.deepcopy(frozen.get("plannedTrigger") or {})
    if not t.get("levelPrice") and isinstance(t.get("level"), dict):
        t["levelPrice"] = t["level"].get("price")
    if not t.get("levelPrice") and isinstance(t.get("entry"), dict):
        t["levelPrice"] = t["entry"].get("price")
    if not t.get("levelPrice"):
        raise ValueError("no level price in the frozen trigger")
    t.setdefault("entry", {"price": t.get("levelPrice"), "basis": "at_level"})
    t.setdefault("stop", {"price": t.get("levelPrice")})
    t.setdefault("targets", [])
    t.setdefault("id", frozen.get("trigger"))
    return analysis_from_trigger(t, str(frozen.get("symbol") or "?"), session_window=str(frozen.get("window") or "unknown"))


def prompt_identity(llm=None) -> str:
    """Hash of the ACTUAL critic prompt/config: the system prompt, the critic pass source (its instruction text), the
    verdict schema and the model/effort in use - not a version label."""
    try:
        from .schemas import SYSTEM_PROMPT, CriticVerdict
        from .vision import VisionPipeline
        body = inspect.getsource(VisionPipeline.run_critic)
        schema = _canonical(CriticVerdict.model_json_schema())
    except Exception:  # pragma: no cover - defensive
        body, schema = "", ""
        SYSTEM_PROMPT = ""
    cfg = f"{getattr(llm, 'model', '')}:{getattr(llm, 'effort', '')}"
    return hashlib.sha256(f"{EVIDENCE_VERSION}\n{SYSTEM_PROMPT}\n{body}\n{schema}\n{cfg}".encode("utf-8")).hexdigest()[:16]


def evidence_key(frozen: dict, *, prompt_hash: str, model: str) -> str:
    return hashlib.sha256(f"{frozen.get('decisionId')}:{frozen.get('inputHash')}:{frozen.get('evidenceInputHash')}:{frozen.get('decisionVersion')}:{prompt_hash}:{model}".encode("utf-8")).hexdigest()[:32]


@dataclass
class EvidenceResult:
    review_outcome: str
    model_opinion: str | None = None            # setup | no_setup | None
    model_confidence: float | None = None
    critic: dict | None = None
    error: str | None = None
    elapsed_ms: int = 0
    usage: dict | None = None
    model_started_at: int | None = None

    def to_record(self, frozen: dict, *, prompt_hash: str, model: str, enqueued_at: int, started_at: int, completed_at: int) -> dict:
        disagreement = None
        if self.review_outcome == "completed" and self.model_opinion is not None:
            app = frozen.get("verdict")
            model_allows = self.model_opinion == "setup"
            disagreement = ("agree" if (app == "allow") == model_allows else ("model_would_refuse" if app == "allow" else "model_would_allow"))
        return {"runId": frozen.get("runId"), "symbol": frozen.get("symbol"), "trigger": frozen.get("trigger"), "decisionId": frozen.get("decisionId"),
                "inputHash": frozen.get("inputHash"), "evidenceInputHash": frozen.get("evidenceInputHash"), "policyVersion": frozen.get("decisionVersion"),
                "frozenSource": frozen.get("frozenSource"), "frozenBarsHash": frozen.get("frozenBarsHash"),
                "evidenceVersion": EVIDENCE_VERSION, "evidenceKey": evidence_key(frozen, prompt_hash=prompt_hash, model=model),
                "model": model, "promptHash": prompt_hash, "asOf": frozen.get("frozenAt"), "enqueuedAt": enqueued_at, "startedAt": started_at,
                "modelStartedAt": self.model_started_at, "completedAt": completed_at, "reviewOutcome": self.review_outcome,
                "modelOpinion": self.model_opinion, "modelConfidence": self.model_confidence,
                "citedEvidence": (self.critic or {}).get("violations"), "summary": (self.critic or {}).get("summary"),
                "usage": self.usage, "error": self.error, "elapsedMs": self.elapsed_ms, "disagreement": disagreement,
                "appVerdict": frozen.get("verdict"), "appReasonCodes": frozen.get("reasonCodes"), "authority": AUTHORITY}


async def run_evidence(frozen: dict, *, client, llm, thresholds, images: dict | None, facts_txt: str, timeout_s: float) -> EvidenceResult:
    """One bounded critic evaluation over the isolated analysis copy. Every failure is an evidence outcome."""
    import asyncio
    from .vision import VisionPipeline
    t0 = time.perf_counter()
    if client is None or llm is None or not getattr(llm, "available", True):
        return EvidenceResult("unavailable", error="no model client / key")
    why = validate_frozen(frozen)
    if why:
        return EvidenceResult("invalid", error=why)
    try:
        a = isolated_analysis(frozen)
    except Exception as exc:  # noqa: BLE001 - a bad frozen input is an evidence outcome, never a batch abort
        return EvidenceResult("invalid", error=f"frozen input unusable: {type(exc).__name__}: {exc}")
    # the evidence prompt must state what the app actually decided - the legacy DTO's kind-derived confirmation
    # booleans are not observations
    facts_txt = (facts_txt or "") + (f"\n\nAPP DECISION (deterministic-entry-v1): {frozen.get('verdict')} "
                                     f"{', '.join(frozen.get('reasonCodes') or []) or 'no refusal codes'}; confirmation variant "
                                     f"{frozen.get('confirmationVariant')}; measured checks: "
                                     + "; ".join(f"{c.get('name')}={c.get('outcome')}" for c in (frozen.get('checks') or []) if isinstance(c, dict)))
    vp = VisionPipeline(client, llm, thresholds=thresholds, max_passes=1, trace=[])
    started = int(time.time() * 1000)
    try:
        critic = await asyncio.wait_for(vp.run_critic(a, images or {}, facts_txt), timeout_s)
    except asyncio.TimeoutError:
        return EvidenceResult("timed_out", error=f"no answer within {timeout_s:g}s", elapsed_ms=int((time.perf_counter() - t0) * 1000), model_started_at=started)
    except Exception as exc:  # noqa: BLE001 - an evidence failure is an evidence outcome
        return EvidenceResult("failed", error=f"{type(exc).__name__}: {exc}", elapsed_ms=int((time.perf_counter() - t0) * 1000), model_started_at=started)
    if critic is None:
        return EvidenceResult("invalid", error="critic returned no structured verdict", elapsed_ms=int((time.perf_counter() - t0) * 1000), model_started_at=started)
    usage = None
    pr = critic.get("passRecord") if isinstance(critic, dict) else None
    if isinstance(pr, dict) and isinstance(pr.get("usage"), dict):
        usage = pr["usage"]
    elif isinstance(critic.get("usage"), dict):
        usage = critic["usage"]
    return EvidenceResult("completed", model_opinion=("no_setup" if critic.get("kill") else "setup"),
                          model_confidence=float(getattr(a, "confidence", 0.0) or 0.0),
                          critic={k: critic.get(k) for k in ("kill", "summary", "violations")}, elapsed_ms=int((time.perf_counter() - t0) * 1000),
                          usage=usage, model_started_at=started)
