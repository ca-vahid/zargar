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
    {"name": "save_note",
     "description": "Save a durable note to the shared tips knowledge base. Use it for context "
                    "that matters BEYOND this run: the tip's own framing (e.g. 'the SPY put is "
                    "downside protection for the source's Oct-Dec calls'), position lifecycle "
                    "info, or a lesson about this source. Future runs on the same ticker/source "
                    "are handed these notes. Do NOT restate the trade itself. scope: 'tip' "
                    "(this tip only), 'ticker', 'source' or 'general'.",
     "input_schema": {"type": "object", "properties": {
         "scope": {"type": "string"}, "text": {"type": "string"}},
         "required": ["scope", "text"]}},
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
- SHARED NOTES: you are handed the desk's saved notes for this ticker/source. Read them — \
they may change your verdict (e.g. an earlier OPEN this alert updates). When THIS tip carries \
durable context (a hedge rationale, 'trimming the runner', why the source is doing something), \
save_note it so later runs know. One note, only when there is something worth keeping.

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


async def _run_tool(eng, name: str, args: dict, ctx: dict | None = None) -> dict:
    sym = str(args.get("symbol") or "").upper()
    if name == "save_note":
        ctx = ctx or {}
        kind = str(args.get("scope") or "general").lower()
        scope = {"ticker": f"ticker:{str(ctx.get('ticker') or '').upper()}",
                 "source": f"source:{ctx.get('source') or 'unknown'}",
                 "tip": f"signal:{ctx.get('signal_id') or ''}",
                 }.get(kind, "general")
        note = await eng.signals_service.add_tip_note(
            scope, str(args.get("text") or ""),
            author=f"analyst:{str(ctx.get('run_id') or '')[:8]}",
            signal_id=ctx.get("signal_id"), run_id=ctx.get("run_id"))
        return {"saved": True, "scope": note["scope"], "id": note["id"]}
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


class _Recorder:
    """Captures the analyst's play-by-play: appends each step to a trace, streams
    it live on the `tip_analyst` bus topic, and periodically persists the run so
    an in-flight run is visible in history. Every step is a plain dict with a
    monotonic `seq`, a `kind` and a prose `text` for the review UI."""

    def __init__(self, eng, run_id: str):
        self.eng = eng
        self.run_id = run_id
        self.trace: list[dict] = []

    def step(self, kind: str, text: str, **extra) -> None:
        rec = {"seq": len(self.trace), "kind": kind, "text": text,
               "at": dt.datetime.now(dt.timezone.utc).isoformat(), **extra}
        self.trace.append(rec)
        try:
            from ... import bus as topics
            self.eng.bus.publish(topics.TIP_ANALYST, {"runId": self.run_id, "step": rec})
        except Exception:      # streaming is best-effort
            pass


async def _persist_run(eng, run_id: str, *, status: str, rec: _Recorder,
                       opinion=None, error: str | None = None, **fields) -> None:
    from ...models import TipAnalystRun
    import datetime as _dt
    async with eng.sf() as session:
        row = await session.get(TipAnalystRun, run_id)
        if row is None:
            return
        row.status = status
        row.trace = list(rec.trace)
        if opinion is not None:
            row.opinion = opinion
            row.verdict = opinion.get("verdict")
        if error is not None:
            row.error = error
        if status in ("done", "failed"):
            row.finished_at = _dt.datetime.now(_dt.timezone.utc)
        for k, v in fields.items():
            setattr(row, k, v)
        await session.commit()


async def analyze_tip(eng, signal_row, verification: dict, policy, *,
                      client=None) -> dict | None:
    """Appraise one tip. Persists a full TipAnalystRun (trace + tools + opinion),
    streams the play-by-play live, and returns the opinion dict (stored on
    extraction.analyst) or None on failure — strictly advisory."""
    from ...domain import new_id
    from ...models import TipAnalystRun

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
    tool_names = [t["name"] for t in TOOLS]
    run_id = new_id()
    async with eng.sf() as session:            # create the run row (visible immediately)
        session.add(TipAnalystRun(
            id=run_id, signal_id=getattr(signal_row, "id", None),
            ticker=signal_row.ticker, source=signal_row.source_name,
            status="running", model=model, tools=tool_names, tip=tip))
        await session.commit()

    rec = _Recorder(eng, run_id)

    # the desk's shared knowledge for this tip (notes earlier runs / the user saved)
    notes: list[dict] = []
    try:
        notes = await eng.signals_service.notes_for_tip(
            signal_row.ticker, signal_row.source_name, signal_id=signal_row.id,
            limit=int(s.get("techniques.tip.analyst_notes_max", 12)))
    except Exception:                                   # knowledge is best-effort
        log.debug("notes lookup failed for %s", signal_row.id)
    notes_txt = "\n".join(
        f"- [{n['scope']}] {n['text']} ({(n['createdAt'] or '')[:10]}, {n['author']})"
        for n in notes) or "(none yet)"

    rec.step("start", f"Appraising {signal_row.ticker} {signal_row.direction} "
             f"from {signal_row.source_name or 'unknown'}. Tools available: "
             f"{', '.join(tool_names)}."
             + (f" {len(notes)} shared note(s) handed to the run." if notes else ""),
             tip=tip, notes=notes,
             verification={k: verification.get(k) for k in ("passed", "park", "shadow_only")})

    header = (f"Today (ET): {dt.datetime.now(dt.timezone(dt.timedelta(hours=-4))):%Y-%m-%d %H:%M}\n"
              f"Per-tip budget: ${policy.budget_per_tip:,.0f} · option DTE window "
              f"{policy.dte_min}-{policy.dte_max} (tip's own contract may override)\n"
              f"TIP: {json.dumps(tip)}\n"
              f"VERIFICATION: {json.dumps({k: verification.get(k) for k in ('passed', 'park', 'shadow_only')})} "
              f"failed checks: {[c['name'] for c in verification.get('checks', []) if not c['passed']]}\n"
              f"SHARED NOTES (desk knowledge from earlier runs):\n{notes_txt}")
    system = SYSTEM + json.dumps(AnalystOpinion.model_json_schema(), separators=(",", ":"))
    messages: list = [{"role": "user", "content": header}]
    tools_used: list[dict] = []
    tool_ctx = {"ticker": signal_row.ticker, "source": signal_row.source_name,
                "signal_id": getattr(signal_row, "id", None), "run_id": run_id}

    async def loop() -> AnalystOpinion | None:
        for _ in range(max_tools + 2):
            resp = await client.messages.create(
                model=model, max_tokens=2000, system=system,
                messages=messages, tools=TOOLS)
            calls = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            think = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            if think.strip():
                rec.step("llm", think.strip())
            if not calls or len(tools_used) >= max_tools:
                await _persist_run(eng, run_id, status="running", rec=rec)
                return _parse_opinion(think)
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for c in calls:
                args = dict(c.input)
                if len(tools_used) >= max_tools:
                    out = {"error": "tool budget exhausted — answer now"}
                    rec.step("note", "Tool budget exhausted — asking for the final answer.")
                else:
                    rec.step("tool_call", f"→ {c.name}({json.dumps(args, default=str)})",
                             tool=c.name, args=args)
                    try:
                        out = await _run_tool(eng, c.name, args, ctx=tool_ctx)
                    except Exception as exc:
                        out = {"error": str(exc)[:300]}
                    tools_used.append({"tool": c.name, "args": args})
                    rec.step("tool_result", f"← {c.name}: {json.dumps(out, default=str)[:500]}",
                             tool=c.name, result=out)
                results.append({"type": "tool_result", "tool_use_id": c.id,
                                "content": json.dumps(out, default=str)[:6000]})
            messages.append({"role": "user", "content": results})
            await _persist_run(eng, run_id, status="running", rec=rec)   # progress visible
        return None

    try:
        opinion = await asyncio.wait_for(loop(), timeout=TIMEOUT_S)
    except Exception as exc:
        log.warning("tip analyst failed for %s: %s", signal_row.id, exc)
        rec.step("error", f"Analyst failed: {exc}")
        await _persist_run(eng, run_id, status="failed", rec=rec, error=str(exc)[:500])
        return None
    if opinion is None:
        rec.step("error", "No opinion produced (loop exhausted).")
        await _persist_run(eng, run_id, status="failed", rec=rec, error="no opinion")
        return None
    result = {**opinion.model_dump(), "model": model, "toolsUsed": tools_used,
              "runId": run_id, "at": dt.datetime.now(dt.timezone.utc).isoformat()}
    rec.step("final", f"Verdict: {opinion.verdict.upper()}"
             + (f" — {opinion.contract_label or opinion.contract}" if opinion.contract else "")
             + (f" @ ≤{opinion.limit_price}" if opinion.limit_price else "")
             + (f" ×{opinion.quantity}" if opinion.quantity else "")
             + f". {opinion.rationale}", opinion=result)
    await _persist_run(eng, run_id, status="done", rec=rec, opinion=result)
    return result
