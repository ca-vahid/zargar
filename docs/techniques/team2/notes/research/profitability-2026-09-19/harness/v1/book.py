"""Chronological book simulation over a replay file (see the preregistration for the definition).
usage: book.py replay.json START END [max_losses=2] [label]  -> prints one JSON line + human summary"""
import json, sys, math, statistics as st, collections
src, START, END = sys.argv[1], sys.argv[2], sys.argv[3]
MAXL = int(sys.argv[4]) if len(sys.argv) > 4 else 2
LABEL = sys.argv[5] if len(sys.argv) > 5 else src
d = json.load(open(src))
FEE = float(d["rules"].get("fee_per_contract", 1.04))
T = []
for r in d["rows"]:
    if r["status"] != "ok" or not (START <= r["date"] <= END):
        continue
    for t in r["trades"]:
        T.append({**t, "date": r["date"], "symbol": r["symbol"]})
T.sort(key=lambda t: t["entryTs"])


def run(trades, drop_dates=()):
    eq, peak, dd = 10000.0, 10000.0, 0.0
    busy_until, day, losses = 0, None, 0
    taken, dropped_busy, dropped_cap, zero = 0, 0, 0, 0
    by_date = collections.defaultdict(float)
    exposure_min = 0.0
    for t in trades:
        if t["date"] in drop_dates:
            continue
        if t["date"] != day:
            day, losses = t["date"], 0
        if t["entryTs"] < busy_until:
            dropped_busy += 1
            continue
        if losses >= MAXL:
            dropped_cap += 1
            continue
        prem = float(t["entryPremium"])
        if prem <= 0:
            continue
        n = math.floor(min(float(t.get("sizeMult") or 1.0) * eq * 0.06 / (prem * 25.0), 2000.0 / (prem * 100.0), 40))
        if n < 1:
            zero += 1
            continue
        pnl = n * (prem * 100.0 + FEE) * float(t["pnlPct"]) / 100.0
        eq += pnl
        by_date[t["date"]] += pnl
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        busy_until = t["exitTs"]
        exposure_min += (t["exitTs"] - t["entryTs"]) / 60000.0
        taken += 1
        if pnl < 0:
            losses += 1
    return {"final": round(eq, 2), "maxDD": round(dd, 2), "taken": taken, "droppedBusy": dropped_busy, "droppedCap": dropped_cap,
            "zeroQty": zero, "byDate": dict(by_date), "exposureMin": round(exposure_min)}


full = run(T)
best3 = [k for k, _ in sorted(full["byDate"].items(), key=lambda kv: -kv[1])[:3]]
ex3 = run(T, drop_dates=set(best3))
p = [t["pnlPct"] for t in T]
sym = {s: round(st.mean([t["pnlPct"] for t in T if t["symbol"] == s]), 2) for s in ("SPY", "QQQ", "IWM") if any(t["symbol"] == s for t in T)}
days = sorted(full["byDate"].values())
out = {"label": LABEL, "window": [START, END], "trades": len(T), "meanPct": round(st.mean(p), 2) if p else None,
       "medianPct": round(st.median(p), 2) if p else None, "winRate": round(100 * sum(x > 0 for x in p) / len(p), 1) if p else None,
       "bySymbolMeanPct": sym, "book": {k: v for k, v in full.items() if k != "byDate"},
       "bookEx3Best": {"final": ex3["final"], "dates": best3},
       "greenDays": sum(v > 0 for v in days), "redDays": sum(v < 0 for v in days),
       "worstDay": round(days[0], 2) if days else None, "bestDay": round(days[-1], 2) if days else None}
print(json.dumps(out))
