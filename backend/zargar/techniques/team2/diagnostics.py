"""Team2 profitability diagnostics — SHADOW measurements only (review team GO, 2026-09-16).

Nothing in this module decides an order. It records what the desk knew when it acted and what the
permitted alternatives did afterwards, so tomorrow's review can rank entry situations and contract
choices on AFTER-COST outcomes with observation counts and missing-data coverage. No delta floor, no
entry-distance cutoff, no re-entry ban lives here — the thresholds below are LABELS for the report.

Four instruments (all pure; the runner wires them and journals `TechniquePlanDiagnostic` rows):

1. **Decision ledger** — every refusal / skip / contract verdict the runner logs gets a STABLE candidate
   identity (`event | setup | source minute`); a revised price on the same candidate is a VERSION of one
   decision, not another opportunity. The close report counts unique decisions from the ledger (which
   rides the persisted state and is rebuilt from the journal), never from the 400-row display buffer.
2. **Entry location** — confirmation close, pullback candle open/close, the setup level, the entry line,
   the underlying at submission and the distances in ATR; flags `sameCloseConfirmation` and `movedAway`.
3. **Attempt context** — first vs subsequent entry into the same setup, whether the previous attempt lost,
   and what fresh evidence existed (pullback episode, bars since the previous exit, a new extreme).
4. **Contract economics** — the selected contract and the alternatives the picker examined, with their
   live quotes and Greeks at the signal, follow-up quotes at fixed horizons (2/5/10 min) and at the actual
   exit, and the after-cost outcome of each (buy at ask, sell at bid, two commissions; mid-to-mid beside
   it as the optimistic reference). A missing quote stays UNKNOWN — an underlying rally is not a fill.
"""
from __future__ import annotations

import hashlib
import json

HORIZONS = ("2m", "5m", "10m")                  # fixed follow-up horizons after the signal's quote
HORIZON_MS = {"2m": 120_000, "5m": 300_000, "10m": 600_000}
MAX_LATE_MS = 90_000                             # an observation taken later than this after its due time is unknown
MAX_QUOTE_AGE_MS = 30_000                        # a quote whose SOURCE time is older than this at collection is not an observation
MAX_FOLLOWED = 6                                 # shadow collection follows at most this many contracts per attempt (bounded)
MOVED_AWAY_ATR = 0.25                            # LABEL: the underlying moved on from the pullback close by this many ATR
FEE_SIDES = 2                                    # a round trip pays the per-contract commission twice
CONFIRM_TF_MS = 15 * 60_000

# ---------------------------------------------------------------- 1. the decision ledger
DECISION_ALIASES = {"max_concurrent_positions": "max_concurrent_skip"}      # journal name -> the UI/log name
DECISION_PREFIXES = ("skip_", "contract_")
DECISION_EVENTS = frozenset({
    "max_concurrent_skip", "max_open_skip", "halt_skip", "paused_skip", "quiesced_skip", "entry_capped",
    "technique_loss_halt", "loss_halt", "stale_signal_skip", "backdated_signal_skip", "entry_gate_refused",
    "deterministic_refused", "policy_error",
})
_VERSION_SKIP = frozenset({"event", "text", "reason", "why", "ts", "runId", "symbol", "trigger", "setup", "touch", "sourceTs"})


def normalize_event(name: str | None) -> str:
    n = str(name or "")
    return DECISION_ALIASES.get(n, n)


def is_decision(name: str | None) -> bool:
    n = normalize_event(name)
    return n.startswith(DECISION_PREFIXES) or n in DECISION_EVENTS


def setup_of(rec: dict) -> str:
    s = rec.get("setup")
    if s:
        return str(s)
    return str(rec.get("trigger") or "").split("#")[0]


def touch_of(rec: dict) -> str:
    """The attempt number a runner-side record names in its trigger (`setup#N`); read-side notes name none — their
    log and journal twins agree on that, so the key stays equal on both sides."""
    trig = str(rec.get("trigger") or "")
    return trig.split("#", 1)[1] if "#" in trig else ""


def decision_key(rec: dict) -> str:
    """The stable identity of one decision: what was refused, on which setup (and attempt, when the trigger names one),
    at which SOURCE minute. A wall-clock `ts` is used only when the record carries no source time (the runner passes
    `sourceTs` for its own refusals)."""
    ts = rec.get("sourceTs") or rec.get("ts")
    return f"{normalize_event(rec.get('event'))}|{setup_of(rec)}|{touch_of(rec)}|{ts}"


def _version(rec: dict) -> dict:
    text = rec.get("text") or rec.get("reason") or rec.get("why") or ""
    detail = {k: v for k, v in rec.items() if k not in _VERSION_SKIP and not str(k).startswith("_")}
    return {"text": str(text)[:300], "ts": rec.get("ts"), "detail": detail}


def note_decision(ledger: dict, rec: dict, *, source: str = "log") -> dict | None:
    """Fold one logged / journaled record into the ledger. Returns the entry, or None when the record is not a
    decision. `rows` counts LOG rows only (the raw count the review asked to keep apart from unique decisions);
    a journal row of a decision the ledger already holds adds evidence, not a row."""
    if not is_decision(rec.get("event")):
        return None
    key = decision_key(rec)
    v = _version(rec)
    e = ledger.get(key)
    if e is None:
        e = ledger[key] = {"key": key, "event": normalize_event(rec.get("event")), "setup": setup_of(rec),
                           "trigger": rec.get("trigger"), "ts": rec.get("sourceTs") or rec.get("ts"),
                           "first": v, "versions": [], "rows": 1 if source == "log" else 0, "sources": [source]}
        return e
    if source == "log":
        e["rows"] += 1
    if source not in e["sources"]:
        e["sources"].append(source)
    if v["text"] and v["text"] != e["first"]["text"] and all(v["text"] != x["text"] for x in e["versions"]):
        e["versions"].append(v)
    return e


def note_journal_row(ledger: dict, payload: dict) -> dict | None:
    """A durable `TechniquePlanTriggerSkipped` / `TechniquePlanContract` row (after a restart) — same identity rule.
    The journal names the setup in `trigger` for read-side skips and the trigger for runner-side ones."""
    rec = dict(payload or {})
    rec.setdefault("text", rec.get("reason") or rec.get("why") or "")
    return note_decision(ledger, rec, source="journal")


def unique_counts(ledger: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in ledger.values():
        out[e["event"]] = out.get(e["event"], 0) + 1
    return dict(sorted(out.items()))


def row_counts(ledger: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in ledger.values():
        out[e["event"]] = out.get(e["event"], 0) + int(e.get("rows") or 0)
    return dict(sorted(out.items()))


def decisions_view(ledger: dict) -> list[dict]:
    rows = sorted(ledger.values(), key=lambda e: (int(e.get("ts") or 0), e["key"]))
    return [{"event": e["event"], "setup": e["setup"], "trigger": e.get("trigger"), "ts": e.get("ts"), "rows": e.get("rows", 0),
             "text": e["first"]["text"], "revisions": [x["text"] for x in e.get("versions") or []],
             "sources": list(e.get("sources") or [])} for e in rows]


def ledger_state(ledger: dict) -> list[dict]:
    return [dict(e) for e in ledger.values()]


def ledger_from_state(items) -> dict:
    out: dict = {}
    for e in items or []:
        if isinstance(e, dict) and e.get("key"):
            out[str(e["key"])] = dict(e)
    return out


def ledger_from_events(events) -> dict:
    """Legacy fallback (a plan restored from a release without the ledger): the display buffer, de-duplicated by the
    same identity rule. Bounded by the buffer — the ledger is the record once it exists."""
    out: dict = {}
    for e in events or []:
        if isinstance(e, dict):
            note_decision(out, e, source="log")
    return out


# ---------------------------------------------------------------- 2. entry location
def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def tape_hash(bars, upto_ts: int | None = None) -> str:
    """Input identity of a decision: the private 1m tape up to the signal's close."""
    h = hashlib.sha1()
    n = 0
    for b in bars or []:
        if upto_ts is not None and int(b.ts) >= int(upto_ts):
            continue
        h.update(f"{b.ts}|{b.open}|{b.high}|{b.low}|{b.close}|{b.volume}|{getattr(b, 'source', '') or ''}\n".encode())
        n += 1
    return f"{h.hexdigest()[:16]}:{n}"


def rules_hash(rules) -> str | None:
    try:
        d = rules.to_dict() if hasattr(rules, "to_dict") else dict(rules)
        return hashlib.sha1(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return None


def entry_location(e: dict, setup: dict, bars_1m, *, confirm_tf_ms: int = CONFIRM_TF_MS) -> dict:
    """What the fire looked like on the tape: the confirmation close, the pullback candle it was judged on, the
    setup level and the entry line, and the candle's distance from both in ATR (signed: + = beyond the level in
    the trade's direction). `sameCloseConfirmation` = the pullback candle closed ON the confirmation close."""
    ts = int(e.get("ts") or 0)
    direction = str(setup.get("direction") or ("long" if (e.get("regime") or {}).get("stack") == "bull" else "short"))
    sign = 1.0 if direction == "long" else -1.0
    anchor = _f(setup.get("anchor"))
    confirmed = setup.get("confirmedTs")
    conf_close = int(confirmed) + int(confirm_tf_ms) if confirmed is not None else None
    atr = _f((e.get("regime") or {}).get("atr"))
    atr = atr if atr and atr > 0 else None
    entry_line = _f(e.get("spot"))
    candle = [b for b in (bars_1m or []) if ts - 120_000 <= int(b.ts) < ts]
    ohlc = None
    if candle:
        ohlc = {"open": float(candle[0].open), "high": max(float(b.high) for b in candle),
                "low": min(float(b.low) for b in candle), "close": float(candle[-1].close), "minutes": len(candle)}

    def d_atr(px, ref):
        if atr is None or px is None or ref is None:
            return None
        return round((float(px) - float(ref)) * sign / atr, 3)

    close = ohlc["close"] if ohlc else None
    return {"signalTs": ts, "direction": direction, "entryKind": e.get("entryKind"), "pullbackEpisode": e.get("touch"),
            "confirmedBarStartTs": confirmed, "confirmationCloseTs": conf_close,
            "pullbackOpenTs": ts - 120_000, "pullbackCloseTs": ts, "pullbackCandle": ohlc,
            "setupLevel": anchor, "entryLine": entry_line, "atr": atr,
            "closeFromLevelAtr": d_atr(close, anchor), "closeFromEntryLineAtr": d_atr(close, entry_line),
            "sameCloseConfirmation": (bool(conf_close is not None and ts == conf_close) if conf_close is not None else None),
            "minutesSinceConfirmation": (round((ts - conf_close) / 60_000, 1) if conf_close is not None else None)}


def submission_displacement(loc: dict, underlying: float | None, at_ts: int, quote_ts: int | None = None,
                            *, moved_away_atr: float = MOVED_AWAY_ATR) -> dict:
    """The underlying at the ORDER boundary against the signal candle: has price moved on since the pullback close?
    `movedAway` is a diagnostic label (+ = further in the trade's direction than the close by `moved_away_atr`)."""
    sign = 1.0 if loc.get("direction") == "long" else -1.0
    atr = loc.get("atr")
    close = (loc.get("pullbackCandle") or {}).get("close")
    px = _f(underlying)

    def d_atr(ref):
        if not atr or px is None or ref is None:
            return None
        return round((px - float(ref)) * sign / float(atr), 3)

    from_close = d_atr(close)
    return {"submission": {"ts": int(at_ts), "underlying": px, "quoteTs": quote_ts,
                           "secondsAfterClose": (round((int(at_ts) - int(loc.get("pullbackCloseTs") or at_ts)) / 1000, 1))},
            "submissionFromLevelAtr": d_atr(loc.get("setupLevel")), "submissionFromEntryLineAtr": d_atr(loc.get("entryLine")),
            "submissionFromCloseAtr": from_close,
            "movedAway": (None if from_close is None else bool(from_close > float(moved_away_atr)))}


def target_room(loc: dict, underlying: float | None, target: float | None, stop: float | None, anchor: float | None) -> dict:
    """Item 4 (2026-09-17): the room to the target and to the stop from the ACTUAL underlying at the order boundary, in
    points and ATR, and whether the target is the setup's own source level. Unknown inputs stay None."""
    sign = 1.0 if loc.get("direction") == "long" else -1.0
    atr = _f(loc.get("atr"))
    px = _f(underlying)
    t, st, a = _f(target), _f(stop), _f(anchor)

    def room(dest, favour: float):
        if px is None or dest is None:
            return None, None
        pts = round((dest - px) * favour, 4)
        return pts, (round(pts / atr, 3) if atr else None)

    tr, tra = room(t, sign)
    sr, sra = room(st, -sign)
    return {"targetRoomPoints": tr, "targetRoomAtr": tra, "stopRoomPoints": sr, "stopRoomAtr": sra,
            "targetIsSourceLevel": (None if t is None or a is None else bool(abs(t - a) <= 0.011)),
            "targetToAnchorPoints": (None if t is None or a is None else round((t - a) * sign, 4)),
            "underlyingAtBoundary": px}


def payoff_estimate(entry_ask, bid, delta, gamma, room_points, fee: float, *, qty: float = 1.0, greeks_source: str | None = None) -> dict:
    """Item 4 (2026-09-17): a LABELLED estimate of what the selected contract could pay at the target — delta (and gamma)
    times the room, no theta or IV change, the current spread held constant and the exit taken at the bid — against the
    round-trip commissions. Never an executable price; an estimate is `insufficient evidence` when a pricing input is
    missing (Greeks unknown, no room, no entry ask)."""
    missing = []
    a, b, d, g, r = _f(entry_ask), _f(bid), _f(delta), _f(gamma), _f(room_points)
    if a is None or a <= 0:
        missing.append("entry ask")
    if r is None:
        missing.append("target room")
    if d is None:
        missing.append("delta")
    if missing:
        return {"status": "insufficient evidence", "missing": missing, "greeksSource": greeks_source}
    spread = round(a - b, 4) if (b is not None and b > 0 and b <= a) else None
    move = abs(d) * r + 0.5 * (g or 0.0) * r * r
    est_exit_bid = a - (spread or 0.0) + move
    gross = (est_exit_bid - a) * 100.0 * float(qty)
    net = gross - FEE_SIDES * float(fee or 0) * float(qty)
    be_move = ((FEE_SIDES * float(fee or 0)) / 100.0 + (spread or 0.0)) / abs(d) if d else None
    return {"status": "estimate", "estExitBid": round(est_exit_bid, 4), "estMovePremium": round(move, 4),
            "grossPerContract": round(gross / float(qty), 2), "netPerContract": round(net / float(qty), 2),
            "netPct": round(net / (a * 100.0 * float(qty)) * 100.0, 2), "breakEvenMovePoints": (round(be_move, 4) if be_move is not None else None),
            "spreadAssumed": spread, "deltaUsed": d, "gammaUsed": g, "greeksSource": greeks_source,
            "assumptions": "delta-gamma over the target room; no theta or IV change; spread held constant; exit at the bid; "
                           "commissions both ways — a labelled estimate, never an executable price"}


# ---------------------------------------------------------------- 3. attempt context
def _net(t, fees_fn) -> float | None:
    if float(getattr(t, "filled_qty", 0) or 0) <= 0:
        return None
    try:
        return round(float(getattr(t, "realized_pnl", 0) or 0) - float(fees_fn(t) or 0), 2)
    except Exception:  # noqa: BLE001
        return round(float(getattr(t, "realized_pnl", 0) or 0), 2)


def _outcome(t, net: float | None) -> str:
    if net is None:
        return "unfilled" if getattr(t, "status", "") not in ("submitting", "working") else "in_flight"
    if getattr(t, "status", "") != "closed":
        return "open"
    return "lost" if net < 0 else ("won" if net > 0 else "flat")


def attempt_context(setup_id: str, tid: str, fired_ts: int, trades, fees_fn, bars_today=None, direction: str = "long") -> dict:
    """First vs subsequent entry into the same setup. `class` is `first` until a PRIOR attempt actually filled; the
    review reports the two separately and, within subsequent, whether the previous filled attempt lost."""
    prior = sorted([t for t in trades if getattr(t, "setup_id", None) == setup_id and t.trigger_id != tid
                    and not getattr(t, "is_add", False) and int(getattr(t, "fired_ts", 0) or 0) <= int(fired_ts)],
                   key=lambda t: int(getattr(t, "fired_ts", 0) or 0))
    rows = []
    for t in prior:
        net = _net(t, fees_fn)
        rows.append({"trigger": t.trigger_id, "status": t.status, "filledQty": float(getattr(t, "filled_qty", 0) or 0),
                     "netPnl": net, "outcome": _outcome(t, net), "firedTs": getattr(t, "fired_ts", None),
                     "closedTs": getattr(t, "closed_ts", None)})
    filled = [r for r in rows if r["filledQty"] > 0]
    prev = filled[-1] if filled else None
    since_exit = None
    if prev and prev.get("closedTs"):
        since_exit = round((int(fired_ts) - int(prev["closedTs"])) / 60_000, 1)
    new_extreme = None
    if prev and bars_today:
        before = [b for b in bars_today if int(b.ts) < int(prev["firedTs"] or 0)]
        between = [b for b in bars_today if int(prev["firedTs"] or 0) <= int(b.ts) < int(fired_ts)]
        if before and between:
            if direction == "long":
                new_extreme = max(float(b.high) for b in between) > max(float(b.high) for b in before)
            else:
                new_extreme = min(float(b.low) for b in between) < min(float(b.low) for b in before)
    return {"attemptIndex": len(rows) + 1, "entryIndex": len(filled) + 1, "class": "first" if not filled else "subsequent",
            "previous": prev, "previousLost": (None if prev is None else prev["outcome"] == "lost"),
            "minutesSincePreviousExit": since_exit, "priorAttempts": rows,
            "freshEvidence": {"sameSetupConfirmation": True, "newExtremeSincePrevious": new_extreme,
                              "barsSincePreviousEntry": (None if prev is None else
                                                         sum(1 for b in (bars_today or []) if int(prev["firedTs"] or 0) <= int(b.ts) < int(fired_ts)))}}


# ---------------------------------------------------------------- 4. contract economics
def quote_check(q: dict | None, collected_ts: int, *, max_age_ms: int = MAX_QUOTE_AGE_MS, need_bid: bool = True) -> tuple[dict | None, str | None]:
    """One quote as EVIDENCE: live-served, a positive ask (and bid when `need_bid`), not crossed, and carrying a SOURCE
    confirmation timestamp (`quoteTs` = the provider's time for THIS bid/ask, `Quote.source_ts`) within `max_age_ms` of
    the moment it was collected. Anything else is unknown, with the reason — neither a receipt time (`Quote.ts`, kept
    apart as `receivedTs`) nor a timestamp stamped by the collector is a fresh market observation."""
    if not q:
        return None, "no quote"
    if q.get("priced") not in (None, "opra") and q.get("priced") != "opra":
        return None, f"not live ({q.get('priced')})"
    bid, ask = _f(q.get("bid")), _f(q.get("ask"))
    if ask is None or ask <= 0:
        return None, "no ask"
    if need_bid and (bid is None or bid <= 0):
        return None, "no bid"
    if bid is not None and bid > ask:
        return None, "crossed quote"
    ts = q.get("quoteTs")
    if ts is None:
        return None, "no source timestamp"
    age = int(collected_ts) - int(ts)
    if age > int(max_age_ms):
        return None, f"stale quote ({age // 1000}s old at collection)"
    if age < -5_000:
        return None, "quote timestamp ahead of the clock"
    return {"bid": bid, "ask": ask, "mid": (round((bid + ask) / 2, 4) if bid is not None else None), "quoteTs": int(ts),
            "receivedTs": q.get("receivedTs"), "source": q.get("priced"), "ageMs": max(0, age)}, None


def candidate_rows(examined: list[dict], chain_rows: dict, pick_symbol: str | None, *, floor: float, band_hi: float,
                   spot: float | None, quote_ts: int, max_age_ms: int = MAX_QUOTE_AGE_MS, max_followed: int = MAX_FOLLOWED) -> list[dict]:
    """The selected contract and every alternative the picker examined, with the quotes it saw and the Greeks the
    chain carried at that moment (delayed chain Greeks unless `greeksLive`). Each examined row is ONE observation: its
    bid/ask, provenance (`source`), the provider's confirmation time (`quoteTs`), the receipt time (`receivedTs`) and the
    capture time (`collectedTs`) were bound together when the picker examined it; validation and the report use exactly
    those fields — never a later lookup. `quote_ts` is the attempt's collection time, used only when a row has none.
    `priceKnown` says whether the entry quote is usable as the denominator of a hypothetical return; `followed` bounds
    the follow-up collection to the selected contract, the in-band alternatives and then the nearest others."""
    out = []
    for x in examined or []:
        sym = str(x.get("symbol") or "")
        row = chain_rows.get(sym) or {}
        g = row.get("greeks") or {}
        ask, bid = _f(x.get("ask")), _f(x.get("bid"))
        eligible = bool(x.get("eligible"))
        strike = _f(x.get("strike"))
        sts = x.get("quoteTs")
        source = x.get("source") or x.get("priced")
        collected = int(x.get("collectedTs") or quote_ts)
        clean, why = quote_check({"bid": bid, "ask": ask, "priced": source, "quoteTs": sts}, collected,
                                 max_age_ms=max_age_ms, need_bid=False) if eligible else (None, "not priced live")
        if clean is None and x.get("provenanceNote") and why == "no source timestamp":
            why = x["provenanceNote"]
        out.append({"symbol": sym, "strike": strike, "bid": bid, "ask": ask,
                    "mid": (round((bid + ask) / 2, 4) if bid is not None and ask is not None and ask > 0 else None),
                    "priced": x.get("priced"), "eligible": eligible,
                    "inBand": bool(eligible and ask is not None and float(floor) <= ask <= float(band_hi)),
                    "selected": bool(pick_symbol and sym == pick_symbol),
                    "delta": _f(g.get("delta")), "gamma": _f(g.get("gamma")), "theta": _f(g.get("theta")), "iv": _f(g.get("mid_iv")),
                    "greeksLive": bool(row.get("greeksLive")), "greeksAsOf": row.get("greeksAsOf") or row.get("asOf") or row.get("ts"),
                    "greeksSource": row.get("greeksSource") or ("chain" if _f(g.get("delta")) is not None else "none"),
                    "greeksProvider": row.get("greeksProvider"),
                    "spot": spot, "distancePct": (round((strike - spot) / spot * 100, 3) if strike is not None and spot else None),
                    "quoteTs": sts, "receivedTs": x.get("receivedTs"), "collectedTs": collected, "source": source,
                    "quoteAgeMs": (clean or {}).get("ageMs"),
                    "priceKnown": clean is not None, "priceUnknownReason": why, "followed": False})
    order = sorted(range(len(out)), key=lambda i: (not out[i]["selected"], not out[i]["inBand"],
                                                  abs(float(out[i]["distancePct"] or 0.0))))
    for i in order[:max(0, int(max_followed))]:
        out[i]["followed"] = True
    return out


def after_cost(entry_ask: float | None, entry_mid: float | None, bid: float | None, mid: float | None,
               fee: float, qty: float = 1.0) -> dict:
    """Per contract unless `qty`: buy at the ask, sell at the bid, two commissions (executable); mid-to-mid beside it."""
    out = {"askToBidNet": None, "askToBidPct": None, "midToMidNet": None, "midToMidPct": None}
    fee2 = FEE_SIDES * float(fee or 0)
    if entry_ask is not None and bid is not None and entry_ask > 0:
        ab = ((float(bid) - float(entry_ask)) * 100.0 - fee2) * float(qty)
        out["askToBidNet"] = round(ab, 2)
        out["askToBidPct"] = round(ab / (float(entry_ask) * 100.0 * float(qty)) * 100.0, 2)
    if entry_mid is not None and mid is not None and entry_mid > 0:
        mm = ((float(mid) - float(entry_mid)) * 100.0 - fee2) * float(qty)
        out["midToMidNet"] = round(mm, 2)
        out["midToMidPct"] = round(mm / (float(entry_mid) * 100.0 * float(qty)) * 100.0, 2)
    return out


def schedule(attempt: str, quote_ts: int, *, with_exit: bool) -> list[dict]:
    rows = [{"attempt": attempt, "horizon": h, "dueTs": int(quote_ts) + HORIZON_MS[h], "status": "pending"} for h in HORIZONS]
    if with_exit:
        rows.append({"attempt": attempt, "horizon": "exit", "dueTs": None, "status": "pending"})
    return rows


def observation(horizon: str, due_ts: int | None, taken_ts: int, quotes: dict, *, max_late_ms: int = MAX_LATE_MS,
                max_quote_age_ms: int = MAX_QUOTE_AGE_MS, unknown: dict | None = None) -> dict:
    """One follow-up observation: `quotes[symbol]` = {bid, ask, priced, quoteTs} or None (no quote). Taken too late
    after its due time, the whole observation is UNKNOWN (kept with its reason), never back-dated. Each quote must be
    live, sane and carry a SOURCE timestamp within `max_quote_age_ms` of collection — a cached quote from the entry
    re-served two minutes later is not the two-minute observation. `unknown[symbol]` names why a quote is missing
    (outage, not followed) when the caller knows."""
    late = (int(taken_ts) - int(due_ts)) if due_ts is not None else 0
    if due_ts is not None and late > int(max_late_ms):
        return {"horizon": horizon, "dueTs": due_ts, "takenTs": int(taken_ts), "status": "unknown",
                "reason": f"taken {late // 1000}s after due (> {max_late_ms // 1000}s)", "quotes": {}, "unknown": {}}
    qs: dict[str, dict | None] = {}
    why: dict[str, str] = {}
    for sym, q in (quotes or {}).items():
        clean, reason = quote_check(q, taken_ts, max_age_ms=max_quote_age_ms)
        qs[sym] = clean
        if clean is None:
            why[sym] = (unknown or {}).get(sym) or reason or "no quote"
    for sym, reason in (unknown or {}).items():
        if sym not in qs:
            qs[sym] = None
            why[sym] = reason
    observed = any(v is not None for v in qs.values())
    return {"horizon": horizon, "dueTs": due_ts, "takenTs": int(taken_ts), "status": "observed" if observed else "unknown",
            "reason": (None if observed else "no fresh valid quote for any followed contract"),
            "lateMs": max(0, late), "quotes": qs, "unknown": why}


def summarize_attempt(rec: dict, fee: float) -> dict:
    """Per candidate, the after-cost outcome at every horizon (None = unknown) and the coverage."""
    obs = rec.get("observations") or {}
    horizons = list(HORIZONS) + (["exit"] if "exit" in obs or rec.get("routing", {}).get("filledQty") else [])
    cands = []
    observed = missing = 0
    for c in rec.get("candidates") or []:
        entry_ask = _f(c.get("ask"))
        entry_ok = c.get("priceKnown", True) and entry_ask is not None and entry_ask > 0
        row = {"symbol": c.get("symbol"), "strike": c.get("strike"), "selected": c.get("selected"), "inBand": c.get("inBand"),
               "delta": c.get("delta"), "entryAsk": entry_ask, "entryMid": c.get("mid"), "followed": c.get("followed", True),
               "entryPriceKnown": bool(entry_ok), "outcomes": {}, "unknown": {}}
        for h in horizons:
            o = obs.get(h)
            if not entry_ok:
                row["outcomes"][h] = None
                row["unknown"][h] = "entry price unknown" + (f" ({c.get('priceUnknownReason')})" if c.get("priceUnknownReason") else "")
                missing += 1
                continue
            if not o:
                row["outcomes"][h] = None
                row["unknown"][h] = "not observed"
                missing += 1
                continue
            q = (o.get("quotes") or {}).get(c.get("symbol")) if o.get("status") == "observed" else None
            if q is None:
                row["outcomes"][h] = None
                row["unknown"][h] = (o.get("unknown") or {}).get(c.get("symbol")) or o.get("reason") or "no quote"
                missing += 1
                continue
            res = after_cost(entry_ask, c.get("mid"), q.get("bid"), q.get("mid"), fee)
            if res.get("askToBidPct") is None:
                row["outcomes"][h] = None
                row["unknown"][h] = "no executable return (bid or entry ask missing)"
                missing += 1
                continue
            row["outcomes"][h] = res
            observed += 1
        cands.append(row)
    routing = rec.get("routing") or {}
    return {"trigger": rec.get("trigger"), "setup": rec.get("setup"), "shadow": bool(rec.get("shadow")), "refusal": rec.get("refusal"),
            "attemptClass": (rec.get("attempt") or {}).get("class"), "previousLost": (rec.get("attempt") or {}).get("previousLost"),
            "sameCloseConfirmation": (rec.get("entryLocation") or {}).get("sameCloseConfirmation"),
            "movedAway": (rec.get("entryLocation") or {}).get("movedAway"),
            "submissionFromCloseAtr": (rec.get("entryLocation") or {}).get("submissionFromCloseAtr"),
            "actual": {"filledQty": routing.get("filledQty"), "avgFill": routing.get("avgFill"), "netPnl": routing.get("netPnl"),
                       "grossPnl": routing.get("grossPnl"), "fees": routing.get("fees"),
                       "grossBreakevenNetLoss": routing.get("grossBreakevenNetLoss"),
                       "exitPrice": routing.get("exitPrice"), "status": routing.get("status")},
            "targetRoomAtr": (rec.get("entryLocation") or {}).get("targetRoomAtr"),
            "targetIsSourceLevel": (rec.get("entryLocation") or {}).get("targetIsSourceLevel"),
            "payoffEstimate": (rec.get("entryLocation") or {}).get("payoffEstimate"),
            "candidates": cands, "coverage": {"observed": observed, "missing": missing, "horizons": horizons}}


def _mean(xs):
    xs = [float(x) for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def summarize_day(attempts: list[dict], fee: float) -> dict:
    """The review's table: entry situations and contract choices ranked on after-cost outcomes, with counts and
    missing-data coverage. `attempts` are the per-attempt diagnostic records (journaled or from the scorecard)."""
    summaries = [summarize_attempt(a, fee) for a in attempts]

    def group(key_fn, label):
        buckets: dict = {}
        for s in summaries:
            k = key_fn(s)
            b = buckets.setdefault(str(k), {"situation": label, "value": k, "attempts": 0, "filled": 0, "actualNet": [], "selected": {h: [] for h in list(HORIZONS) + ["exit"]},
                                            "missing": 0, "observed": 0})
            b["attempts"] += 1
            if (s["actual"].get("filledQty") or 0) > 0:
                b["filled"] += 1
                b["actualNet"].append(s["actual"].get("netPnl"))
            b["missing"] += s["coverage"]["missing"]
            b["observed"] += s["coverage"]["observed"]
            for c in s["candidates"]:
                if c.get("selected"):
                    for h, o in c["outcomes"].items():
                        b["selected"].setdefault(h, []).append(o["askToBidPct"] if (o and o.get("askToBidPct") is not None) else None)
        out = []
        for b in buckets.values():
            out.append({"situation": b["situation"], "value": b["value"], "attempts": b["attempts"], "filled": b["filled"],
                        "actualNetSum": (round(sum(x for x in b["actualNet"] if x is not None), 2) if b["actualNet"] else None),
                        "actualNetMean": _mean(b["actualNet"]),
                        "selectedAskToBidPct": {h: {"mean": _mean(v), "n": sum(1 for x in v if x is not None), "missing": sum(1 for x in v if x is None)}
                                                for h, v in b["selected"].items() if v},
                        "coverage": {"observed": b["observed"], "missing": b["missing"]}})
        return out

    situations = (group(lambda s: s["sameCloseConfirmation"], "sameCloseConfirmation")
                  + group(lambda s: s["movedAway"], "movedAway")
                  + group(lambda s: (s["attemptClass"] if s["attemptClass"] != "subsequent" else
                                     ("subsequentAfterLoss" if s["previousLost"] else "subsequentAfterNonLoss")), "attemptClass"))
    # contract choice: selected vs the in-band alternatives, per horizon
    choice = {h: {"selected": [], "alternativesInBand": [], "alternativesOther": [], "alternativeBeatSelected": 0, "compared": 0}
              for h in list(HORIZONS) + ["exit"]}
    for s in summaries:
        sel = next((c for c in s["candidates"] if c.get("selected")), None)
        for h in choice:
            so = (sel or {}).get("outcomes", {}).get(h) if sel else None
            sp = so.get("askToBidPct") if so else None
            if sp is not None:
                choice[h]["selected"].append(sp)
            for c in s["candidates"]:
                if c.get("selected"):
                    continue
                o = c["outcomes"].get(h)
                op = o.get("askToBidPct") if o else None
                if op is None:
                    continue                                   # unknown never enters a denominator or a comparison
                (choice[h]["alternativesInBand"] if c.get("inBand") else choice[h]["alternativesOther"]).append(op)
                if sp is not None:
                    choice[h]["compared"] += 1
                    if op > sp:
                        choice[h]["alternativeBeatSelected"] += 1
    contract = {h: {"selectedMeanPct": _mean(v["selected"]), "selectedN": len(v["selected"]),
                    "inBandAlternativesMeanPct": _mean(v["alternativesInBand"]), "inBandAlternativesN": len(v["alternativesInBand"]),
                    "otherAlternativesMeanPct": _mean(v["alternativesOther"]), "otherAlternativesN": len(v["alternativesOther"]),
                    "alternativeBeatSelected": v["alternativeBeatSelected"], "compared": v["compared"]}
                for h, v in choice.items() if v["selected"] or v["alternativesInBand"] or v["alternativesOther"]}
    # item 4 (2026-09-17): coverage is reported SEPARATELY for attempts (did a contract set get captured at all), for
    # Greeks (do the captured candidates carry a delta, and from where) and for follow-up quotes (observed / missing)
    without = [{"trigger": a.get("trigger"), "reason": (a.get("refusal") or "no contracts captured (deferred or refused before examination)")}
               for a in attempts if not (a.get("candidates") or [])]
    cands_all = [c for a in attempts for c in (a.get("candidates") or [])]
    greeks_cov = {"candidates": len(cands_all), "withDelta": sum(1 for c in cands_all if c.get("delta") is not None),
                  "bySource": {}}
    for c in cands_all:
        k = str(c.get("greeksSource") or ("chain" if c.get("delta") is not None else "none"))
        greeks_cov["bySource"][k] = greeks_cov["bySource"].get(k, 0) + 1
    gross_sum = sum(float(s["actual"].get("grossPnl") or 0) for s in summaries if (s["actual"].get("filledQty") or 0) > 0)
    net_sum = sum(float(s["actual"].get("netPnl") or 0) for s in summaries if (s["actual"].get("filledQty") or 0) > 0)
    return {"attempts": len(summaries), "filled": sum(1 for s in summaries if (s["actual"].get("filledQty") or 0) > 0),
            "shadow": sum(1 for s in summaries if s["shadow"]),
            "coverage": {"observed": sum(s["coverage"]["observed"] for s in summaries),
                         "missing": sum(s["coverage"]["missing"] for s in summaries)},
            "coverageDetail": {"attempts": {"total": len(attempts), "withCandidates": len(attempts) - len(without), "withoutCandidates": without},
                               "greeks": greeks_cov,
                               "followUps": {"observed": sum(s["coverage"]["observed"] for s in summaries),
                                             "missing": sum(s["coverage"]["missing"] for s in summaries)}},
            "actualOutcomes": {"grossSum": round(gross_sum, 2), "netSum": round(net_sum, 2),
                               "grossBreakevenNetLoss": sum(1 for s in summaries if s["actual"].get("grossBreakevenNetLoss")),
                               "note": "book fills: gross realized and net after commissions, apart; the risk counter's basis is unchanged"},
            "situations": situations, "contractChoice": contract, "perAttempt": summaries,
            "labels": {"movedAwayAtr": MOVED_AWAY_ATR, "horizons": list(HORIZONS) + ["exit"], "feePerSide": fee,
                       "maxQuoteAgeMs": MAX_QUOTE_AGE_MS, "maxFollowed": MAX_FOLLOWED,
                       "actual": "book fills: realized P&L after commissions, from the execution records",
                       "candidates": "HYPOTHETICAL quoted ask-to-bid returns after two commissions — never fills, never realized",
                       "note": "shadow measurements; unknown stays unknown and enters no denominator"}}
