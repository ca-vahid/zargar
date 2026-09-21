"""SIMPLIFIED RESEARCH BOOK SIMULATION (v2). NOT a calibrated forecast of the running books: see 04-book-and-opportunity-attribution.md
for what is reproduced and what is not. One book under the Control rules, trades taken in time order across the three symbols.

Reproduced: one open position per book; the deployed sizing (floor of min(bucket x equity x 6% / (premium x 25), $2,000 / (premium x 100), 40));
integer contracts on every leg (trims/adds as whole contracts, the last leg takes the remainder); $ fees on executed contracts;
the two-loss desk cap on the deployed GROSS basis (a round trip whose gross P&L is negative counts); the 10% technique day-loss pause.
NOT reproduced: the effect of a refused fire on the setup's later state (in the running system a fire refused for occupancy still
spends the two-pullback allowance, see the 2026-09-18 C1 trace), the size-after-a-win rule, partial fills, the 15% book breaker,
and marked-to-market equity between fills (only realized equity is tracked; `mtmTroughApprox` uses the print LOW during each hold).
usage: book.py FILE START END [DATA]"""
import json, sys, math, pathlib, datetime as dt, collections
src, START, END = sys.argv[1], sys.argv[2], sys.argv[3]
DATA = pathlib.Path(sys.argv[4]) if len(sys.argv) > 4 else None
d = json.load(open(src))
FEE = float(d["rules"].get("fee_per_contract", 1.04))
MAXL = int(d["rules"].get("max_losses_per_day", 2))
T = []
for r in d["rows"]:
    if r["status"] == "ok" and START <= r["date"] <= END:
        for t in r["trades"]:
            if not t.get("censored"):
                T.append({**t, "date": r["date"], "symbol": r["symbol"]})
T.sort(key=lambda t: t["entryTs"])


def occ(sym, date, call, strike):
    x = dt.date.fromisoformat(date)
    return f"{sym}{x:%y%m%d}{'C' if call else 'P'}{int(round(strike * 1000)):08d}"


def low_during(t):
    if DATA is None:
        return None
    p = DATA / "opt" / f"{occ(t['symbol'], t['date'], t['call'], t['strike'])}.json"
    if not p.exists():
        return None
    lows = [b["l"] for b in json.loads(p.read_text())
            if t["entryTs"] <= int(dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp() * 1000) <= t["exitTs"]]
    return min(lows) if lows else None


def legs_dollars(t, n):
    """integer legs: buys (entry + adds) and sells (exits); returns gross dollars, fee dollars, contracts traded"""
    held, gross, traded = n, -n * t["entryPremium"] * 100.0, n
    events = [("sell", e["ts"], e["fraction"], e["premium"]) for e in t["exits"]] + [("buy", a["ts"], a["fraction"], a["premium"]) for a in t.get("added") or []]
    events.sort(key=lambda x: (x[1], x[0] == "buy"))
    last_sell = max(i for i, e in enumerate(events) if e[0] == "sell")
    for i, (side, _, f, prem) in enumerate(events):
        if side == "buy":
            q = math.floor(f * n)
            held += q
            gross -= q * prem * 100.0
        else:
            q = held if i == last_sell else min(held, math.floor(f * n))
            held -= q
            gross += q * prem * 100.0
        traded += q
    return gross, traded * FEE, traded


eq, peak, dd = 10000.0, 10000.0, 0.0
busy, day, losses, day_start, halted = 0, None, 0, 10000.0, False
taken = collections.Counter()
by_date = collections.defaultdict(float)
mtm_worst = 0.0
for t in T:
    if t["date"] != day:
        day, losses, day_start, halted = t["date"], 0, eq, False
    if t["entryTs"] < busy:
        taken["displacedOccupancy"] += 1
        continue
    if halted:
        taken["displacedDayLossPause"] += 1
        continue
    if losses >= MAXL:
        taken["displacedLossCap"] += 1
        continue
    prem = float(t["entryPremium"])
    n = math.floor(min(float(t.get("sizeMult") or 1.0) * eq * 0.06 / (prem * 25.0), 2000.0 / (prem * 100.0), 40))
    if n < 1:
        taken["zeroQuantity"] += 1
        continue
    gross, fees, _ = legs_dollars(t, n)
    lo = low_during(t)
    if lo is not None:
        mtm_worst = max(mtm_worst, peak - (eq - n * (prem - lo) * 100.0 - n * FEE))
    eq += gross - fees
    by_date[t["date"]] += gross - fees
    peak = max(peak, eq)
    dd = max(dd, peak - eq)
    busy = t["exitTs"]
    taken["taken"] += 1
    if gross < 0:
        losses += 1
    if eq <= day_start * 0.90:
        halted = True
days = sorted(by_date.items(), key=lambda kv: -kv[1])
print(json.dumps({"label": src.split("/")[-1].split("\\")[-1], "kind": "SIMPLIFIED RESEARCH SIMULATION", "window": [START, END], **taken,
                  "finalRealized": round(eq, 2), "maxRealizedDrawdown": round(dd, 2), "mtmTroughApprox": round(mtm_worst, 2) if DATA else None,
                  "greenDays": sum(v > 0 for _, v in days), "redDays": sum(v < 0 for _, v in days),
                  "best3Dates": [[k, round(v)] for k, v in days[:3]], "finalWithoutBest3Dates": round(eq - sum(v for _, v in days[:3]), 2),
                  "worstDay": [days[-1][0], round(days[-1][1])] if days else None}))
