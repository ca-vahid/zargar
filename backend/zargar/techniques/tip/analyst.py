"""The Tips Analyst — an LLM agent with market tools that appraises each tip.

Runs after verification (POC, 2026-08-28): given the extracted tip, the
verification result and the source's policy budget, it may call read-only
tools (quote, bars, option expiries/chain, flow read, source scorecard,
earnings) and must answer with a JSON opinion: take / watch / skip, the
contract it would buy, a limit premium, size within budget, invalidation and
a short rationale. STRICTLY ADVISORY — it places no orders and gates nothing;
the opinion rides on the signal (`extraction.analyst`), shows on the tip card
and inside any proposal rationale. Hard rules it is told and we enforce
downstream anyway: never 0DTE, never naked calls, shorts are puts only.

Fail-open: any error, timeout or budget stop returns None and the pipeline
continues exactly as before. Tool budget: `techniques.tip.analyst_max_tools`.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

TIMEOUT_S = 120.0


class AnalystOpinion(BaseModel):
    verdict: str = Field(description='"take", "watch" or "skip"')
    instrument: str = Field(default="option", description='"option" or "shares"')
    contract: Optional[str] = Field(
        default=None, description="Unpadded OCC symbol of the suggested contract "
                                  "(e.g. NTR270319C00082500); null for shares/skip")
    contract_label: Optional[str] = Field(
        default=None, description='Human label, e.g. "NTR 82.5C 2027-03-19"')
    limit_price: Optional[float] = Field(
        default=None, description="Suggested limit: the option premium (or share price)")
    quantity: Optional[int] = Field(
        default=None, description="Contracts (or shares) within the stated budget")
    invalidation: Optional[str] = Field(
        default=None, description="One sentence: what kills the idea (level/premium/date)")
    rationale: str = Field(description="2-3 sentences: why this verdict and this expression")
    confidence: float = Field(default=0.5, description="0..1")


TOOLS = [
    {"name": "get_quote", "description": "Live quote for a stock symbol.",
     "input_schema": {"type": "object", "properties": {
         "symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "get_bars",
     "description": "Recent OHLC bars for a symbol (compact). tf: 1h or 5m.",
     "input_schema": {"type": "object", "properties": {
         "symbol": {"type": "string"}, "tf": {"type": "string"},
         "sessions": {"type": "integer"}}, "required": ["symbol"]}},
    {"name": "get_expiries", "description": "Listed option expiries with DTE and spot.",
     "input_schema": {"type": "object", "properties": {
         "symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "get_chain",
     "description": "Option chain for one expiry, strikes near the money (bid/ask/delta/OI).",
     "input_schema": {"type": "object", "properties": {
         "symbol": {"type": "string"}, "expiry": {"type": "string"}},
         "required": ["symbol", "expiry"]}},
    {"name": "get_flow", "description": "Latest options-flow read for the symbol, if any.",
     "input_schema": {"type": "object", "properties": {
         "symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "get_source_stats",
     "description": "The tip source's shadow-book scorecard (trust evidence).",
     "input_schema": {"type": "object", "properties": {
         "source": {"type": "string"}}, "required": ["source"]}},
    {"name": "get_earnings", "description": "Days until the symbol's next earnings, if known.",
     "input_schema": {"type": "object", "properties": {
         "symbol": {"type": "string"}}, "required": ["symbol"]}},
]

SYSTEM = """You are the tips-desk analyst for a personal trading app. A tip was just \
extracted and verified; your job is to appraise it and suggest HOW to express it, using \
the tools to look at the actual market. You are advisory: a human (or a shadow book) acts.

Rules you must respect in suggestions:
- Options only via LISTED contracts with a real market (avoid spreads > ~10% of mid, \
zero-bid contracts, and open interest under ~100 unless the tip names the exact contract).
- NEVER suggest 0DTE, naked call writing, or shorting shares (bearish = long puts).
- Size within the stated budget. Suggest quantity = floor(budget / (ask x 100)) for options.
- When the tip names an exact contract, prefer it verbatim unless the market says it is \
untradeable (say so in the rationale).
- "watch" = right idea, wrong moment (level not reached, spread too wide pre-open). \
"skip" = the tip is stale, incoherent, or the market contradicts it.

Use at most a few tool calls (they are metered). Then reply with ONLY one JSON object \
matching this schema — no prose, no markdown fences:
"""


def _compact_bars(bars: list) -> dict:
    if not bars:
        return {"note": "no bars"}
    closes = [round(float(b.close), 4) for b in bars[-24:]]
    return {"bars": len(bars), "lastCloses": closes,
            "high": round(max(float(b.high) for b in bars), 4),
            "low": round(min(float(b.low) for b in bars), 4)}


def _compact_chain(chain: dict, want: float | None = None) -> dict:
    spot = float(chain.get("spot") or 0)
    center = want or spot
    rows = chain.get("rows") or []
    rows = sorted(rows, key=lambda r: abs(float(r["strike"]) - center))[:9]
    rows = sorted(rows, key=lambda r: float(r["strike"]))
    slim = []
    for r in rows:
        row = {"strike": r["strike"]}
        for side in ("call", "put"):
            c = r.get(side)
            if c:
                row[side] = {k: c.get(k) for k in
                             ("symbol", "bid", "ask", "spreadPct", "volume",
                              "openInterest", "delta")}
        slim.append(row)
    return {"underlying": chain.get("underlying"), "expiry": chain.get("expiry"),
            "dte": chain.get("dte"), "spot": chain.get("spot"), "strikes": slim}


async def _run_tool(eng, name: str, args: dict) -> dict:
    sym = str(args.get("symbol") or "").upper()
    if name == "get_quote":
        await eng.ensure_symbol(sym)
        q = eng.quotes.get(sym)
        if q is None:
            return {"error": f"no quote for {sym}"}
        return {"symbol": sym, "last": q.last, "bid": q.bid, "ask": q.ask,
                "spreadPct": round(q.spread_pct, 3), "prevClose": q.prev_close,
                "session": getattr(q, "session", None)}
    if name == "get_bars":
        from ...marketstructure.history import fetch_recent
        tf = str(args.get("tf") or "1h")
        if tf not in ("1h", "5m", "15m", "30m"):
            tf = "1h"
        bars = await fetch_recent(sym, tf, sessions=int(args.get("sessions") or 5))
        return {"symbol": sym, "tf": tf, **_compact_bars(bars)}
    if name == "get_expiries":
        out = await eng.options.expiries(sym)
        exps = [e for e in out.get("expiries", []) if not e.get("is0dte")][:12]
        return {"symbol": sym, "spot": out.get("spot"), "expiries": exps}
    if name == "get_chain":
        chain = await eng.options.chain(sym, str(args.get("expiry")))
        return _compact_chain(chain)
    if name == "get_flow":
        flow = getattr(eng, "flow_service", None)
        if flow is None:
            return {"note": "flow not available"}
        line = await flow.context_for(sym, consumer="tip_analyst", ref_id=None)
        return {"symbol": sym, "flow": line or "no read"}
    if name == "get_source_stats":
        cards = await eng.signals_service.source_scorecards()
        src = str(args.get("source") or "")
        card = next((c for c in cards if c["source"] == src), None)
        if card is None:
            return {"note": f"no scorecard yet for {src}"}
        return {k: card.get(k) for k in ("source", "signals", "verified", "failed",
                                         "expiredUnfilled", "barCleared", "books")}
    if name == "get_earnings":
        cal = getattr(eng, "calendar", None)
        if cal is None:
            return {"note": "calendar not available"}
        days = await cal.days_to_earnings(sym)
        return {"symbol": sym, "daysToEarnings": days,
                "note": "dates are advisory, not confirmed"}
    return {"error": f"unknown tool {name}"}


def _parse_opinion(raw: str) -> AnalystOpinion:
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    i, j = s.find("{"), s.rfind("}")
    if i == -1 or j <= i:
        raise ValueError("no JSON object in analyst reply")
    return AnalystOpinion.model_validate_json(s[i:j + 1])


async def analyze_tip(eng, signal_row, verification: dict, policy, *,
                      client=None) -> dict | None:
    """Appraise one tip. Returns the opinion dict (stored on
    extraction.analyst) or None on any failure — strictly advisory."""
    s = eng.settings
    if not bool(s.get("techniques.tip.analyst_enabled", True)):
        return None
    api_key = getattr(eng.config, "anthropic_api_key", "")
    if client is None and not api_key:
        return None
    model = str(s.get("techniques.tip.analyst_model") or "") or eng.config.extraction_model
    max_tools = int(s.get("techniques.tip.analyst_max_tools", 8))
    if client is None:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)

    tip = {
        "ticker": signal_row.ticker, "direction": signal_row.direction,
        "action": signal_row.action, "instrument": signal_row.instrument,
        "strike": signal_row.strike, "premium": signal_row.premium,
        "expiry": signal_row.expiry, "dteHintDays": signal_row.dte_hint_days,
        "entryPrice": signal_row.entry_price, "targetPrice": signal_row.target_price,
        "stopPrice": signal_row.stop_price, "horizonSessions": signal_row.horizon_sessions,
        "catalyst": signal_row.catalyst, "thesis": signal_row.thesis_summary,
        "confidence": signal_row.confidence, "source": signal_row.source_name,
        "status": signal_row.status,
    }
    header = (f"Today (ET): {dt.datetime.now(dt.timezone(dt.timedelta(hours=-4))):%Y-%m-%d %H:%M}\n"
              f"Per-tip budget: ${policy.budget_per_tip:,.0f} · option DTE window "
              f"{policy.dte_min}-{policy.dte_max} (tip's own contract may override)\n"
              f"TIP: {json.dumps(tip)}\n"
              f"VERIFICATION: {json.dumps({k: verification.get(k) for k in ('passed', 'park', 'shadow_only')})} "
              f"failed checks: {[c['name'] for c in verification.get('checks', []) if not c['passed']]}")
    system = SYSTEM + json.dumps(AnalystOpinion.model_json_schema(), separators=(",", ":"))
    messages: list = [{"role": "user", "content": header}]
    tools_used: list[dict] = []

    async def loop() -> AnalystOpinion | None:
        for _ in range(max_tools + 2):
            resp = await client.messages.create(
                model=model, max_tokens=2000, system=system,
                messages=messages, tools=TOOLS)
            calls = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            if not calls or len(tools_used) >= max_tools:
                text = "".join(b.text for b in resp.content
                               if getattr(b, "type", "") == "text")
                return _parse_opinion(text)
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for c in calls:
                if len(tools_used) >= max_tools:
                    out = {"error": "tool budget exhausted — answer now"}
                else:
                    try:
                        out = await _run_tool(eng, c.name, dict(c.input))
                    except Exception as exc:
                        out = {"error": str(exc)[:300]}
                    tools_used.append({"tool": c.name, "args": dict(c.input)})
                results.append({"type": "tool_result", "tool_use_id": c.id,
                                "content": json.dumps(out, default=str)[:6000]})
            messages.append({"role": "user", "content": results})
        return None

    try:
        opinion = await asyncio.wait_for(loop(), timeout=TIMEOUT_S)
    except Exception as exc:
        log.warning("tip analyst failed for %s: %s", signal_row.id, exc)
        return None
    if opinion is None:
        return None
    return {**opinion.model_dump(), "model": model, "toolsUsed": tools_used,
            "at": dt.datetime.now(dt.timezone.utc).isoformat()}
