"""EM source-candidate ledger + evaluator (`source-continuation-v1`, STRATEGY-PROPOSAL-2026-09-14 §1).

ORDER-FREE research: rows are the author's numeric morning ideas, scored on the day's stored 1-minute bars
under the frozen definition. Nothing here arms, sizes or trades; unknowns stay unknown.

    python -m zargar.tools.em_source_candidates add --date 2026-09-14 --symbol MSFT --direction long --level 498.97 \\
        --target 505 --note a5a519f6... --available-at 2026-09-14T09:20:51-04:00 [--retrospective]
    python -m zargar.tools.em_source_candidates evaluate --date 2026-09-14        # read-only DB, writes the result file
    python -m zargar.tools.em_source_candidates show --date 2026-09-14

Ledger: docs/techniques/enhanced-market/research/source-candidates.json (one list of rows).
Results: docs/techniques/enhanced-market/research/source-candidates-<date>.result.json.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys

VERSION = "source-continuation-v1"
ET = dt.timezone(dt.timedelta(hours=-4))            # the research clock is ET; bars carry ms epochs
OPENING_RANGE_MINUTES = 5                             # stop = low of the first five completed minutes (09:30-09:34)
NO_CHASE_PCT = 0.5                                    # executable entry may not exceed level * (1 + 0.5%)
RETEST_TOLERANCE = 0.10                               # a retest = a low within level + 0.10 after the confirming close
MIN_RR = 3.0                                          # EM's R2 gate to the author's target with OUR stop
CONFIRM_DEADLINE = (11, 30)                           # R6 prime window: unconfirmed by 11:30 ET -> expired
FLATTEN = (15, 55)                                    # the baseline flatten clock (flattenMinutesBeforeClose=5)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
LEDGER = os.path.join(ROOT, "docs", "techniques", "enhanced-market", "research", "source-candidates.json")


def _hm(ms: int) -> tuple[int, int]:
    d = dt.datetime.fromtimestamp(ms / 1000, ET)
    return d.hour, d.minute


def _label(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, ET).strftime("%H:%M")


def evaluate_candidate(bars: list[dict], row: dict) -> dict:
    """Score one row on one session's 1-minute bars (dicts with ts/open/high/low/close). Pure.

    Outcomes: unknown (no bars) | early_cross_only | never_confirmed | expired | no_chase_refused |
    gated (fails the R2 gate) | target | stopped | flattened. Every intermediate observation is listed."""
    rth = [b for b in bars if (9, 30) <= _hm(b["ts"]) < (16, 0)]
    out = {"version": VERSION, "symbol": row["symbol"], "date": row["date"], "direction": row.get("direction", "long"),
           "level": row["level"], "target": row.get("target"), "observations": [], "outcome": "unknown", "why": None}
    if len(rth) < OPENING_RANGE_MINUTES + 1:
        out["why"] = f"{len(rth)} RTH bars stored - not enough to know the opening range"
        return out
    long = str(row.get("direction", "long")) == "long"
    level = float(row["level"])
    target = float(row["target"]) if row.get("target") is not None else None
    opening = rth[:OPENING_RANGE_MINUTES]
    stop = min(b["low"] for b in opening) if long else max(b["high"] for b in opening)
    out["stop"] = stop
    out["stopKnownAt"] = _label(rth[OPENING_RANGE_MINUTES]["ts"])          # the first minute after the range
    eligible_from = OPENING_RANGE_MINUTES
    crosses_before = [b for b in rth[:eligible_from] if (b["high"] > level if long else b["low"] < level)]
    if crosses_before:
        out["observations"].append({"at": _label(crosses_before[0]["ts"]), "event": "early_cross",
                                    "note": "before the opening range was complete - recorded, not entered"})

    def beyond(b):
        return b["close"] > level if long else b["close"] < level

    def stopped(b):
        return b["close"] < stop if long else b["close"] > stop

    def hit_target(b):
        return target is not None and (b["high"] >= target if long else b["low"] <= target)

    i = eligible_from
    entered = None
    retest_armed = False
    while i < len(rth):
        b = rth[i]
        if _hm(b["ts"]) >= CONFIRM_DEADLINE:
            out["outcome"] = "never_confirmed"
            out["why"] = f"no completed close beyond the level by {CONFIRM_DEADLINE[0]:02d}:{CONFIRM_DEADLINE[1]:02d} ET"
            return out
        if beyond(b):
            if i + 1 >= len(rth):
                out["outcome"] = "unknown"; out["why"] = "confirming close is the last stored bar"; return out
            nxt = rth[i + 1]
            entry_px = float(nxt["open"])
            out["observations"].append({"at": _label(b["ts"]), "event": "confirmed_close", "close": b["close"]})
            cap = level * (1 + NO_CHASE_PCT / 100) if long else level * (1 - NO_CHASE_PCT / 100)
            if (entry_px > cap + 1e-9) if long else (entry_px < cap - 1e-9):
                if retest_armed:
                    out["outcome"] = "no_chase_refused"
                    out["why"] = f"next open {entry_px} beyond the no-chase cap {cap:.2f} after the one allowed retest"
                    return out
                out["observations"].append({"at": _label(nxt["ts"]), "event": "no_chase_wait_retest", "open": entry_px, "cap": round(cap, 4)})
                retest_armed = True
                # wait for a retest: a low within tolerance of the level, then the next confirming close re-enters here
                j = i + 1
                while j < len(rth) and not ((rth[j]["low"] <= level + RETEST_TOLERANCE) if long else (rth[j]["high"] >= level - RETEST_TOLERANCE)):
                    j += 1
                if j >= len(rth):
                    out["outcome"] = "no_chase_refused"; out["why"] = "no retest before the close"; return out
                out["observations"].append({"at": _label(rth[j]["ts"]), "event": "retest"})
                i = j + 1
                continue
            entered = {"at": _label(nxt["ts"]), "entry": entry_px, "basis": "next-open-proxy"}
            break
        i += 1
    if entered is None:
        out["outcome"] = "never_confirmed"; out["why"] = "no completed close beyond the level in the eligible window"
        return out
    out["entry"] = entered
    risk = (entered["entry"] - stop) if long else (stop - entered["entry"])
    out["riskPerShare"] = round(risk, 4)
    if risk <= 0:
        out["outcome"] = "gated"; out["why"] = "entry is on the wrong side of the stop"; return out
    rr = ((target - entered["entry"]) / risk if long else (entered["entry"] - target) / risk) if target is not None else None
    out["rewardToRisk"] = round(rr, 3) if rr is not None else None
    if rr is None:
        out["outcome"] = "unknown"; out["why"] = "the author gave no target"; return out
    if rr < MIN_RR:
        out["outcome"] = "gated"; out["why"] = f"{rr:.2f}R to the author's target with our stop is below the {MIN_RR:g}R gate"
        # still walk the path for the record (what the gated candidate would have done)
    start = next(k for k, b in enumerate(rth) if _label(b["ts"]) == entered["at"])
    for b in rth[start:]:
        if _hm(b["ts"]) >= FLATTEN:
            r = ((b["close"] - entered["entry"]) / risk) if long else ((entered["entry"] - b["close"]) / risk)
            out["path"] = {"end": "flattened", "at": _label(b["ts"]), "price": b["close"], "r": round(r, 2)}
            break
        if stopped(b):
            r = ((b["close"] - entered["entry"]) / risk) if long else ((entered["entry"] - b["close"]) / risk)
            out["path"] = {"end": "stopped", "at": _label(b["ts"]), "price": b["close"], "r": round(r, 2)}
            break
        if hit_target(b):
            out["path"] = {"end": "target", "at": _label(b["ts"]), "price": target, "r": round(rr, 2)}
            break
    else:
        out["path"] = {"end": "unknown", "why": "bars end before a terminal event"}
    if out["outcome"] != "gated":
        out["outcome"] = out["path"]["end"]
    return out


def load_ledger() -> list[dict]:
    if not os.path.exists(LEDGER):
        return []
    return json.load(open(LEDGER, encoding="utf-8"))


def save_ledger(rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    json.dump(rows, open(LEDGER, "w", encoding="utf-8"), indent=1)


async def _bars(symbol: str, date: str) -> list[dict]:
    from ..config import AppConfig
    from ..db import make_engine, make_session_factory
    from sqlalchemy import text
    db = make_engine(AppConfig().database_url)
    try:
        sf = make_session_factory(db)
        async with sf() as session:
            await session.execute(text("set transaction read only"))
            day = dt.date.fromisoformat(date)
            a = int(dt.datetime(day.year, day.month, day.day, 9, 0, tzinfo=ET).timestamp() * 1000)
            b = int(dt.datetime(day.year, day.month, day.day, 16, 30, tzinfo=ET).timestamp() * 1000)
            rows = (await session.execute(text(
                "select ts, open, high, low, close from bars where symbol=:s and tf='1m' and ts>=:a and ts<:b order by ts"),
                {"s": symbol, "a": a, "b": b})).all()
            return [{"ts": int(r[0]), "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])} for r in rows]
    finally:
        await db.dispose()


async def evaluate(date: str) -> list[dict]:
    rows = [r for r in load_ledger() if r.get("date") == date]
    results = []
    for r in rows:
        bars = await _bars(r["symbol"], date)
        res = evaluate_candidate(bars, r)
        res.update({"noteId": r.get("note"), "availableAt": r.get("availableAt"), "retrospective": bool(r.get("retrospective"))})
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
    a.add_argument("--retrospective", action="store_true", help="the row was written after the session's outcome was seen")
    e = sub.add_parser("evaluate"); e.add_argument("--date", required=True)
    s = sub.add_parser("show"); s.add_argument("--date", required=True)
    args = p.parse_args(argv)
    if args.cmd == "add":
        rows = load_ledger()
        rows.append({"date": args.date, "symbol": args.symbol.upper(), "direction": args.direction, "level": float(args.level),
                     "target": (float(args.target) if args.target else None), "note": args.note, "availableAt": args.available_at,
                     "horizon": args.horizon, "retrospective": bool(args.retrospective), "version": VERSION,
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
              f"{r.get('why') or ''} entry={r.get('entry')} stop={r.get('stop')} rr={r.get('rewardToRisk')} path={r.get('path')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
