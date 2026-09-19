"""Selection study S1 (registration `s1-r2`, 2026-09-19): an ORDER-FREE, DEFAULT-OFF collector.

Pure functions only. Nothing here reads a setting, touches an order, a portfolio, a proposal or a plan's decisions; the runner
calls it from the shadow-diagnostics path when `techniques.team2.selection_study == "collect"` and journals what it returns.
Spec: docs/techniques/team2/notes/research/profitability-2026-09-19/07-selection-study-spec.md (frozen definitions live there;
this module implements them and its tests pin them).

Timing, exactly:
  T_signal   the close time of the 2m contact bar the read fired on (`entryLocation.signalTs`), a market fact.
  t_q0       the SOURCE timestamp of the chosen contract's entry quote (`quoteTs`, the provider's time for that bid/ask).
  entry delay = t_q0 - T_signal; the entry quote is valid evidence only when 0 <= delay <= MAX_ENTRY_DELAY_MS and the quote
               passed `diagnostics.quote_check` when it was bound (live OPRA, positive bid/ask, not crossed, fresh at collection).
  clocks     every horizon runs from t_q0, never from T_signal or from a receipt time: due_h = t_q0 + h minutes.
  observation valid only when its own quote is valid evidence AND due_h <= its SOURCE timestamp <= due_h + MAX_LATE_MS.
  late       due_30 after 15:45 ET: the opportunity has no primary outcome.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from zoneinfo import ZoneInfo

from . import diagnostics as diag

STUDY = "s1-r2"
ET = ZoneInfo("America/New_York")
MIN_MS = 60_000
HORIZONS_MIN = (10, 30)                 # 30 = PRIMARY, 10 = secondary (descriptive)
PRIMARY_MIN = 30
MAX_ENTRY_DELAY_MS = 90_000
MAX_LATE_MS = 90_000
MAX_PENDING = 12                        # opportunities followed at once across the desk; beyond it: unknown `capacity`
WINSOR_PCT = 200.0
FLATTEN_HHMM = (15, 45)
FLAG_BARS, IMPULSE_BARS = 4, 6
FLAG_RANGE_ATR, IMPULSE_MIN_ATR = 1.25, 1.5
UNKNOWN = "unknown"


def opportunity_id(date: str, symbol: str, setup_id: str, signal_ts: int) -> str:
    """BOOK-INDEPENDENT identity: the session, the symbol, the setup (its kind and the 15m bar that confirmed it, both
    derived from the tape) and the CLOSE TIME OF THE CONTACT BAR. No per-book counter is used: a book's contact number
    depends on what that book refused earlier (2026-09-18: C1's touch #1 was 10:14, Control's touch #1 was 10:22)."""
    return f"{date}|{str(symbol).upper()}|{setup_id}|{int(signal_ts)}"


def _bars_2m(bars_1m: list, until_ts: int) -> list[dict]:
    """Closed 2m bars built ONLY from 1m bars that closed at or before `until_ts` (purity: nothing after T is read)."""
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
             bars_1m: list, target: float | None, actionable_px: float | None) -> dict:
    """The six frozen features, each `{"value": ..., "inputs": {...}}`; a missing input gives value `unknown` with the reason."""
    long = str(direction) == "long"
    out: dict[str, dict] = {}
    # F-a flag
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
    # F-b level origin
    kind = str(setup_id).split("@")[0]
    origin = "pm" if kind.startswith("pm_break") else ("prior" if kind.startswith("scenario_") else UNKNOWN)
    out["levelOrigin"] = {"value": origin, "inputs": {"setupKind": kind}}
    # F-c wait since confirmation
    if confirmation_close_ts is None or int(confirmation_close_ts) > int(signal_ts):
        out["wait"] = {"value": UNKNOWN, "inputs": {"reason": "no confirmation time at or before the signal"}}
    else:
        m = (int(signal_ts) - int(confirmation_close_ts)) / MIN_MS
        out["wait"] = {"value": "short" if m < 15 else ("medium" if m <= 60 else "long"), "inputs": {"minutes": round(m, 1)}}
    # F-d first fifteen minutes
    t = dt.datetime.fromtimestamp(int(signal_ts) / 1000, ET).time()
    out["first15"] = {"value": "first15" if dt.time(9, 45) <= t < dt.time(10, 0) else "later", "inputs": {"signalEt": t.strftime("%H:%M")}}
    # F-e scenario 4
    out["scenario4"] = {"value": "scenario_4" if kind == "scenario_4" else "other", "inputs": {"setupKind": kind}}
    # F-f room to the target
    if target is None or actionable_px is None or not atr or atr <= 0:
        why = "no target" if target is None else ("no actionable underlying price" if actionable_px is None else "no ATR")
        out["room"] = {"value": UNKNOWN, "inputs": {"reason": why}}
    else:
        r = abs(float(target) - float(actionable_px)) / float(atr)
        out["room"] = {"value": "near" if r < 1.5 else ("mid" if r < 3.0 else "far"), "inputs": {"roomAtr": round(r, 3)}}
    return out


def flatten_ms(date: str) -> int:
    d = dt.date.fromisoformat(date)
    return int(dt.datetime(d.year, d.month, d.day, FLATTEN_HHMM[0], FLATTEN_HHMM[1], tzinfo=ET).timestamp() * 1000)


def open_record(*, date: str, symbol: str, setup_id: str, signal_ts: int, book: dict, trigger: str, direction: str,
                feats: dict, selected: dict | None, shadow: bool, refusal: str | None, recorded_ts: int, pending_now: int,
                inputs: dict | None = None) -> dict:
    """The record written WHEN THE OBSERVATION BEGINS. It is journaled at once, so an opportunity whose follow-ups never
    complete (crash, disarm, restart) still sits in the coverage denominator as `open`/`incomplete`."""
    oid = opportunity_id(date, symbol, setup_id, signal_ts)
    rec = {"study": STUDY, "opportunityId": oid, "date": date, "symbol": str(symbol).upper(), "setup": setup_id, "signalTs": int(signal_ts),
           "trigger": trigger, "direction": direction, "book": book, "shadow": bool(shadow), "refusal": refusal,
           "features": feats, "recordedTs": int(recorded_ts), "inputs": inputs or {}, "observations": {}, "status": "open"}
    sel = selected or {}
    q0 = sel.get("quoteTs")
    entry = {"contract": sel.get("symbol"), "ask": sel.get("ask"), "bid": sel.get("bid"), "quoteTs": q0, "receivedTs": sel.get("receivedTs"),
             "collectedTs": sel.get("collectedTs"), "source": sel.get("source"), "valid": False, "reason": None, "delayMs": None}
    if not sel or not sel.get("symbol"):
        entry["reason"] = "no contract chosen"
    elif not sel.get("priceKnown"):
        entry["reason"] = f"entry quote not valid evidence: {sel.get('priceUnknownReason')}"
    elif not q0:
        entry["reason"] = "entry quote has no source timestamp"
    else:
        delay = int(q0) - int(signal_ts)
        entry["delayMs"] = delay
        if delay < 0:
            entry["reason"] = "entry quote predates the signal"
        elif delay > MAX_ENTRY_DELAY_MS:
            entry["reason"] = f"entry quote {delay} ms after the signal (max {MAX_ENTRY_DELAY_MS})"
        else:
            entry["valid"] = True
    rec["entryQuote"] = entry
    rec["schedule"] = []
    if entry["valid"]:
        fl = flatten_ms(date)
        for h in HORIZONS_MIN:
            due = int(q0) + h * MIN_MS
            row = {"horizonMin": h, "dueTs": due, "status": "pending"}
            if due > fl:
                row.update(status="done")
                rec["observations"][str(h)] = {"horizonMin": h, "dueTs": due, "valid": False, "reason": "late: due after the 15:45 flatten"}
            elif pending_now >= MAX_PENDING:
                row.update(status="done")
                rec["observations"][str(h)] = {"horizonMin": h, "dueTs": due, "valid": False, "reason": "capacity"}
            rec["schedule"].append(row)
    if not any(s["status"] == "pending" for s in rec["schedule"]):
        rec["status"] = "closed"
    return rec


def observe(rec: dict, horizon_min: int, taken_ts: int, quote: dict | None, *, reason: str | None = None) -> dict:
    """Resolve one scheduled observation from a NEW quote `{bid, ask, priced, quoteTs, receivedTs}` (or None with a reason)."""
    row = next(s for s in rec["schedule"] if s["horizonMin"] == horizon_min)
    due = int(row["dueTs"])
    obs = {"horizonMin": horizon_min, "dueTs": due, "takenTs": int(taken_ts), "valid": False, "reason": reason, "quote": quote}
    if reason is None:
        clean, why = diag.quote_check(quote, int(taken_ts))
        sts = int((quote or {}).get("quoteTs") or 0)
        if clean is None:
            obs["reason"] = why
        elif sts < due:
            obs["reason"] = "quote predates its due time"
        elif sts > due + MAX_LATE_MS:
            obs["reason"] = f"late: quote {sts - due} ms after due (max {MAX_LATE_MS})"
        else:
            obs.update(valid=True, reason=None, bid=float(quote["bid"]), ask=float(quote["ask"]), quoteTs=sts, lateMs=sts - due)
    rec["observations"][str(horizon_min)] = obs
    row["status"] = "done"
    if not any(s["status"] == "pending" for s in rec["schedule"]):
        rec["status"] = "closed"
    return obs


def abandon(rec: dict, reason: str, now_ts: int) -> None:
    """Every still-pending observation becomes unknown with `reason` (restart, disarm, session end); the record closes."""
    for s in rec["schedule"]:
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
    """Primary and secondary outcomes of a record, or the reason there is none. Winsorised primary at +WINSOR_PCT."""
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
            else:
                out["secondary"][str(h)] = r
        elif h == PRIMARY_MIN:
            out["primaryReason"] = (o or {}).get("reason") or ("incomplete: no observation recorded" if rec.get("status") != "closed" else "missing")
    return out


def record_hash(rec: dict) -> str:
    import json
    return hashlib.sha256(json.dumps({k: rec.get(k) for k in ("study", "opportunityId", "features", "entryQuote")}, sort_keys=True, default=str).encode()).hexdigest()[:16]


BOOK_PRIORITY = {"control": 0, "sizing": 1, "c1": 2}


def collapse(open_rows: list[dict], close_rows: list[dict]) -> list[dict]:
    """ONE row per opportunity across books, revisions and restarts. `open_rows` are the records journaled when observation
    began, `close_rows` the ones journaled when it ended. The source book is Control's record, else Sizing's, else C1's; an
    opportunity only C1 examined is flagged `c1Only`. An open record with no close stays in the result as `incomplete`, so
    crashes, disarms and unfinished follow-ups remain in the coverage denominator."""
    closed = {}
    for r in close_rows:
        closed[(r.get("opportunityId"), (r.get("book") or {}).get("portfolioId"))] = r
    by: dict[str, list[dict]] = {}
    for r in open_rows:
        by.setdefault(str(r.get("opportunityId")), []).append(r)
    out = []
    for oid, rows in sorted(by.items()):
        rows.sort(key=lambda r: (BOOK_PRIORITY.get(str((r.get("book") or {}).get("role")), 9), int(r.get("recordedTs") or 0)))
        src = rows[0]
        fin = closed.get((oid, (src.get("book") or {}).get("portfolioId")))
        roles = sorted({str((r.get("book") or {}).get("role")) for r in rows})
        out.append({**(fin or src), "complete": fin is not None, "status": (fin or {}).get("status", "incomplete") if fin else "incomplete",
                    "books": roles, "c1Only": roles == ["c1"]})
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
