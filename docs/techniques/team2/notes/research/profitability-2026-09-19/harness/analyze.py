"""Statistics for one replay file or a baseline/arm pair (v2). Uncertainty is DATE-CLUSTERED: whole dates are resampled, so the
three symbols of one session and repeated entries of one setup are never treated as independent.
usage: analyze.py one  FILE START END [label]
       analyze.py pair BASE ARM START END [label]      (same dates resampled for both: a paired, clustered difference)
Prints one JSON line."""
import json, sys, math, random, statistics as st, collections
random.seed(20260919)
B = 4000


def trades(path, a, b):
    d = json.load(open(path))
    out, cens, days = [], 0, set()
    for r in d["rows"]:
        if r["status"] != "ok" or not (a <= r["date"] <= b):
            continue
        days.add(r["date"])
        for t in r["trades"]:
            if t.get("censored") or (isinstance(t["pnlPct"], float) and math.isnan(t["pnlPct"])):
                cens += 1
                continue
            out.append({"date": r["date"], "symbol": r["symbol"], "pnl": float(t["pnlPct"]), "setup": t["setup"], "entryTs": t["entryTs"]})
    return out, cens, sorted(days), d.get("meta", {})


def by_date(T, days):
    g = {d: [] for d in days}
    for t in T:
        g[t["date"]].append(t["pnl"])
    return g


def cl_mean(g, keys):
    v = [x for k in keys for x in g[k]]
    return sum(v) / len(v) if v else float("nan")


def ci(vals):
    vals = sorted(x for x in vals if not math.isnan(x))
    return [round(vals[int(0.025 * len(vals))], 2), round(vals[int(0.975 * len(vals)) - 1], 2)]


def one(path, a, b, label):
    T, cens, days, meta = trades(path, a, b)
    g = by_date(T, days)
    boots = [cl_mean(g, random.choices(days, k=len(days))) for _ in range(B)]
    p = [t["pnl"] for t in T]
    day_sum = {d: sum(v) for d, v in g.items()}
    top = sorted(day_sum.items(), key=lambda kv: -kv[1])
    total = sum(p)
    ex = {}
    for k in (1, 3, 5):
        drop = {d for d, _ in top[:k]}
        v = [t["pnl"] for t in T if t["date"] not in drop]
        ex[f"meanWithoutBest{k}Dates"] = round(st.mean(v), 2) if v else None
    opp = len({(t["date"], t["symbol"], t["setup"]) for t in T})
    iid = st.pstdev(p) / math.sqrt(len(p)) if len(p) > 1 else float("nan")
    return {"label": label, "window": [a, b], "sessions": len(days), "sessionsWithTrades": sum(1 for d in days if g[d]), "trades": len(T),
            "setupOpportunities": opp, "censored": cens, "meanPct": round(st.mean(p), 2), "medianPct": round(st.median(p), 2),
            "winRate": round(100 * sum(x > 0 for x in p) / len(p), 1), "ciDateClustered95": ci(boots),
            "ciNaiveIid95": [round(st.mean(p) - 1.96 * iid, 2), round(st.mean(p) + 1.96 * iid, 2)],
            "sumPct": round(total, 1), "best3DatesSumPct": round(sum(v for _, v in top[:3]), 1), "best3Dates": [d for d, _ in top[:3]],
            "worst3DatesSumPct": round(sum(v for _, v in top[-3:]), 1), **ex,
            "bySymbol": {s: [sum(1 for t in T if t["symbol"] == s), round(st.mean([t["pnl"] for t in T if t["symbol"] == s]), 2)] for s in ("SPY", "QQQ", "IWM") if any(t["symbol"] == s for t in T)},
            "codeCommit": meta.get("codeCommit"), "conventions": meta.get("conventions"), "overrides": meta.get("overrides")}


def pair(base, arm, a, b, label):
    TB, cb, days, _ = trades(base, a, b)
    TA, ca, days2, meta = trades(arm, a, b)
    assert days == days2, "arms must cover the same sessions"
    gb, ga = by_date(TB, days), by_date(TA, days)
    diffs = []
    for _ in range(B):
        ks = random.choices(days, k=len(days))
        diffs.append(cl_mean(ga, ks) - cl_mean(gb, ks))
    kb = {(t["date"], t["symbol"], t["entryTs"]) for t in TB}
    ka = {(t["date"], t["symbol"], t["entryTs"]) for t in TA}
    common = kb & ka
    mb = st.mean([t["pnl"] for t in TB if (t["date"], t["symbol"], t["entryTs"]) in common]) if common else float("nan")
    ma = st.mean([t["pnl"] for t in TA if (t["date"], t["symbol"], t["entryTs"]) in common]) if common else float("nan")
    only_a = [t["pnl"] for t in TA if (t["date"], t["symbol"], t["entryTs"]) not in common]
    only_b = [t["pnl"] for t in TB if (t["date"], t["symbol"], t["entryTs"]) not in common]
    d = st.mean([t["pnl"] for t in TA]) - st.mean([t["pnl"] for t in TB])
    nA, nB = len(TA), len(TB)
    contrib = {k: sum(ga[k]) / nA - sum(gb[k]) / nB for k in days}
    infl = sorted(days, key=lambda k: -abs(contrib[k]))[:3]
    keep = [k for k in days if k not in infl]
    d_ex = cl_mean(ga, keep) - cl_mean(gb, keep)
    return {"label": label, "window": [a, b], "sessions": len(days), "baseTrades": len(TB), "armTrades": len(TA), "censoredBase": cb, "censoredArm": ca,
            "baseMean": round(st.mean([t["pnl"] for t in TB]), 2), "armMean": round(st.mean([t["pnl"] for t in TA]), 2), "diff": round(d, 2),
            "diffCiDateClustered95": ci(diffs), "influentialDates": infl, "diffWithout3MostInfluentialDates": round(d_ex, 2), "pDiffAtLeast3": round(sum(x >= 3 for x in diffs) / len(diffs), 3),
            "commonEntries": len(common), "commonBaseMean": round(mb, 2), "commonArmMean": round(ma, 2),
            "entriesOnlyInArm": [len(only_a), round(st.mean(only_a), 2) if only_a else None],
            "entriesOnlyInBase": [len(only_b), round(st.mean(only_b), 2) if only_b else None], "overrides": meta.get("overrides")}


if sys.argv[1] == "one":
    print(json.dumps(one(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else sys.argv[2])))
else:
    print(json.dumps(pair(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6] if len(sys.argv) > 6 else sys.argv[3])))
