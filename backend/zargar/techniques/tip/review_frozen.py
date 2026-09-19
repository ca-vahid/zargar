"""Frozen evaluation of INTAKE REVIEWS (2026-09-19, model-cost alternatives - research only).

The appraisal side has `frozen.py`; an intake review had nothing replayable: its header (rules, notes, source
history at that minute) was never kept. This module closes that gap WITHOUT touching production behaviour:

* capture - behind `techniques.tip.review_capture_context` (default OFF) the live review stamps the exact request
  (header + system + model + tool budget) on its own run trace. Observation only: the request sent is unchanged.
* case    - `build_case(run)` assembles a case from that manifest plus the run's OWN recorded tool calls/results.
* replay  - `replay_review(case, client, model, budget)` runs the same request against another model. Every tool is
  served from the case; a MUTATING tool (save_note / update_exit_plan / close_position / disarm_plan) is NEVER
  executed - it is recorded as a proposed action and answered with a frozen acknowledgement. No engine, no feed,
  no order, no note. Paid: refuses to run without a `frozen.ReplayBudget`.
* compare - `compare(case, report)` judges the decision that matters for the desk: the management actions
  (tool + symbol), the missed-entry flag, and whether a valid review came back at all.

Nothing here changes which model production uses.
"""
from __future__ import annotations

import datetime as dt
import json
import time

from .frozen import ReplayBudget, ReplayBudgetExceeded, _call_key, _iso, _sha

CASE_VERSION = 1
MGMT_TOOLS = ("update_exit_plan", "close_position", "disarm_plan")
MUTATING = ("save_note",) + MGMT_TOOLS


def review_manifest(*, header: str, system: str, model: str, max_tools: int, source: str) -> dict:
    """The exact request of one live intake review (called by the analyst behind the capture knob)."""
    return {"version": CASE_VERSION, "exact": True, "header": header, "headerSha": _sha(header),
            "system": system, "systemSha": _sha(system), "model": model, "maxTools": int(max_tools), "source": source}


def _symbol(args: dict) -> str:
    for k in ("symbol", "ticker", "position_id", "positionId", "run_id", "runId", "plan_id"):
        if args.get(k):
            return str(args[k]).upper()
    return "?"


def action_set(calls: list[dict]) -> list[str]:
    """The desk-relevant decision of a review: which management tool on which target (order-free, sorted)."""
    return sorted({f"{c['tool']}:{_symbol(c.get('args') or {})}" for c in calls if c.get("tool") in MGMT_TOOLS})


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
                         "missedTip": bool(op.get("missedTip")), "watch": sorted(op.get("watch") or []),
                         "notes": sum(1 for t in used if t["tool"] == "save_note"), "usage": op.get("usage")}}


class _ServedReview:
    def __init__(self, case: dict):
        self.outputs: dict[str, list] = {}
        for t in case.get("toolOutputs") or []:
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
        same_tool = next((v for k, v in self.outputs.items() if k.startswith(tool + "|") and v), None)
        if same_tool:                                         # same tool, other arguments: serve the recorded read, say so
            self.missing.append({"tool": tool, "args": args, "served": "same tool, different arguments"})
            out = same_tool[0]
            return out if isinstance(out, dict) else {"result": out}
        self.missing.append({"tool": tool, "args": args, "served": None})
        return {"error": f"frozen evaluation - {tool} was not called in the original review; its output is not in the case"}


async def replay_review(case: dict, *, client, model: str, budget: ReplayBudget, max_tokens: int = 3000) -> dict:
    """One paid, isolated replay of a captured review on `model`. A budget is mandatory."""
    from .analyst import TOOLS, ReviewOpinion, parse_single_object

    if budget is None:
        raise ValueError("a ReplayBudget is required - a paid evaluation never runs uncapped")
    base = {"runId": case.get("runId"), "model": model, "at": _iso(dt.datetime.now(dt.timezone.utc)), "baseline": case.get("baseline")}
    man = case.get("manifest") or {}
    if not case.get("replayable"):
        return {**base, "skipped": True, "reason": "; ".join(case.get("gaps") or ["not replayable"])}
    served = _ServedReview(case)
    max_tools = int(man.get("maxTools") or 8)
    messages: list = [{"role": "user", "content": man["header"]}]
    usage = {"in": 0, "out": 0, "calls": 0}
    text, error, tools_used, t0 = None, None, 0, time.perf_counter()
    try:
        for _ in range(max_tools + 2):
            entry: dict = {"attempt": usage["calls"] + 1, "model": model}
            est = budget.estimate_usd(system=man["system"], messages=messages, tools=TOOLS, max_tokens=max_tokens)
            entry["estimateUsd"] = round(est, 4)
            budget.allow(est, label=f"{case.get('runId')} attempt {entry['attempt']}")
            try:
                resp = await client.messages.create(model=model, max_tokens=max_tokens, system=man["system"],
                                                    messages=messages, tools=TOOLS)
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                budget.charge(entry)
                raise
            usage["calls"] += 1
            u = getattr(resp, "usage", None)
            entry.update(inputTokens=int(getattr(u, "input_tokens", 0) or 0) if u is not None else None,
                         outputTokens=int(getattr(u, "output_tokens", 0) or 0) if u is not None else None,
                         cacheReadTokens=int(getattr(u, "cache_read_input_tokens", 0) or 0) if u is not None else None,
                         cacheWriteTokens=int(getattr(u, "cache_creation_input_tokens", 0) or 0) if u is not None else None)
            usage["in"] += entry["inputTokens"] or 0
            usage["out"] += entry["outputTokens"] or 0
            budget.charge(entry)
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
    except ReplayBudgetExceeded as exc:
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
           "actions": action_set(served.proposed), "proposed": served.proposed,
           "missedTip": bool(op.missed_tip) if op else None, "watch": sorted(op.watch or []) if op else None,
           "notes": sum(1 for p in served.proposed if p["tool"] == "save_note"),
           "headline": (op.headline[:300] if op else None), "toolCalls": len(served.calls), "unserved": served.missing,
           "tokens": usage, "latencyMs": round((time.perf_counter() - t0) * 1000.0, 1), "budget": budget.summary()}
    rep["compare"] = compare(case, rep)
    return rep


def compare(case: dict, rep: dict) -> dict:
    """Agreement with the production review on the desk-relevant decision. A MISSED management action is the costly
    direction (the desk would not have managed a position); an EXTRA one is reported apart - never netted."""
    b = case.get("baseline") or {}
    if not rep.get("valid"):
        return {"agree": False, "failure": "no valid review", "missedActions": list(b.get("actions") or []), "extraActions": []}
    base_a, new_a = set(b.get("actions") or []), set(rep.get("actions") or [])
    missed, extra = sorted(base_a - new_a), sorted(new_a - base_a)
    flag_same = bool(b.get("missedTip")) == bool(rep.get("missedTip"))
    return {"agree": not missed and not extra and flag_same, "missedActions": missed, "extraActions": extra,
            "missedEntryFlag": {"baseline": bool(b.get("missedTip")), "candidate": bool(rep.get("missedTip")), "same": flag_same}}


def summarize(reports: list[dict]) -> dict:
    done = [r for r in reports if not r.get("skipped")]
    return {"cases": len(reports), "replayed": len(done), "skipped": len(reports) - len(done),
            "valid": sum(1 for r in done if r.get("valid")),
            "agree": sum(1 for r in done if (r.get("compare") or {}).get("agree")),
            "missedManagement": sum(1 for r in done if (r.get("compare") or {}).get("missedActions")),
            "extraManagement": sum(1 for r in done if (r.get("compare") or {}).get("extraActions")),
            "missedEntryFlagDiffers": sum(1 for r in done if not ((r.get("compare") or {}).get("missedEntryFlag") or {"same": True})["same"]),
            "spentUsd": round(max((float((r.get("budget") or {}).get("spentUsd") or 0) for r in done), default=0.0), 4)}
