"""Multi-pass vision analysis (spec plan §3).

    PASS 1  context   highest timeframe → structure, major levels      (PassNotes)
    PASS 2  pattern   mid timeframe    → wedge / flag / consolidation   (PassNotes)
    PASS 3  entry     primary timeframe → the TechniqueAnalysis draft   (structured)
    PASS 4  critic    adversarial "kill this setup"                     (CriticVerdict)
    ground  verify every number against FACTS; on failure re-run PASS 3
            with the corrections, bounded by max_passes.

Every pass streams its thinking/text through `on_event` so the UI shows the
model working, and every request/response is returned as a transcript the
service persists into the run's chat thread.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .analysis import facts_for_prompt
from .grounding import ground_analysis
from .llm import LLMConfig, blocks_to_json, image_block, stream_message
from .rulebook import Thresholds
from .schemas import SYSTEM_PROMPT, CriticVerdict, PassNotes, TechniqueAnalysis

EventCb = Callable[[dict], Awaitable[None]]


@dataclass
class PassRecord:
    name: str
    request_blocks: list[dict]
    response_blocks: list[dict]
    parsed: dict | None
    usage: dict
    seconds: float

    def to_dict(self) -> dict:
        return {"name": self.name, "parsed": self.parsed, "usage": self.usage,
                "seconds": round(self.seconds, 2)}


@dataclass
class PipelineResult:
    analysis: TechniqueAnalysis | None
    grounding: dict
    passes: list[PassRecord] = field(default_factory=list)
    mode: str = "full"              # full | image_only
    error: str | None = None
    total_usage: dict = field(default_factory=lambda: {"input": 0, "output": 0,
                                                       "cacheRead": 0, "cacheWrite": 0})
    # Decision trace: one record per step the pipeline took and *why* — which
    # pass ran, why a retry happened, what the critic changed, why the loop
    # stopped. Reviewers read this instead of inferring it from pass names.
    trace: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "analysis": self.analysis.to_contract() if self.analysis else None,
            "grounding": self.grounding,
            "passes": [p.to_dict() for p in self.passes],
            "mode": self.mode,
            "error": self.error,
            "usage": self.total_usage,
            "trace": list(self.trace),
        }


def _system_blocks() -> list[dict]:
    # Stable prefix → cacheable. Any byte change here re-caches (~5k tokens).
    return [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]


def _strip_images(blocks: list[dict]) -> list[dict]:
    """Transcript copy without base64 payloads (the service stores images
    separately as chat assets); keeps a marker so the UI can show a thumbnail."""
    out = []
    for b in blocks:
        if b.get("type") == "image":
            out.append({"type": "image_ref", "mediaType": b["source"]["media_type"],
                        "bytes": len(b["source"]["data"]) * 3 // 4})
        else:
            out.append(b)
    return out


class VisionPipeline:
    def __init__(self, client, cfg: LLMConfig, *, thresholds: Thresholds,
                 max_passes: int = 6, on_event: EventCb | None = None,
                 trace: list[dict] | None = None, t0: float | None = None) -> None:
        self.client = client
        self.cfg = cfg
        self.t = thresholds
        self.max_passes = max_passes
        self.on_event = on_event
        self._calls = 0
        # Shared with the service so data-gathering / options / setup steps
        # land in the same ordered list as the model passes.
        self.trace: list[dict] = trace if trace is not None else []
        self._t0 = t0 if t0 is not None else time.time()

    async def _emit(self, ev: dict) -> None:
        if self.on_event:
            await self.on_event(ev)

    async def note(self, stage: str, step: str, reason: str, **detail) -> dict:
        """Record one decision. `stage` is the pipeline stage (data, context,
        pattern, entry, critic, grounding, loop, options, setup, proposal),
        `step` the concrete action, `reason` why it happened (plain English),
        `detail` any numbers worth keeping."""
        rec = {"seq": len(self.trace) + 1, "t": round(time.time() - self._t0, 2),
               "stage": stage, "step": step, "reason": reason, "call": self._calls}
        if detail:
            rec["detail"] = detail
        self.trace.append(rec)
        await self._emit({"type": "trace", **rec})
        return rec

    async def _call(self, name: str, user_blocks: list[dict], output_format,
                    *, prior: list[dict] | None = None) -> PassRecord:
        """One model call. `prior` is earlier conversation to keep in context."""
        self._calls += 1
        t0 = time.time()
        await self._emit({"type": "pass_start", "pass": name, "call": self._calls})
        messages = list(prior or []) + [{"role": "user", "content": user_blocks}]

        async def fwd(ev: dict) -> None:
            ev = dict(ev)
            ev["pass"] = name
            await self._emit(ev)

        msg = await stream_message(
            self.client, self.cfg, on_event=fwd,
            system=_system_blocks(), messages=messages, output_format=output_format,
        )
        parsed = None
        po = getattr(msg, "parsed_output", None)
        if po is not None:
            parsed = po.model_dump() if hasattr(po, "model_dump") else po
        u = msg.usage
        usage = {"input": u.input_tokens, "output": u.output_tokens,
                 "cacheRead": getattr(u, "cache_read_input_tokens", 0) or 0,
                 "cacheWrite": getattr(u, "cache_creation_input_tokens", 0) or 0}
        rec = PassRecord(name=name, request_blocks=user_blocks,
                         response_blocks=blocks_to_json(msg.content),
                         parsed=parsed, usage=usage, seconds=time.time() - t0)
        await self._emit({"type": "pass_done", "pass": name, "parsed": parsed,
                          "usage": usage, "seconds": round(rec.seconds, 2),
                          "stopReason": msg.stop_reason})
        return rec

    # ------------------------------------------------------------------ full
    async def run(self, facts: dict, images: dict[str, bytes],
                  *, user_image: bytes | None = None, user_note: str = "") -> PipelineResult:
        """Full pipeline with FACTS. `images` maps timeframe → PNG bytes, in
        the order they should be shown (context → primary)."""
        result = PipelineResult(analysis=None, grounding={"passed": False, "checks": []},
                                trace=self.trace)
        tfs = list(images.keys())
        if not tfs:
            result.error = "no chart images"
            await self.note("loop", "abort", "no chart images were rendered, nothing to analyse")
            return result
        facts_txt = facts_for_prompt(facts)
        primary = facts.get("primaryTf") or tfs[-1]
        ctx_tf = tfs[0]
        mid_tf = tfs[1] if len(tfs) > 2 else (tfs[0] if len(tfs) > 1 else tfs[-1])
        cands = facts.get("candidateSetups") or []
        await self.note("loop", "plan",
                        f"4-pass vision loop: context on {ctx_tf}, pattern on {mid_tf}, entry on "
                        f"{primary}, critic only if a setup is claimed; call budget {self.max_passes}",
                        timeframes=tfs, primaryTf=primary, contextTf=ctx_tf, patternTf=mid_tf,
                        maxPasses=self.max_passes, userImage=bool(user_image), userNote=bool(user_note),
                        keyLevels=len(facts.get("keyLevels") or []),
                        candidateSetups=[{"setupType": c.get("setupType"), "valid": c.get("valid"),
                                          "riskReward": c.get("riskReward"),
                                          "entry": (c.get("entry") or {}).get("price")} for c in cands])

        def acc(rec: PassRecord) -> None:
            result.passes.append(rec)
            for k in result.total_usage:
                result.total_usage[k] += rec.usage.get(k, 0)

        # PASS 1 — context
        await self.note("context", "pass_1", f"read structure / major levels / volume on the {ctx_tf} chart")
        p1 = await self._call("context", [
            image_block(images[ctx_tf], "image/png"),
            {"type": "text", "text": (
                f"PASS 1 of 4 — CONTEXT on the {ctx_tf} chart.\n"
                f"Read market structure (T3.5), the major horizontal levels that matter (T1), and "
                f"whether volume confirms or contradicts the trend (T2). Keep only levels from FACTS.\n\n"
                f"FACTS:\n{facts_txt}")},
        ], PassNotes)
        acc(p1)
        await self.note("context", "result", "context pass returned",
                        parsed=bool(p1.parsed), seconds=round(p1.seconds, 1),
                        hypothesis=(p1.parsed or {}).get("pattern_hypothesis"),
                        candidateLevels=(p1.parsed or {}).get("candidate_levels"))

        # PASS 2 — pattern
        await self.note("pattern", "pass_2",
                        f"look for wedge / flag / consolidation and breakout tests on the {mid_tf} chart")
        p2 = await self._call("pattern", [
            image_block(images[mid_tf], "image/png"),
            {"type": "text", "text": (
                f"PASS 2 of 4 — PATTERN on the {mid_tf} chart.\n"
                f"Is there a falling wedge (T3.1a-c), flag, or consolidation (T3.2) forming or just "
                f"completed? Is price approaching a level, or has it broken one — and if so, apply the "
                f"breakout/fakeout tests (T3.3a-f)? Context pass said:\n"
                f"{json.dumps(p1.parsed or {}, indent=1)}")},
        ], PassNotes)
        acc(p2)
        await self.note("pattern", "result", "pattern pass returned",
                        parsed=bool(p2.parsed), seconds=round(p2.seconds, 1),
                        hypothesis=(p2.parsed or {}).get("pattern_hypothesis"))

        # PASS 3 — entry (structured), with retries on grounding failure
        corrections: list[str] = []
        analysis: TechniqueAnalysis | None = None
        grounding: dict = {"passed": False, "checks": [], "corrections": []}
        critic: dict | None = None
        remaining = max(1, self.max_passes - 3)
        for attempt in range(remaining):
            if attempt == 0:
                await self.note("entry", "pass_3", f"draft the full analysis on the {primary} chart"
                                + (" with the user's image alongside" if user_image else ""))
            else:
                await self.note("entry", f"pass_3_retry{attempt}",
                                "previous draft failed grounding; re-running entry pass with corrections"
                                + (" and the critic verdict" if critic else ""),
                                corrections=list(corrections), attempt=attempt + 1, maxAttempts=remaining)
            blocks: list[dict] = [image_block(images[primary], "image/png")]
            if user_image:
                blocks.append(image_block(user_image))
            intro = (f"PASS 3 of 4 — ENTRY on the {primary} chart. Produce the full analysis.\n"
                     f"Decide: setup or no_setup. If setup: type, entry (copied from a FACTS level or bar "
                     f"price), stop, targets (30/40/15 + 15% runner), R:R (must be >= 3), rules fired, "
                     f"options expression. Remember: bounce = enter AT the level, no confirmation; "
                     f"breakout = confirmation required. Prefer no_setup over a weak setup.\n"
                     f"Context notes: {json.dumps(p1.parsed or {})}\n"
                     f"Pattern notes: {json.dumps(p2.parsed or {})}\n")
            if user_note:
                intro += f"User note: {user_note}\n"
            if corrections:
                intro += ("\nYOUR PREVIOUS DRAFT FAILED GROUNDING. Fix exactly these:\n- "
                          + "\n- ".join(corrections) + "\n")
            if critic:
                intro += f"\nCritic verdict on the previous draft: {json.dumps(critic)}\n"
            blocks.append({"type": "text", "text": intro + f"\nFACTS:\n{facts_txt}"})
            p3 = await self._call(f"entry{'' if attempt == 0 else f'_retry{attempt}'}", blocks,
                                  TechniqueAnalysis)
            acc(p3)
            if not p3.parsed:
                corrections = ["Return the full TechniqueAnalysis structure."]
                await self.note("entry", "unparsed", "model returned no structured analysis; retrying")
                continue
            analysis = TechniqueAnalysis.model_validate(p3.parsed).clamp()
            analysis.symbol = facts.get("symbol", analysis.symbol)
            await self.note("entry", "draft", f"draft verdict {analysis.verdict}"
                            + (f" ({analysis.setup_type})" if analysis.verdict == "setup" else ""),
                            verdict=analysis.verdict, setupType=analysis.setup_type,
                            entry=analysis.entry_price, stop=analysis.stop_price,
                            targets=[t.price for t in analysis.targets], riskReward=analysis.risk_reward,
                            confidence=analysis.confidence, rulesFired=list(analysis.rules_fired),
                            noTradeReasons=list(analysis.no_trade_reasons), seconds=round(p3.seconds, 1))

            # PASS 4 — critic, only when a setup is claimed (no point killing nothing)
            critic = None
            if analysis.verdict == "setup" and self._calls < self.max_passes:
                await self.note("critic", "pass_4", "a setup is claimed, so the adversarial critic runs",
                                callsUsed=self._calls, maxPasses=self.max_passes)
                p4 = await self._call("critic", [
                    image_block(images[primary], "image/png"),
                    image_block(images[mid_tf], "image/png"),
                    {"type": "text", "text": (
                        "PASS 4 of 4 — CRITIC. Your job is to KILL this setup if it deserves it. "
                        "Check every fakeout tell (T3.3d-f), the higher-timeframe read (T3.3g), volume "
                        "(T2.6, R3.1), chop (R3.2), R:R (R2), and whether the entry is chased (T4.1). "
                        "Be adversarial; a surviving setup must earn it.\n\nDRAFT:\n"
                        + json.dumps(analysis.model_dump(), indent=1)
                        + f"\n\nFACTS:\n{facts_txt}")},
                ], CriticVerdict)
                acc(p4)
                critic = p4.parsed
                if critic:
                    cv = CriticVerdict.model_validate(critic)
                    before = analysis.confidence
                    if cv.kill:
                        analysis.verdict = "no_setup"
                        analysis.no_trade_reasons = list(analysis.no_trade_reasons) + [
                            f"CRITIC: {v}" for v in cv.violations] + [f"CRITIC: {cv.summary}"]
                        analysis.confidence = max(0.0, min(1.0, analysis.confidence + cv.confidence_adjustment))
                        await self.note("critic", "kill", "critic killed the setup; verdict flipped to no_setup",
                                        violations=list(cv.violations), fakeoutRisk=cv.fakeout_risk,
                                        summary=cv.summary, confidenceBefore=round(before, 3),
                                        confidenceAfter=round(analysis.confidence, 3))
                    else:
                        analysis.confidence = max(0.0, min(1.0, analysis.confidence + cv.confidence_adjustment))
                        if cv.violations:
                            analysis.no_trade_reasons = list(analysis.no_trade_reasons) + [
                                f"CRITIC-WARN: {v}" for v in cv.violations]
                        await self.note("critic", "survive", "setup survived the critic"
                                        + (" with warnings" if cv.violations else ""),
                                        violations=list(cv.violations), fakeoutRisk=cv.fakeout_risk,
                                        adjustments=list(cv.adjustments), summary=cv.summary,
                                        confidenceBefore=round(before, 3),
                                        confidenceAfter=round(analysis.confidence, 3))
                else:
                    await self.note("critic", "unparsed",
                                    "critic returned no structured verdict; draft kept as-is")
            elif analysis.verdict == "setup":
                await self.note("critic", "skipped",
                                "setup claimed but the call budget is exhausted, critic skipped",
                                callsUsed=self._calls, maxPasses=self.max_passes)
            else:
                await self.note("critic", "skipped", "no setup claimed, nothing for the critic to kill")

            grounding = ground_analysis(analysis, facts, thresholds=self.t)
            await self._emit({"type": "grounding", "passed": grounding["passed"],
                              "checks": grounding["checks"], "attempt": attempt + 1})
            failed = [c for c in grounding["checks"] if not c.get("passed")]
            await self.note("grounding", "check",
                            ("every number verified against FACTS" if grounding["passed"]
                             else f"{len(failed)} check(s) failed against FACTS"),
                            passed=grounding["passed"], attempt=attempt + 1,
                            failed=[{"name": c["name"], "detail": c.get("detail", "")} for c in failed],
                            corrections=list(grounding.get("corrections") or []))
            if grounding["passed"]:
                await self.note("loop", "stop", "grounding passed; analysis accepted",
                                callsUsed=self._calls)
                break
            if self._calls >= self.max_passes:
                await self.note("loop", "stop",
                                "grounding failed but the call budget is exhausted; last draft kept, "
                                "marked not grounded", callsUsed=self._calls, maxPasses=self.max_passes)
                break
            if attempt + 1 >= remaining:
                await self.note("loop", "stop",
                                "grounding failed on the last allowed attempt; last draft kept, "
                                "marked not grounded", attempt=attempt + 1, maxAttempts=remaining)
                break
            corrections = grounding["corrections"]

        result.analysis = analysis
        result.grounding = grounding
        if analysis is None:
            result.error = "model returned no analysis"
            await self.note("loop", "stop", "model never returned a parseable analysis")
        else:
            await self.note("loop", "final", f"final verdict {analysis.verdict}"
                            + (f" ({analysis.setup_type})" if analysis.verdict == "setup" else "")
                            + f", confidence {analysis.confidence:.2f}, grounded {grounding['passed']}",
                            verdict=analysis.verdict, setupType=analysis.setup_type,
                            confidence=round(analysis.confidence, 3), grounded=grounding["passed"],
                            callsUsed=self._calls, usage=dict(result.total_usage))
        return result

    # ----------------------------------------------------------- image-only
    async def run_image_only(self, image: bytes, *, note: str = "",
                             symbol_hint: str = "") -> PipelineResult:
        """Screenshot with no bars to ground against. Prices are read from the
        axis and are approximate — the result says so loudly."""
        result = PipelineResult(analysis=None, grounding={"passed": False, "checks": [],
                                                          "note": "image_only: no bar data to ground"},
                                mode="image_only", trace=self.trace)
        await self.note("loop", "plan", "image-only: single entry pass on the user's screenshot; "
                        "no FACTS, so no grounding and confidence capped at 0.6",
                        symbolHint=symbol_hint, userNote=bool(note))
        rec = await self._call("image_entry", [
            image_block(image),
            {"type": "text", "text": (
                "IMAGE-ONLY ANALYSIS. There are no FACTS; read levels and prices from the chart axis "
                "as best you can and state that prices are approximate in the rationale. Apply the "
                "full method: levels (T1), volume (T2), pattern (T3), breakout/fakeout (T3.3), and "
                "the two setup types. Cap confidence at 0.6 because nothing is grounded.\n"
                + (f"Symbol hint: {symbol_hint}\n" if symbol_hint else "")
                + (f"User note: {note}\n" if note else ""))},
        ], TechniqueAnalysis)
        result.passes.append(rec)
        for k in result.total_usage:
            result.total_usage[k] += rec.usage.get(k, 0)
        if rec.parsed:
            a = TechniqueAnalysis.model_validate(rec.parsed).clamp()
            a.confidence = min(a.confidence, 0.6)
            result.analysis = a
            await self.note("loop", "final",
                            f"image-only verdict {a.verdict}, confidence {a.confidence:.2f} (capped)",
                            verdict=a.verdict, setupType=a.setup_type, confidence=round(a.confidence, 3))
        else:
            result.error = "model returned no analysis"
            await self.note("loop", "stop", "model returned no parseable analysis")
        return result


def transcript_messages(passes: list[PassRecord]) -> list[dict]:
    """Passes → chat messages (user prompt, assistant response) for persistence."""
    out: list[dict] = []
    for p in passes:
        out.append({"role": "user", "blocks": _strip_images(p.request_blocks),
                    "meta": {"pass": p.name, "kind": "pipeline_prompt"}})
        out.append({"role": "assistant", "blocks": p.response_blocks,
                    "meta": {"pass": p.name, "kind": "pipeline_response", "usage": p.usage,
                             "seconds": round(p.seconds, 2), "parsed": p.parsed}})
    return out
