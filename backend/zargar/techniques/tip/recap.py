"""INTRA-03 (2026-09-16): a CHEAP, deterministic content-type read of a multi-signal message
BEFORE the paid appraisal - so a confirmed map / recap / holdings digest can be routed to a
compact appraisal context, while management instructions and anything ambiguous keep the
full route.

Why: on 2026-09-16 four appraisals cost 482,420 input tokens over 12 provider calls -
37k-45k per call - because every call re-reads the full header (rulebook, notes, the
source's three-day history). The SPX level map (2 calls, 78.7k) and the APLD holdings digest
(4 calls, 154.2k) were not entries at all. The multi-branch appraisal is already shared by the
siblings (fan-in); the remaining lever is the SIZE of each call and the NUMBER of calls.

What this is NOT: a keyword filter that decides trades. The classification never changes a
verdict, never creates or suppresses a card, and routes to the compact context only when the
knob `techniques.tip.recap_route` is `compact` AND the read is confident AND no management
instruction is present. With the knob `off` (default) it only journals the read
(`TipRecapClassified`) so the routing can be evaluated on frozen examples first.
"""
from __future__ import annotations

import re

CLASSIFIER_VERSION = "recap-read-v1"
MANAGEMENT_ACTIONS = ("trim", "close", "update_stop")
RECAP_CUES = ("map", "levels", "level map", "recap", "digest", "update", "unrealized", "positions", "holdings",
              "running", "scoreboard", "watchlist", "eyeing", "watching", "candidates", "summary", "review")
ENTRY_CUES = ("bto", "buying", "bought", "sending it", "adding", "add", "in at", "filled", "entry", "grabbed",
              "full port", "back in", "opening")


def _sig(s) -> dict:
    """Accept TradeSignal objects or dicts."""
    g = (lambda k, d=None: getattr(s, k, d)) if not isinstance(s, dict) else (lambda k, d=None: s.get(k, d))
    return {"ticker": str(g("ticker") or "").upper(), "direction": g("direction"), "action": str(g("action") or "open"),
            "instrument": g("instrument"), "strike": g("strike"), "expiry": g("expiry"), "premium": g("premium"),
            "entry_price": g("entry_price"), "is_actionable": bool(g("is_actionable", True))}


def classify(signals, text: str | None, *, fan_in_min: int = 3) -> dict:
    """Read the message shape. Returns {category, confidence, route, reasons, features}.
    category: 'recap' | 'management' | 'new' | 'mixed' | 'single'."""
    sigs = [_sig(s) for s in (signals or [])]
    n = len(sigs)
    t = (text or "").lower()
    mgmt = [s for s in sigs if s["action"] in MANAGEMENT_ACTIONS]
    priced_opens = [s for s in sigs if s["action"] in ("open", "add") and (s["premium"] or s["entry_price"])]
    unpriced_opens = [s for s in sigs if s["action"] in ("open", "add") and not (s["premium"] or s["entry_price"])]
    actionable = [s for s in sigs if s["is_actionable"]]
    by_under: dict[str, set] = {}
    for s in sigs:
        if s["instrument"] in ("call", "put"):
            by_under.setdefault(s["ticker"], set()).add(s["instrument"])
    both_sides = [u for u, kinds in by_under.items() if kinds >= {"call", "put"}]
    distinct = len({s["ticker"] for s in sigs})
    recap_cues = [c for c in RECAP_CUES if c in t]
    entry_cues = [c for c in ENTRY_CUES if re.search(r"\b" + re.escape(c) + r"\b", t)]
    features = {"branches": n, "distinctTickers": distinct, "management": len(mgmt), "pricedOpens": len(priced_opens),
                "unpricedOpens": len(unpriced_opens), "actionable": len(actionable), "bothSidesSameUnderlying": both_sides,
                "recapCues": recap_cues, "entryCues": entry_cues}
    reasons: list[str] = []
    if n <= 1:
        cat, conf = "single", 1.0
        reasons.append("one signal - the ordinary route")
    elif mgmt and not priced_opens:
        cat, conf = "management", 0.9
        reasons.append(f"{len(mgmt)} management instruction(s) (trim/close/update_stop), no priced open")
    elif mgmt and priced_opens:
        cat, conf = "mixed", 0.6
        reasons.append("management instructions beside priced opens - mixed message")
    else:
        score = 0.0
        if n >= fan_in_min:
            score += 0.35
            reasons.append(f"{n} branches (>= fan-in {fan_in_min})")
        if both_sides:
            score += 0.25
            reasons.append(f"both sides listed for {', '.join(both_sides)} - a level map, not a directional call")
        if not priced_opens:
            score += 0.2
            reasons.append("no branch carries a stated premium or entry price")
        elif len(priced_opens) <= max(1, n // 4):
            score += 0.05
        if recap_cues:
            score += min(0.2, 0.1 * len(recap_cues))
            reasons.append("recap cues in the text: " + ", ".join(recap_cues[:4]))
        if entry_cues:
            score -= min(0.3, 0.15 * len(entry_cues))
            reasons.append("entry cues in the text: " + ", ".join(entry_cues[:4]))
        if distinct >= 4:
            score += 0.1
            reasons.append(f"{distinct} distinct tickers in one post")
        conf = max(0.0, min(1.0, round(score, 2)))
        if conf >= 0.8:
            cat = "recap"
        elif conf >= 0.5:
            cat = "mixed"
            reasons.append("recap-like but not confident - full route")
        else:
            cat = "new"
    route = "compact" if (cat == "recap" and conf >= 0.8 and not mgmt) else "full"
    return {"version": CLASSIFIER_VERSION, "category": cat, "confidence": conf, "route": route,
            "reasons": reasons, "features": features,
            "note": "advisory read - never changes a verdict or a card; compact routing only when the knob allows it"}


def compact_rules(rules: list[dict], *, fallback: int = 5) -> list[dict]:
    """CORE (pinned) rules only; when nothing is pinned, the newest few."""
    core = [r for r in rules if r.get("core")]
    return core if core else list(rules[:fallback])


def compact_notes(notes: list[dict], *, ticker: str | None, source: str | None) -> list[dict]:
    """Notes relevant to THIS message: its ticker, its source, and core notes."""
    t = f"ticker:{(ticker or '').upper()}"
    s = f"source:{source or ''}"
    return [n for n in notes if n.get("core") or str(n.get("scope") or "") in (t, s)]


def trim_history(text: str | None, lines: int = 12) -> str:
    rows = [r for r in str(text or "").split("\n")]
    return "\n".join(rows[:max(1, int(lines))])
