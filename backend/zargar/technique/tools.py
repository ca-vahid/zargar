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
`backtest_window` for "how has this done". When the user pastes a chart image, analyse it directly
but say prices are approximate unless you also fetch bars. Keep answers concrete: numbers, rule ids,
what would change the verdict.
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
                              setup: dict | None = None, title: str = ""):
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
        setup_d = None
        if setup:
            setup_d = {"entry": {"price": setup.get("entry")}, "stop": {"price": setup.get("stop")},
                       "targets": [{"price": p} for p in (setup.get("targets") or [])]}
        png = render_chart(blist[-bars:], title=title or f"{symbol.upper()} {tf}", tf=tf,
                           levels=levels, wedge=wedge, setup=setup_d)
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

    async def _t_list_recent_runs(self, symbol: str | None = None, limit: int = 10):
        rows = await self.technique.list_runs(limit=limit, symbol=symbol)
        slim = [{k: r.get(k) for k in ("id", "symbol", "verdict", "setupType", "confidence",
                                        "grounded", "createdAt", "status")} for r in rows]
        return json.dumps(slim, default=str), {}
