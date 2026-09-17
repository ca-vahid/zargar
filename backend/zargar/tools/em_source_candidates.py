"""EM source-candidate ledger + evaluator (`source-continuation-v1`, STRATEGY-PROPOSAL-2026-09-14 §1).

ORDER-FREE research: rows are the author's numeric morning ideas, scored on the day's stored 1-minute bars
under the frozen definition. Nothing here arms, sizes or trades; unknowns stay unknown.

Temporal evidence rules (FM-05 / SE-01 / SE-02, 2026-09-15):
- a candidate is eligible only after BOTH the opening range is complete AND the source was available
  (`availableAt`, timezone-aware; missing or unparseable availability = unknown for a forward result);
- the bars must belong to the row's New York session date, be unique and ordered; the opening range needs all
  five 09:30-09:34 minutes; the next-open proxy needs the IMMEDIATELY following minute; a gap inside the path
  from entry to the terminal event is an unresolved interval = unknown. Missing minutes are never replaced by
  later bars.
- the result reports the underlying path and, per gate, evaluated | passed | failed | not_evaluated: only R2 is
  evaluated here; option NBBO/liquidity, the daily budget and final dispatch are NOT - a `target` path is not a
  fully admitted option trade.

    python -m zargar.tools.em_source_candidates add --date 2026-09-14 --symbol MSFT --direction long --level 498.97 \\
        --target 505 --note a5a519f6... --available-at 2026-09-14T09:20:51-04:00 [--retrospective]
    python -m zargar.tools.em_source_candidates evaluate --date 2026-09-14        # read-only DB, writes the result file
    python -m zargar.tools.em_source_candidates show --date 2026-09-14
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

VERSION = "source-continuation-v1"
NY = ZoneInfo("America/New_York")
OPENING_RANGE_MINUTES = 5                             # stop = low of the first five completed minutes (09:30-09:34)
NO_CHASE_PCT = 0.5                                    # executable entry may not exceed level * (1 + 0.5%)
RETEST_TOLERANCE = 0.10                               # a retest = a low within level + 0.10 after the confirming close
MIN_RR = 3.0                                          # EM's R2 gate to the author's target with OUR stop
CONFIRM_DEADLINE = (11, 30)                           # R6 prime window: unconfirmed by 11:30 ET -> never_confirmed
FLATTEN = (15, 55)                                    # the baseline flatten clock (flattenMinutesBeforeClose=5)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
LEDGER = os.path.join(ROOT, "docs", "techniques", "enhanced-market", "research", "source-candidates.json")
GATES_NOT_EVALUATED = ("optionLiquidity", "dailyBudget", "finalDispatch", "contractSelection")


def _ny(ms: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ms / 1000, NY)


def _hm(ms: int) -> tuple[int, int]:
    d = _ny(ms)
    return d.hour, d.minute


def _label(ms: int) -> str:
    return _ny(ms).strftime("%H:%M")


def parse_available(s) -> dt.datetime | None:
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None                    # a naive availability is ambiguous -> unknown


def _unknown(out: dict, why: str) -> dict:
    out["outcome"] = "unknown"
    out["why"] = why
    return out


def evaluate_candidate(bars: list[dict], row: dict) -> dict:
    """Score one row on one session's 1-minute bars (dicts with ts/open/high/low/close). Pure."""
    out = {"version": VERSION, "symbol": row["symbol"], "date": row["date"], "direction": row.get("direction", "long"),
           "level": row["level"], "target": row.get("target"), "availableAt": row.get("availableAt"),
           "observations": [], "outcome": "unknown", "why": None, "path": None,
           "gates": {"r2": "not_evaluated", **{g: "not_evaluated" for g in GATES_NOT_EVALUATED}},
           "evidence": {"barCount": len(bars), "provenance": row.get("barsProvenance", "bars table, tf=1m")}}
    available = parse_available(row.get("availableAt"))
    if available is None:
        return _unknown(out, "source availability missing or ambiguous - no as-of result")
    session = dt.date.fromisoformat(row["date"])
    # ---- bar validity: this session, unique, ordered, RTH minutes only
    rth = []
    seen_ts = set()
    prev = None
    for b in sorted(bars, key=lambda x: x["ts"]):
        d = _ny(int(b["ts"]))
        if d.date() != session:
            return _unknown(out, f"a bar belongs to another session ({d.date()})")
        if (9, 30) <= (d.hour, d.minute) < (16, 0):
            if b["ts"] in seen_ts:
                return _unknown(out, "duplicate minute in the stored bars")
            if int(b["ts"]) % 60000 != 0:
                return _unknown(out, "a bar is not minute-aligned")
            seen_ts.add(b["ts"]); rth.append(b)
    if not rth:
        return _unknown(out, "no RTH bars stored")
    day0 = int(dt.datetime(session.year, session.month, session.day, 9, 30, tzinfo=NY).timestamp() * 1000)
    by_ts = {int(b["ts"]): b for b in rth}

    def minute(i: int):
        return by_ts.get(day0 + i * 60000)

    # ---- opening range: all five 09:30-09:34 minutes must exist
    opening = [minute(i) for i in range(OPENING_RANGE_MINUTES)]
    if any(b is None for b in opening):
        missing = [_label(day0 + i * 60000) for i, b in enumerate(opening) if b is None]
        return _unknown(out, f"opening range incomplete - missing {missing}; the stop is unknown")
    long = str(row.get("direction", "long")) == "long"
    level = float(row["level"])
    target = float(row["target"]) if row.get("target") is not None else None
    stop = min(b["low"] for b in opening) if long else max(b["high"] for b in opening)
    out["stop"] = stop
    range_complete_ms = day0 + OPENING_RANGE_MINUTES * 60000            # the 09:34 bar is complete at 09:35:00
    out["stopKnownAt"] = _label(range_complete_ms)
    # ---- eligibility: opening range complete AND the source available; a bar is usable once it has CLOSED
    avail_ms = int(available.timestamp() * 1000)
    out["eligibleFrom"] = _label(max(range_complete_ms, avail_ms))
    crosses_before = [b for b in opening if (b["high"] > level if long else b["low"] < level)]
    if crosses_before:
        out["observations"].append({"at": _label(crosses_before[0]["ts"]), "event": "early_cross",
                                    "note": "before the opening range was complete - recorded, not entered"})

    def usable(b) -> bool:                                             # its close is known after the minute ends
        return (int(b["ts"]) + 60000) >= max(range_complete_ms, avail_ms)

    def beyond(b):
        return b["close"] > level if long else b["close"] < level

    def stopped(b):
        return b["close"] < stop if long else b["close"] > stop

    def hit_target(b):
        return target is not None and (b["high"] >= target if long else b["low"] <= target)

    # ---- CONTIGUOUS walk from the first eligible minute (MF-03): every eligible minute up to the confirmation,
    #      through any retest, and up to the deadline must be stored - an unseen eligible minute could hold the
    #      confirmation, a no-chase event or a stop, so the result is unknown, never a later substitute
    eligible_ms = max(range_complete_ms, avail_ms)
    t = range_complete_ms                                   # the 09:35 bar is the first that can confirm
    while t + 60000 < eligible_ms:
        t += 60000
    if t not in by_ts:
        if (t // 60000) * 60000 >= day0 + 390 * 60000 or _hm(t) >= CONFIRM_DEADLINE:
            return _unknown(out, "no observation after the source became available and the opening range completed")
    entered = None
    retest_armed = False
    while True:
        if _hm(t) >= CONFIRM_DEADLINE:
            out["outcome"] = "never_confirmed"
            out["why"] = f"no completed close beyond the level by {CONFIRM_DEADLINE[0]:02d}:{CONFIRM_DEADLINE[1]:02d} ET"
            return out
        b = by_ts.get(t)
        if b is None:
            return _unknown(out, f"eligible minute {_label(t)} is not stored - it could contain the confirmation, a retest or a stop")
        if beyond(b):
            nxt = by_ts.get(t + 60000)
            out["observations"].append({"at": _label(t), "event": "confirmed_close", "close": b["close"]})
            if nxt is None:
                return _unknown(out, f"the minute after the confirming close ({_label(t + 60000)}) is not stored - no next-open proxy")
            entry_px = float(nxt["open"])
            cap = level * (1 + NO_CHASE_PCT / 100) if long else level * (1 - NO_CHASE_PCT / 100)
            if (entry_px > cap + 1e-9) if long else (entry_px < cap - 1e-9):
                if retest_armed:
                    out["outcome"] = "no_chase_refused"
                    out["why"] = f"next open {entry_px} beyond the no-chase cap {cap:.2f} after the one allowed retest"
                    return out
                out["observations"].append({"at": _label(t + 60000), "event": "no_chase_wait_retest", "open": entry_px, "cap": round(cap, 4)})
                retest_armed = True
                u = t + 60000
                while True:                                 # contiguous retest search
                    if _hm(u) >= (16, 0):
                        out["outcome"] = "no_chase_refused"; out["why"] = "no retest before the close"; return out
                    rb = by_ts.get(u)
                    if rb is None:
                        return _unknown(out, f"minute {_label(u)} is not stored during the retest wait")
                    if (rb["low"] <= level + RETEST_TOLERANCE) if long else (rb["high"] >= level - RETEST_TOLERANCE):
                        out["observations"].append({"at": _label(u), "event": "retest"})
                        break
                    u += 60000
                t = u + 60000
                continue
            entered = {"at": _label(t + 60000), "ts": int(t + 60000), "entry": entry_px, "basis": "next-open-proxy"}
            break
        t += 60000
    if entered is None:
        out["outcome"] = "never_confirmed"; out["why"] = "no completed close beyond the level in the eligible window"
        return out
    out["entry"] = {k: v for k, v in entered.items() if k != "ts"}
    risk = (entered["entry"] - stop) if long else (stop - entered["entry"])
    out["riskPerShare"] = round(risk, 4)
    if risk <= 0:
        out["outcome"] = "gated"; out["gates"]["r2"] = "failed"; out["why"] = "entry is on the wrong side of the stop"; return out
    rr = ((target - entered["entry"]) / risk if long else (entered["entry"] - target) / risk) if target is not None else None
    out["rewardToRisk"] = round(rr, 3) if rr is not None else None
    if rr is None:
        return _unknown(out, "the author gave no target - R2 cannot be evaluated")
    out["gates"]["r2"] = "passed" if rr >= MIN_RR else "failed"
    if rr < MIN_RR:
        out["outcome"] = "gated"; out["why"] = f"{rr:.2f}R to the author's target with our stop is below the {MIN_RR:g}R gate"
    # ---- terminal walk over CONTIGUOUS minutes from the entry; a gap = unresolved interval
    t = entered["ts"]
    while True:
        b = by_ts.get(t)
        if b is None:
            out["path"] = {"end": "unknown", "at": _label(t), "why": "minute not stored - the interval could contain a stop, target or flatten"}
            break
        if _hm(t) >= FLATTEN:
            r = ((b["close"] - entered["entry"]) / risk) if long else ((entered["entry"] - b["close"]) / risk)
            out["path"] = {"end": "flattened", "at": _label(t), "price": b["close"], "r": round(r, 2)}; break
        if stopped(b):
            r = ((b["close"] - entered["entry"]) / risk) if long else ((entered["entry"] - b["close"]) / risk)
            out["path"] = {"end": "stopped", "at": _label(t), "price": b["close"], "r": round(r, 2)}; break
        if hit_target(b):
            out["path"] = {"end": "target", "at": _label(t), "price": target, "r": round(rr, 2)}; break
        t += 60000
        if _hm(t) >= (16, 0):
            out["path"] = {"end": "unknown", "why": "bars end before a terminal event"}; break
    if out["outcome"] != "gated":
        out["outcome"] = out["path"]["end"]
    if out["path"]["end"] == "unknown" and out["outcome"] == "gated":
        out["why"] += "; path unresolved (missing minute)"
    return out


def load_ledger() -> list[dict]:
    if not os.path.exists(LEDGER):
        return []
    return json.load(open(LEDGER, encoding="utf-8"))


def save_ledger(rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    json.dump(rows, open(LEDGER, "w", encoding="utf-8"), indent=1)


async def _bars(symbol: str, date: str) -> tuple[list[dict], dict]:
    from ..config import AppConfig
    from ..db import make_engine, make_session_factory
    from sqlalchemy import text
    db = make_engine(AppConfig().database_url)
    try:
        sf = make_session_factory(db)
        async with sf() as session:
            await session.execute(text("set transaction read only"))
            day = dt.date.fromisoformat(date)
            a = int(dt.datetime(day.year, day.month, day.day, 9, 0, tzinfo=NY).timestamp() * 1000)
            b = int(dt.datetime(day.year, day.month, day.day, 16, 30, tzinfo=NY).timestamp() * 1000)
            rows = (await session.execute(text(
                "select ts, open, high, low, close, source from bars where symbol=:s and tf='1m' and ts>=:a and ts<:b order by ts"),
                {"s": symbol, "a": a, "b": b})).all()
            sources = sorted({str(r[5]) for r in rows})
            ver = None
            try:
                ver = (await session.execute(text("select value from settings where key='marketdata.dataset_version'"))).scalar()
            except Exception:                              # noqa: BLE001 - optional identity
                ver = None
            return ([{"ts": int(r[0]), "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])} for r in rows],
                    {"sources": sources, "datasetVersion": ver, "provenance": "bars table, tf=1m"})
    finally:
        await db.dispose()


async def evaluate(date: str) -> list[dict]:
    rows = [r for r in load_ledger() if r.get("date") == date]
    results = []
    for r in rows:
        bars, meta = await _bars(r["symbol"], date)
        res = evaluate_candidate(bars, {**r, "barsProvenance": meta["provenance"]})
        res["evidence"].update({"sources": meta["sources"], "datasetVersion": meta["datasetVersion"]})
        res.update({"noteId": r.get("note"), "retrospective": bool(r.get("retrospective")), "ledgerVersion": r.get("version")})
        results.append(res)
    out = os.path.join(os.path.dirname(LEDGER), f"source-candidates-{date}.result.json")
    json.dump({"version": VERSION, "date": date, "evaluatedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "rows": results},
              open(out, "w", encoding="utf-8"), indent=1)
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="EM source-candidate ledger (order-free research)")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    for k in ("--date", "--symbol", "--direction", "--level", "--note", "--available-at"):
        a.add_argument(k, required=True)
    a.add_argument("--target")
    a.add_argument("--horizon", default="intraday")
    a.add_argument("--conditions", default=None, help="the author's stated condition for the level (verbatim); omitted = recorded as missing")
    a.add_argument("--retrospective", action="store_true", help="the row was written after the session's outcome was seen")
    a.add_argument("--author", default="enhancedmarket", help="who posted the level (the EM author by default; other Discord contributors are recorded apart)")
    e = sub.add_parser("evaluate"); e.add_argument("--date", required=True)
    s = sub.add_parser("show"); s.add_argument("--date", required=True)
    args = p.parse_args(argv)
    if args.cmd == "add":
        if parse_available(args.available_at) is None:
            print("refused: --available-at must be a timezone-aware ISO timestamp"); return 2
        rows = load_ledger()
        rows.append({"date": args.date, "symbol": args.symbol.upper(), "direction": args.direction, "level": float(args.level),
                     "target": (float(args.target) if args.target else None), "note": args.note, "availableAt": args.available_at,
                     "horizon": args.horizon, "conditions": (args.conditions or None), "retrospective": bool(args.retrospective), "version": VERSION,
                     "author": args.author,
                     "addedAt": dt.datetime.now(dt.timezone.utc).isoformat()})
        save_ledger(rows)
        print(f"added; ledger now {len(rows)} row(s)")
        return 0
    if args.cmd == "show":
        for r in load_ledger():
            if r.get("date") == args.date:
                print(json.dumps(r))
        return 0
    results = asyncio.run(evaluate(args.date))
    for r in results:
        print(f"{r['date']} {r['symbol']:5} {r['direction']:5} level {r['level']} target {r.get('target')} -> {r['outcome']:16} "
              f"{r.get('why') or ''} entry={r.get('entry')} stop={r.get('stop')} rr={r.get('rewardToRisk')} gates={r['gates']} path={r.get('path')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
