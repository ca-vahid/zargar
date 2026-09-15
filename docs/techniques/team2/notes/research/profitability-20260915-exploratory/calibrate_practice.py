"""Practice-scale calibration of the sizing-cap and C1 arms (reviewer's correction 2, 2026-09-15): re-price every arm's
model trades with the LIVE sizing path — risk$ = equity x risk_pct, per-contract risk = premium x 100 x premium_stop_pct,
n = int(raw x sizeMult), min(budget // premium), the 0DTE contract cap, min 1 — through the same chronological book
(one position desk-wide, two losses end the day, the day-loss halt), with equity compounding. Modeled $ = pnlPct x
position premium (the model's pnlPct is per unit of position and already fee/slippage-adjusted at $1.04/side + 1 tick).
Input: arms_trades.json (per-trade model results on the exploratory tape). Output: practice_calibration.json."""
import json, os
from collections import defaultdict
D = os.path.dirname(os.path.abspath(__file__))   # reads arms_trades.json beside it
d = json.load(open(os.path.join(D, "arms_trades.json")))
LIVE = {"equity0": 9934.16, "risk_pct": 6.0, "premium_stop_pct": 25.0, "budget": 2000.0, "cap_0dte": 40, "cap_risk": 50,
        "min_one": True, "day_loss_limit_mult": 2.0, "technique_pause_pct": 10.0, "book_breaker_pct": 15.0, "max_losses": 2}


def contracts(equity, premium, size_mult, cap):
    risk = equity * LIVE["risk_pct"] / 100.0
    per = premium * 100.0 * LIVE["premium_stop_pct"] / 100.0
    n = int(risk / max(per, 1e-9) * size_mult)
    n = min(n, int(LIVE["budget"] // max(premium * 100.0, 1e-9)))
    n = min(n, cap)
    return max(1 if LIVE["min_one"] else 0, n)


def practice_book(trades, *, cap, compounding=True, size_override=None):
    ts = sorted(trades, key=lambda t: (t["entryTs"], t["symbol"]))
    equity = LIVE["equity0"]; start = equity; peak = equity; mdd = 0.0
    open_until = 0; losses = defaultdict(int); day_pnl = defaultdict(float); day_halted = set()
    taken = []; skip_c = skip_l = skip_h = 0; paused = False
    day_limit = LIVE["equity0"] * LIVE["risk_pct"] / 100.0 * LIVE["day_loss_limit_mult"]
    for t in ts:
        d = t["date"]
        if t["entryTs"] < open_until:
            skip_c += 1; continue
        if losses[d] >= LIVE["max_losses"]:
            skip_l += 1; continue
        if d in day_halted:
            skip_h += 1; continue
        mult = float(t["sizeMult"] or 1.0)
        if size_override is not None and mult >= 0.999:
            mult = size_override
        prem = float(t["entryPremium"])
        n = contracts(equity if compounding else LIVE["equity0"], prem, mult, cap)
        invested = n * prem * 100.0
        pnl = t["pnlPct"] / 100.0 * invested
        stop_risk = invested * LIVE["premium_stop_pct"] / 100.0
        taken.append({"date": d, "symbol": t["symbol"], "setup": t["setup"], "sizeMult": mult, "premium": round(prem, 2), "contracts": n,
                      "invested$": round(invested, 0), "stopRisk$": round(stop_risk, 0), "pnlPct": round(t["pnlPct"], 1), "pnl$": round(pnl, 0)})
        open_until = t["exitTs"]; day_pnl[d] += pnl; equity += pnl
        if pnl < 0:
            losses[d] += 1
        if day_pnl[d] <= -day_limit or day_pnl[d] <= -start * LIVE["technique_pause_pct"] / 100.0:
            day_halted.add(d)
        peak = max(peak, equity); mdd = min(mdd, equity - peak)
    total = equity - start
    by_date = {k: round(v, 0) for k, v in sorted(day_pnl.items())}
    best = max(by_date, key=by_date.get) if by_date else None
    inv = [x["invested$"] for x in taken]
    return {"cap": cap, "taken": len(taken), "skippedConcurrent": skip_c, "skippedLossCap": skip_l, "skippedDayHalt": skip_h,
            "total$": round(total, 0), "endEquity": round(equity, 0), "maxDrawdown$": round(mdd, 0), "maxDrawdownPct": round(mdd / start * 100, 1),
            "worstDay$": round(min(by_date.values()), 0) if by_date else 0, "bestDay": best, "totalWithoutBestDay$": round(total - by_date.get(best, 0), 0) if best else round(total, 0),
            "contracts": {"min": min((x["contracts"] for x in taken), default=0), "median": sorted(x["contracts"] for x in taken)[len(taken) // 2] if taken else 0,
                          "max": max((x["contracts"] for x in taken), default=0), "atCap": sum(1 for x in taken if x["contracts"] == cap)},
            "invested$": {"median": sorted(inv)[len(inv) // 2] if inv else 0, "max": max(inv, default=0), "sum": round(sum(inv), 0)},
            "stopRisk$": {"median": sorted(x["stopRisk$"] for x in taken)[len(taken) // 2] if taken else 0, "max": max((x["stopRisk$"] for x in taken), default=0)},
            "grossWins$": round(sum(x["pnl$"] for x in taken if x["pnl$"] > 0), 0), "grossLosses$": round(sum(x["pnl$"] for x in taken if x["pnl$"] < 0), 0),
            "byDate$": by_date, "bySymbol$": {s: round(sum(x["pnl$"] for x in taken if x["symbol"] == s), 0) for s in ("SPY", "QQQ", "IWM")},
            "trades": taken}


out = {"live": LIVE, "datasetVersion": d["datasetVersion"], "arms": {}}
for arm in ("baseline", "size_half", "C1"):
    for cap_label, cap in (("cap40", 40), ("cap50", 50)):
        r = practice_book(d["arms"][arm], cap=cap)
        out["arms"][f"{arm}@{cap_label}"] = r
        print(f"{arm:10s} {cap_label}: taken={r['taken']} total=${r['total$']:>6} end=${r['endEquity']} mdd=${r['maxDrawdown$']} ({r['maxDrawdownPct']}%) worst=${r['worstDay$']} "
              f"noBest=${r['totalWithoutBestDay$']} contracts min/med/max={r['contracts']['min']}/{r['contracts']['median']}/{r['contracts']['max']} atCap={r['contracts']['atCap']} "
              f"invested med/max=${r['invested$']['median']}/${r['invested$']['max']} stopRisk med/max=${r['stopRisk$']['median']}/${r['stopRisk$']['max']} "
              f"skip conc/loss/halt={r['skippedConcurrent']}/{r['skippedLossCap']}/{r['skippedDayHalt']} bySym={r['bySymbol$']}")
# the sizing cap expressed directly on the baseline trades (identical to the size_half arm's own trade list by construction)
r = practice_book(d["arms"]["baseline"], cap=40, size_override=0.5)
out["arms"]["baseline_resized_0.5@cap40"] = r
print(f"baseline resized 0.5 @cap40: total=${r['total$']} mdd=${r['maxDrawdown$']} (check vs size_half@cap40)")
json.dump(out, open(os.path.join(D, "practice_calibration.json"), "w"), indent=1)
print("written practice_calibration.json")
