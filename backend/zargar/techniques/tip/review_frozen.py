"""Frozen evaluation of INTAKE REVIEWS (2026-09-19, model-cost alternatives - research only; safeguards rev 2).

The appraisal side has `frozen.py`; an intake review had nothing replayable: its header (rules, notes, source
history at that minute) was never kept. This module closes that gap WITHOUT touching production behaviour:

* capture - behind `techniques.tip.review_capture_context` the live review stamps the exact request (header +
  system + model + tool budget) on its own run trace. Observation only: the request sent is unchanged.
* case    - `build_case(run)` assembles a case from that manifest plus the run's OWN recorded tool calls/results.
* replay  - `replay_review(case, client, model, budget)` runs the same request against another model. A read is
  served ONLY when the case holds that exact tool + arguments; anything else stays MISSING (never another request's
  evidence). A MUTATING tool (save_note / update_exit_plan / close_position / disarm_plan) is NEVER executed - it is
  recorded as a proposed instruction and answered with a frozen acknowledgement. No engine, no feed, no order.
* compare - `compare(case, report)` judges the INSTRUCTION, not just the tool: target, stop levels, targets,
  fractions, sale quantity, hold cap. A changed level is a disagreement. A replay that asked for evidence the case
  does not hold is INCONCLUSIVE - never an equivalence pass.
* budget  - `SuiteBudget`: ONE estimate-based spending GUARD for the whole evaluation (not a guaranteed maximum) (all models, cases, turns, retries, separate
  invocations) - durable write-ahead ledger, per-model rate cards, conservative reservation before every attempt.

Nothing here changes which model production uses.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time

from .frozen import _call_key, _iso, _sha

CASE_VERSION = 2
MGMT_TOOLS = ("update_exit_plan", "close_position", "disarm_plan")
MUTATING = ("save_note",) + MGMT_TOOLS
_TARGET_KEYS = ("position_id", "positionId", "run_id", "runId", "plan_id", "symbol", "ticker")
_FREE_TEXT = ("reason", "note", "rationale")          # prose is not part of the instruction
_ROUND = 4


def review_manifest(*, header: str, system: str, model: str, max_tools: int, source: str) -> dict:
    """The exact request of one live intake review (called by the analyst behind the capture knob)."""
    return {"version": 1, "exact": True, "header": header, "headerSha": _sha(header),
            "system": system, "systemSha": _sha(system), "model": model, "maxTools": int(max_tools), "source": source}


# ------------------------------------------------------------------ instructions
def _norm(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return round(float(v), _ROUND)
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _norm(x) for k, x in sorted(v.items())}
    return str(v).strip()


def instruction(call: dict) -> dict:
    """One management instruction in comparable form: tool, target, and EVERY operative parameter (stop levels,
    targets, fractions, sale fraction, hold cap). Free-text reasons are excluded; an absent parameter is absent."""
    args = dict(call.get("args") or {})
    target = next((str(args[k]).strip().upper() for k in _TARGET_KEYS if args.get(k)), "?")
    params = {k: _norm(v) for k, v in sorted(args.items()) if k not in _TARGET_KEYS and k not in _FREE_TEXT and v is not None}
    return {"tool": call.get("tool"), "target": target, "params": params}


def instructions(calls: list[dict]) -> list[dict]:
    out = [instruction(c) for c in calls if c.get("tool") in MGMT_TOOLS]
    return sorted(out, key=lambda i: (i["tool"], i["target"], json.dumps(i["params"], sort_keys=True)))


def action_set(calls: list[dict]) -> list[str]:
    """Coarse labels (tool:target) for display only - agreement is judged on `instructions`."""
    return sorted({f"{i['tool']}:{i['target']}" for i in instructions(calls)})


def build_case(run: dict) -> dict:
    """`run` = {id, source, model, created_at, opinion, trace}. A case is replayable only with an exact manifest."""
    trace = list(run.get("trace") or [])
    man = next((s.get("reviewManifest") for s in trace if s.get("kind") == "context" and s.get("reviewManifest")), None)
    gaps = [] if man else ["review request not captured (techniques.tip.review_capture_context was off) - not replayable"]
    outputs, pending = [], None
    for s in trace:
        if s.get("kind") == "tool_call":
            pending = {"tool": s.get("tool"), "args": s.get("args") or {}}
        elif s.get("kind") == "tool_result" and pending and s.get("tool") == pending["tool"]:
            outputs.append({**pending, "result": s.get("result")})
            pending = None
    op = run.get("opinion") or {}
    used = [{"tool": t.get("tool") or t.get("name"), "args": t.get("args") or {}} for t in (op.get("toolsUsed") or [])]
    return {"version": CASE_VERSION, "runId": run.get("id"), "source": run.get("source"), "at": _iso(run.get("created_at")),
            "manifest": man, "toolOutputs": outputs, "gaps": gaps, "replayable": bool(man),
            "baseline": {"model": op.get("model") or run.get("model"), "actions": action_set(used),
                         "instructions": instructions(used), "missedTip": bool(op.get("missedTip")),
                         "watch": sorted(op.get("watch") or []),
                         "notes": sum(1 for t in used if t["tool"] == "save_note"), "usage": op.get("usage")}}


class _ServedReview:
    """Serves a read ONLY for the exact tool + arguments the case recorded. Never another request's evidence."""

    def __init__(self, case: dict):
        self.outputs: dict[str, list] = {}
        for t in case.get("toolOutputs") or []:
            if t.get("tool") in MUTATING:
                continue
            self.outputs.setdefault(_call_key(t["tool"], t.get("args") or {}), []).append(t["result"])
        self.calls: list[dict] = []
        self.proposed: list[dict] = []
        self.missing: list[dict] = []

    def call(self, tool: str, args: dict) -> dict:
        self.calls.append({"tool": tool, "args": args})
        if tool in MUTATING:                                  # NEVER executed - recorded as a proposal
            self.proposed.append({"tool": tool, "args": args})
            return {"ok": True, "saved": True, "frozen": True, "note": "frozen evaluation - recorded as a PROPOSED action, nothing was changed"}
        bucket = self.outputs.get(_call_key(tool, args))
        if bucket:
            out = bucket.pop(0) if len(bucket) > 1 else bucket[0]
            return out if isinstance(out, dict) else {"result": out}
        self.missing.append({"tool": tool, "args": args})
        return {"error": f"frozen evaluation - {tool} was not called with these arguments in the original review; this "
                         "evidence is MISSING from the case and is not replaced by any other request's output"}


# ------------------------------------------------------------------ one spending guard for the whole evaluation
class SuiteBudgetExceeded(Exception):
    """The next attempt's reservation would cross the suite guard - refused before anything is sent."""


class SuiteBudget:
    """ONE estimate-based spending GUARD across every model, case, turn, retry and separate invocation of an evaluation.

    It is NOT a guaranteed maximum: reservations are estimates (request characters / 3, list prices) and the provider's
    actual bill can exceed a reservation; the guard refuses the NEXT attempt once recorded spend plus the next
    reservation would pass the cap, so the final bill can end above the cap by at most one attempt's overrun.

    * durable: the ledger is a JSON file, re-read on construction - a second process continues the same total;
    * write-ahead: `reserve()` records the attempt's RESERVATION before the provider call; `settle()` replaces it
      with the provider's own usage; an attempt that fails, is cut, or is never settled (crash) stays charged at
      its reservation - billing unknown is never free;
    * conservative reservation: input = request characters / 3 (not /4) at that model's input rate, plus the FULL
      `max_tokens` at its output rate, times HEADROOM. The total stays within the cap only as long as no single attempt's
      real bill exceeds HEADROOM x that reservation; an overrun is recorded (`overruns`) and still counted;
    * per-model complete rate cards are mandatory; the client must not retry silently (`replay_review` disables SDK
      retries where the client allows it - every retry is its own reserved attempt).
    """
    CHARS_PER_TOKEN = 3.0
    HEADROOM = 1.25

    def __init__(self, cap_usd: float, rates: dict, *, ledger_path: str | None = None):
        self.cap_usd = float(cap_usd)
        self.rates = {m: dict(r) for m, r in (rates or {}).items()}
        for m, r in self.rates.items():
            missing = [k for k in ("in", "out", "cacheRead", "cacheWrite") if r.get(k) is None]
            if missing:
                raise ValueError(f"no complete rate card for model {m!r} (missing {missing}) - a paid evaluation cannot be budgeted")
        self.ledger_path = ledger_path
        self.entries: list[dict] = []
        self.refused: list[dict] = []
        if ledger_path and os.path.exists(ledger_path):
            with open(ledger_path, encoding="utf-8") as fh:
                doc = json.load(fh)
            if abs(float(doc.get("capUsd", self.cap_usd)) - self.cap_usd) > 1e-9:
                raise ValueError(f"ledger {ledger_path} was opened with cap ${doc.get('capUsd')} - a run cannot change the ceiling")
            self.entries = list(doc.get("entries") or [])
            self.refused = list(doc.get("refused") or [])

    # -- accounting
    @staticmethod
    def _cost(e: dict) -> float:
        return float(e["usd"] if e.get("settled") else e["reservedUsd"])

    @property
    def spent_usd(self) -> float:
        return round(sum(self._cost(e) for e in self.entries), 6)

    def _save(self) -> None:
        if not self.ledger_path:
            return
        tmp = self.ledger_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"capUsd": self.cap_usd, "entries": self.entries, "refused": self.refused}, fh, indent=1)
        os.replace(tmp, self.ledger_path)

    def _rate(self, model: str) -> dict:
        if model not in self.rates:
            raise ValueError(f"no rate card for model {model!r} - it cannot be run inside this budget")
        return self.rates[model]

    def reservation_usd(self, model: str, *, system, messages, tools, max_tokens: int) -> float:
        r = self._rate(model)
        chars = sum(len(p) if isinstance(p, str) else len(json.dumps(p, default=str)) for p in (system, messages, tools))
        tokens_in = chars / self.CHARS_PER_TOKEN
        return (tokens_in / 1e6 * float(r["in"]) + int(max_tokens) / 1e6 * float(r["out"])) * self.HEADROOM

    def reserve(self, model: str, *, label: str, system, messages, tools, max_tokens: int) -> dict:
        est = self.reservation_usd(model, system=system, messages=messages, tools=tools, max_tokens=max_tokens)
        if self.spent_usd + est > self.cap_usd + 1e-9:
            self.refused.append({"label": label, "model": model, "reservedUsd": round(est, 4), "spentUsd": round(self.spent_usd, 4)})
            self._save()
            raise SuiteBudgetExceeded(f"budget: {label} reserves ${est:.2f} on top of ${self.spent_usd:.2f} (ceiling "
                                      f"${self.cap_usd:.2f}) - refused before the call")
        e = {"n": len(self.entries) + 1, "label": label, "model": model, "reservedUsd": round(est, 6), "settled": False,
             "at": _iso(dt.datetime.now(dt.timezone.utc))}
        self.entries.append(e)
        self._save()                                          # write-ahead: durable BEFORE the provider is called
        return e

    def settle(self, e: dict, *, inp=None, out=None, cache_read=0, cache_write=0, error: str | None = None) -> None:
        if error or inp is None or out is None:
            e.update(settled=False, billing="unknown - stays charged at its reservation", error=error)
        else:
            r = self._rate(e["model"])
            usd = (inp / 1e6 * float(r["in"]) + out / 1e6 * float(r["out"])
                   + (cache_read or 0) / 1e6 * float(r["cacheRead"]) + (cache_write or 0) / 1e6 * float(r["cacheWrite"]))
            e.update(settled=True, usd=round(usd, 6), billing="provider usage", inputTokens=inp, outputTokens=out,
                     overrun=bool(usd > e["reservedUsd"] + 1e-9))
        self._save()

    def summary(self) -> dict:
        by: dict[str, float] = {}
        for e in self.entries:
            by[e["model"]] = round(by.get(e["model"], 0.0) + self._cost(e), 6)
        return {"capUsd": self.cap_usd, "spentUsd": round(self.spent_usd, 4), "attempts": len(self.entries), "byModel": by,
                "unknownBilled": sum(1 for e in self.entries if not e.get("settled")),
                "overruns": sum(1 for e in self.entries if e.get("overrun")), "refused": len(self.refused),
                "withinGuard": self.spent_usd <= self.cap_usd + 1e-9, "guaranteedMaximum": False}


# ------------------------------------------------------------------ replay
async def replay_review(case: dict, *, client, model: str, budget: SuiteBudget, max_tokens: int = 3000,
                        prompt_cache: str | None = None, header_transform=None, extra_kw: dict | None = None) -> dict:
    """One paid, isolated replay of a captured review on `model`. The suite budget is mandatory."""
    from .analyst import TOOLS, ReviewOpinion, cache_messages, cacheable_request, parse_single_object

    if not isinstance(budget, SuiteBudget):
        raise ValueError("a SuiteBudget is required - a paid evaluation never runs uncapped or on a per-case budget")
    base = {"runId": case.get("runId"), "model": model, "at": _iso(dt.datetime.now(dt.timezone.utc)), "baseline": case.get("baseline")}
    man = case.get("manifest") or {}
    if not case.get("replayable"):
        return {**base, "skipped": True, "reason": "; ".join(case.get("gaps") or ["not replayable"])}
    if hasattr(client, "with_options"):                       # a silent SDK retry would be an unreserved attempt
        client = client.with_options(max_retries=0)
    served = _ServedReview(case)
    max_tools = int(man.get("maxTools") or 8)
    header = header_transform(man["header"]) if header_transform else man["header"]
    messages: list = [{"role": "user", "content": header}]
    usage = {"in": 0, "out": 0, "calls": 0}
    text, error, tools_used, t0 = None, None, 0, time.perf_counter()
    try:
        for _ in range(max_tools + 2):
            entry = budget.reserve(model, label=f"{case.get('runId')}/{model} attempt {usage['calls'] + 1}",
                                   system=man["system"], messages=messages, tools=TOOLS, max_tokens=max_tokens)
            try:
                _sys, _tools = cacheable_request(man["system"], TOOLS, enabled=bool(prompt_cache))
                _msgs = cache_messages(messages, enabled=prompt_cache == "conversation")
                resp = await client.messages.create(model=model, max_tokens=max_tokens, system=_sys,
                                                    messages=_msgs, tools=_tools, **(extra_kw or {}))
            except Exception as exc:
                budget.settle(entry, error=f"{type(exc).__name__}: {str(exc)[:200]}")
                raise
            usage["calls"] += 1
            u = getattr(resp, "usage", None)
            if u is not None:
                usage["cacheRead"] = usage.get("cacheRead", 0) + int(getattr(u, "cache_read_input_tokens", 0) or 0)
                usage["cacheWrite"] = usage.get("cacheWrite", 0) + int(getattr(u, "cache_creation_input_tokens", 0) or 0)
            if u is None:
                budget.settle(entry, error="no usage on the response")
            else:
                i, o = int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0)
                budget.settle(entry, inp=i, out=o, cache_read=int(getattr(u, "cache_read_input_tokens", 0) or 0),
                              cache_write=int(getattr(u, "cache_creation_input_tokens", 0) or 0))
                usage["in"] += i
                usage["out"] += o
            calls = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            if not calls:
                text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
                break
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for c in calls:
                out = {"error": "tool budget exhausted - answer now"} if tools_used >= max_tools else served.call(c.name, dict(c.input))
                tools_used += 1
                results.append({"type": "tool_result", "tool_use_id": c.id, "content": json.dumps(out, default=str)[:6000]})
            messages.append({"role": "user", "content": results})
            if tools_used >= max_tools:
                messages.append({"role": "user", "content": "Tool budget exhausted. Reply with ONLY the JSON opinion object now - request no more tools."})
    except SuiteBudgetExceeded as exc:
        error = str(exc)[:300]
    except Exception as exc:                                  # a provider failure is a measured outcome
        error = f"{type(exc).__name__}: {str(exc)[:300]}"
    op = None
    if text is not None and error is None:
        try:
            op = parse_single_object(text, ReviewOpinion, what="review reply")
        except Exception as exc:                              # noqa: BLE001 - an unparseable reply is an outcome
            error = f"no parseable review: {str(exc)[:200]}"
    rep = {**base, "headerSha": man.get("headerSha"), "valid": op is not None, "error": error,
           "actions": action_set(served.proposed), "instructions": instructions(served.proposed), "proposed": served.proposed,
           "missedTip": bool(op.missed_tip) if op else None, "watch": sorted(op.watch or []) if op else None,
           "notes": sum(1 for p in served.proposed if p["tool"] == "save_note"),
           "headline": (op.headline[:300] if op else None), "toolCalls": len(served.calls), "missingEvidence": served.missing,
           "tokens": usage, "latencyMs": round((time.perf_counter() - t0) * 1000.0, 1), "budget": budget.summary()}
    rep["compare"] = compare(case, rep)
    return rep


# ------------------------------------------------------------------ compare
def _key(i: dict) -> tuple:
    return (i["tool"], i["target"])


def compare(case: dict, rep: dict) -> dict:
    """Agreement on the actual INSTRUCTION. Outcomes: `agree` | `disagree` | `inconclusive` | `invalid`.

    * missed  - the production review managed something the candidate did not (the costly direction);
    * changed - same tool and target, different operative parameters (a stop 30.58 -> 25.00 is a disagreement);
    * extra   - the candidate managed something production did not; reported apart, never netted;
    * inconclusive - the candidate asked for evidence the case does not hold: it decided on less than production
      saw, so identical instructions are NOT an equivalence pass (and differences are not a clean failure)."""
    b = case.get("baseline") or {}
    base_i = list(b.get("instructions") or [])
    if not rep.get("valid"):
        return {"outcome": "invalid", "agree": False, "failure": rep.get("error") or "no valid review",
                "missed": base_i, "changed": [], "extra": [], "missingEvidence": list(rep.get("missingEvidence") or [])}
    new_i = list(rep.get("instructions") or [])
    rest = list(new_i)
    missed, changed = [], []
    for bi in base_i:
        exact = next((n for n in rest if n == bi), None)
        if exact is not None:
            rest.remove(exact)
            continue
        same = next((n for n in rest if _key(n) == _key(bi)), None)
        if same is None:
            missed.append(bi)
            continue
        rest.remove(same)
        keys = sorted(set(bi["params"]) | set(same["params"]))
        changed.append({"tool": bi["tool"], "target": bi["target"],
                        "fields": {k: {"baseline": bi["params"].get(k), "candidate": same["params"].get(k)}
                                   for k in keys if bi["params"].get(k) != same["params"].get(k)}})
    flag_same = bool(b.get("missedTip")) == bool(rep.get("missedTip"))
    missing = list(rep.get("missingEvidence") or [])
    clean = not missed and not changed and not rest and flag_same
    outcome = "inconclusive" if missing else ("agree" if clean else "disagree")
    return {"outcome": outcome, "agree": outcome == "agree", "missed": missed, "changed": changed, "extra": rest,
            "missingEvidence": missing,
            "missedEntryFlag": {"baseline": bool(b.get("missedTip")), "candidate": bool(rep.get("missedTip")), "same": flag_same}}


def summarize(reports: list[dict], budget: SuiteBudget | None = None) -> dict:
    done = [r for r in reports if not r.get("skipped")]
    cmp_ = [(r.get("compare") or {}) for r in done]
    return {"cases": len(reports), "replayed": len(done), "skipped": len(reports) - len(done),
            "agree": sum(1 for c in cmp_ if c.get("outcome") == "agree"),
            "disagree": sum(1 for c in cmp_ if c.get("outcome") == "disagree"),
            "inconclusive": sum(1 for c in cmp_ if c.get("outcome") == "inconclusive"),
            "invalid": sum(1 for c in cmp_ if c.get("outcome") == "invalid"),
            "missedManagement": sum(1 for c in cmp_ if c.get("missed")),
            "changedManagement": sum(1 for c in cmp_ if c.get("changed")),
            "extraManagement": sum(1 for c in cmp_ if c.get("extra")),
            "missedEntryFlagDiffers": sum(1 for c in cmp_ if not (c.get("missedEntryFlag") or {"same": True})["same"]),
            "budget": budget.summary() if budget is not None else None}
