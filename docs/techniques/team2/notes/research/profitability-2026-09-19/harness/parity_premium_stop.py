"""P1.1 premium-stop parity overlay (registration: notes/research/2026-09-27-p1-premium-stop-parity-registration.md).

OFFLINE, ORDER-FREE. Reads one existing replay file and the cached 1m option prints; re-runs nothing.
usage: parity_premium_stop.py REPLAY.json DATA_DIR OUT.json
"""
import json, math, pathlib, random, sys, datetime as dt
from collections import defaultdict

MIN = 60_000
PCT, FLOOR_TICKS, TICK, EXIT_WINDOW_MIN = 0.25, 3, 0.01, 5
SEED, RESAMPLES = 20260927, 10_000


def occ(sym, date, call, strike):
    d = dt.date.fromisoformat(date)
    return f"{sym}{d:%y%m%d}{'C' if call else 'P'}{int(round(strike * 1000)):08d}"


def minutes(data, o):
    p = data / "opt" / f"{o}.json"
    if not p.exists():
        return None
    rows = json.loads(p.read_text())
    out = []
    for r in rows:
        ts = int(dt.datetime.fromisoformat(r["t"].replace("Z", "+00:00")).timestamp() * 1000)
        out.append((ts, float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"])))
    return sorted(out)


def unit_pnl(entry, legs):
    return sum(f * (p / entry - 1.0) for f, p in legs) * 100.0


def overlay(tr, bars, proxy):
    e = float(tr["entryPremium"])
    line = min((1 - PCT) * e, e - FLOOR_TICKS * TICK)
    legs = [(float(x["fraction"]), float(x["premium"]), int(x["ts"])) for x in tr["exits"]]
    end = int(tr["exitTs"])
    trig = None
    for ts, o, h, l, c in bars:
        if ts <= int(tr["entryTs"]) or ts >= end:
            continue
        if (c if proxy == "close" else l) <= line + 1e-12:
            trig = ts
            break
    base = unit_pnl(e, [(f, p) for f, p, _ in legs])
    if trig is None:
        return base, base, "no_trigger"
    after = trig + MIN
    kept = [(f, p) for f, p, t in legs if t < after]
    if len(kept) == len(legs):
        return base, base, "baseline_first"
    px = next((o for ts, o, *_ in bars if after <= ts < after + EXIT_WINDOW_MIN * MIN), None)
    if px is None:
        return base, base, "censored"
    rem = 1.0 - sum(f for f, _ in kept)
    return base, unit_pnl(e, kept + [(rem, px)]), "earlier_stop"


def boot(diffs_by_date):
    dates = sorted(diffs_by_date)
    rnd = random.Random(SEED)
    n = sum(len(v) for v in diffs_by_date.values())
    point = sum(sum(v) for v in diffs_by_date.values()) / n
    means = []
    for _ in range(RESAMPLES):
        pick = [diffs_by_date[rnd.choice(dates)] for _ in dates]
        k = sum(len(v) for v in pick)
        means.append(sum(sum(v) for v in pick) / k)
    means.sort()
    return point, means[int(0.025 * RESAMPLES)], means[int(0.975 * RESAMPLES) - 1]


def main(replay, data, out):
    d = json.loads(pathlib.Path(replay).read_text())
    data = pathlib.Path(data)
    trades = [(row, t) for row in d["rows"] for t in (row.get("trades") or [])]
    res = {"replay": str(replay), "replayMeta": d["meta"], "trades": len(trades), "excludedAdds": 0,
           "missingPrints": 0, "reconstructionMaxErr": 0.0, "proxies": {}}
    usable = []
    for row, t in trades:
        if t.get("adds"):
            res["excludedAdds"] += 1
            continue
        bars = minutes(data, occ(row["symbol"], row["date"], t["call"], t["strike"]))
        if not bars:
            res["missingPrints"] += 1
            continue
        rec = unit_pnl(float(t["entryPremium"]), [(float(x["fraction"]), float(x["premium"])) for x in t["exits"]])
        res["reconstructionMaxErr"] = max(res["reconstructionMaxErr"], abs(rec - float(t["pnlPct"])))
        usable.append((row, t, bars))
    res["usable"] = len(usable)
    for proxy in ("close", "low"):
        by_date, outcomes, base_sum, var_sum = defaultdict(list), defaultdict(int), 0.0, 0.0
        for row, t, bars in usable:
            b, v, why = overlay(t, bars, proxy)
            outcomes[why] += 1
            by_date[row["date"]].append(v - b)
            base_sum += b
            var_sum += v
        point, lo, hi = boot(by_date)
        n = len(usable)
        res["proxies"][proxy] = {"meanDiffPts": round(point, 2), "ci95": [round(lo, 2), round(hi, 2)],
                                 "baselineMeanPct": round(base_sum / n, 2), "variantMeanPct": round(var_sum / n, 2),
                                 "outcomes": dict(outcomes), "sessions": len(by_date)}
    pathlib.Path(out).write_text(json.dumps(res, indent=2))
    print(json.dumps({k: v for k, v in res.items() if k != "replayMeta"}, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:4])
