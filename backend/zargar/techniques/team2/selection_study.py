"""Selection study S1 (registration `s1-r4`, 2026-09-19): an ORDER-FREE, DEFAULT-OFF, PASSIVE collector.

Pure functions only. Nothing here reads a setting, touches an order, a portfolio, a proposal or a plan's decisions, and nothing
here (or in the runner's `_study_*` hooks) asks a provider for anything: observations are READ from the quote cache the options
service already maintains. Spec: docs/techniques/team2/notes/research/profitability-2026-09-19/07-selection-study-spec.md.

Quote evidence (the study's OWN rule, stricter than the shared diagnostics, applied at BOTH ends):
  bid > 0 and ask > 0, both finite, ask >= bid; the quote's own source is exactly "opra" (never inferred, never synthesised);
  a positive SOURCE timestamp that is NOT after the moment it was collected (no clock tolerance) and at most
  MAX_QUOTE_AGE_MS before it.

Timing:
  T_signal   the close time of the 2m contact bar the read fired on, a market fact.
  t_q0       the SOURCE timestamp of the chosen contract's entry quote. Entry delay = t_q0 - T_signal must lie in
             [0, MAX_ENTRY_DELAY_MS].
  clocks     every horizon runs from t_q0: due_h = t_q0 + h minutes.
  observation valid only when it is quote evidence AND due_h <= its SOURCE time <= due_h + MAX_LATE_MS.
  late       due_30 after 15:45 ET: no primary outcome.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from zoneinfo import ZoneInfo

STUDY = "s1-r4"
ET = ZoneInfo("America/New_York")
MIN_MS = 60_000
HORIZONS_MIN = (10, 30)                 # 30 = PRIMARY, 10 = secondary (descriptive)
PRIMARY_MIN = 30
MAX_ENTRY_DELAY_MS = 90_000
MAX_LATE_MS = 90_000
MAX_QUOTE_AGE_MS = 30_000
MAX_FOLLOWED = 12                       # UNIQUE opportunities (= unique contracts) followed at once across the desk
WINSOR_PCT = 200.0
FLATTEN_HHMM = (15, 45)
FLAG_BARS, IMPULSE_BARS = 4, 6
FLAG_RANGE_ATR, IMPULSE_MIN_ATR = 1.25, 1.5
UNKNOWN = "unknown"
FEATURES = ("flag", "levelOrigin", "wait", "first15", "scenario4", "room")
FAVOURED = {"flag": "flag", "levelOrigin": "prior", "wait": "long", "first15": "first15", "scenario4": "scenario_4", "room": "mid"}


# ------------------------------------------------------------------ the registration (frozen before activation)
# Every value that defines the study. Its canonical hash is stamped on every record; the analysis file's own hash is part of it.
# A material change to ANY entry is a new registration (new STUDY id); records of an older registration are kept and never mixed.
ANALYSIS_SHA256 = "4022fccf7e06d9102d0c3048e0951be35a7a34541fcb46574b04ff4ac9f1aa48"           # sha256 of selection_study_analysis.py (LF line endings); pinned by the tests
REGISTRATION = {
    "study": STUDY,
    "identity": "date|SYMBOL|setupId|signalTs (close time of the 2m contact bar); no per-book counter; first opening owns",
    "features": {"flag": {"flagBars": FLAG_BARS, "impulseBars": IMPULSE_BARS, "flagRangeAtr": FLAG_RANGE_ATR, "impulseMinAtr": IMPULSE_MIN_ATR},
                 "levelOrigin": "pm_break* -> pm; scenario_* -> prior; else unknown",
                 "wait": "minutes from the confirming 15m close to the signal: short < 15 <= medium <= 60 < long",
                 "first15": "signal in [09:45, 10:00) ET", "scenario4": "setup kind == scenario_4",
                 "room": "abs(target - field-bound underlying price) / ATR: near < 1.5 <= mid < 3.0 <= far"},
    "favoured": FAVOURED, "featureOrder": list(FEATURES),
    "quoteEvidence": {"bidAsk": "finite, > 0, ask >= bid", "source": "opra", "maxQuoteAgeMs": MAX_QUOTE_AGE_MS, "futureToleranceMs": 0},
    "timing": {"maxEntryDelayMs": MAX_ENTRY_DELAY_MS, "horizonsMin": list(HORIZONS_MIN), "primaryMin": PRIMARY_MIN,
               "maxLateMs": MAX_LATE_MS, "clock": "entry quote SOURCE time", "lateAfterEt": "15:45"},
    "outcome": {"primary": "R30 = (bid_30 - ask_0 - 2 fee) / (ask_0 + fee)", "feePerContract": 1.04, "winsorUpperPct": WINSOR_PCT,
                "secondary": ["R10", "R30 at one tick worse on each side"], "secondaryTested": False},
    "capacity": {"uniqueOpportunities": MAX_FOLLOWED},
    "analysis": {"sha256": ANALYSIS_SHA256},
}
REGISTRATION_HASH = hashlib.sha256(json.dumps(REGISTRATION, sort_keys=True).encode()).hexdigest()[:16]


def opportunity_id(date: str, symbol: str, setup_id: str, signal_ts: int) -> str:
    """BOOK-INDEPENDENT identity: session, symbol, setup (kind + the 15m bar that confirmed it) and the CLOSE TIME OF THE
    CONTACT BAR. No per-book counter (2026-09-18: C1's touch #1 was 10:14, Control's touch #1 was 10:22)."""
    return f"{date}|{str(symbol).upper()}|{setup_id}|{int(signal_ts)}"


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def quote_evidence(q: dict | None, collected_ts: int | None) -> tuple[dict | None, str | None]:
    """The study's strict validation of ONE bound quote `{bid, ask, source, quoteTs}` collected at `collected_ts`."""
    if not q:
        return None, "no quote"
    bid, ask = _num(q.get("bid")), _num(q.get("ask"))
    if bid is None or bid <= 0:
        return None, "no positive bid"
    if ask is None or ask <= 0:
        return None, "no positive ask"
    if ask < bid:
        return None, "crossed quote"
    src = q.get("source")
    if src != "opra":
        return None, f"source is not OPRA ({src!r})"
    sts, col = q.get("quoteTs"), collected_ts
    if not isinstance(sts, int) or isinstance(sts, bool) or sts <= 0:
        return None, "no source timestamp"
    if not isinstance(col, int) or isinstance(col, bool) or col <= 0:
        return None, "no collection timestamp"
    if sts > col:
        return None, f"source time {sts - col} ms after collection (future-dated)"
    if col - sts > MAX_QUOTE_AGE_MS:
        return None, f"stale: source time {col - sts} ms before collection (max {MAX_QUOTE_AGE_MS})"
    return {"bid": bid, "ask": ask, "quoteTs": sts, "ageMs": col - sts}, None


def _bars_2m(bars_1m: list, until_ts: int) -> list[dict]:
    """Closed 2m bars built ONLY from 1m bars that closed at or before `until_ts`."""
    out: dict[int, dict] = {}
    for b in bars_1m:
        ts = int(b.ts if hasattr(b, "ts") else b["ts"])
        if ts + MIN_MS > until_ts:
            continue
        o, h, l, c = ((b.open, b.high, b.low, b.close) if hasattr(b, "ts") else (b["open"], b["high"], b["low"], b["close"]))
        k = ts - ts % (2 * MIN_MS)
        r = out.get(k)
        if r is None:
            out[k] = {"ts": k, "open": o, "high": h, "low": l, "close": c, "n": 1}
        else:
            r["high"], r["low"], r["close"], r["n"] = max(r["high"], h), min(r["low"], l), c, r["n"] + 1
    return [r for _, r in sorted(out.items()) if r["n"] == 2 and r["ts"] + 2 * MIN_MS <= until_ts]


def features(*, signal_ts: int, direction: str, setup_id: str, confirmation_close_ts: int | None, atr: float | None,
             bars_1m: list, target: float | None, actionable: dict | None) -> dict:
    """The six frozen features, each `{"value": ..., "inputs": {...}}`. `actionable` = `{"price", "source", "ts"}` of a price whose
    OWN timestamp was checked by the caller, or None: the room feature is `unknown` without it (never a picker spot)."""
    long = str(direction) == "long"
    out: dict[str, dict] = {}
    two = [b for b in _bars_2m(bars_1m, int(signal_ts)) if b["ts"] + 2 * MIN_MS <= int(signal_ts) - 2 * MIN_MS]   # bars BEFORE the contact bar
    sess = [b for b in two if dt.datetime.fromtimestamp(b["ts"] / 1000, ET).time() >= dt.time(9, 30)]
    if not atr or atr <= 0 or len(sess) < FLAG_BARS + IMPULSE_BARS:
        out["flag"] = {"value": UNKNOWN, "inputs": {"reason": "no ATR" if not atr or atr <= 0 else f"only {len(sess)} closed session 2m bars before the contact bar"}}
    else:
        fb, ib = sess[-FLAG_BARS:], sess[-(FLAG_BARS + IMPULSE_BARS):-FLAG_BARS]
        rng = max(b["high"] for b in fb) - min(b["low"] for b in fb)
        imp = (ib[-1]["close"] - ib[0]["open"]) * (1 if long else -1)
        out["flag"] = {"value": "flag" if (rng <= FLAG_RANGE_ATR * atr and imp >= IMPULSE_MIN_ATR * atr) else "no_flag",
                       "inputs": {"rangeAtr": round(rng / atr, 3), "impulseAtr": round(imp / atr, 3), "lastBarTs": fb[-1]["ts"]}}
    kind = str(setup_id).split("@")[0]
    origin = "pm" if kind.startswith("pm_break") else ("prior" if kind.startswith("scenario_") else UNKNOWN)
    out["levelOrigin"] = {"value": origin, "inputs": {"setupKind": kind}}
    if confirmation_close_ts is None or int(confirmation_close_ts) > int(signal_ts):
        out["wait"] = {"value": UNKNOWN, "inputs": {"reason": "no confirmation time at or before the signal"}}
    else:
        m = (int(signal_ts) - int(confirmation_close_ts)) / MIN_MS
        out["wait"] = {"value": "short" if m < 15 else ("medium" if m <= 60 else "long"), "inputs": {"minutes": round(m, 1)}}
    t = dt.datetime.fromtimestamp(int(signal_ts) / 1000, ET).time()
    out["first15"] = {"value": "first15" if dt.time(9, 45) <= t < dt.time(10, 0) else "later", "inputs": {"signalEt": t.strftime("%H:%M")}}
    out["scenario4"] = {"value": "scenario_4" if kind == "scenario_4" else "other", "inputs": {"setupKind": kind}}
    px = _num((actionable or {}).get("price"))
    if target is None or px is None or not atr or atr <= 0:
        why = "no target" if target is None else ("no fresh actionable underlying price" if px is None else "no ATR")
        out["room"] = {"value": UNKNOWN, "inputs": {"reason": why, "actionableWhy": (actionable or {}).get("why")}}
    else:
        r = abs(float(target) - px) / float(atr)
        out["room"] = {"value": "near" if r < 1.5 else ("mid" if r < 3.0 else "far"),
                       "inputs": {"roomAtr": round(r, 3), "price": px, "priceSource": (actionable or {}).get("source"), "priceTs": (actionable or {}).get("ts")}}
    return out


def unknown_features(reason: str) -> dict:
    return {k: {"value": UNKNOWN, "inputs": {"reason": reason}} for k in FEATURES}


def snapshot(*, signal_ts: int, direction: str, setup_id: str, confirmation_close_ts: int | None, atr: float | None,
             bars_1m: list, target: float | None, actionable: dict | None, captured_ts: int) -> dict:
    """The point-in-time capture taken SYNCHRONOUSLY when the signal is created, before any awaited contract work: the
    features AND the exact bar values they were computed from. A later revision of an earlier bar cannot change it."""
    used = [[int(b.ts), float(b.open), float(b.high), float(b.low), float(b.close)] for b in bars_1m if int(b.ts) + MIN_MS <= int(signal_ts)][-40:]
    feats = features(signal_ts=signal_ts, direction=direction, setup_id=setup_id, confirmation_close_ts=confirmation_close_ts, atr=atr,
                     bars_1m=bars_1m, target=target, actionable=actionable)
    return {"signalTs": int(signal_ts), "setup": setup_id, "direction": direction, "capturedTs": int(captured_ts), "features": feats,
            "barsHash": hashlib.sha256(json.dumps(used).encode()).hexdigest()[:16], "bars": len(used)}


def flatten_ms(date: str) -> int:
    d = dt.date.fromisoformat(date)
    return int(dt.datetime(d.year, d.month, d.day, FLATTEN_HHMM[0], FLATTEN_HHMM[1], tzinfo=ET).timestamp() * 1000)


def _open_hash(rec: dict) -> str:
    core = {k: rec.get(k) for k in ("study", "registrationHash", "opportunityId", "book", "trigger", "features", "entryQuote", "recordedTs", "duplicateOf")}
    core["due"] = [s["dueTs"] for s in rec.get("schedule") or []]
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()[:16]


def open_record(*, date: str, symbol: str, setup_id: str, signal_ts: int, book: dict, trigger: str, direction: str,
                feats: dict, selected: dict | None, shadow: bool, refusal: str | None, recorded_ts: int, followed_now: int,
                duplicate_of: dict | None = None, inputs: dict | None = None) -> dict:
    """The record written WHEN THE OBSERVATION BEGINS. `openHash` binds every later close to THIS immutable opening."""
    oid = opportunity_id(date, symbol, setup_id, signal_ts)
    rec = {"study": STUDY, "registrationHash": REGISTRATION_HASH, "opportunityId": oid, "date": date, "symbol": str(symbol).upper(), "setup": setup_id, "signalTs": int(signal_ts),
           "trigger": trigger, "direction": direction, "book": book, "shadow": bool(shadow), "refusal": refusal,
           "features": feats, "recordedTs": int(recorded_ts), "inputs": inputs or {}, "observations": {}, "status": "open",
           "duplicateOf": duplicate_of, "schedule": []}
    sel = selected or {}
    entry = {"contract": sel.get("symbol"), "ask": sel.get("ask"), "bid": sel.get("bid"), "quoteTs": sel.get("quoteTs"),
             "receivedTs": sel.get("receivedTs"), "collectedTs": sel.get("collectedTs"), "source": sel.get("source"),
             "valid": False, "reason": None, "delayMs": None}
    if not sel or not sel.get("symbol"):
        entry["reason"] = "no contract chosen"
    else:
        clean, why = quote_evidence({"bid": sel.get("bid"), "ask": sel.get("ask"), "source": sel.get("source"), "quoteTs": sel.get("quoteTs")},
                                    sel.get("collectedTs"))
        if clean is None:
            entry["reason"] = f"entry quote is not study evidence: {why}"
        else:
            delay = int(clean["quoteTs"]) - int(signal_ts)
            entry["delayMs"] = delay
            if delay < 0:
                entry["reason"] = "entry quote predates the signal"
            elif delay > MAX_ENTRY_DELAY_MS:
                entry["reason"] = f"entry quote {delay} ms after the signal (max {MAX_ENTRY_DELAY_MS})"
            else:
                entry["valid"] = True
    rec["entryQuote"] = entry
    if duplicate_of is not None:
        rec["status"] = "closed"                       # another book already follows this opportunity: no slot, no observation here
    elif entry["valid"]:
        fl = flatten_ms(date)
        for h in HORIZONS_MIN:
            due = int(entry["quoteTs"]) + h * MIN_MS
            row = {"horizonMin": h, "dueTs": due, "status": "pending"}
            if due > fl:
                row["status"] = "done"
                rec["observations"][str(h)] = {"horizonMin": h, "dueTs": due, "valid": False, "reason": "late: due after the 15:45 flatten"}
            elif followed_now >= MAX_FOLLOWED:
                row["status"] = "done"
                rec["observations"][str(h)] = {"horizonMin": h, "dueTs": due, "valid": False, "reason": "capacity"}
            rec["schedule"].append(row)
    if not any(s["status"] == "pending" for s in rec["schedule"]):
        rec["status"] = "closed"
    rec["openHash"] = _open_hash(rec)
    return rec


def pending(rec: dict) -> bool:
    return any(s.get("status") == "pending" for s in rec.get("schedule") or [])


def observe(rec: dict, horizon_min: int, taken_ts: int, quote: dict | None, *, reason: str | None = None) -> dict:
    """Resolve one scheduled observation from a quote `{bid, ask, source, quoteTs, receivedTs}` read at `taken_ts`."""
    row = next(s for s in rec["schedule"] if s["horizonMin"] == horizon_min)
    due = int(row["dueTs"])
    obs = {"horizonMin": horizon_min, "dueTs": due, "takenTs": int(taken_ts), "valid": False, "reason": reason, "quote": quote}
    if reason is None:
        clean, why = quote_evidence(quote, int(taken_ts))
        if clean is None:
            obs["reason"] = why
        elif clean["quoteTs"] < due:
            obs["reason"] = "quote predates its due time"
        elif clean["quoteTs"] > due + MAX_LATE_MS:
            obs["reason"] = f"late: quote {clean['quoteTs'] - due} ms after due (max {MAX_LATE_MS})"
        else:
            obs.update(valid=True, reason=None, bid=clean["bid"], ask=clean["ask"], quoteTs=clean["quoteTs"], lateMs=clean["quoteTs"] - due)
    rec["observations"][str(horizon_min)] = obs
    row["status"] = "done"
    if not pending(rec):
        rec["status"] = "closed"
    return obs


def try_observe(rec: dict, horizon_min: int, now_ts: int, quote: dict | None) -> dict | None:
    """PASSIVE polling inside the window: resolve only when the cached quote is valid evidence inside [due, due+MAX_LATE];
    otherwise return None and keep waiting. Past the window the caller resolves it as unknown."""
    row = next(s for s in rec["schedule"] if s["horizonMin"] == horizon_min)
    clean, _ = quote_evidence(quote, int(now_ts))
    if clean is None or not (int(row["dueTs"]) <= clean["quoteTs"] <= int(row["dueTs"]) + MAX_LATE_MS):
        return None
    return observe(rec, horizon_min, now_ts, quote)


def abandon(rec: dict, reason: str, now_ts: int) -> None:
    """Every still-pending observation becomes unknown with `reason`; the record closes and frees its slot."""
    for s in rec.get("schedule") or []:
        if s["status"] == "pending":
            rec["observations"][str(s["horizonMin"])] = {"horizonMin": s["horizonMin"], "dueTs": s["dueTs"], "takenTs": int(now_ts),
                                                         "valid": False, "reason": reason}
            s["status"] = "done"
    rec["status"] = "closed"


def after_cost_return(entry_ask: float, exit_bid: float, fee_per_contract: float) -> float:
    """R = (bid_h - ask_0 - 2 fee) / (ask_0 + fee), per share, in percent."""
    f = float(fee_per_contract) / 100.0
    return (float(exit_bid) - float(entry_ask) - 2 * f) / (float(entry_ask) + f) * 100.0


def outcome(rec: dict, fee_per_contract: float) -> dict:
    e = rec.get("entryQuote") or {}
    out = {"opportunityId": rec.get("opportunityId"), "primary": None, "primaryReason": None, "secondary": {}}
    if not e.get("valid"):
        out["primaryReason"] = f"entry: {e.get('reason')}"
        return out
    for h in HORIZONS_MIN:
        o = (rec.get("observations") or {}).get(str(h))
        if o and o.get("valid"):
            r = after_cost_return(e["ask"], o["bid"], fee_per_contract)
            if h == PRIMARY_MIN:
                out["primary"], out["primaryRaw"] = min(r, WINSOR_PCT), r
                out["secondary"]["30_oneTickWorse"] = after_cost_return(float(e["ask"]) + 0.01, float(o["bid"]) - 0.01, fee_per_contract)
            else:
                out["secondary"][str(h)] = r
        elif h == PRIMARY_MIN:
            out["primaryReason"] = (o or {}).get("reason") or "incomplete: no observation recorded"
    return out


def collapse(open_rows: list[dict], close_rows: list[dict]) -> list[dict]:
    """ONE row per opportunity across books, revisions, restarts and duplicate journal rows; inputs in JOURNAL ORDER.

    The FOLLOWER is the first opening that is not a `duplicateOf` another book's; its features and entry quote are immutable:
    a close is accepted only when it carries the follower's `openHash`, the FIRST such close wins, and later or foreign
    closes are counted (`ignoredCloses`), never merged. An opening with no accepted close stays in the result as `incomplete`."""
    by: dict[str, list[dict]] = {}
    for r in open_rows:
        by.setdefault(str(r.get("opportunityId")), []).append(r)
    # a close whose OPENING row never reached the journal (the write failed, or the process died before it ran) still carries
    # the full opening fields: it stands in as the opening, flagged, so the opportunity is never missing from the denominator
    for c in close_rows:
        if str(c.get("opportunityId")) not in by:
            by[str(c.get("opportunityId"))] = [{**c, "status": "open", "observations": {}, "openingRecovered": True}]
    closes: dict[tuple, list[dict]] = {}
    for c in close_rows:
        closes.setdefault((str(c.get("opportunityId")), str(c.get("openHash"))), []).append(c)
    out = []
    for oid, rows in by.items():
        followers = [r for r in rows if not r.get("duplicateOf")]
        src = followers[0] if followers else rows[0]
        mine = closes.get((oid, str(src.get("openHash"))), [])
        fin = mine[0] if mine else None
        ignored = sum(len(v) for (o, _h), v in closes.items() if o == oid) - (1 if fin else 0)
        roles = sorted({str((r.get("book") or {}).get("role")) for r in rows})
        merged = dict(src)
        if fin is not None:
            merged["observations"], merged["status"] = fin.get("observations") or {}, "closed"
        complete = fin is not None or src.get("status") == "closed"
        merged.update(complete=complete, status=("closed" if complete else "incomplete"), books=roles, c1Only=(roles == ["c1"]),
                      openings=len(rows), ignoredCloses=ignored)
        out.append(merged)
    return out


def coverage(rows: list[dict], feature: str, fee_per_contract: float) -> dict:
    """Coverage by feature bucket with EVERYTHING in the denominator: valid, late, capacity, unknown by reason, incomplete."""
    table: dict[str, dict] = {}
    for r in rows:
        b = str(((r.get("features") or {}).get(feature) or {}).get("value") or UNKNOWN)
        t = table.setdefault(b, {"opportunities": 0, "valid": 0, "reasons": {}})
        t["opportunities"] += 1
        o = outcome(r, fee_per_contract)
        if o["primary"] is not None:
            t["valid"] += 1
        else:
            why = "incomplete" if not r.get("complete", True) else str(o["primaryReason"] or "missing").split(":")[0]
            t["reasons"][why] = t["reasons"].get(why, 0) + 1
    for t in table.values():
        t["coveragePct"] = round(100.0 * t["valid"] / t["opportunities"], 1) if t["opportunities"] else None
    return table
