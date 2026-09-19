"""Round 3 (registered): bracket exits on the BASELINE entries, real option 1m prints.
usage: bracket.py DATA base_replay.json START END tp_mult [stress=0|1] -> writes a replay-shaped file for book.py"""
import json, sys, pathlib, datetime as dt, statistics as st
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
DATA = pathlib.Path(sys.argv[1]); d = json.load(open(sys.argv[2])); START, END = sys.argv[3], sys.argv[4]
TP = float(sys.argv[5]); STRESS = len(sys.argv) > 6 and sys.argv[6] == "1"
SL, HOLD, MIN, TICK, FEE = 0.70, 60, 60_000, 0.01, 1.04


def idx(rows):
    return {int(dt.datetime.fromisoformat(r["t"].replace("Z", "+00:00")).timestamp() * 1000): r for r in rows}


def occ(sym, date, call, strike):
    x = dt.date.fromisoformat(date)
    return f"{sym}{x:%y%m%d}{'C' if call else 'P'}{int(round(strike * 1000)):08d}"


def flat(date):
    return int(dt.datetime.fromisoformat(date + "T15:45:00").replace(tzinfo=ET).timestamp() * 1000)


out_rows, reasons = [], {}
for r in d["rows"]:
    if r["status"] != "ok" or not (START <= r["date"] <= END):
        continue
    busy = 0
    new = []
    for t in sorted(r["trades"], key=lambda x: x["entryTs"]):
        e = t["entryTs"]
        if e < busy:
            continue
        o = idx(json.loads((DATA / "opt" / f"{occ(r['symbol'], r['date'], t['call'], t['strike'])}.json").read_text()))
        p0 = float(t["entryPremium"])
        lim, need = round(p0 * TP, 2), (2 if STRESS else 1) * TICK
        give = TICK if STRESS else 0.0
        fl = flat(r["date"])
        px, ts, why = None, None, None
        pending_stop = False
        k = e + MIN                                     # the entry minute itself is the fill minute; manage from the next one
        while k <= fl:
            b = o.get(k)
            if k >= fl or k >= e + HOLD * MIN or pending_stop:
                if b is None:                            # no print this minute: wait for the next real print
                    k += MIN
                    if k > fl + 10 * MIN:
                        break
                    continue
                px, ts = b["o"] - give, k
                why = "premium stop (1m close <= 70%)" if pending_stop else ("flatten 15:45" if k >= fl else "time stop 60m")
                break
            if b:
                if b["h"] >= lim + need:
                    px, ts, why = lim, k, f"limit x{TP:.2f}"
                    break
                if b["c"] <= p0 * SL:
                    pending_stop = True
            k += MIN
        if px is None:
            last = max((kk for kk in o if kk <= fl + 10 * MIN), default=None)
            px, ts, why = (o[last]["c"] - give if last else 0.0), (last or fl), "last print (no later print)"
        pct = ((px * 100 - FEE) - (p0 * 100 + FEE)) / (p0 * 100 + FEE) * 100
        busy = ts
        reasons[why.split(" (")[0]] = reasons.get(why.split(" (")[0], 0) + 1
        new.append({**t, "exitTs": ts, "exitReason": why, "pnlPct": round(pct, 2), "win": pct > 0, "exits": [], "added": []})
    out_rows.append({**r, "trades": new})
tag = f"X_tp{TP:g}{'_stress' if STRESS else ''}"
dst = str(pathlib.Path(sys.argv[2]).parent / f"train_{tag}.json")
json.dump({"rules": d["rules"], "overrides": {"bracket": tag}, "rows": out_rows}, open(dst, "w"))
p = [t["pnlPct"] for r in out_rows for t in r["trades"]]
print(tag, "trades", len(p), "mean", round(st.mean(p), 2), "median", round(st.median(p), 2), "win%", round(100 * sum(x > 0 for x in p) / len(p), 1), reasons, "->", dst)
