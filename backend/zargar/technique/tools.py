"""Tools the conversational agent can call (spec plan §5).

Each tool is a thin, journaled wrapper over the technique layer so the model
answers with real artifacts — an actual rendered chart, actual levels — rather
than prose. Tool results may include image blocks; the same PNG is stored as a
chat asset so the UI renders it inline.
"""
from __future__ import annotations

import json
import time

from .analysis import AnalysisRequest, compute_facts, facts_for_prompt, gather_bars
from .history import fetch_recent, split_sessions
from .llm import image_block
from .render import render_chart
from .rulebook import RULES

TOOL_DEFS: list[dict] = [
    {
        "name": "get_bars",
        "description": "Fetch recent OHLCV bars for a symbol at a timeframe (1m, 5m, 15m, 1h, 1d). "
                       "Returns the last N bars as [ts_ms, open, high, low, close, volume] rows plus "
                       "session stats. Use as_of_ms to look at a past moment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "tf": {"type": "string", "enum": ["1m", "5m", "15m", "1h", "1d"]},
                "sessions": {"type": "integer", "minimum": 1, "maximum": 30},
                "last_n": {"type": "integer", "minimum": 10, "maximum": 400},
                "as_of_ms": {"type": "integer"},
            },
            "required": ["symbol", "tf"],
        },
    },
    {
        "name": "compute_facts",
        "description": "Run the deterministic detectors (levels with touch counts, time-of-day volume, "
                       "trend structure, wedge geometry, candle metrics, candidate setups) for a symbol "
                       "and return the FACTS text. This is the source of truth for every price.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "tf": {"type": "string", "enum": ["1m", "5m", "15m", "1h"]},
                "as_of_ms": {"type": "integer"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "render_chart",
        "description": "Render a candlestick+volume chart image for a symbol/timeframe, optionally "
                       "overlaying detected levels, the wedge, and a setup (entry/stop/targets). "
                       "Returns the image so you can look at it and the user sees it inline.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "tf": {"type": "string", "enum": ["1m", "5m", "15m", "1h", "1d"]},
                "bars": {"type": "integer", "minimum": 20, "maximum": 400,
                         "description": "How many of the most recent bars to draw"},
                "as_of_ms": {"type": "integer"},
                "show_levels": {"type": "boolean"},
                "show_wedge": {"type": "boolean"},
                "setup": {"type": "object",
                          "description": "Optional {entry, stop, targets:[...]} prices to draw"},
                "rejected": {"type": "object",
                             "description": "Optional {entry, stop, targets:[...]} for a candidate that "
                                            "FAILED, drawn muted/dashed to show what was declined"},
                "caption": {"type": "string",
                            "description": "Short note drawn on the chart, e.g. why there is no setup"},
                "title": {"type": "string"},
            },
            "required": ["symbol", "tf"],
        },
    },
    {
        "name": "run_analysis",
        "description": "Run the full multi-pass technique analysis (context → pattern → entry → critic "
                       "→ grounding) for a symbol. Expensive (several model calls). Returns the "
                       "analysis contract and grounding result. Use when the user asks for a fresh, "
                       "complete setup read.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "tf": {"type": "string", "enum": ["1m", "5m", "15m"]},
                "as_of_ms": {"type": "integer"},
                "note": {"type": "string"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_option_chain",
        "description": "Pick the contract the method would trade (first strike just OTM, current-week "
                       "Friday or 0DTE) with bid/ask, greeks, IV and the T5 warnings. Requires the "
                       "Tradier integration to be configured.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "direction": {"type": "string", "enum": ["long", "short"]},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "backtest_window",
        "description": "Replay recent history and score the deterministic setups (fill, stop/targets, "
                       "R multiples). Answers 'how has this method done on X lately'. No model calls.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "tf": {"type": "string", "enum": ["1m", "5m", "15m"]},
                "days": {"type": "integer", "minimum": 1, "maximum": 60},
                "horizon_bars": {"type": "integer", "minimum": 10, "maximum": 300},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "list_recent_runs",
        "description": "List recent analysis runs (verdict, setup type, confidence, time), optionally "
                       "for one symbol.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer", "maximum": 50}},
        },
    },
    {
        "name": "get_run",
        "description": "Fetch one analysis run by id (or id prefix): its verdict/plan, the decision trace, "
                       "what price did afterwards (outcomes), and any reviews. Use it when the user talks "
                       "about a specific run or 'this run' in a run thread.",
        "input_schema": {
            "type": "object",
            "properties": {"run_id": {"type": "string", "description": "full id or the first 8+ characters"}},
            "required": ["run_id"],
        },
    },
    {
        "name": "record_review",
        "description": "Persist the user's review of a run: whether the call was right (correct | wrong_verdict | "
                       "wrong_levels | wrong_plan | late | data_issue | unclear), which pipeline stage was at fault "
                       "(data | detectors | facts_prompt | pass_context | pass_pattern | pass_entry | critic | "
                       "grounding | options | thresholds | rulebook | other), what they expected, notes, and planned "
                       "fixes. Call it when the user states a judgement about a run ('this was wrong', 'it should "
                       "have been a setup at 101.2'). Reviewer is the user unless they ask you to judge.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "review_verdict": {"type": "string"},
                "root_cause_stage": {"type": "string"},
                "expected_verdict": {"type": "string", "description": "setup | no_setup"},
                "expected_setup_type": {"type": "string"},
                "expected_entry": {"type": "number"},
                "expected_stop": {"type": "number"},
                "expectation_note": {"type": "string"},
                "notes": {"type": "string"},
                "actions": {"type": "array", "items": {"type": "string"}},
                "reviewer": {"type": "string", "description": "user | claude"},
            },
            "required": ["run_id", "review_verdict"],
        },
    },
    {
        "name": "get_rule",
        "description": "Look up the text of a technique rule by id (e.g. T3.3d, R2).",
        "input_schema": {
            "type": "object",
            "properties": {"rule_id": {"type": "string"}},
            "required": ["rule_id"],
        },
    },
]

CHAT_TOOL_GUIDE = """
You also have TOOLS. Use them instead of guessing: `compute_facts` for any price, level or volume
claim; `render_chart` whenever a picture would help (and always when the user asks to "show" or
"draw"); `run_analysis` for a full fresh read; `get_option_chain` for contract questions;
`backtest_window` for "how has this done"; `get_run` to read a specific run (its trace, plan, what
happened next); `record_review` when the user judges a run ("this was wrong", "should have been a
setup at 101.2") so the judgement is persisted for the review loop. When the user pastes a chart
image, analyse it directly but say prices are approximate unless you also fetch bars. Keep answers
concrete: numbers, rule ids, what would change the verdict.
"""


class ToolExecutor:
    """Executes tool calls. `technique` is the TechniqueService; `store_asset` is
    a coroutine (bytes, media_type) -> asset_id provided by the chat service."""

    def __init__(self, technique, store_asset, thread_id: str | None = None) -> None:
        self.technique = technique
        self.store_asset = store_asset
        self.thread_id = thread_id

    async def run(self, name: str, args: dict) -> tuple[list[dict] | str, dict]:
        """Returns (tool_result content, ui_meta). Content is a string or a list
        of content blocks (text/image). ui_meta is attached to the event the UI
        gets (e.g. assetId for an image)."""
        fn = getattr(self, f"_t_{name}", None)
        if fn is None:
            return f"unknown tool {name}", {"error": True}
        t0 = time.time()
        try:
            content, meta = await fn(**(args or {}))
        except Exception as exc:  # the model should see tool errors, not crash the loop
            return f"tool error: {type(exc).__name__}: {exc}", {"error": True}
        meta = dict(meta or {})
        meta["seconds"] = round(time.time() - t0, 2)
        return content, meta

    # --- tools ----------------------------------------------------------------
    async def _t_get_rule(self, rule_id: str):
        txt = RULES.get(rule_id)
        return (f"{rule_id}: {txt}" if txt else f"no rule {rule_id}"), {}

    async def _t_get_bars(self, symbol: str, tf: str, sessions: int = 3, last_n: int = 120,
                          as_of_ms: int | None = None):
        bars = await fetch_recent(symbol, tf, sessions=sessions, as_of_ms=as_of_ms)
        if not bars:
            return "no bars returned", {}
        rows = [b.to_row() for b in bars[-last_n:]]
        sess = split_sessions(bars)
        summ = {k: {"open": v[0].open, "high": max(b.high for b in v), "low": min(b.low for b in v),
                    "close": v[-1].close, "bars": len(v)} for k, v in sess.items()}
        return json.dumps({"symbol": symbol.upper(), "tf": tf, "bars": rows, "sessions": summ}), \
            {"bars": len(rows)}

    async def _t_compute_facts(self, symbol: str, tf: str = "1m", as_of_ms: int | None = None):
        req = AnalysisRequest(symbol=symbol, primary_tf=tf, as_of_ms=as_of_ms,
                              thresholds=self.technique.thresholds())
        bars, notes = await gather_bars(req)
        facts = compute_facts(req, bars, notes)
        return facts_for_prompt(facts, max_bars=30), {"keyLevels": facts.get("keyLevels", [])[:8]}

    async def _t_render_chart(self, symbol: str, tf: str, bars: int = 150, as_of_ms: int | None = None,
                              show_levels: bool = True, show_wedge: bool = True,
                              setup: dict | None = None, rejected: dict | None = None,
                              caption: str = "", title: str = ""):
        req = AnalysisRequest(symbol=symbol, primary_tf=tf, context_tfs=(), as_of_ms=as_of_ms,
                              thresholds=self.technique.thresholds())
        bars_by_tf, notes = await gather_bars(req)
        blist = bars_by_tf.get(tf) or []
        if not blist:
            return "no bars to render", {}
        levels = None
        wedge = None
        if show_levels or show_wedge:
            facts = compute_facts(req, {tf: blist}, notes)
            if show_levels:
                levels = [lv for lv in facts.get("keyLevels", []) if tf in lv.get("timeframes", [tf])][:8]
            if show_wedge:
                wedge = (facts.get("wedge") or {}).get(tf)
        def _plan(d: dict | None) -> dict | None:
            if not d:
                return None
            return {"entry": {"price": d.get("entry")}, "stop": {"price": d.get("stop")},
                    "targets": [{"price": p} for p in (d.get("targets") or [])]}

        png = render_chart(blist[-bars:], title=title or f"{symbol.upper()} {tf}", tf=tf,
                           levels=levels, wedge=wedge, setup=_plan(setup),
                           rejected=_plan(rejected), caption=caption)
        asset_id = await self.store_asset(png, "image/png")
        content = [image_block(png, "image/png"),
                   {"type": "text", "text": f"Rendered {symbol.upper()} {tf}, last {min(bars, len(blist))} bars"
                                            f"{' with levels' if levels else ''}."}]
        return content, {"assetId": asset_id, "symbol": symbol.upper(), "tf": tf}

    async def _t_run_analysis(self, symbol: str, tf: str = "1m", as_of_ms: int | None = None,
                              note: str = ""):
        run = await self.technique.analyze(symbol, primary_tf=tf, as_of_ms=as_of_ms, note=note,
                                           trigger="chat", thread_id=self.thread_id, wait=True)
        res = run.get("result") or {}
        a = res.get("analysis")
        content: list[dict] = []
        img_id = (run.get("images") or {}).get("annotated")
        if img_id:
            data = await self.technique.chat.get_asset_bytes(img_id)
            if data:
                content.append(image_block(data, "image/png"))
        content.append({"type": "text", "text": json.dumps({
            "runId": run.get("id"), "analysis": a, "grounding": res.get("grounding"),
            "usage": res.get("usage")}, default=str)})
        return content, {"runId": run.get("id"), "assetId": img_id}

    async def _t_get_option_chain(self, symbol: str, direction: str = "long"):
        out = await self.technique.option_pick(symbol, direction)
        return json.dumps(out, default=str), {}

    async def _t_backtest_window(self, symbol: str, tf: str = "5m", days: int = 10,
                                 horizon_bars: int = 60):
        out = await self.technique.backtest(symbol, tf, days=days, horizon_bars=horizon_bars)
        summ = out.get("summary") or {}
        trades = out.get("trades") or []
        return json.dumps({"summary": summ, "sampleTrades": trades[:15]}, default=str), \
            {"n": len(trades)}

    async def _resolve_run_id(self, run_id: str) -> str | None:
        run_id = (run_id or "").strip()
        if not run_id:
            return None
        if await self.technique.get_run(run_id) is not None:
            return run_id
        rows = await self.technique.list_runs(limit=500)
        hit = [r["id"] for r in rows if r["id"].startswith(run_id)]
        return hit[0] if len(hit) == 1 else None

    async def _t_get_run(self, run_id: str):
        rid = await self._resolve_run_id(run_id) or (self.thread_id and None)
        if rid is None and self.thread_id:
            # a run thread: fall back to the run this thread belongs to
            t = await self.technique.chat.get_thread(self.thread_id)
            rid = (t or {}).get("runId")
        if rid is None:
            return f"no run matches {run_id!r}", {"error": True}
        run = await self.technique.get_run(rid)
        if run is None:
            return f"run {rid} not found", {"error": True}
        res = run.get("result") or {}
        slim = {
            "id": run["id"], "symbol": run["symbol"], "mode": run["mode"], "verdict": run["verdict"],
            "setupType": run["setupType"], "confidence": run["confidence"], "grounded": run["grounded"],
            "asOf": run["asOf"], "createdAt": run["createdAt"], "sessionWindow": res.get("sessionWindow"),
            "analysis": res.get("analysis"), "plan": res.get("plan"),
            "trace": [{k: t.get(k) for k in ("seq", "stage", "step", "reason")} for t in (res.get("trace") or [])],
            "outcomes": [{k: o.get(k) for k in ("planSource", "status", "outcome", "rMultiple", "mfeR", "maeR", "note")}
                         for o in (run.get("outcomes") or [])],
            "reviews": [{k: r.get(k) for k in ("reviewer", "reviewVerdict", "rootCauseStage", "notes", "createdAt")}
                        for r in (run.get("reviews") or [])],
            "setups": [{k: s.get(k) for k in ("setupType", "entry", "stop", "valid", "noTradeReasons")}
                       for s in (run.get("setups") or [])],
        }
        return json.dumps(slim, default=str), {"runId": rid}

    async def _t_record_review(self, run_id: str, review_verdict: str, root_cause_stage: str | None = None,
                               expected_verdict: str | None = None, expected_setup_type: str | None = None,
                               expected_entry: float | None = None, expected_stop: float | None = None,
                               expectation_note: str = "", notes: str = "", actions: list | None = None,
                               reviewer: str = "user"):
        rid = await self._resolve_run_id(run_id)
        if rid is None and self.thread_id:
            t = await self.technique.chat.get_thread(self.thread_id)
            rid = (t or {}).get("runId")
        if rid is None:
            return f"no run matches {run_id!r}", {"error": True}
        plan = {}
        if expected_entry is not None:
            plan["entry"] = expected_entry
        if expected_stop is not None:
            plan["stop"] = expected_stop
        try:
            d = await self.technique.add_review(
                rid, review_verdict=review_verdict, reviewer=reviewer if reviewer in ("user", "claude") else "user",
                expected_verdict=expected_verdict, expected_setup_type=expected_setup_type, expected_plan=plan,
                expectation_note=expectation_note or "", root_cause_stage=root_cause_stage, notes=notes or "",
                actions=[{"desc": a} for a in (actions or [])])
        except (KeyError, ValueError) as exc:
            return f"review not recorded: {exc}", {"error": True}
        return json.dumps({"recorded": True, "reviewId": d["id"], "runId": rid, "reviewVerdict": d["reviewVerdict"],
                           "rootCauseStage": d["rootCauseStage"]}), {"runId": rid, "reviewId": d["id"]}

    async def _t_list_recent_runs(self, symbol: str | None = None, limit: int = 10):
        rows = await self.technique.list_runs(limit=limit, symbol=symbol)
        slim = [{k: r.get(k) for k in ("id", "symbol", "verdict", "setupType", "confidence",
                                        "grounded", "createdAt", "status")} for r in rows]
        return json.dumps(slim, default=str), {}
