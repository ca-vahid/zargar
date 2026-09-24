"""P-B study (2026-09-23): would moving the stop to the PRIOR CLOSE after a large favourable gap have kept more?

Read-only, no model calls. For every tip SHARE position in a non-quarantined book, every session it was held after its
entry day: R = entry - stop; a qualifying gap = (open - prior close) >= `--min-r` x R in our favour (long). The
alternative rule moves the stop to max(stop, prior close) at 09:30. Walking that session's 1-minute bars, if a bar's low
reaches the new stop the alternative exits the shares still held there (at the new stop, or the bar's open when it
opened below it). The actual outcome for the same shares is the average price at which they really left (later exits),
or the latest close for shares still held. Only the qualifying session is simulated; later days are identical in both.

Caveats printed with the result: the stop is the one JOURNALED in force that morning (adoption + policy changes);
trailing moves inside the manager are not journaled and are not seen. A sample this small gives direction only.

    python -m zargar.tools.tip_gap_stop_study [--min-r 1.0]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def stop_at(history: list[tuple[int, float]], ts_ms: int) -> float | None:
    """Pure: the stop in force at `ts_ms` from [(ts_ms, stop)] (adoption first, then every policy change)."""
    cur = None
    for t, v in sorted(history):
        if t <= ts_ms:
            cur = v
    return cur


def simulate(entry: float, stop: float, prev_close: float, bars: list[tuple], held: float,
             later_exit_avg: float, min_r: float = 1.0, r_stop: float | None = None) -> dict | None:
    """Pure. `bars` = [(open, low, close)] of the session from 09:30; `stop` = the stop in force that morning; R is
    measured from `r_stop` (the INITIAL stop) when given. Returns the case, or None when no qualifying gap."""
    r = entry - (r_stop if r_stop is not None else stop)
    if r <= 0 or not bars or held <= 0:
        return None
    gap_r = (bars[0][0] - prev_close) / r
    if gap_r < min_r:
        return None
    if prev_close <= stop:
        return None                    # the stop in force is already at/above the prior close: the rule changes nothing
    new_stop = prev_close
    alt = None
    for o, lo, _c in bars:
        if lo <= new_stop:
            alt = min(o, new_stop)
            break
    delta = (alt - later_exit_avg) * held if alt is not None else 0.0
    return {"gapR": round(gap_r, 2), "open": bars[0][0], "prevClose": prev_close, "newStop": round(new_stop, 4),
            "altExit": alt, "actualAvg": round(later_exit_avg, 4), "held": held, "delta": round(delta, 2)}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--min-r", type=float, default=1.0)
    a = ap.parse_args()
    import asyncpg
    from ..marketstructure import market_calendar as mc
    c = await asyncpg.connect(a.db, server_settings={"default_transaction_read_only": "on"})
    cases, skipped = [], {"no_r": 0, "no_bars": 0}
    try:
        rows = await c.fetch("""select mp.id, mp.symbol, p.name, mp.legs, mp.config, mp.state from managed_positions mp
                                join portfolios p on p.id = mp.portfolio_id
                                where mp.technique = 'tip' and not coalesce(p.quarantined, false)""")
        for r in rows:
            legs = r["legs"] if isinstance(r["legs"], list) else json.loads(r["legs"] or "[]")
            if not legs or legs[0].get("secType") != "STK":
                continue
            cfg = r["config"] if isinstance(r["config"], dict) else json.loads(r["config"] or "{}")
            st = r["state"] if isinstance(r["state"], dict) else json.loads(r["state"] or "{}")
            entry = float(legs[0].get("avgFill") or 0)
            qty0 = float(legs[0].get("qty") or 0) + sum(float(x.get("filledQty") or x.get("qty") or 0)
                                                         for x in (st.get("exits") or []) if x.get("status") == "FILLED")
            hist = []
            for e in await c.fetch("""select ts, payload from events where aggregate_id = $1 and type in
                                      ('ManagedPositionAdopted', 'ManagedPositionPolicyChanged', 'TipExitPlanUpdated')
                                      order by ts""", r["id"]):
                pl = e["payload"] if isinstance(e["payload"], dict) else json.loads(e["payload"] or "{}")
                sp = ((pl.get("policy") or {}).get("stop") or {}).get("price")
                if sp:
                    hist.append((int(e["ts"].timestamp() * 1000), float(sp)))
            init = hist[0][1] if hist else None
            if not init or entry <= 0 or init >= entry:
                skipped["no_r"] += 1
                continue
            opened = dt.datetime.fromtimestamp((st.get("openedMs") or 0) / 1000, ET)
            closed_ms = st.get("closedMs")
            end = dt.datetime.fromtimestamp(closed_ms / 1000, ET) if closed_ms else dt.datetime.now(ET)
            exits = sorted([x for x in (st.get("exits") or []) if x.get("status") == "FILLED"], key=lambda x: x["ts"])
            day = mc.next_trading_day(opened.date())
            while day <= end.date():
                prev = mc.previous_trading_day(day)
                t0 = int(dt.datetime.combine(prev, dt.time(15, 59), ET).timestamp() * 1000)
                o0 = int(dt.datetime.combine(day, dt.time(9, 30), ET).timestamp() * 1000)
                o1 = int(dt.datetime.combine(day, dt.time(16, 0), ET).timestamp() * 1000)
                pc = await c.fetchval("select close from bars where symbol=$1 and tf='1m' and ts between $2 and $3 order by ts desc limit 1",
                                      r["symbol"], t0 - 30 * 60_000, t0)
                bars = [(float(b["open"]), float(b["low"]), float(b["close"])) for b in await c.fetch(
                    "select open, low, close from bars where symbol=$1 and tf='1m' and ts >= $2 and ts < $3 order by ts",
                    r["symbol"], o0, o1)]
                if pc is None or not bars:
                    skipped["no_bars"] += 1
                    day = mc.next_trading_day(day)
                    continue
                gone = sum(float(x.get("filledQty") or x.get("qty") or 0) for x in exits if x["ts"] < o0)
                held = qty0 - gone
                later = [x for x in exits if x["ts"] >= o0]
                q_l = sum(float(x.get("filledQty") or x.get("qty") or 0) for x in later)
                if later and q_l > 0:
                    avg = sum(float(x["price"]) * float(x.get("filledQty") or x.get("qty") or 0) for x in later) / q_l
                else:
                    avg = bars[-1][2]
                stop = stop_at(hist, o0) or init
                case = simulate(entry, float(stop), float(pc), bars, held, avg, a.min_r, r_stop=init)
                if case:
                    cases.append({"symbol": r["symbol"], "book": r["name"], "day": str(day), "entry": entry,
                                  "stop": float(stop), "initialStop": init, **case})
                day = mc.next_trading_day(day)
    finally:
        await c.close()
    total = round(sum(x["delta"] for x in cases), 2)
    fired = [x for x in cases if x["altExit"] is not None]
    print(f"# Gap-stop study (P-B) - gaps >= {a.min_r:g} R in our favour, stop -> prior close at the open\n")
    print("| symbol | book | day | gap R | prior close | open | alt stop hit? | alt exit | actual avg | shares | delta $ |")
    print("|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|")
    for x in cases:
        print(f"| {x['symbol']} | {x['book']} | {x['day']} | {x['gapR']} | {x['prevClose']:.2f} | {x['open']:.2f} | "
              f"{'yes' if x['altExit'] is not None else 'no'} | {x['altExit'] if x['altExit'] is not None else '-'} | "
              f"{x['actualAvg']:.2f} | {x['held']:g} | {x['delta']:+.2f} |")
    print(f"\nQualifying gaps: {len(cases)}; the alternative stop fired on {len(fired)}; net difference {total:+.2f} "
          f"(positive = the alternative kept more). Skipped: {skipped}. Direction only - journaled stops only (trailing "
          "moves unseen), small sample; no rule changes on this alone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
