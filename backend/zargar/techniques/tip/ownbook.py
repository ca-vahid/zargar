"""MK own-book classification — the shadow-first workflow (KFIN-08, 2026-09-14).

Meet Kevin (and any source that narrates its OWN trading rather than calling
trades for the reader) posts five kinds of first-person content that the tip
pipeline used to treat alike — "I bought" was recognised as actionable and
could reach a proposal:

  own_open      "I added $50k of NVDA at 118"          → the OWN-BOOK shadow ledger ONLY
  own_exit      "sold half my NVDA today"              → reduces an own-book position; never opens
  recap         "bought NVDA at 95 last year, up 40%"  → recorded as context; never opens
  hypothetical  "if it dips I'd buy more"              → recorded as context; never opens
  third_party   "a member sent me his TSLA position"   → recorded as context; never opens
  tip           anything else (a call to the reader)   → the normal pipeline, untouched

Reviewer conditions (TRADING-RULES 2026-09-11, packet KFIN-08):
  * source identity is explicit — only sources enrolled in
    `techniques.tip.mk_ownbook_sources` are classified; nobody else's pipeline changes;
  * every price/contract grounding requirement is kept — a self-disclosed buy
    without a grounded price (shares) or contract (strike + expiry) stays
    UNRESOLVED, journaled, and is never a proposal;
  * own-book activity trades in a DEDICATED shadow book (`Portfolio.kind ==
    "shadow"`, `book == "ownbook"`) — never the Practice book, never a proposal,
    never an armed plan; `techniques.tip.allow_live_auto` and every Practice /
    live gate are not consulted because that path is never entered;
  * grading uses EXECUTABLE evidence (a qualified quote at the decision, the
    fill our own book got) and a DECLARED cohort (`techniques.tip.mk_ownbook_cohort`)
    — entries booked under no cohort never grade;
  * promotion criteria are predefined knobs (`techniques.tip.mk_ownbook_min_*`),
    all inert; meeting them is reported, never acted on — a human makes the
    promotion verdict on the evidence, with no calendar deadline.

Deterministic text rules come first; the extraction schema's `actor` /
`activity` fields fill in only when the text is silent. Where the two disagree
the text wins and the disagreement is recorded on the signal.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import re
import time as _time

log = logging.getLogger("zargar.tip.ownbook")

BOOK = "ownbook"
MODES = ("off", "observe", "shadow")
CLASSES = ("own_open", "own_exit", "recap", "hypothetical", "third_party", "tip")
CONTEXT_CLASSES = ("recap", "hypothetical", "third_party")
STATUS_BOOKED = "ownbook"                 # resolved own activity, booked in the own-book ledger
STATUS_UNRESOLVED = "ownbook_unresolved"  # own activity whose evidence is missing/ambiguous
STATUS_CONTEXT = "ownbook_context"        # recap / hypothetical / third-party / exit with nothing to reduce
STATUSES = (STATUS_BOOKED, STATUS_UNRESOLVED, STATUS_CONTEXT)

# --- deterministic text rules (case-insensitive) ---------------------------------
_FRESH = re.compile(
    r"\b(just|today|this morning|this afternoon|right now|now|moments ago|minutes ago|"
    r"a few minutes ago|at the open|after the close|premarket|pre-market)\b", re.I)

_THIRD_PARTY = [re.compile(p, re.I) for p in (
    r"\b(someone|somebody|a (member|subscriber|viewer|follower|friend|buddy|guy)|"
    r"my (friend|buddy|brother|sister|dad|mom|wife|husband|cousin|client)|"
    r"this (guy|person|trader|dude)|his|her|their|another trader'?s?)\s+"
    r"(account|position|positions|portfolio|trade|trades|screenshot|entry|entries|fill|fills|buy|buys|calls|puts)\b",
    r"\bnot (my|mine)\b",
    r"\bsent me (this|a screenshot|their|his|her)\b",
    r"\bscreenshot (from|of) (a |an |some |someone|somebody|@)",
    r"\b@\w+'?s\s+(position|account|trade|entry|portfolio|fill|calls|puts)\b",
    r"\b(someone|somebody|a (member|subscriber|viewer|follower)|my (friend|buddy)) (bought|added|sold|is (in|long|short))\b",
)]

_HYPOTHETICAL = [re.compile(p, re.I) for p in (
    r"\bif\b[^.!?\n]{0,80}\b(i'?d|i would|i'?ll|i might|i may|i could|we'?d|we would|we might|we'?ll)\b",
    r"\b(i'?d|i would|we'?d|we would)\s+(probably |likely |definitely |maybe |be )?"
    r"(buy|add|sell|trim|load|grab|pick up|consider|look at|buying|adding)\b",
    r"\b(i'?m|i am|we'?re|we are)\s+(thinking about|considering|tempted to|looking to|looking at|"
    r"planning to|planning on|eyeing|waiting (for|to))\b",
    r"\b(might|may|could)\s+(buy|add|sell|trim|pick up|grab|load)\b",
    r"\bwould consider\b",
    r"\bon my (watch ?list|radar)\b",
    r"\b(haven'?t|have not|not yet|didn'?t) (bought|buy|added|add|pulled the trigger)\b",
)]

_OWN_EXIT = [re.compile(p, re.I) for p in (
    r"\b(i|we)('ve| have|'m| am)?\s*(just |also |fully |completely |partially |finally )?"
    r"(sold|trimmed|closed|exited|dumped|cut|unloaded|liquidated|reduced|"
    r"got out of|took profits? (on|in)|took some off|scaled out of|lightened up on)\b",
    r"\b(i'?m|i am|we'?re|we are)\s+(fully |completely |all )?out( of)?\b",
    r"\bsold\s+(half|all|some|most|everything|a (third|quarter|portion|piece)|\d+ ?%|the rest|"
    r"my|our|the position|out of)\b",
    r"\btrimmed\b",
    r"\bclosed (out |my |our |the )",
    r"\btook (profits?|gains|the (profit|gain|loss)|some off)\b",
)]

_OWN_OPEN = [re.compile(p, re.I) for p in (
    r"\b(i|we)('ve| have|'m| am)?\s*(just |also |finally )?"
    r"(bought|buying|added|adding|picked up|grabbed|grabbing|loaded( up)?( on)?|scooped( up)?|"
    r"opened|entered|initiated|shorted|took a starter|got a starter|started a position|went long|am long)\b",
    r"\b(bought|added|picked up|grabbed|loaded)\s+(more|some|another|a (starter|position|little|few)|\$|\d)",
    # subject-less past tense at the start of the text ("Bought TSLA 300c 10/17 for
    # 12.40 today") — on an enrolled own-book source that is the author's own fill
    r"^\s*(just |also |finally )?(bought|added|picked up|grabbed|loaded( up)?( on)?|scooped( up)?)\b",
    r"\badded (to )?(my|our)\b",
    r"\b(my|our) (buy|add|entry|starter|fill)s? (on|in|of|at)\b",
    r"\b(starter|full) position\b",
    r"\bi'?m (long|in)\b",
    r"\bfilled (on|at|for)\b",
)]

_RECAP = [re.compile(p, re.I) for p in (
    r"\blast (week|month|year|quarter|summer|fall|winter|spring|time)\b",
    r"\bback in\b",
    r"\bin (january|february|march|april|may|june|july|august|september|october|november|december|20\d\d)\b",
    r"\bsince (i|we) (bought|added|entered|got in)\b",
    r"\b(still|been) holding\b",
    r"\b(held|holding) (it |them )?(since|for)\b",
    r"\b(up|down)\s+\$?\d+(\.\d+)?\s?%",
    r"\b\d+(\.\d+)?%\s+(gain|return|profit|loss|winner|loser)",
    r"\b(portfolio|position|account|book) (is|was|ended|finished|closed) (up|down|flat)\b",
    r"\brecap\b", r"\breview of\b", r"\bscorecard\b",
    r"\bhow (i|we|it) (did|went|played out)\b",
    r"\b(year|month|week|quarter)[- ]to[- ]date\b", r"\bytd\b",
    r"\bperformance\b", r"\btrack record\b",
    r"\b(paid off|played out|worked out|didn'?t work)\b",
    r"\b(that|this) (trade|call|play) (was|is) (a )?(winner|loser)\b",
)]

_EXIT_FRACTION = [                # a STATED fraction beats the whole-position words:
    (re.compile(r"\b(\d{1,3})\s?%", re.I), None),   # "sold half, holding the rest" is a half
    (re.compile(r"\bhalf\b", re.I), 0.5),
    (re.compile(r"\b(a |one )?third\b", re.I), 1 / 3),
    (re.compile(r"\b(a |one )?quarter\b", re.I), 0.25),
    (re.compile(r"\b(all|everything|the rest|the whole|fully|completely|entire|out of)\b", re.I), 1.0),
    (re.compile(r"\b(i'?m|i am|we'?re|we are)\s+out\b", re.I), 1.0),
    (re.compile(r"\bclosed\b", re.I), 1.0),
]


def _hits(pats, text: str) -> list[str]:
    return [p.pattern for p in pats if p.search(text)]


def _decide(text: str) -> tuple[str | None, list[str]]:
    """Precedence on one piece of text. Recap beats an own action unless a
    FRESH marker says the action is today's ('I bought NVDA today, up 3%
    already' is an open; 'I bought NVDA at 95 last year' is a recap)."""
    if not text.strip():
        return None, []
    tp = _hits(_THIRD_PARTY, text)
    if tp:
        return "third_party", tp
    hyp = _hits(_HYPOTHETICAL, text)
    if hyp:
        return "hypothetical", hyp
    recap = _hits(_RECAP, text)
    fresh = bool(_FRESH.search(text))
    if recap and not fresh:
        return "recap", recap
    ex = _hits(_OWN_EXIT, text)
    if ex:
        return "own_exit", ex
    op = _hits(_OWN_OPEN, text)
    if op:
        return "own_open", op
    if recap:
        return "recap", recap
    return None, []


def classify(sig, source_text: str, *, result=None) -> dict:
    """Pure classification of one extracted signal against its message.

    Order of authority: the signal's own evidence quotes (the grounded
    per-signal snippet), then the whole message, then the extraction schema's
    `actor`/`activity` fields. Returns the class plus the basis and every
    matched rule so the record explains itself."""
    snippet = " \n ".join(q for q in (sig.evidence_quotes or []) if q)
    cls, matched = _decide(snippet)
    basis = "evidence_quotes"
    if cls is None:
        cls, matched = _decide(source_text or "")
        basis = "message"
    actor = str(getattr(sig, "actor", "unknown") or "unknown")
    activity = str(getattr(sig, "activity", "unspecified") or "unspecified")
    ext_cls: str | None = None
    if actor == "third_party":
        ext_cls = "third_party"
    elif activity == "hypothetical":
        ext_cls = "hypothetical"
    elif activity == "recap":
        ext_cls = "recap"
    elif activity == "own_trade":
        ext_cls = "own_exit" if sig.action in ("trim", "close") else "own_open"
    if cls is None:
        cls, basis = (ext_cls, "extraction") if ext_cls else ("tip", "none")
    # the extractor's action verb refines a text-level "own" read: "I'm in,
    # sold half" style messages carry the action in the schema too
    if cls == "own_open" and sig.action in ("trim", "close"):
        cls = "own_exit"
    if cls == "own_open" and sig.action == "update_stop":
        cls = "recap"       # a stop move on an existing holding never opens
    return {
        "class": cls,
        "basis": basis,
        "matched": matched[:6],
        "extraction": {"actor": actor, "activity": activity, "class": ext_cls},
        "agreement": (None if ext_cls is None or basis == "extraction" else ext_cls == cls),
    }


# --- settings -----------------------------------------------------------------------
def mode(settings) -> str:
    m = str(settings.get("techniques.tip.mk_ownbook_mode") or "off").strip().lower()
    return m if m in MODES else "off"


def enrolled(settings, source: str | None) -> bool:
    """Only explicitly enrolled sources are classified; `off` enrolls nobody."""
    if mode(settings) == "off" or not source:
        return False
    names = settings.get("techniques.tip.mk_ownbook_sources") or []
    if isinstance(names, str):
        names = [n for n in re.split(r"[,\n]", names)]
    key = source.strip().lower()
    return any(str(n or "").strip().lower() == key for n in names)


def declared_cohort(settings) -> str:
    return str(settings.get("techniques.tip.mk_ownbook_cohort") or "").strip()


# --- resolution: does the disclosure carry executable evidence? --------------------
def qualified_quote(quote, *, max_age_s: float, now_ms: int | None = None) -> tuple[dict | None, str | None]:
    """A quote that could actually have been executed at the decision: warm,
    not halted, a real two-sided book, fresh. Returns (evidence, reason)."""
    if quote is None or float(getattr(quote, "last", 0) or 0) <= 0:
        return None, "no market data at the decision"
    if getattr(quote, "halted", False):
        return None, "instrument halted at the decision"
    bid, ask = float(quote.bid or 0), float(quote.ask or 0)
    if bid <= 0 or ask <= 0 or ask < bid:
        return None, "no two-sided quote at the decision"
    now = now_ms if now_ms is not None else int(_time.time() * 1000)
    age = max(0.0, (now - int(quote.ts or now)) / 1000.0)
    ev = {"symbol": quote.symbol, "last": float(quote.last), "bid": bid, "ask": ask,
          "ts": int(quote.ts or 0), "ageSeconds": round(age, 1),
          "spreadPct": round((ask - bid) / ((ask + bid) / 2) * 100, 3) if ask + bid > 0 else None}
    if age > max_age_s:
        return ev, f"quote {age:.0f}s old at the decision (max {max_age_s:.0f}s)"
    return ev, None


def resolve(ob: dict, sig, *, grounding: dict, quote, settings,
            stale: bool, age_hours: float | None, now_ms: int | None = None) -> dict:
    """Attach the evidence verdict to a classified signal. Only own activity
    resolves/unresolves; context classes are 'noop' by construction."""
    cls = ob["class"]
    ob = {**ob, "cohort": declared_cohort(settings), "reasons": [], "evidence": {}}
    checks = (grounding or {}).get("checks") or {}
    if cls in CONTEXT_CLASSES:
        ob["resolution"] = "noop"
        return ob
    reasons: list[str] = []
    if not checks.get("ticker_evidenced", False) or not checks.get("quotes_found", False):
        reasons.append("ticker / evidence quotes not found in the source text")
    is_option = sig.instrument in ("call", "put")
    if cls == "own_open":
        if is_option:
            if not sig.strike or not checks.get("strike_evidenced", False):
                reasons.append("option disclosure without a grounded strike")
            if not sig.expiry and not sig.dte_hint_days:
                reasons.append("option disclosure without an expiry")
        else:
            if sig.direction == "short":
                reasons.append("short share disclosure — never expressed (no share shorting)")
            if not sig.entry_price or not checks.get("entry_evidenced", False):
                reasons.append("share disclosure without a grounded entry price")
        if stale:
            reasons.append(f"content is ~{(age_hours or 0):.0f}h old — no qualified quote existed "
                           "at the decision; nothing is back-filled")
    max_age = float(settings.get("techniques.tip.mk_ownbook_quote_max_age_seconds", 120) or 120)
    q_ev, q_reason = qualified_quote(quote, max_age_s=max_age, now_ms=now_ms)
    if q_ev is not None:
        ob["evidence"]["quote"] = q_ev
    if q_reason and cls == "own_open":
        reasons.append(q_reason)
    ob["evidence"]["grounding"] = checks
    ob["evidence"]["stated"] = {"entryPrice": sig.entry_price, "premium": sig.premium,
                                "strike": sig.strike, "expiry": sig.expiry,
                                "instrument": sig.instrument}
    ob["reasons"] = reasons
    ob["resolution"] = "unresolved" if reasons else "resolved"
    return ob


def exit_fraction(text: str) -> float | None:
    """'sold half' → 0.5, 'out'/'closed' → 1.0, '40%' → 0.4; None when the
    message does not say how much (ambiguous stays unresolved)."""
    for pat, value in _EXIT_FRACTION:
        m = pat.search(text or "")
        if not m:
            continue
        if value is None:
            try:
                pct = float(m.group(1))
            except (TypeError, ValueError):
                continue
            if 0 < pct <= 100:
                return pct / 100.0
            continue
        return float(value)
    return None


def status_for(ob: dict) -> str:
    if ob.get("booked"):
        return STATUS_BOOKED
    if ob.get("class") in CONTEXT_CLASSES or ob.get("resolution") == "noop":
        return STATUS_CONTEXT
    return STATUS_UNRESOLVED


# --- the ledger: booking in the dedicated shadow book ----------------------------
def _underlying_of(symbol: str) -> str:
    from ...options import occ
    parsed = occ.parse(symbol)
    return (parsed.underlying if parsed else symbol).upper()


async def book(svc, row, sig, ob: dict, *, source_text: str = "") -> dict:
    """Express a RESOLVED own_open / own_exit in the own-book shadow book.
    Every order goes through OrderManager.place() (RiskGate inside) on a
    portfolio of kind 'shadow', book 'ownbook' — never anything else. A
    booking failure turns the entry UNRESOLVED with the reason on the record;
    an exit with nothing to reduce is a noop."""
    from ...orders import OrderIntent

    eng = svc.engine
    source = row.source_name or "unknown"
    cls = ob["class"]
    if cls not in ("own_open", "own_exit"):
        return ob
    cohort_tag = f"cohort:{ob.get('cohort')}" if ob.get("cohort") else "cohort:undeclared"
    tags = [f"source:{source}", "ownbook", cohort_tag]

    if cls == "own_exit":
        frac = exit_fraction(" ".join(sig.evidence_quotes or []) + " " + (source_text or ""))
        shadow = await svc.shadow_portfolio(source, BOOK)
        held = [p for p in eng.positions.positions_list(shadow["id"])
                if p.get("qty", 0) > 0 and _underlying_of(p["symbol"]) == row.ticker.upper()]
        if not held:
            ob["resolution"] = "noop"
            ob["reasons"] = ["no own-book position to reduce — recorded, nothing opened"]
            return ob
        if frac is None:
            ob["resolution"] = "unresolved"
            ob["reasons"] = ["exit size ambiguous (no 'half' / 'all' / N%) — nothing reduced"]
            return ob
        booked = []
        for pos in held:
            qty = int(pos["qty"]) if frac >= 0.999 else max(1, int(math.floor(pos["qty"] * frac)))
            placed = await eng.orders.place(OrderIntent(
                portfolio_id=shadow["id"], symbol=pos["symbol"],
                sec_type=pos.get("secType") or "STK", side="SELL", qty=qty,
                order_type="MKT", reduce_only=True, source="auto",
                signal_id=row.id, technique_id="tip", tags=tags))
            booked.append({"orderId": (placed or {}).get("id"), "symbol": pos["symbol"],
                           "qty": qty, "status": (placed or {}).get("status"),
                           "fraction": round(frac, 4)})
        ob["booked"] = {"portfolioId": shadow["id"], "side": "SELL", "orders": booked}
        ob["resolution"] = "resolved"
        return ob

    # own_open
    if ob.get("resolution") != "resolved":
        return ob
    shadow = await svc.shadow_portfolio(source, BOOK)
    budget = float(eng.settings.get("techniques.tip.mk_ownbook_budget", 1000.0) or 1000.0)
    quote_ev = (ob.get("evidence") or {}).get("quote") or {}
    if sig.instrument in ("call", "put"):
        from .express import pick_tip_contract
        pick = await pick_tip_contract(
            eng, symbol=row.ticker.upper(), direction=sig.direction,
            dte_min=0, dte_max=3650, strike=row.strike, expiry=row.expiry,
            stated_min_dte=int(eng.settings.get("techniques.tip.entry_cutoff_dte", 2)),
            allow_0dte=False)
        if pick.get("available") and pick.get("symbol") and getattr(eng, "options", None) is not None:
            try:
                await eng.options.reprice(pick)
            except Exception:
                log.debug("own-book reprice failed", exc_info=True)
        ask = float(pick.get("ask") or pick.get("mid") or 0) if pick.get("available") else 0.0
        if not (pick.get("available") and pick.get("symbol") and ask > 0):
            ob["resolution"] = "unresolved"
            ob["reasons"] = [f"stated contract not quotable: {pick.get('error') or 'no ask'}"]
            return ob
        from ...execution.sizing import size_by_budget
        contracts = max(1, size_by_budget(budget, ask, max_units=1_000, multiplier=100.0))
        occ_sym = str(pick["symbol"])
        await eng.ensure_symbol(occ_sym)
        placed = await eng.orders.place(OrderIntent(
            portfolio_id=shadow["id"], symbol=occ_sym, sec_type="OPT", side="BUY",
            qty=contracts, order_type="MKT", source="auto", signal_id=row.id,
            technique_id="tip", tags=tags))
        vehicle = {"vehicle": "option", "symbol": occ_sym, "display": pick.get("display"),
                   "ask": ask, "qty": contracts}
    else:
        ask = float(quote_ev.get("ask") or 0)
        if ask <= 0:
            ob["resolution"] = "unresolved"
            ob["reasons"] = ["no executable ask at the decision"]
            return ob
        qty = max(1, int(math.floor(budget / ask)))
        placed = await eng.orders.place(OrderIntent(
            portfolio_id=shadow["id"], symbol=row.ticker.upper(), side="BUY", qty=qty,
            order_type="MKT", source="auto", signal_id=row.id,
            technique_id="tip", tags=tags))
        vehicle = {"vehicle": "shares", "symbol": row.ticker.upper(), "ask": ask, "qty": qty}
    status = (placed or {}).get("status")
    if not placed or status in ("REJECTED", "REJECTED_RISK", "ERROR"):
        ob["resolution"] = "unresolved"
        ob["reasons"] = [f"own-book order not accepted: {status or 'no order'} "
                         f"{(placed or {}).get('rejectReason') or ''}".strip()]
        return ob
    ob["booked"] = {"portfolioId": shadow["id"], "side": "BUY", "orderId": placed.get("id"),
                    "status": status, "budget": budget, **vehicle}
    return ob


# --- the read: ledger + grading against the predefined criteria ------------------
def criteria(settings) -> dict:
    return {
        "cohort": declared_cohort(settings),
        "minAgeSessions": int(settings.get("techniques.tip.mk_ownbook_min_age_sessions", 5) or 0),
        "minGraded": int(settings.get("techniques.tip.mk_ownbook_min_graded", 20) or 0),
        "minHitRate": float(settings.get("techniques.tip.mk_ownbook_min_hit", 0.55) or 0),
        "minAvgReturnPct": float(settings.get("techniques.tip.mk_ownbook_min_avg_return_pct", 0.0) or 0),
        "maxUnresolvedPct": float(settings.get("techniques.tip.mk_ownbook_max_unresolved_pct", 25.0) or 0),
    }


async def ledger(svc, source: str, *, today: dt.date | None = None) -> dict:
    """Everything the own-book workflow recorded for one source, graded on
    executable evidence inside the DECLARED cohort. The verdict line is a
    report, not a decision — nothing in the app reads it back."""
    from sqlalchemy import select

    from ...models import Execution, Signal
    from .horizon import sessions_between

    eng = svc.engine
    settings = eng.settings
    crit = criteria(settings)
    today = today or dt.datetime.now(dt.timezone.utc).date()
    async with eng.sf() as session:
        rows = (await session.execute(
            select(Signal).where(Signal.source_name == source,
                                 Signal.status.in_(STATUSES))
            .order_by(Signal.created_at.asc()))).scalars().all()
    book_pf = next((p for p in eng.positions.portfolios()
                    if p.get("kind") == "shadow" and p.get("book") == BOOK
                    and p.get("sourceName") == source), None)
    first_fill: dict[str, dt.date] = {}
    if book_pf is not None:
        async with eng.sf() as session:
            execs = (await session.execute(
                select(Execution).where(Execution.portfolio_id == book_pf["id"])
                .order_by(Execution.ts.asc()))).scalars().all()
        for e in execs:
            if e.side == "BUY" and e.symbol not in first_fill and e.ts:
                first_fill[e.symbol] = e.ts.date()
    positions = {p["symbol"]: p for p in
                 (eng.positions.positions_list(book_pf["id"]) if book_pf else [])}

    entries, counts = [], {c: 0 for c in CLASSES}
    graded = hits = 0
    returns: list[float] = []
    own_total = unresolved = 0
    for r in rows:
        ob = (r.extraction or {}).get("ownbook") or {}
        cls = ob.get("class") or "tip"
        counts[cls] = counts.get(cls, 0) + 1
        entry = {"signalId": r.id, "ticker": r.ticker, "class": cls, "status": r.status,
                 "resolution": ob.get("resolution"), "reasons": ob.get("reasons") or [],
                 "cohort": ob.get("cohort") or None, "basis": ob.get("basis"),
                 "quoteAtDecision": (ob.get("evidence") or {}).get("quote"),
                 "stated": (ob.get("evidence") or {}).get("stated"),
                 "booked": ob.get("booked"),
                 "createdAt": r.created_at.isoformat() if r.created_at else None,
                 "graded": False}
        if cls in ("own_open", "own_exit"):
            own_total += 1
            if r.status == STATUS_UNRESOLVED:
                unresolved += 1
        booked = ob.get("booked") or {}
        if (cls == "own_open" and booked and entry["quoteAtDecision"]
                and entry["cohort"] and entry["cohort"] == crit["cohort"]):
            sym = booked.get("symbol")
            pos = positions.get(sym) or {}
            filled = first_fill.get(sym)
            aged = sessions_between(filled, today) if filled else 0
            closed = bool(pos) and abs(float(pos.get("qty") or 0)) < 1e-9
            if filled and (closed or aged >= crit["minAgeSessions"]):
                if closed:
                    cost = float(pos.get("avgCost") or 0) or 1.0
                    ret = float(pos.get("realizedPnl") or 0) / (cost * float(booked.get("qty") or 1)
                                                               * (100.0 if booked.get("vehicle") == "option" else 1.0)) * 100
                else:
                    ret = float(pos.get("unrealizedPnlPct") or 0)
                entry.update({"graded": True, "agedSessions": aged, "closed": closed,
                              "returnPct": round(ret, 2)})
                graded += 1
                hits += 1 if ret > 0 else 0
                returns.append(ret)
            else:
                entry["agedSessions"] = aged
                entry["gradeNote"] = ("not filled yet" if not filled else
                                      f"aged {aged}/{crit['minAgeSessions']} sessions")
        elif cls == "own_open" and booked and not entry["cohort"]:
            entry["gradeNote"] = "booked under no declared cohort — never grades"
        elif cls == "own_open" and booked and entry["cohort"] != crit["cohort"]:
            entry["gradeNote"] = f"cohort {entry['cohort']!r} is not the declared {crit['cohort']!r}"
        entries.append(entry)

    hit_rate = (hits / graded) if graded else None
    avg_ret = (sum(returns) / len(returns)) if returns else None
    unresolved_pct = (unresolved / own_total * 100) if own_total else None
    checks = {
        "graded": {"actual": graded, "need": crit["minGraded"], "met": graded >= crit["minGraded"]},
        "hitRate": {"actual": hit_rate, "need": crit["minHitRate"],
                    "met": hit_rate is not None and hit_rate >= crit["minHitRate"]},
        "avgReturnPct": {"actual": avg_ret, "need": crit["minAvgReturnPct"],
                         "met": avg_ret is not None and avg_ret >= crit["minAvgReturnPct"]},
        "unresolvedPct": {"actual": unresolved_pct, "need": crit["maxUnresolvedPct"],
                          "met": unresolved_pct is not None and unresolved_pct <= crit["maxUnresolvedPct"]},
        "cohortDeclared": {"actual": crit["cohort"] or None, "met": bool(crit["cohort"])},
    }
    equity = None
    if book_pf is not None:
        try:
            equity = await eng.positions.equity(book_pf["id"])
        except Exception:
            equity = None
    return {
        "source": source,
        "mode": mode(settings),
        "enrolled": enrolled(settings, source),
        "book": ({"portfolioId": book_pf["id"], "kind": book_pf.get("kind"), "book": BOOK,
                  "equity": equity, "startingCash": book_pf.get("startingCash"),
                  "positions": list(positions.values())} if book_pf else None),
        "counts": counts,
        "entries": entries,
        "grading": {"cohort": crit["cohort"] or None, "graded": graded, "hits": hits,
                    "hitRate": hit_rate, "avgReturnPct": avg_ret,
                    "ownActivity": own_total, "unresolved": unresolved,
                    "unresolvedPct": unresolved_pct},
        "promotion": {
            "criteria": crit, "checks": checks,
            "allMet": all(c["met"] for c in checks.values()),
            "verdict": "human",
            "note": ("Promotion is a separate evidence-based verdict a person makes on this "
                     "record; nothing in the app acts on these criteria and there is no "
                     "calendar deadline. Own-book text never reaches Practice."),
        },
    }
