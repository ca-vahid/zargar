"""DESCRIPTIVE, already examined before any registration (see 03, 'What had been examined'). Exit-free view of the baseline ENTRIES:
the underlying's signed move and the chosen contract's print-to-print return N minutes after the execution print, with
DATE-CLUSTERED intervals. A favourable-direction RATE near 50% does not by itself mean zero expectancy: the mean move and the
option's convexity and decay matter, so both are shown. usage: horizon.py DATA REPLAY.json START END"""
import json, sys, pathlib, random, datetime as dt, statistics as st
random.seed(20260919)
DATA = pathlib.Path(sys.argv[1]); d = json.load(open(sys.argv[2])); START, END = sys.argv[3], sys.argv[4]
MIN, FEE_RT = 60_000, 0.0208


def idx(rows):
    return {int(dt.datetime.fromisoformat(r["t"].replace("Z", "+00:00")).timestamp() * 1000): r for r in rows}


def occ(sym, date, call, strike):
    x = dt.date.fromisoformat(date)
    return f"{sym}{x:%y%m%d}{'C' if call else 'P'}{int(round(strike * 1000)):08d}"


und = {s: idx(json.loads((DATA / f"{s}_1m.json").read_text())) for s in ("SPY", "QQQ", "IWM")}
H = (4, 10, 20, 30, 60, 120)
opt = {h: {} for h in H}
unm = {h: {} for h in H}
miss = {h: 0 for h in H}
n = 0
for r in d["rows"]:
    if r["status"] != "ok" or not (START <= r["date"] <= END):
        continue
    for t in r["trades"]:
        n += 1
        o = idx(json.loads((DATA / "opt" / f"{occ(r['symbol'], r['date'], t['call'], t['strike'])}.json").read_text()))
        e = (t.get("pricing") or {}).get("executionTs") or t["entryTs"]
        p0 = t["entryPremium"]; sgn = 1 if t["direction"] == "long" else -1
        u0 = und[r["symbol"]].get(e)
        for h in H:
            b = next((o[e + (h + k) * MIN] for k in range(2) if e + (h + k) * MIN in o), None)      # print within 2 minutes of the horizon, else unknown
            if b:
                opt[h].setdefault(r["date"], []).append(100 * (b["o"] - p0 - FEE_RT) / p0)
            else:
                miss[h] += 1
            u = und[r["symbol"]].get(e + h * MIN)
            if u and u0:
                unm[h].setdefault(r["date"], []).append(sgn * (u["o"] - u0["o"]) / u0["o"] * 100)


def cl(g):
    ds = sorted(g)
    v = [x for k in ds for x in g[k]]
    boots = sorted(st.mean([x for k in random.choices(ds, k=len(ds)) for x in g[k]]) for _ in range(3000))
    return st.mean(v), boots[75], boots[2924], len(v), len(ds)


print(f"entries {n}, window {START}..{END}; option return = print at the horizon vs the execution print, minus two commissions")
for h in H:
    m, lo, hi, k, nd = cl(opt[h])
    um, ulo, uhi, uk, _ = cl(unm[h])
    fav = [x for v in unm[h].values() for x in v]
    print(f"+{h:3d}m option mean {m:7.2f}% [{lo:6.2f},{hi:6.2f}] n={k} dates={nd} unknown={miss[h]} | underlying favourable {100 * sum(x > 0 for x in fav) / len(fav):5.1f}% "
          f"mean signed move {um:+.4f}% [{ulo:+.4f},{uhi:+.4f}]")
