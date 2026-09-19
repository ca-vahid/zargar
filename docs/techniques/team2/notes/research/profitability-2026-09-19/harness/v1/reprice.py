"""Reprice every replayed leg with REAL option prints (Alpaca 1m trade bars). Nothing is modelled except the cost layer:
half-spread per leg (HS) and the fee per contract per leg (FEE). A leg with no print within LAG minutes is UNPRICED and the
trade is excluded (coverage reported). usage: reprice.py DATA in.json out.json [field=o|vw] [hs=0.01]"""
import json, sys, pathlib, datetime as dt
DATA = pathlib.Path(sys.argv[1])
src, out = sys.argv[2], sys.argv[3]
opts = dict(a.split("=") for a in sys.argv[4:])
FIELD = opts.get("field", "o")
HS = float(opts.get("hs", 0.01))
FEE = float(opts.get("fee", 0.0104))
LAG = int(opts.get("lag", 3))
TOUCH = opts.get("touch", "1") == "1"
MIN = 60_000


def occ(sym, date, call, strike):
    d = dt.date.fromisoformat(date)
    return f"{sym}{d:%y%m%d}{'C' if call else 'P'}{int(round(strike * 1000)):08d}"


_cache = {}


def bars(o):
    if o not in _cache:
        p = DATA / "opt" / f"{o}.json"
        rows = json.loads(p.read_text()) if p.exists() else []
        _cache[o] = {int(dt.datetime.fromisoformat(r["t"].replace("Z", "+00:00")).timestamp() * 1000): r for r in rows}
    return _cache[o]


_und = {}


def und(sym):
    if sym not in _und:
        rows = json.loads((DATA / f"{sym}_1m.json").read_text())
        _und[sym] = {int(dt.datetime.fromisoformat(r["t"].replace("Z", "+00:00")).timestamp() * 1000): r for r in rows}
    return _und[sym]


def touch_px(sym, o, ts, target, long):
    """Target exits: the model books them AT the target inside the 2m bar that ends at `ts`; the desk sells on the first
    print through it. Real proxy = the option minute in which the underlying first touched (volume-weighted price)."""
    u, b = und(sym), bars(o)
    for t0 in (ts - 2 * MIN, ts - MIN):
        r = u.get(t0)
        if r and ((r["h"] >= target) if long else (r["l"] <= target)) and b.get(t0):
            return float(b[t0]["vw"]), 0
    return None, None


def px(o, ts):
    b = bars(o)
    t0 = (ts // MIN) * MIN
    for k in range(LAG + 1):
        r = b.get(t0 + k * MIN)
        if r:
            return float(r[FIELD]), k
    return None, None


d = json.load(open(src))
n = priced = 0
for r in d["rows"]:
    for t in r.get("trades") or []:
        n += 1
        o = occ(r["symbol"], r["date"], t["call"], t["strike"])
        legs = [("buy", 1.0, t["entryTs"], None)] + [("buy", a["fraction"], a["ts"], None) for a in t.get("added") or []] + \
               [("sell", e["fraction"], e["ts"], e) for e in t["exits"]]
        cash, ok, lagmax, detail = 0.0, True, 0, []
        for side, f, ts, ex in legs:
            p = k = None
            if TOUCH and ex is not None and ex.get("fillAssumption") == "target_touch_intrabar" and t.get("target") is not None:
                p, k = touch_px(r["symbol"], o, ts, float(ex["spot"]), t["direction"] == "long")
            if p is None:
                p, k = px(o, ts)
            if p is None:
                ok = False
                break
            lagmax = max(lagmax, k)
            cash += f * ((p - HS) if side == "sell" else -(p + HS)) - f * FEE
            detail.append([side, f, ts, p])
        t["occ"] = o
        if not ok:
            t["realPct"] = None
            continue
        entry_p = detail[0][3]
        t["realEntry"] = entry_p
        t["realLegs"] = detail
        t["realPct"] = round(100 * cash / (entry_p + HS), 2)
        # gross of costs, for the attribution split
        g = sum(f * (p if s == "sell" else -p) for s, f, _, p in detail)
        t["realGrossPct"] = round(100 * g / entry_p, 2)
        t["modelEntry"] = t["entryPremium"]
        priced += 1
json.dump(d, open(out, "w"))
print("trades", n, "priced", priced, "unpriced", n - priced, "field", FIELD, "hs", HS, "fee", FEE)
