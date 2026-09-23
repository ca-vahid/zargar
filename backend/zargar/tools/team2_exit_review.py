"""After-close exit review for Team2 — read-only, order-free.

For every Team2 exit on a session: who decided it, the fill and the exit price, whether the 2-minute
structure the entry leaned on was still intact at the moment of exit, when structure actually broke,
and what the held contract did afterwards.

Why this exists (2026-09-22): a live premium stop closed a trade whose structure was intact and whose
contract then nearly reached its first trim. The registered replay (H6) found the premium stop's
width is NOT where Team2 loses money over 69 sessions — but the replay judges the stop at 2-minute
closes and the live desk judges it every ~2 seconds, so the live stop may cut intact trades more
often than the replay can see. This report counts that directly, session by session, so the question
is answered by prospective evidence rather than by one memorable trade.

The contract path uses stored 1-minute bars (real prints). It is evidence about what happened, never
a fill: "what a different exit would have got" is an estimate and is labelled as one.

    python -m zargar.tools.team2_exit_review 2026-09-22
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json

ET = dt.timezone(dt.timedelta(hours=-4))
K13 = 2 / 14
TWO_MIN = 120_000


def ema_path(bars1m: list[tuple], seed_ts: int, seed_ema: float, open_ms: int) -> list[dict]:
    """2-minute closes after `seed_ts`, with EMA13 rolled forward from the value the fire itself
    journalled. Pure. Seeding from the journalled value means no warm-up assumption is made here."""
    two: dict[int, float] = {}
    for ts, _o, _h, _l, c in bars1m:
        b = open_ms + ((ts - open_ms) // TWO_MIN) * TWO_MIN
        two[b] = float(c)                      # last close in the bucket
    out, e = [], float(seed_ema)
    for b in sorted(two):
        if b < seed_ts:
            continue
        if b > seed_ts:
            e = two[b] * K13 + e * (1 - K13)
        out.append({"closeTs": b + TWO_MIN, "close": two[b], "ema13": e})
    return out


def judge(path: list[dict], exit_ms: int, direction: str) -> dict:
    """Was structure intact at the exit, and when did it first break? Pure."""
    long = direction != "short"
    before = [p for p in path if p["closeTs"] <= exit_ms]
    last = before[-1] if before else None
    intact = None if last is None else ((last["close"] >= last["ema13"]) if long else (last["close"] <= last["ema13"]))
    brk = next((p for p in path if ((p["close"] < p["ema13"]) if long else (p["close"] > p["ema13"]))), None)
    return {"structureIntactAtExit": intact, "lastCloseBeforeExit": last,
            "structuralBreakTs": brk["closeTs"] if brk else None}


def after_exit(opt1m: list[tuple], exit_ms: int, until_ms: int) -> dict:
    """What the held contract did after the exit, from stored prints. Pure."""
    rows = [r for r in opt1m if exit_ms < r[0] <= until_ms]
    if not rows:
        return {"bars": 0}
    hi = max(rows, key=lambda r: r[2])
    return {"bars": len(rows), "maxHigh": float(hi[2]), "maxHighTs": int(hi[0]),
            "minLow": float(min(r[3] for r in rows)), "lastClose": float(rows[-1][4])}


async def review(sf, day: str) -> list[dict]:
    from sqlalchemy import text
    d = dt.date.fromisoformat(day)
    lo = dt.datetime.combine(d, dt.time(13, 0), dt.timezone.utc)
    hi = dt.datetime.combine(d, dt.time(21, 0), dt.timezone.utc)
    open_ms = int(dt.datetime.combine(d, dt.time(9, 30), ET).timestamp() * 1000)
    close_ms = int(dt.datetime.combine(d, dt.time(16, 0), ET).timestamp() * 1000)
    async with sf() as s:
        fires = (await s.execute(text("""select ts, payload from events where type='TechniquePlanTriggerFired'
            and ts >= :lo and ts < :hi and payload->>'symbol' in ('SPY','QQQ','IWM') order by ts"""), {"lo": lo, "hi": hi})).all()
        exits = (await s.execute(text("""select ts, payload from events where type='TechniquePlanExit'
            and ts >= :lo and ts < :hi and payload->>'symbol' in ('SPY','QQQ','IWM') order by ts"""), {"lo": lo, "hi": hi})).all()
        contracts = (await s.execute(text("""select payload->>'trigger', payload->>'contract', payload->>'symbol'
            from events where type='TechniquePlanContract' and ts >= :lo and ts < :hi
              and payload->>'event' = 'contract_picked'"""), {"lo": lo, "hi": hi})).all()
        fills = (await s.execute(text("""select ts, symbol, side, price from executions
            where ts >= :lo and ts < :hi order by ts"""), {"lo": lo, "hi": hi})).all()
        bars_cache: dict[str, list] = {}

        async def bars(sym):
            if sym not in bars_cache:
                bars_cache[sym] = [tuple(r) for r in (await s.execute(text("""select ts, open, high, low, close from bars
                    where symbol=:s and tf='1m' and ts >= :a and ts <= :b order by ts"""),
                    {"s": sym, "a": open_ms, "b": close_ms})).all()]
            return bars_cache[sym]

        by_trigger = {}
        for ts, p in fires:
            by_trigger.setdefault(p.get("trigger"), p)
        contract_of = {t: c for t, c, _ in contracts if t and c}
        seen, out = set(), []
        for ts, p in exits:
            trig = p.get("trigger")
            key = (trig, p.get("kind"))
            if key in seen:                   # one exit DECISION per trigger and kind, not one per book
                continue
            seen.add(key)
            f = by_trigger.get(trig) or {}
            rg = ((f.get("trace") or [{}])[0].get("regime") or {})
            direction = "short" if str(f.get("kind", "")).endswith(("4", "down")) else "long"
            ex_ms = int(ts.timestamp() * 1000)
            row = {"trigger": trig, "symbol": p.get("symbol"), "kind": p.get("kind"),
                   "exitEt": ts.astimezone(ET).strftime("%H:%M:%S"),
                   "authority": (p.get("authority") or {}).get("authority"),
                   "decidedBy": (p.get("authority") or {}).get("decidedBy"),
                   "fillBasis": (p.get("authority") or {}).get("fillBasis"),
                   "reason": str(p.get("reason") or "")[:140]}
            if rg.get("ema13") is not None and rg.get("ts"):
                path = ema_path(await bars(p.get("symbol")), int(rg["ts"]), float(rg["ema13"]), open_ms)
                j = judge(path, ex_ms, direction)
                row["structureIntactAtExit"] = j["structureIntactAtExit"]
                row["structuralBreakEt"] = (dt.datetime.fromtimestamp(j["structuralBreakTs"] / 1000, ET).strftime("%H:%M")
                                            if j["structuralBreakTs"] else None)
                # intact at the instant of exit is not the same as intact: a break on the very next 2m close means the
                # structural stop was about to act anyway, so the premium stop only got there first
                gap = (j["structuralBreakTs"] - ex_ms) if j["structuralBreakTs"] else None
                row["minutesUntilStructuralBreak"] = round(gap / 60000, 1) if gap is not None else None
                row["cutAheadOfStructure"] = bool(j["structureIntactAtExit"] and (gap is None or gap > TWO_MIN))
            occ = contract_of.get(trig)
            if occ:
                sells = [r for r in fills if r[1] == occ and r[2] == "SELL" and abs(r[0].timestamp() * 1000 - ex_ms) < 60_000]
                row["contract"] = occ
                row["exitPrice"] = float(sells[0][3]) if sells else None
                row["afterExit30m"] = after_exit(await bars(occ), ex_ms, ex_ms + 30 * 60_000)
            out.append(row)
    return out


def summarise(rows: list[dict]) -> dict:
    prem = [r for r in rows if r.get("authority") == "live premium stop"]
    ahead = [r for r in prem if r.get("cutAheadOfStructure") is True]
    return {"exits": len(rows), "livePremiumStops": len(prem),
            "livePremiumStopsCutAheadOfStructure": len(ahead),
            "definition": ("a live premium stop whose 2m structure was intact at the exit AND did not break within the "
                           "next 2m close - the case the H6 replay could not see"),
            "note": ("counts exit DECISIONS, one per trigger across books; the contract path is stored prints, "
                     "never a fill")}


async def _amain(a) -> int:
    from ..config import get_config
    from ..db import make_engine, make_session_factory
    eng = make_engine(get_config().database_url)
    try:
        rows = await review(make_session_factory(eng), a.date)
    finally:
        await eng.dispose()
    print(json.dumps({"date": a.date, "summary": summarise(rows), "exits": rows}, indent=1, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only Team2 exit review for one session.")
    ap.add_argument("date", help="YYYY-MM-DD")
    return asyncio.run(_amain(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
