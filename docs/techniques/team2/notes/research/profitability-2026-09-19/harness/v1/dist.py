import json, sys, statistics as st, collections
d = json.load(open(sys.argv[1]))
field = sys.argv[2] if len(sys.argv) > 2 else "pnlPct"
T = []
for r in d["rows"]:
    for t in r.get("trades") or []:
        T.append({**t, "date": r["date"], "symbol": r["symbol"], "scenario": r.get("scenario"), "dayType": r.get("dayType")})
T = [t for t in T if t.get(field) is not None]
p = sorted(t[field] for t in T)
n = len(p)
print("n", n, "sum", round(sum(p), 1), "mean", round(st.mean(p), 2), "median", round(st.median(p), 2), "win%", round(100 * sum(x > 0 for x in p) / n, 1))
print("quantiles", [round(p[int(q * (n - 1))], 1) for q in (0, .1, .25, .5, .75, .9, 1)])
top = sorted(T, key=lambda t: -t[field])[:10]
print("top10 sum", round(sum(t[field] for t in top), 1), [(t["date"], t["symbol"], round(t[field])) for t in top])


def grp(name, key):
    g = collections.defaultdict(list)
    for t in T:
        g[key(t)].append(t[field])
    print("--", name)
    for k in sorted(g, key=str):
        v = g[k]
        print(f"  {str(k):28s} n={len(v):4d} win%={100 * sum(x > 0 for x in v) / len(v):5.1f} mean={st.mean(v):7.2f} sum={sum(v):8.1f}")


grp("month", lambda t: t["date"][:7])
grp("symbol", lambda t: t["symbol"])
grp("setup kind", lambda t: t["setup"].split("@")[0])
grp("direction", lambda t: t["direction"])
grp("touch", lambda t: min(t["touchIndex"], 3))
grp("entryKind", lambda t: t["entryKind"])
grp("bucket", lambda t: t["bucket"])
grp("exit", lambda t: t["exitReason"].split("(")[-1][:25] if "(" in t["exitReason"] else t["exitReason"][:25])
grp("barsHeld", lambda t: "<=2" if t["barsHeld"] <= 2 else "3-5" if t["barsHeld"] <= 5 else "6-15" if t["barsHeld"] <= 15 else ">15")
import datetime as dt
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
grp("entry hour", lambda t: dt.datetime.fromtimestamp(t["entryTs"] / 1000, ET).strftime("%H"))
grp("split dev/seal", lambda t: "sealed(>=09-14)" if t["date"] >= "2026-09-14" else "dev")
