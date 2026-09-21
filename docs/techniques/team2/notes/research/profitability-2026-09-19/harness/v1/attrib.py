"""Loss attribution on the replayed + really-priced trades. Observational; the forward-looking columns (what the tape
did AFTER the exit) are diagnostics of the exit rule, never inputs to a setup. usage: attrib.py DATA base_real.json [end_date]"""
import json, sys, pathlib, datetime as dt, statistics as st, collections
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
DATA = pathlib.Path(sys.argv[1])
d = json.load(open(sys.argv[2]))
END = sys.argv[3] if len(sys.argv) > 3 else "9999"
MIN = 60_000
und = {}
for sym in ("SPY", "QQQ", "IWM"):
    rows = json.loads((DATA / f"{sym}_1m.json").read_text())
    und[sym] = {int(dt.datetime.fromisoformat(r["t"].replace("Z", "+00:00")).timestamp() * 1000): r for r in rows}


def flatten_ts(date):
    return int(dt.datetime.fromisoformat(date + "T15:45:00").replace(tzinfo=ET).timestamp() * 1000)


T = []
for r in d["rows"]:
    if r["status"] != "ok" or r["date"] > END:
        continue
    for t in r["trades"]:
        if t.get("realPct") is None:
            continue
        u = und[r["symbol"]]
        long = t["direction"] == "long"
        sgn = 1 if long else -1
        e, x, fl = t["entryTs"], t["exitTs"], flatten_ts(r["date"])
        spot = t["entrySpot"]
        tgt = t.get("target")
        room = None if tgt is None else sgn * (tgt - spot)
        # path after entry until the flatten
        path = [u[k] for k in range(e, fl, MIN) if k in u]
        after = [u[k] for k in range(x, fl, MIN) if k in u]
        def fav(b): return sgn * ((b["h"] if long else b["l"]) - spot)
        def adv(b): return -sgn * ((b["l"] if long else b["h"]) - spot)
        mfe_day = max((fav(b) for b in path), default=0.0)
        hit_day = room is not None and room > 0 and mfe_day >= room
        hit_after_exit = room is not None and room > 0 and any(fav(b) >= room for b in after)
        def close_at(mins):
            b = u.get(e + mins * MIN)
            return None if b is None else sgn * (b["c"] - spot)
        T.append({**t, "date": r["date"], "symbol": r["symbol"], "room": room, "roomPct": None if not room else 100 * room / spot,
                  "hitDay": hit_day, "hitAfterExit": hit_after_exit, "mfeDayPct": 100 * mfe_day / spot,
                  "c10": close_at(10), "c30": close_at(30), "c60": close_at(60),
                  "stopKind": "S1" if "S1" in t["exitReason"] else "P1" if "P1" in t["exitReason"] else "other",
                  "costPct": t["realGrossPct"] - t["realPct"]})
n = len(T)
print("trades", n, "through", END)
print("net mean %", round(st.mean(t["realPct"] for t in T), 2), "| gross mean %", round(st.mean(t["realGrossPct"] for t in T), 2),
      "| cost mean %", round(st.mean(t["costPct"] for t in T), 2))
for k in ("c10", "c30", "c60"):
    v = [t[k] for t in T if t[k] is not None]
    print(f"direction: underlying favourable at +{k[1:]}m: {100 * sum(x > 0 for x in v) / len(v):.1f}% of {len(v)}  mean move {st.mean(v):+.3f} pts")
w = [t for t in T if t["room"] and t["room"] > 0]
print(f"target ahead at entry: {len(w)}/{n}; target reached before 15:45 ignoring stops: {100 * sum(t['hitDay'] for t in w) / len(w):.1f}%")
stopped = [t for t in w if t["stopKind"] in ("S1", "P1")]
print(f"stopped out (S1/P1): {len(stopped)}; of those the underlying later reached the target the same day: "
      f"{sum(t['hitAfterExit'] for t in stopped)} ({100 * sum(t['hitAfterExit'] for t in stopped) / len(stopped):.1f}%)")
for sk in ("S1", "P1"):
    s = [t for t in stopped if t["stopKind"] == sk]
    print(f"  {sk}: n={len(s)} mean real {st.mean(t['realPct'] for t in s):.1f}%  later reached target {100 * sum(t['hitAfterExit'] for t in s) / len(s):.1f}%  "
          f"held<=2 bars {sum(t['barsHeld'] <= 2 for t in s)}")
print("target room (% of spot) quartiles:", [round(x, 3) for x in st.quantiles([t["roomPct"] for t in w], n=4)])
g = collections.defaultdict(list)
for t in w:
    q = "room<0.10%" if t["roomPct"] < 0.10 else "0.10-0.20%" if t["roomPct"] < 0.20 else "0.20-0.40%" if t["roomPct"] < 0.40 else ">=0.40%"
    g[q].append(t)
for q, v in sorted(g.items()):
    print(f"  {q:12s} n={len(v):3d} win%={100 * sum(t['realPct'] > 0 for t in v) / len(v):5.1f} mean real={st.mean(t['realPct'] for t in v):6.2f} hitDay={100 * sum(t['hitDay'] for t in v) / len(v):5.1f}%")
g = collections.defaultdict(list)
for t in T:
    p = t["realEntry"]
    g["<0.30" if p < .3 else "0.30-0.45" if p < .45 else "0.45-0.60" if p < .6 else "0.60-0.80" if p < .8 else ">=0.80"].append(t)
print("by real entry premium:")
for q, v in sorted(g.items()):
    print(f"  {q:10s} n={len(v):3d} net={st.mean(t['realPct'] for t in v):6.2f} gross={st.mean(t['realGrossPct'] for t in v):6.2f} cost={st.mean(t['costPct'] for t in v):5.2f}")
print("model vs real entry premium: mean model", round(st.mean(t["modelEntry"] for t in T), 3), "real", round(st.mean(t["realEntry"] for t in T), 3))
json.dump(T, open(str(sys.argv[2]).replace(".json", "_attrib.json"), "w"))
