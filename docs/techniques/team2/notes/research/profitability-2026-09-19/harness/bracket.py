"""Round 3 (registered X1/X2): bracket exits on the BASELINE entries, real option 1m prints (v2: no price is carried beyond
EXIT_WINDOW minutes; an exit with no print in the window is CENSORED, never priced at the last or a zero price).
usage: bracket.py DATA base_replay.json START END tp_mult OUT [stress=0|1]"""
import json, sys, pathlib, datetime as dt, statistics as st
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
DATA = pathlib.Path(sys.argv[1]); d = json.load(open(sys.argv[2])); START, END = sys.argv[3], sys.argv[4]
TP = float(sys.argv[5]); OUT = sys.argv[6]; STRESS = len(sys.argv) > 7 and sys.argv[7] == "1"
SL, HOLD, MIN, TICK, FEE, EXIT_WINDOW = 0.70, 60, 60_000, 0.01, 1.04, 5


def idx(rows):
    return {int(dt.datetime.fromisoformat(r["t"].replace("Z", "+00:00")).timestamp() * 1000): r for r in rows}


def occ(sym, date, call, strike):
    x = dt.date.fromisoformat(date)
    return f"{sym}{x:%y%m%d}{'C' if call else 'P'}{int(round(strike * 1000)):08d}"


def flat(date):
    return int(dt.datetime.fromisoformat(date + "T15:45:00").replace(tzinfo=ET).timestamp() * 1000)


def market_exit(o, k, give):
    for j in range(EXIT_WINDOW):
        b = o.get(k + j * MIN)
        if b:
            return b["o"] - give, k + j * MIN
    return None, k


out_rows, reasons = [], {}
for r in d["rows"]:
    if r["status"] != "ok" or not (START <= r["date"] <= END):
        continue
    busy, new = 0, []
    for t in sorted(r["trades"], key=lambda x: x["entryTs"]):
        if t.get("censored") or t["entryTs"] < busy:
            continue
        e, p0, fl = t["entryTs"], float(t["entryPremium"]), flat(r["date"])
        o = idx(json.loads((DATA / "opt" / f"{occ(r['symbol'], r['date'], t['call'], t['strike'])}.json").read_text()))
        lim, need, give = round(p0 * TP, 2), (2 if STRESS else 1) * TICK, (TICK if STRESS else 0.0)
        px = ts = why = None
        k = e + MIN
        while k <= fl:
            if k >= fl or k >= e + HOLD * MIN:
                px, ts = market_exit(o, k, give)
                why = "flatten 15:45" if k >= fl else "time stop 60m"
                break
            b = o.get(k)
            if b:
                if b["h"] >= lim + need:
                    px, ts, why = lim, k, f"limit x{TP:.2f}"
                    break
                if b["c"] <= p0 * SL:
                    px, ts = market_exit(o, k + MIN, give)
                    why = "premium stop (1m close <= 70%)"
                    break
            k += MIN
        cens = px is None
        pct = float("nan") if cens else ((px * 100 - FEE) - (p0 * 100 + FEE)) / (p0 * 100 + FEE) * 100
        busy = ts or k
        key = ("CENSORED " if cens else "") + (why or "").split(" (")[0]
        reasons[key] = reasons.get(key, 0) + 1
        new.append({**t, "exitTs": busy, "exitReason": why, "pnlPct": pct, "win": (not cens) and pct > 0, "censored": cens,
                    "exits": [{"ts": busy, "fraction": 1.0, "premium": px if not cens else float("nan")}], "added": []})
    out_rows.append({**r, "trades": new, "pricingLog": []})
json.dump({"meta": {**(d.get("meta") or {}), "bracket": {"tp": TP, "sl": SL, "holdMin": HOLD, "stress": STRESS}}, "rules": d["rules"],
           "overrides": {"bracket": TP}, "rows": out_rows}, open(OUT, "w"))
p = [t["pnlPct"] for r in out_rows for t in r["trades"] if not t["censored"]]
print("tp", TP, "stress", STRESS, "trades", len(p), "mean", round(st.mean(p), 2), "win%", round(100 * sum(x > 0 for x in p) / len(p), 1), reasons)
