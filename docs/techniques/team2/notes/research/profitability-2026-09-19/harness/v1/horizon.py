"""EXPLORATORY (not part of the preregistration). Exit-free decomposition of the baseline ENTRIES: what the chosen contract
is worth N minutes after the entry (real prints), and what the underlying did. Separates signal+contract from exit rules.
usage: horizon.py DATA replay.json START END"""
import json, sys, pathlib, datetime as dt, statistics as st
DATA = pathlib.Path(sys.argv[1]); d = json.load(open(sys.argv[2])); START, END = sys.argv[3], sys.argv[4]
MIN = 60_000
FEE = 0.0208  # round trip, in premium terms


def idx(rows):
    return {int(dt.datetime.fromisoformat(r["t"].replace("Z", "+00:00")).timestamp() * 1000): r for r in rows}


def occ(sym, date, call, strike):
    x = dt.date.fromisoformat(date)
    return f"{sym}{x:%y%m%d}{'C' if call else 'P'}{int(round(strike * 1000)):08d}"


und = {s: idx(json.loads((DATA / f"{s}_1m.json").read_text())) for s in ("SPY", "QQQ", "IWM")}
H = (4, 10, 20, 30, 60, 120)
res = {h: [] for h in H}
undm = {h: [] for h in H}
best = []
for r in d["rows"]:
    if r["status"] != "ok" or not (START <= r["date"] <= END):
        continue
    for t in r["trades"]:
        o = idx(json.loads((DATA / "opt" / f"{occ(r['symbol'], r['date'], t['call'], t['strike'])}.json").read_text()))
        e = t["entryTs"]; p0 = t["entryPremium"]; sgn = 1 if t["direction"] == "long" else -1
        hi = 0.0
        for k in range(1, 121):
            b = o.get(e + k * MIN)
            if b:
                hi = max(hi, b["h"])
        best.append(100 * (hi - p0) / p0 if hi else 0)
        for h in H:
            b = None
            for k in range(0, 3):
                b = o.get(e + (h + k) * MIN)
                if b:
                    break
            u = und[r["symbol"]].get(e + h * MIN)
            if b:
                res[h].append(100 * (b["o"] - p0 - FEE) / p0)
            u0 = und[r["symbol"]].get(e)             # the underlying at the DECISION minute (the read's entrySpot is the EMA/level line)
            if u and u0:
                undm[h].append(sgn * (u["o"] - u0["o"]) / u0["o"] * 100)
print(f"entries {len(best)} window {START}..{END}")
for h in H:
    v, u = res[h], undm[h]
    se = st.pstdev(v) / len(v) ** .5
    print(f"+{h:3d}m: option net mean {st.mean(v):7.2f}% (se {se:4.2f}) median {st.median(v):7.2f}% win {100 * sum(x > 0 for x in v) / len(v):5.1f}% n={len(v)} | "
          f"underlying favourable {100 * sum(x > 0 for x in u) / len(u):5.1f}% mean {st.mean(u):+.4f}%")
q = sorted(best)
print("best premium reachable within 120m of entry (MFE, a ceiling no rule can reach): median %+.0f%%, share >=+50%%: %.0f%%, >=+100%%: %.0f%%"
      % (st.median(q), 100 * sum(x >= 50 for x in q) / len(q), 100 * sum(x >= 100 for x in q) / len(q)))
