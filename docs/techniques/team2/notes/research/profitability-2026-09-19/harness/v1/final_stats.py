import json, sys, statistics as st, collections, random, datetime as dt
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
d = json.load(open(sys.argv[1]))
T = [{**t, "date": r["date"], "symbol": r["symbol"], "dayType": r.get("dayType"), "scenario": r.get("scenario")}
     for r in d["rows"] if r["status"] == "ok" for t in r["trades"]]
random.seed(7)


def line(name, v):
    if not v:
        return
    m = st.mean(v)
    boots = sorted(st.mean(random.choices(v, k=len(v))) for _ in range(2000))
    print(f"  {name:34s} n={len(v):4d} win%={100 * sum(x > 0 for x in v) / len(v):5.1f} mean={m:7.2f}  95% CI [{boots[50]:6.2f}, {boots[1949]:6.2f}]  median={st.median(v):7.2f}")


W = {"TRAIN 05-07..08-14": ("2026-05-07", "2026-08-14"), "HOLDOUT 08-17..09-11": ("2026-08-17", "2026-09-11"),
     "POST 09-14..09-18": ("2026-09-14", "2026-09-18"), "ALL": ("2026-05-07", "2026-09-18")}
print("== baseline net % per trade (real prints, fees in, 0 slip)")
for k, (a, b) in W.items():
    line(k, [t["pnlPct"] for t in T if a <= t["date"] <= b])
A = [t for t in T if t["date"] <= "2026-09-11"]
for title, key in (("setup", lambda t: t["setup"].split("@")[0]), ("day type", lambda t: t["dayType"]), ("symbol", lambda t: t["symbol"]),
                   ("direction", lambda t: t["direction"]), ("attempt", lambda t: "first entry" if t["touchIndex"] == 1 else "re-entry (touch 2)"),
                   ("entry kind", lambda t: t["entryKind"]), ("size bucket", lambda t: t["bucket"]),
                   ("time of day", lambda t: (lambda h: "09:45-10:00" if h < 10 else "10:00-11:00" if h < 11 else "11:00-12:00" if h < 12 else "12:00-14:00" if h < 14 else "14:00-15:30")(dt.datetime.fromtimestamp(t["entryTs"] / 1000, ET).hour)),
                   ("exit", lambda t: "candle stop S1" if "S1" in t["exitReason"] else "premium stop P1" if "P1" in t["exitReason"] else "target" if "target" in t["exitReason"] else "runner X2" if "X2" in t["exitReason"] else "flatten"),
                   ("hold", lambda t: "<=2 bars (<=4 min)" if t["barsHeld"] <= 2 else "3-5 bars" if t["barsHeld"] <= 5 else "6-15 bars" if t["barsHeld"] <= 15 else ">15 bars")):
    print(f"== by {title} (05-07..09-11)")
    g = collections.defaultdict(list)
    for t in A:
        g[key(t)].append(t["pnlPct"])
    for k in sorted(g, key=str):
        line(str(k), g[k])
# fees share: gross = net + fees; fee per round trip per unit = 2*1.04 / (prem*100+1.04)
fee = [100 * 2 * 1.04 / (t["entryPremium"] * 100 + 1.04) for t in A if not t.get("added")]
print("== cost layer: mean fee drag per round trip %.2f%% of cost; mean entry premium $%.2f" % (st.mean(fee), st.mean(t["entryPremium"] for t in A)))
# displaced opportunities
A.sort(key=lambda t: t["entryTs"])
busy, day, losses = 0, None, 0
taken, dbusy, dcap = [], [], []
for t in A:
    if t["date"] != day:
        day, losses = t["date"], 0
    if t["entryTs"] < busy:
        dbusy.append(t["pnlPct"]); continue
    if losses >= 2:
        dcap.append(t["pnlPct"]); continue
    taken.append(t["pnlPct"]); busy = t["exitTs"]
    if t["pnlPct"] < 0:
        losses += 1
print("== displaced opportunities (desk-wide book rules applied in time order)")
line("taken by the book", taken); line("displaced: position already open", dbusy); line("displaced: two-loss cap reached", dcap)
