"""The Tips Analyst — an INDEPENDENT trader persona with market tools.

Charter: docs/techniques/tip/ANALYST.md (2026-08-28). The analyst trades the
tip technique with its OWN judgement and its OWN self-maintained rules — the
EnhancedMarket method book never applies here ("our book" in its tools means
the desk's own POSITIONS, the trading sense of the word). Per tip it appraises
(tools: quote, bars, chains, flow, source scorecard, earnings, our positions,
open tips, shared notes), decides take/watch/skip, and on a take authors both
the ENTRY (contract, limit, size within budget) and the EXIT PLAN (scale-out
targets + fractions, stop or premium-stop guard, hold cap) that the position
manager executes mechanically after the fill. Retro runs on closed positions
feed lessons back into the shared notes and the analyst's rules (scope `rule`).

It never places orders itself — its "take" becomes a proposal; approval (human
or earned auto mode) goes through RiskGate like every other order.

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
    # --- entry timing (a take chooses WHEN, not just what — ARM-PLAN P1) -------
    entry_mode: str = Field(
        default="now", description='"now" = buy immediately (proposal at your limit); '
                                   '"at_level" = ARM a plan that waits for entry_level')
    entry_level: Optional[float] = Field(
        default=None, description="UNDERLYING price to wait for when entry_mode is "
                                  "at_level (defaults to the tip's own entry)")
    entry_note: Optional[str] = Field(
        default=None, description="One sentence: why now / why wait")
    entry_levels: list[float] = Field(
        default_factory=list,
        description="SCALE-IN: underlying prices to buy at, nearest first (with "
                    "entry_mode=at_level). Empty = the single entry_level.")
    entry_fractions: list[float] = Field(
        default_factory=list,
        description="Fraction of the size at each entry level; sums to <= 1")
    entry_conditions: list[dict] = Field(
        default_factory=list,
        description='CONDITIONS gating the entry (with entry_mode=at_level): guard docs like '
                    '{"kind": "ema_reclaim", "period": 8}, {"kind": "holds_above", "price": 640, '
                    '"bars": 3}, {"kind": "guard_symbol", "symbol": "SPY", "op": ">=", "price": 640}, '
                    '{"kind": "time_at", "et": "09:45"}. With conditions but NO entry_level the plan '
                    'enters at the close of the first bar where they all pass.')
    # --- the exit campaign (required on a take; the position manager runs it) ---
    exit_targets: list[float] = Field(
        default_factory=list,
        description="UNDERLYING prices to trim at, nearest first (sell in pieces)")
    exit_fractions: list[float] = Field(
        default_factory=list,
        description="Fraction of the position to sell at each target; sums to <= 1 "
                    "(a final runner may trail)")
    underlying_stop: Optional[float] = Field(
        default=None, description="Underlying price where the idea is wrong; null only "
                                  "when premium_stop_pct is the declared guard")
    premium_stop_pct: Optional[float] = Field(
        default=None, description="Close if the option mark bleeds this % from entry (e.g. 50)")
    max_hold_sessions: Optional[int] = Field(
        default=None, description="Time box in TRADING sessions; re-evaluate dies with it")
    exit_rationale: Optional[str] = Field(
        default=None, description="One sentence: the exit campaign in words")
    legs: list[dict] = Field(
        default_factory=list,
        description='DEFINED-RISK SPREAD expression (exactly 2 legs, one buy one sell, '
                    'same type): [{"action": "buy", "type": "call", "strike": 340}, '
                    '{"action": "sell", "type": "call", "strike": 360}]. Empty for '
                    'single-leg trades. Never a lone short leg.')
    legs_expiry: Optional[str] = Field(
        default=None, description="Shared expiry (YYYY-MM-DD) for the spread legs")


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
    {"name": "get_flow",
     "description": "The options-flow desk's full evidence for the symbol: today's flagged "
                    "contracts (both sides), overnight open-interest confirmations, repeat "
                    "streaks (same contract flagged N of 5 sessions — the strongest pattern), "
                    "premium aggregates and the multi-day score story. ALWAYS call this for a "
                    "tip from source 'flow-scan' — the tip IS this evidence.",
     "input_schema": {"type": "object", "properties": {
         "symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "get_source_stats",
     "description": "The tip source's shadow-book scorecard (trust evidence).",
     "input_schema": {"type": "object", "properties": {
         "source": {"type": "string"}}, "required": ["source"]}},
    {"name": "get_earnings", "description": "Days until the symbol's next earnings, if known.",
     "input_schema": {"type": "object", "properties": {
         "symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "get_positions",
     "description": "OUR OWN open positions: every share/option position across the app's "
                    "portfolios (live, practice, sim), plus multi-day managed positions with "
                    "their exit policies. Use it to judge a tip against what the desk already "
                    "holds (adds, hedges of OUR book, overlap with the source's idea).",
     "input_schema": {"type": "object", "properties": {
         "symbol": {"type": "string",
                    "description": "optional — only positions touching this underlying"}}}},
    {"name": "get_open_tips",
     "description": "Open tips already on the desk (verified/parked/shadow/proposed), newest "
                    "first — status, direction, contract, seen count, analyst verdict. Filter "
                    "by ticker and/or source to see whether this message updates an existing "
                    "tip instead of opening a new one.",
     "input_schema": {"type": "object", "properties": {
         "ticker": {"type": "string"}, "source": {"type": "string"}}}},
    {"name": "search_messages",
     "description": "Search the desk's mirror of Discord messages from monitored channels — "
                    "the source's own history. Messages are linked stories: a morning 'bought "
                    "NVDA' and an afternoon 'sold 40%' belong together. Use it to find the "
                    "original OPEN behind an update, follow-ups on a ticker, or what a source "
                    "has been saying. Args: source (exact source name), contains (substring, "
                    "e.g. a ticker), hours (lookback), limit.",
     "input_schema": {"type": "object", "properties": {
         "source": {"type": "string"}, "contains": {"type": "string"},
         "hours": {"type": "number"}, "limit": {"type": "integer"}}}},
    {"name": "view_image",
     "description": "LOOK at an image from a mirrored Discord message (charts, screenshots — "
                    "alert rooms often post the chart instead of words). The image is returned "
                    "to you visually. message_id comes from the source history / search_messages "
                    "([images: <id>] markers); index = which image (0-based).",
     "input_schema": {"type": "object", "properties": {
         "message_id": {"type": "string"}, "index": {"type": "integer"}},
         "required": ["message_id"]}},
    {"name": "update_exit_plan",
     "description": "Rewrite the exit campaign of an OPEN managed tip position (get_positions "
                    "shows ids). EXIT-ONLY: this changes when/how we sell — it can never add "
                    "exposure, and a stop may only tighten. Use it when a source follow-up or "
                    "the market changes the campaign ('they sold 40%' → trim and tighten). "
                    "Args: position_id, exit_targets (underlying prices), exit_fractions, "
                    "underlying_stop, premium_stop_pct, max_hold_sessions, reason (required).",
     "input_schema": {"type": "object", "properties": {
         "position_id": {"type": "string"}, "exit_targets": {"type": "array", "items": {"type": "number"}},
         "exit_fractions": {"type": "array", "items": {"type": "number"}},
         "underlying_stop": {"type": "number"}, "premium_stop_pct": {"type": "number"},
         "max_hold_sessions": {"type": "integer"}, "reason": {"type": "string"}},
         "required": ["position_id", "reason"]}},
    {"name": "close_position",
     "description": "Sell part or all of an OPEN managed tip position NOW (market, reduce-only "
                    "— goes through the risk gate's safety list). fraction: 0.25 = sell a "
                    "quarter, 1.0 = close it. Use when the source exited ('sold the rest') or "
                    "the thesis is dead. Args: position_id, fraction, reason (required).",
     "input_schema": {"type": "object", "properties": {
         "position_id": {"type": "string"}, "fraction": {"type": "number"},
         "reason": {"type": "string"}}, "required": ["position_id", "reason"]}},
    {"name": "save_note",
     "description": "Save a durable note to the shared tips knowledge base. Use it for context "
                    "that matters BEYOND this run: the tip's own framing (e.g. 'the SPY put is "
                    "downside protection for the source's Oct-Dec calls'), position lifecycle "
                    "info, or a lesson about this source. Future runs on the same ticker/source "
                    "are handed these notes. Do NOT restate the trade itself. scope: 'tip' "
                    "(this tip only), 'ticker', 'source', 'general' — or 'rule' to add/refine "
                    "one of YOUR TRADING RULES (a durable lesson about how you trade, with the "
                    "why and the evidence).",
     "input_schema": {"type": "object", "properties": {
         "scope": {"type": "string"}, "text": {"type": "string"}},
         "required": ["scope", "text"]}},
    {"name": "disarm_plan",
     "description": "Disarm a WAITING armed tip plan — one still watching for its level "
                    "(get_open_tips shows armedRunId and what it waits for). Use it when the "
                    "source exited or reversed BEFORE our level filled: the thesis is dead, so "
                    "the plan must stop waiting. Refuses when the plan already holds a position "
                    "(use close_position on the managed position instead). "
                    "Args: run_id, reason (required — it is journaled).",
     "input_schema": {"type": "object", "properties": {
         "run_id": {"type": "string"}, "reason": {"type": "string"}},
         "required": ["run_id", "reason"]}},
]

SYSTEM = """You are the TIPS DESK TRADER for a personal trading app — an independent \
options-first trader with your own judgement, your own memory and your own rules. A tip \
from a followed source was just extracted and verified; decide what to do with it.

You are NOT bound by any other technique's method (the desk's EnhancedMarket book does \
not apply to you). You answer to exactly two things: the platform's safety floor below, \
and YOUR TRADING RULES — rules you and your past runs wrote, handed to you every run. \
Everything else is your call as a trader.

Safety floor (platform-enforced — do not fight it):
- never 0DTE, never naked option writing, never shorting shares (bearish = long puts)
- size within the stated per-tip budget: quantity = floor(budget / (ask x 100)) for options
- your verdict becomes an order only through a proposal + the risk gate; a human (or an \
earned auto mode) pulls the trigger

How to work:
- Look at the actual market with the tools before judging: liquidity is real (spread vs \
mid, open interest, zero bids), levels and the tape matter, the source's track record \
matters, and what the desk already holds matters (get_positions = OUR own open positions; \
get_open_tips = tips already on the desk — is this an update, an add, a hedge?).
- When the tip names an exact contract, prefer it verbatim unless the market says it is \
untradeable — and say why when you deviate.
- verdict "take" = trade it (contract, limit, quantity AND your exit plan). "watch" = \
right idea but nothing to do yet. "skip" = stale, incoherent, or the market contradicts it.
- ENTRY MODE — a take also chooses WHEN. entry_mode "now" buys immediately (a proposal \
at your limit). entry_mode "at_level" ARMS a plan that waits for entry_level on the \
underlying and fires only when price actually trades there (1m bars; the plan dies with \
the tip's horizon/contract). Choose "at_level" when the tip says wait for a retest, when \
price is extended past the stated entry, or when chasing would break your rules — a \
PARKED tip (price already ran away) is almost always "at_level". Set entry_level to the \
price you would pay; it defaults to the tip's own entry. You may also SCALE IN: \
entry_levels + entry_fractions ("half at 22.60, half at 22.10") arm one rung per level \
sharing a single stop and one exit campaign — use it for zones and accumulation tips. \
And you may set entry_conditions ("if it reclaims the 8EMA", "while SPY holds 640", \
"at 09:45 ET"): the plan stays dormant until every condition passes; with conditions \
and no entry_level it enters at the first bar where they open.
- EXIT PLAN — required on every take. You manage the position after the fill, so plan \
the whole campaign now: exit_targets = UNDERLYING prices where you trim, exit_fractions \
= how much at each (sell in pieces at opportune levels, never all-or-nothing on size), \
underlying_stop = where the idea is simply wrong (null only when premium_stop_pct is \
your declared guard), premium_stop_pct = max premium bleed you will sit through, \
max_hold_sessions = the time box. The platform executes this plan mechanically on \
closed bars — write the plan you would actually trade.
- THE SOURCE'S HISTORY: their messages are linked stories — a morning "bought NVDA" and \
an afternoon "sold 40%" belong together. Recent messages from this source are handed to \
you; search_messages digs deeper (older, other tickers, the original OPEN behind an \
update). If this tip UPDATES a position the desk already holds (get_positions), MANAGE \
that position (update_exit_plan / close_position — exit-only) instead of opening a \
duplicate, and say so in the rationale.
- IMAGES ARE NOT OPTIONAL: alert rooms put the trade IN the chart. Whenever the tip's \
own message or a relevant history line is marked [images: <id>], ALWAYS view_image it \
before judging — levels, annotations and entries live in the picture, not the caption.
- SHARED NOTES: read what you are handed — it may change the verdict (an earlier OPEN \
this message updates, a hedge rationale). save_note durable context (scope tip / ticker \
/ source / general) — a few precise notes beat many vague ones.
- YOUR TRADING RULES: follow them. When this tip (or a retro) teaches you a durable \
lesson about HOW YOU TRADE — not about one ticker — save_note it with scope "rule": \
state the rule, the why, and the evidence. The rules are yours to evolve; keep them \
few and sharp, and refine or replace a rule rather than piling on near-duplicates.

Use at most a few tool calls (they are metered). Then reply with ONLY one JSON object \
matching this schema — no prose, no markdown fences:
"""

# Shown only while the analyst has not yet written any rules of its own — the
# stored rulebook (tip_notes scope "rule") replaces this the moment it exists.
STARTER_RULES = """- Prefer the tip's own contract when it is liquid; say why when deviating.
- Judge liquidity before price: spread <= ~10% of mid, OI >= ~100 unless the tip names the exact contract.
- Scale out — first trim near a level that pays the risk; let a runner trail.
- Respect the stated framing: a hedge is sized and exited like insurance, not conviction.
- Time is a position: if the move hasn't started by ~half the runway, re-evaluate instead of hoping.
(starter rules — none saved yet; write your own with save_note scope "rule" as experience accrues)"""


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


def _our_positions(eng, symbol: str = "") -> dict:
    """Compact snapshot of the desk's own book for the analyst."""
    want = symbol.upper()
    rows = []
    for pos in eng.positions.positions_list():
        if abs(float(pos.get("qty") or 0)) < 1e-9:
            continue
        pf = eng.positions.portfolio(pos.get("portfolioId")) or {}
        if pf.get("book"):                       # shadow-book fills are not OUR positions
            continue
        opt = pos.get("option") or {}
        under = (opt.get("underlying") or pos.get("symbol") or "").upper()
        if want and want not in (under, str(pos.get("symbol") or "").upper()):
            continue
        rows.append({"portfolio": pf.get("name") or pos.get("portfolioId"),
                     "kind": pf.get("kind"), "symbol": pos.get("symbol"),
                     "secType": pos.get("secType"), "qty": pos.get("qty"),
                     "avgCost": pos.get("avgCost"), "last": pos.get("last"),
                     "unrealizedPnl": pos.get("unrealizedPnl"),
                     "unrealizedPnlPct": pos.get("unrealizedPnlPct")})
    managed = []
    pm = getattr(eng, "position_manager", None)
    if pm is not None:
        try:
            for p in pm.positions(status="open"):
                if want and str(p.get("symbol") or "").upper() != want:
                    continue
                pfm = eng.positions.portfolio(p.get("portfolioId")) or {}
                if pfm.get("book"):        # shadow-book counterfactuals are NOT ours (D9)
                    continue
                pol = p.get("policy") or {}
                managed.append({
                    "positionId": p.get("id"), "symbol": p.get("symbol"),
                    "direction": p.get("direction"), "technique": p.get("technique"),
                    "status": p.get("status"), "sessionsHeld": p.get("sessionsHeld"),
                    "entryUnderlying": p.get("entry"), "realizedPnl": p.get("realizedPnl"),
                    "legs": [{k: l.get(k) for k in ("symbol", "secType", "qty", "avgFill")}
                             for l in (p.get("legs") or []) if abs(float(l.get("qty") or 0)) > 1e-9],
                    "exitPlan": {"stop": (pol.get("stop") or {}).get("price"),
                                 "ladder": pol.get("ladder"),
                                 "premiumStopPct": pol.get("premium_stop_pct"),
                                 "timeStopSessions": pol.get("time_stop_sessions")},
                    "tags": p.get("tags"),
                })
        except Exception:                          # advisory — never fail the tool
            pass
    out: dict = {"positions": rows[:40], "managed": managed[:20]}
    if not rows and not managed:
        out["note"] = f"no open positions{f' touching {want}' if want else ''}"
    return out


async def _open_tips(eng, ticker: str = "", source: str = "") -> dict:
    import datetime as _dt

    from sqlalchemy import select

    from ...models import Signal
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=30)
    stmt = (select(Signal)
            .where(Signal.status.in_(("verified", "parked", "shadow", "proposed")),
                   Signal.created_at >= cutoff)
            .order_by(Signal.created_at.desc()).limit(25))
    if ticker:
        stmt = stmt.where(Signal.ticker == ticker.upper())
    if source:
        stmt = stmt.where(Signal.source_name == source)
    async with eng.sf() as session:
        rows = (await session.execute(stmt)).scalars().all()
        from ...models import Proposal
        pend_rows = (await session.execute(
            select(Proposal.id, Proposal.signal_id)
            .where(Proposal.status == "pending"))).all()
    pending = {p.signal_id: p.id for p in pend_rows}
    runner = getattr(eng, "tip_runner", None)
    tips = []
    for r in rows:
        t = {"ticker": r.ticker, "source": r.source_name, "direction": r.direction,
             "action": r.action, "instrument": r.instrument, "strike": r.strike,
             "expiry": r.expiry, "status": r.status, "seenCount": r.seen_count,
             "created": (r.created_at.isoformat()[:16] if r.created_at else None),
             "analystVerdict": (((r.extraction or {}).get("analyst") or {}).get("verdict"))}
        # the desk's WAITING commitments are part of the book (ARM-GAPS D3):
        # a live armed plan and/or a pending proposal ride on the tip row
        rid = runner.live_run_for_signal(r.id) if runner is not None else None
        if rid:
            ap = runner.get(rid)
            if ap is not None:
                t["armedRunId"] = rid
                t["armedWaitingAt"] = [tr.entry for tr in ap.trackers.values()
                                       if tr.status in ("waiting", "observed")]
                t["armedDay"] = f"{ap.sessions_used + 1} of {ap.horizon_sessions}"
                t["armedMode"] = ap.config.mode
        if pending.get(r.id):
            t["pendingProposalId"] = pending[r.id]
        tips.append(t)
    return {"tips": tips} if tips else {"note": "no open tips match"}


def _manage_guard(eng, pid: str) -> tuple:
    """(position, error) — the cage around the position-management tools:
    only OPEN, tip-technique managed positions, only when the knob allows."""
    if not bool(eng.settings.get("techniques.tip.analyst_manage_enabled", True)):
        return None, {"error": "position management by the analyst is disabled "
                               "(techniques.tip.analyst_manage_enabled)"}
    pm = getattr(eng, "position_manager", None)
    if pm is None:
        return None, {"error": "position manager not attached"}
    p = pm.get(str(pid))
    if p is None:
        return None, {"error": f"no open managed position {pid}"}
    if p.technique != "tip":
        return None, {"error": f"position {pid} belongs to technique "
                               f"'{p.technique}' — not yours to manage"}
    if p.status not in ("open", "attention"):
        return None, {"error": f"position {pid} is {p.status}"}
    pfm = eng.positions.portfolio(p.portfolio_id) or {}
    if pfm.get("book"):
        # ARM-GAPS D9: the shadow books are the scorecard's counterfactual —
        # managing them would corrupt the very record trust is judged on
        return None, {"error": f"position {pid} is a SHADOW-BOOK counterfactual "
                              f"({pfm.get('name')}) — never managed by hand"}
    return p, None


async def _run_tool(eng, name: str, args: dict, ctx: dict | None = None) -> dict:
    sym = str(args.get("symbol") or "").upper()
    if name == "get_positions":
        return _our_positions(eng, sym)
    if name == "search_messages":
        rows = await eng.signals_service.discord_search_messages(
            source=str(args.get("source") or "") or None,
            contains=str(args.get("contains") or "") or None,
            hours=float(args["hours"]) if args.get("hours") else None,
            limit=int(args.get("limit") or 20))
        slim = [{"at": (r.get("postedAt") or "")[:16], "source": r.get("source"),
                 "author": r.get("author"), "text": (r.get("text") or "")[:280],
                 **({"images": len(r.get("images") or []), "messageId": r.get("id")}
                    if r.get("images") else {})} for r in rows]
        return {"messages": slim} if slim else {"note": "no mirrored messages match "
                                                        "(is the intake running with the mirror?)"}
    if name == "view_image":
        got = await eng.signals_service.discord_media_bytes(
            str(args.get("message_id") or ""), int(args.get("index") or 0))
        if got is None:
            return {"error": "image unavailable — not in the mirror and the CDN link expired"}
        blob, media_type = got
        if len(blob) > 4 * 1024 * 1024:
            return {"error": f"image too large to view ({len(blob) // 1024} kB)"}
        import base64
        return {"_image_b64": base64.b64encode(blob).decode("ascii"),
                "_media_type": media_type,
                "note": f"image {args.get('index') or 0} of message "
                        f"{args.get('message_id')} ({len(blob) // 1024} kB)"}
    if name == "update_exit_plan":
        p, err = _manage_guard(eng, str(args.get("position_id") or ""))
        if err:
            return err
        reason = str(args.get("reason") or "").strip()
        if not reason:
            return {"error": "a reason is required — it is journaled"}
        from .lifecycle import policy_from_exit_plan
        plan = {"targets": args.get("exit_targets") or [],
                "fractions": args.get("exit_fractions") or [],
                "underlyingStop": args.get("underlying_stop"),
                "premiumStopPct": args.get("premium_stop_pct"),
                "maxHoldSessions": args.get("max_hold_sessions")
                or p.policy.get("time_stop_sessions") or 10,
                "avoidEarnings": bool(p.policy.get("flatten_before"))}
        policy = policy_from_exit_plan(plan, is_option=p.has_options, settings=eng.settings)
        # keep trims already done — the evaluator's state carries them; only the doc changes
        try:
            out = await eng.position_manager.set_policy(p.id, policy)
        except ValueError as exc:
            return {"error": f"plan rejected: {exc}"}
        from ... import events as ev
        await eng.journal.append(ev.TIP_EXIT_PLAN_UPDATED,
                                 {"positionId": p.id, "reason": reason, "policy": policy,
                                  "runId": (ctx or {}).get("run_id")},
                                 aggregate_type="position", aggregate_id=p.id,
                                 portfolio_id=p.portfolio_id)
        return {"updated": True, "positionId": p.id,
                "policy": {k: policy.get(k) for k in
                           ("stop", "ladder", "premium_stop_pct", "time_stop_sessions")},
                "note": "stops may only tighten; trims already taken stay taken"}
    if name == "close_position":
        p, err = _manage_guard(eng, str(args.get("position_id") or ""))
        if err:
            return err
        reason = str(args.get("reason") or "").strip()
        if not reason:
            return {"error": "a reason is required — it is journaled"}
        frac = float(args.get("fraction") or 1.0)
        frac = min(1.0, max(0.05, frac))
        out = await eng.position_manager.close(
            p.id, fraction=frac, reason=f"analyst: {reason}"[:200])
        return {"closed": True, "fraction": frac, "positionId": p.id,
                "result": ({k: out.get(k) for k in ("status", "realizedPnl")}
                           if isinstance(out, dict) else str(out)[:200])}
    if name == "disarm_plan":
        if not bool(eng.settings.get("techniques.tip.analyst_manage_enabled", True)):
            return {"error": "plan management by the analyst is disabled "
                             "(techniques.tip.analyst_manage_enabled)"}
        runner = getattr(eng, "tip_runner", None)
        if runner is None:
            return {"error": "tip runner not attached"}
        rid = str(args.get("run_id") or "")
        reason = str(args.get("reason") or "").strip()
        if not reason:
            return {"error": "a reason is required — it is journaled"}
        ap = runner.get(rid)
        if ap is None:
            return {"error": f"no live armed plan {rid} (already disarmed/expired?)"}
        if getattr(ap, "technique", "") != "tip":
            return {"error": f"plan {rid} belongs to technique "
                             f"'{getattr(ap, 'technique', '?')}' — not yours to disarm"}
        if any(t.remaining > 0 for t in ap.trades.values()):
            return {"error": "the plan holds a position — manage it with close_position / "
                             "update_exit_plan on the managed position, not a disarm"}
        ok = await runner.disarm(rid, reason=f"analyst: {reason}"[:200])
        return {"disarmed": bool(ok), "runId": rid, "symbol": ap.symbol}
    if name == "get_open_tips":
        return await _open_tips(eng, str(args.get("ticker") or ""),
                                str(args.get("source") or ""))
    if name == "save_note":
        ctx = ctx or {}
        kind = str(args.get("scope") or "general").lower()
        scope = {"ticker": f"ticker:{str(ctx.get('ticker') or '').upper()}",
                 "source": f"source:{ctx.get('source') or 'unknown'}",
                 "tip": f"signal:{ctx.get('signal_id') or ''}",
                 "rule": "rule",                       # the analyst's own rulebook
                 }.get(kind, "general")
        text = str(args.get("text") or "")
        if ctx.get("experiment"):
            # F12 hard-guard (batch b1, 2026-08-30): a HISTORICAL run must never
            # mutate live knowledge unsupervised — the prompt-only rule leaked 11
            # per-item recaps into `general`. Every save is quarantined under the
            # batch's scope; the batch review (or the human) promotes keepers.
            wanted = scope
            scope = f"experiment:{ctx['experiment']}"
            text = f"[wanted scope: {wanted}] {text}"
        note = await eng.signals_service.add_tip_note(
            scope, text,
            author=f"analyst:{str(ctx.get('run_id') or '')[:8]}",
            signal_id=ctx.get("signal_id"), run_id=ctx.get("run_id"))
        return {"saved": True, "scope": note["scope"], "id": note["id"]}
    if name == "get_quote":
        await eng.ensure_symbol(sym)
        q = eng.quotes.get(sym)
        if q is None:
            # cold symbol / closed market: nudge the feed once (same fix as
            # verification's AMZN case), then wait briefly for the sweep
            import contextlib as _ctx
            poll = (getattr(eng.feed, "poll_once", None)
                    or getattr(getattr(eng.feed, "yahoo", None), "poll_once", None))
            if poll is not None:
                with _ctx.suppress(Exception):
                    await poll()
                deadline = asyncio.get_event_loop().time() + 4.0
                while (eng.quotes.get(sym) is None
                       and asyncio.get_event_loop().time() < deadline):
                    await asyncio.sleep(0.25)
                q = eng.quotes.get(sym)
        if q is None:
            # still nothing (weekend, cold feed): the last session's close from
            # history — never leave the analyst priced blind (CRM skip,
            # run d7aedd08, 2026-08-29: SKIP purely for want of a print)
            try:
                from ...marketstructure.history import fetch_recent
                bars = await fetch_recent(sym, "1h", sessions=2)
                if bars:
                    return {"symbol": sym, "last": round(float(bars[-1].close), 4),
                            "stale": True,
                            "note": "no LIVE quote (market closed / cold feed) — this is "
                                    "the last session's close from history; fine for "
                                    "judging the idea, do not treat as a fillable price"}
            except Exception:
                log.debug("get_quote history fallback failed for %s", sym, exc_info=True)
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
        view = None
        if hasattr(flow, "analyst_view"):
            try:
                view = await flow.analyst_view(sym)
            except Exception:                       # evidence is best-effort
                log.debug("flow analyst_view failed for %s", sym, exc_info=True)
        if view is not None:
            return view
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


async def _source_history(eng, source: str | None, *, hours: float = 72,
                          limit: int = 20) -> str:
    """The source's recent mirrored messages, for the run header — follow-ups
    ('sold 40%') live here, not in the tip that triggered the run."""
    if not source:
        return "(no source)"
    try:
        rows = await eng.signals_service.discord_search_messages(
            source=source, hours=hours, limit=limit)
    except Exception:
        return "(mirror unavailable)"
    if not rows:
        return "(nothing mirrored yet — the intake mirrors watched channels while it runs)"
    return "\n".join(f"- [{(r.get('postedAt') or '')[:16]}] {r.get('author')}: "
                     f"{(r.get('text') or '').strip()[:220]}"
                     + (f" [images: {r.get('id')} — view_image to look]"
                        if r.get("images") else "")
                     for r in rows)


async def _rules_text(eng) -> tuple[str, int]:
    """The analyst's own rulebook (tip_notes scope 'rule'), oldest first so the
    rulebook reads in the order it was written; starter rules until one exists."""
    try:
        rules = await eng.signals_service.tip_notes(["rule"], limit=50)
    except Exception:
        rules = []
    if not rules:
        return STARTER_RULES, 0
    lines = "\n".join(f"- {n['text']} ({(n['createdAt'] or '')[:10]})"
                      for n in reversed(rules))
    return lines, len(rules)


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
            v = opinion.get("verdict")
            row.verdict = str(v)[:16] if v else None   # retro grades can be long
        if error is not None:
            row.error = error
        if status in ("done", "failed"):
            row.finished_at = _dt.datetime.now(_dt.timezone.utc)
        for k, v in fields.items():
            setattr(row, k, v)
        await session.commit()


async def run_agent_loop(eng, client, *, model: str, system: str, header: str,
                         rec: _Recorder, run_id: str, max_tools: int,
                         tool_ctx: dict, tools_used: list[dict]) -> str | None:
    """The shared tool loop: LLM turns with metered tool calls, every step
    streamed + persisted. Returns the final text (the JSON answer) or None."""
    messages: list = [{"role": "user", "content": header}]
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
            return think
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
                if "_image_b64" in out:
                    # the model SEES the image; the trace records only a stub
                    rec.step("tool_result", f"← {c.name}: {out.get('note') or 'image shown'}",
                             tool=c.name, result={"image": True, "note": out.get("note")})
                else:
                    rec.step("tool_result", f"← {c.name}: {json.dumps(out, default=str)[:500]}",
                             tool=c.name, result=out)
            if "_image_b64" in out:
                results.append({"type": "tool_result", "tool_use_id": c.id, "content": [
                    {"type": "image", "source": {"type": "base64",
                                                 "media_type": out["_media_type"],
                                                 "data": out["_image_b64"]}},
                    {"type": "text", "text": out.get("note") or "the image"}]})
            else:
                results.append({"type": "tool_result", "tool_use_id": c.id,
                                "content": json.dumps(out, default=str)[:6000]})
        messages.append({"role": "user", "content": results})
        await _persist_run(eng, run_id, status="running", rec=rec)   # progress visible
    return None


async def analyze_tip(eng, signal_row, verification: dict, policy, *,
                      client=None, parent_run_id: str | None = None,
                      experiment: str | None = None,
                      historical_note: str | None = None) -> dict | None:
    """Appraise one tip. Persists a full TipAnalystRun (trace + tools + opinion),
    streams the play-by-play live, and returns the opinion dict (stored on
    extraction.analyst) or None on failure — strictly advisory.
    `experiment`/`historical_note` (KNOWLEDGE plan Phase 2): an out-of-band
    historical appraisal — tagged on the run + opinion, with a prompt block
    warning that the live tools show TODAY's market, not the tip's."""
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
        **({"experiment": experiment} if experiment else {}),
    }
    tool_names = [t["name"] for t in TOOLS]
    run_id = new_id()
    async with eng.sf() as session:            # create the run row (visible immediately)
        session.add(TipAnalystRun(
            id=run_id, signal_id=getattr(signal_row, "id", None),
            parent_id=parent_run_id,
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
    rules_txt, rules_n = await _rules_text(eng)
    history_txt = await _source_history(eng, signal_row.source_name)

    rec.step("start", f"Appraising {signal_row.ticker} {signal_row.direction} "
             f"from {signal_row.source_name or 'unknown'}. Tools available: "
             f"{', '.join(tool_names)}."
             + (f" {len(notes)} shared note(s)" if notes else "")
             + (f" · {rules_n} own rule(s) handed to the run." if rules_n
                else " · starter rules (none saved yet)."),
             tip=tip, notes=notes, rules=rules_n,
             verification={k: verification.get(k) for k in ("passed", "park", "shadow_only")})

    header = (f"Today (ET): {dt.datetime.now(dt.timezone(dt.timedelta(hours=-4))):%Y-%m-%d %H:%M}\n"
              f"Per-tip budget: ${policy.budget_per_tip:,.0f} · option DTE window "
              f"{policy.dte_min}-{policy.dte_max} (tip's own contract may override)\n"
              f"TIP: {json.dumps(tip)}\n"
              f"VERIFICATION: {json.dumps({k: verification.get(k) for k in ('passed', 'park', 'shadow_only')})} "
              f"failed checks: {[c['name'] for c in verification.get('checks', []) if not c['passed']]}\n"
              f"YOUR TRADING RULES (self-maintained — follow them):\n{rules_txt}\n"
              f"SHARED NOTES (desk knowledge from earlier runs):\n{notes_txt}\n"
              f"THIS SOURCE'S LAST ~3 DAYS (their channel, mirrored, newest first — the "
              f"backstory this tip arrived in: earlier OPENs, trims, exits, mood. Read it "
              f"before judging; search_messages digs deeper/older):\n{history_txt}")
    if historical_note:
        header = historical_note + "\n\n" + header
    system = SYSTEM + json.dumps(AnalystOpinion.model_json_schema(), separators=(",", ":"))
    tools_used: list[dict] = []
    tool_ctx = {"ticker": signal_row.ticker, "source": signal_row.source_name,
                "signal_id": getattr(signal_row, "id", None), "run_id": run_id,
                "experiment": experiment}

    async def loop() -> AnalystOpinion | None:
        text = await run_agent_loop(
            eng, client, model=model, system=system, header=header, rec=rec,
            run_id=run_id, max_tools=max_tools, tool_ctx=tool_ctx,
            tools_used=tools_used)
        if text is None:
            return None
        try:
            return _parse_opinion(text)
        except ValueError as exc:
            # one cheap retry: an unparseable reply cost a whole appraisal (TSLA
            # 2026-08-31 — the run failed and auto-approve had to fail closed).
            # The overall TIMEOUT_S still bounds both attempts.
            rec.step("note", f"Reply had no parseable opinion ({exc}) — one retry, "
                             "JSON only.")
            text = await run_agent_loop(
                eng, client, model=model, system=system,
                header=header + "\n\nYour previous reply contained no JSON opinion "
                                "object. Reply with ONLY the JSON opinion object now.",
                rec=rec, run_id=run_id, max_tools=2, tool_ctx=tool_ctx,
                tools_used=tools_used)
            return _parse_opinion(text) if text is not None else None

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
              "runId": run_id, "at": dt.datetime.now(dt.timezone.utc).isoformat(),
              **({"experiment": experiment} if experiment else {})}
    exit_bits = []
    if opinion.exit_targets:
        fr = opinion.exit_fractions or []
        exit_bits.append("trims " + ", ".join(
            f"{int(round((fr[i] if i < len(fr) else 0) * 100))}% @ {t:g}"
            for i, t in enumerate(opinion.exit_targets)))
    if opinion.underlying_stop is not None:
        exit_bits.append(f"stop {opinion.underlying_stop:g}")
    if opinion.premium_stop_pct is not None:
        exit_bits.append(f"premium stop {opinion.premium_stop_pct:g}%")
    if opinion.max_hold_sessions is not None:
        exit_bits.append(f"time box {opinion.max_hold_sessions} sessions")
    rec.step("final", f"Verdict: {opinion.verdict.upper()}"
             + (f" — {opinion.contract_label or opinion.contract}" if opinion.contract else "")
             + (f" @ ≤{opinion.limit_price}" if opinion.limit_price else "")
             + (f" ×{opinion.quantity}" if opinion.quantity else "")
             + f". {opinion.rationale}"
             + (f" Exit plan: {'; '.join(exit_bits)}." if exit_bits else ""),
             opinion=result)
    await _persist_run(eng, run_id, status="done", rec=rec, opinion=result)
    if notes and experiment is None:
        # KNOWLEDGE B5: knowledge that participates in a completed LIVE
        # appraisal stays alive (historical batches must not refresh TTLs)
        import contextlib as _ctx
        with _ctx.suppress(Exception):
            await eng.signals_service.refresh_notes_cited([n["id"] for n in notes])
    return result


# --------------------------------------------------------------- intake runs
# One streamed run per processed message: the live play-by-play of extraction
# → per-signal verification → appraisal hand-offs — and, when a message
# extracts signals but none is tradable (a positions recap, an exit note),
# the analyst REVIEWS the update against the desk's own book instead of
# going silent (user, 2026-08-28: "refreshed page showed me nothing new").

class ReviewOpinion(BaseModel):
    headline: str = Field(description="One sentence: what this message told the desk")
    details: str = Field(default="", description="2-4 sentences: reconciliation vs our "
                                                 "positions/open tips; what changed")
    watch: list[str] = Field(default_factory=list,
                             description="Tickers worth watching after this update")
    missed_tip: Optional[str] = Field(
        default=None, description="If something in the message actually IS a fresh "
                                  "actionable trade that verification discarded, say "
                                  "which and why; else null")
    confidence: float = Field(default=0.5)


REVIEW_SYSTEM = """You are the tips-desk analyst. This message from a tip source \
extracted signals, but NONE became a tradable tip (a positions recap, an update on \
running trades, an exit note — the per-signal outcomes are attached). Your job is to \
make the update USEFUL instead of discarded:

- Reconcile it against the desk: call get_open_tips (this source) and get_positions to \
see what we hold or track that this message updates.
- save_note durable context the desk must remember: the source's open book, exits \
("expiring worthless", "trimmed"), hedge rationale, adds. Scope notes to the ticker or \
source. A few precise notes beat many vague ones.
- If any line is actually a FRESH actionable call that verification wrongly discarded \
(e.g. "Added Today"), say so in missed_tip with the exact ticker/contract — a human \
will decide.
- MANAGE what we hold: when the update moves the campaign on a position the desk holds \
("sold 40%", "stopped out", "letting it ride to 90"), act with update_exit_plan / \
close_position (EXIT-ONLY: they can trim, tighten or close — never add exposure). \
search_messages finds the original OPEN behind an update. Cite the message in the reason.
- IMAGES ARE NOT OPTIONAL: whenever the message or a history line is marked \
[images: <id>], ALWAYS view_image it — an "update" is often just a chart or a P&L \
screenshot, and the substance lives in the picture.
- Never open NEW exposure here; entries only ever come from a verified tip's proposal.

Use at most a few tool calls (metered). Then reply with ONLY one JSON object matching \
this schema — no prose, no markdown fences:
"""


class IntakeRun:
    """Lifecycle of one message's intake run (kind='intake'). Fail-open: every
    method swallows its own errors so intake visibility never breaks intake."""

    def __init__(self, eng):
        self.eng = eng
        self.id: str | None = None
        self.rec: _Recorder | None = None

    async def start(self, *, source: str, chars: int, has_image: bool,
                    preview: str = "", experiment: str | None = None) -> None:
        from ...domain import new_id
        from ...models import TipAnalystRun
        try:
            self.id = new_id()
            async with self.eng.sf() as session:
                session.add(TipAnalystRun(
                    id=self.id, signal_id=None, ticker="message", source=source,
                    status="running", kind="intake", model=None,
                    tools=[t["name"] for t in TOOLS],
                    tip={"chars": chars, "hasImage": has_image,
                         "preview": preview[:400],
                         # batch tag → the runs list can hide out-of-band runs
                         **({"experiment": experiment} if experiment else {})}))
                await session.commit()
            self.rec = _Recorder(self.eng, self.id)
            self.rec.step("start", f"Message from {source or 'unknown'} — {chars} chars"
                          + (" + image" if has_image else "")
                          + ". Extraction → verification → appraisal, live.",
                          preview=preview[:400])
        except Exception:
            log.exception("intake run start failed")
            self.id, self.rec = None, None

    def step(self, kind: str, text: str, **extra) -> None:
        if self.rec is not None:
            try:
                self.rec.step(kind, text, **extra)
            except Exception:
                pass

    async def checkpoint(self, **fields) -> None:
        if self.id and self.rec:
            try:
                await _persist_run(self.eng, self.id, status="running", rec=self.rec,
                                   **fields)
            except Exception:
                pass

    async def finish(self, verdict: str, text: str, *, failed: bool = False,
                     opinion: dict | None = None) -> None:
        if not self.id or not self.rec:
            return
        try:
            self.step("final", text, opinion=opinion or {"verdict": verdict,
                                                         "rationale": text})
            await _persist_run(self.eng, self.id,
                               status="failed" if failed else "done", rec=self.rec,
                               opinion=opinion or {}, verdict=verdict[:16],
                               error=text[:500] if failed else None)
        except Exception:
            log.exception("intake run finish failed")

    async def review(self, *, source: str, message_text: str, outcomes: list[dict],
                     client=None) -> dict | None:
        """The analyst reviews a non-tradable update in THIS run. Advisory,
        fail-open; returns the review dict or None."""
        eng = self.eng
        if not self.id or not self.rec:
            return None
        s = eng.settings
        if not bool(s.get("techniques.tip.review_enabled", True)):
            self.step("note", "Review disabled (techniques.tip.review_enabled).")
            return None
        api_key = getattr(eng.config, "anthropic_api_key", "")
        if client is None and not api_key:
            return None
        if client is None:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=api_key)
        model = str(s.get("techniques.tip.analyst_model") or "") or eng.config.extraction_model
        max_tools = int(s.get("techniques.tip.analyst_max_tools", 8))
        notes_txt = "(none yet)"
        try:
            notes = await eng.signals_service.notes_for_tip(
                None, source, limit=int(s.get("techniques.tip.analyst_notes_max", 12)))
            if notes:
                notes_txt = "\n".join(
                    f"- [{n['scope']}] {n['text']} ({(n['createdAt'] or '')[:10]})"
                    for n in notes)
        except Exception:
            pass
        self.step("note", "Nothing tradable — reviewing the update against the desk's "
                          "own book (positions, open tips, notes).")
        rules_txt, _rules_n = await _rules_text(eng)
        history_txt = await _source_history(eng, source)
        header = (f"Today (ET): {dt.datetime.now(dt.timezone(dt.timedelta(hours=-4))):%Y-%m-%d %H:%M}\n"
                  f"SOURCE: {source}\n"
                  f"MESSAGE:\n{message_text[:4000]}\n\n"
                  f"PER-SIGNAL OUTCOMES: {json.dumps(outcomes, default=str)[:2500]}\n"
                  f"YOUR TRADING RULES (self-maintained):\n{rules_txt}\n"
                  f"SHARED NOTES (desk knowledge):\n{notes_txt}\n"
                  f"RECENT MESSAGES FROM THIS SOURCE (mirror, newest first):\n{history_txt}")
        system = REVIEW_SYSTEM + json.dumps(ReviewOpinion.model_json_schema(),
                                            separators=(",", ":"))
        tools_used: list[dict] = []
        tool_ctx = {"ticker": (outcomes[0].get("ticker") if outcomes else ""),
                    "source": source, "signal_id": None, "run_id": self.id}
        try:
            text = await asyncio.wait_for(run_agent_loop(
                eng, client, model=model, system=system, header=header,
                rec=self.rec, run_id=self.id, max_tools=max_tools,
                tool_ctx=tool_ctx, tools_used=tools_used), timeout=TIMEOUT_S)
            if text is None:
                raise ValueError("no review produced (loop exhausted)")
            op = ReviewOpinion.model_validate_json(
                text[text.find("{"):text.rfind("}") + 1])
        except Exception as exc:
            log.warning("intake review failed: %s", exc)
            self.step("error", f"Review failed: {exc}")
            await self.finish("review", f"Review failed: {exc}", failed=True)
            return None
        result = {"verdict": "review", "rationale": op.headline
                  + (f" {op.details}" if op.details else ""),
                  "watch": op.watch, "missedTip": op.missed_tip,
                  "confidence": op.confidence, "model": model,
                  "toolsUsed": tools_used}
        await self.finish("review", f"Review: {op.headline}"
                          + (f" Watch: {', '.join(op.watch)}." if op.watch else "")
                          + (f" POSSIBLE MISSED TIP: {op.missed_tip}" if op.missed_tip else ""),
                          opinion=result)
        return result
