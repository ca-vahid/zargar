"""Entry-study fixed horizons (entry-horizons-v1, 2026-09-19): TAKES and SKIPS on ONE evidence standard.

Every `TipEntryStudy` row with phase=created carries the EXECUTABLE ask the decision saw (OPRA, real time), for a
take and a skip alike - so both groups can be scored the same way, from the same starting price, on the same
fixed horizons, instead of judging skips from memorable winners or underlying closes:

  +30 min (first print 30-45 min after the decision), decision-session close (last print in the final 30 min),
  next-session close.

Outcome per contract = (print - ask) / ask and $ = (print - ask) x 100 - round-trip fees. Prints are Yahoo 1m
TRADE prints, NOT NBBO quotes: a print exit is optimistic against a bid exit, and a contract that does not trade
in the window is MISSING, never filled in. Research only - it books nothing and changes no rule.

  .venv/Scripts/python -m zargar.tools.tip_entry_horizons --since 2026-09-11 [--until 2026-09-18] [--json out.json]
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
import json
import re
import statistics
import time

import asyncpg
import httpx

VERSION = "entry-horizons-v1"
ET = dt.timezone(dt.timedelta(hours=-4))
OCC = re.compile(r"^([A-Z.]{1,6})(\d{6})([CP])(\d{8})$")
FEES_ROUND_TRIP = 2.08


def J(v):
    return (json.loads(v) if isinstance(v, str) else v) or {}


def next_session(d: dt.date) -> dt.date:
    n = d + dt.timedelta(days=1)
    while n.weekday() >= 5:
        n += dt.timedelta(days=1)
    return n


def score(t0: dt.datetime, ask: float, prints: list[tuple[dt.datetime, float]] | None) -> dict:
    """Pure: the three horizon prints for one decision. Missing stays None."""
    out = {"p30": None, "pclose": None, "pnext": None, "missing": prints is None}
    if not prints:
        return out
    t0 = t0.astimezone(ET)
    after = [p for p in prints if p[0] >= t0 + dt.timedelta(minutes=30)]
    if after and after[0][0] <= t0 + dt.timedelta(minutes=45):
        out["p30"] = after[0][1]
    day_end = t0.replace(hour=16, minute=0, second=0, microsecond=0)
    same = [p for p in prints if p[0] <= day_end]
    if same and same[-1][0] >= day_end - dt.timedelta(minutes=30):
        out["pclose"] = same[-1][1]
    nxt = [p for p in prints if p[0].date() == next_session(t0.date())]
    if nxt:
        out["pnext"] = nxt[-1][1]
    return out


def dte_bucket(symbol: str, day: dt.date) -> str:
    m = OCC.match(symbol or "")
    if not m:
        return "shares"
    d = (dt.datetime.strptime(m.group(2), "%y%m%d").date() - day).days
    return "0-4" if d <= 4 else "5-14" if d <= 14 else "15-45" if d <= 45 else "46+"


def _fetch(symbol: str, a: dt.datetime, b: dt.datetime):
    for _ in range(3):
        try:
            r = httpx.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                          params={"period1": int(a.timestamp()), "period2": int(b.timestamp()), "interval": "1m"},
                          headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            res = (r.json().get("chart") or {}).get("result")
            if not res:
                return []
            j = res[0]; ts = j.get("timestamp") or []; q = j["indicators"]["quote"][0]
            return [(dt.datetime.fromtimestamp(t, ET), q["close"][i]) for i, t in enumerate(ts)
                    if q["close"][i] is not None and (q["volume"][i] or 0) > 0]
        except Exception:                                   # noqa: BLE001
            time.sleep(1.5)
    return None


def summarize(rows: list[dict], key: str) -> dict:
    vals = [(r[key] - r["ask"]) / r["ask"] for r in rows if r.get(key) is not None]
    usd = [(r[key] - r["ask"]) * 100 - FEES_ROUND_TRIP for r in rows if r.get(key) is not None]
    if not vals:
        return {"n": 0, "of": len(rows)}
    return {"n": len(vals), "of": len(rows), "median": statistics.median(vals), "mean": statistics.mean(vals),
            "up": sum(v > 0 for v in vals), "usdMean": statistics.mean(usd), "usdMedian": statistics.median(usd)}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--since", default="2026-09-11")
    ap.add_argument("--until", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    c = await asyncpg.connect(a.db, server_settings={"default_transaction_read_only": "on"})
    try:
        since = dt.datetime.fromisoformat(a.since).replace(tzinfo=ET)
        until = (dt.datetime.fromisoformat(a.until).replace(tzinfo=ET) + dt.timedelta(days=1)) if a.until else None
        rows = await c.fetch("""select ts, payload from events where type='TipEntryStudy' and payload->>'phase'='created'
                                and ts >= $1 order by ts""", since)
    finally:
        await c.close()
    out = []
    for r in rows:
        if until and r["ts"] >= until:
            continue
        p = J(r["payload"]); sym = p.get("symbol") or ""; ask = (p.get("atDecision") or {}).get("ask")
        if not ask or not OCC.match(sym):
            continue
        t0 = r["ts"].astimezone(ET)
        end = dt.datetime.combine(next_session(t0.date()), dt.time(16, 0), tzinfo=ET)
        s = score(t0, float(ask), _fetch(sym, t0, end))
        out.append({"symbol": sym, "verdict": p.get("verdict") or "-", "ask": float(ask), "t0": t0.isoformat(),
                    "dte": dte_bucket(sym, t0.date()), **s})
        time.sleep(0.3)
    print(f"# Entry-study fixed horizons ({VERSION}) - decisions since {a.since}\n")
    print("Start = the executable ask the decision saw; prints are TRADE prints (not NBBO); missing stays missing. "
          f"$ = per contract after ${FEES_ROUND_TRIP:.2f} round-trip fees.\n")
    for group, key in (("verdict", "verdict"), ("DTE bucket", "dte")):
        print(f"| {group} | contracts | horizon | n | median | mean | up | $ mean | $ median |")
        print("|---|---:|---|---:|---:|---:|---:|---:|---:|")
        by = collections.defaultdict(list)
        for x in out:
            by[x[key]].append(x)
        for g, xs in sorted(by.items()):
            for h, label in (("p30", "+30 min"), ("pclose", "session close"), ("pnext", "next close")):
                s = summarize(xs, h)
                if not s["n"]:
                    print(f"| {g} | {len(xs)} | {label} | 0 | | | | | |")
                    continue
                print(f"| {g} | {len(xs)} | {label} | {s['n']} | {s['median']:+.0%} | {s['mean']:+.0%} | {s['up']} | "
                      f"{s['usdMean']:+,.0f} | {s['usdMedian']:+,.0f} |")
        print()
    pair = [(x["pnext"] - x["pclose"]) / x["pclose"] for x in out if x.get("pnext") and x.get("pclose")]
    if pair:
        print(f"Overnight drift, session close -> next close (same contract, all verdicts): n={len(pair)} "
              f"median {statistics.median(pair):+.0%} mean {statistics.mean(pair):+.0%} up {sum(v > 0 for v in pair)}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, default=str)


if __name__ == "__main__":
    asyncio.run(main())
