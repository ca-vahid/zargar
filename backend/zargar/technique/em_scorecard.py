"""EM scorecard: the running track record, the stop rule and the preregistered tests (`em-scorecard-v1`, 2026-09-22).

Why this exists. By 2026-09-22 EM had closed 38 trades for −$219.40 after fees, profit factor 0.84, and the record
was too short to show an edge in either direction. The tempting response is to tune whatever lost last week. This
module is the opposite of that: every threshold below was fixed BEFORE the data that will decide it exists, and the
module only ever reports whether a question is still collecting, ready to decide, or already decided.

Three things are computed, and none of them changes a trade:

  * the TRACK RECORD - closed trades matched first-in-first-out from fills, per book;
  * the STOP RULE for EM itself - after enough evaluable sessions with no edge, stop paying for the model review;
  * the PREREGISTERED TESTS - each open method question, its threshold, and where it stands.

Everything here is pure. `tools/em_scorecard.py` reads the database and hands the rows in.
"""
from __future__ import annotations

import random
import re
import statistics as st

VERSION = "em-scorecard-v1"
BASELINE_BOOK = "045d8c35b3f149628ea001ae90a58edb"
EXPERIMENT_BOOK = "07ef1e867cad4150bc81e072a8fd600a"

# ---- the stop rule, adopted 2026-09-22 on the user's decision --------------------------------------------------
# Counted FORWARD from its adoption, deliberately. The sessions that motivated the rule are not allowed to decide it:
# a rule fitted to the data that suggested it proves nothing.
STOP_RULE = {
    "version": "em-stop-rule-v1",
    "adopted": "2026-09-22",
    "countFrom": "2026-09-22",            # the first session in which both books actually traded
    "minEvaluableSessions": 20,
    "maxCumulativeR": 0.0,                # at or below zero ...
    "upperMeanRBelow": 0.10,              # ... AND the optimistic end of the average trade below +0.1R
    "decides": "the paid model review that prepares the baseline book",
    "action": "stop the paid review and keep EM watch-only: plans still built and scored, no money spent",
}

# ---- session-book pairs the environment, not the method, decided --------------------------------------------------
# Kept in every chronological report and excluded only from evaluation. Per BOOK: on 2026-09-21 the baseline traded
# normally and only the experimental book was blocked.
IMPAIRED = {
    ("2026-09-21", EXPERIMENT_BOOK): "host clock 10.5 s behind true time; the admission gate correctly refused every "
                                     "experimental entry as future-dated (reviews/2026-09-21-FIX-CLOSURE.md)",
}

# ---- fills the record keeps but must not be believed -------------------------------------------------------------
DISPUTED_FILLS = {
    "04be1c67c0754bc9be2ab28e4c55965f": {
        "fairPrice": 2.29,
        "why": "ORCL 2026-09-17: a buy limit at 2.29 recorded a fill at 1.12 while the quote was 2.10 / 2.29 - below "
               "any price offered (E17-01). Reported as booked AND at the ask; never silently replaced",
    },
}

# ---- the preregistered tests -------------------------------------------------------------------------------------
TESTS = [
    {"id": "midday", "question": "does allowing entries between 10:30 and 14:45 ET add value?",
     "registered": "2026-08-26", "threshold": "30 scored midday fires", "status": "decided",
     "decision": "2026-09-22: OFF. 62 fires; filled midday trades lost −0.30R each against −0.09R in the prime "
                 "windows (not statistically separable, p = 0.36). No evidence FOR midday, so the book's R6 stands."},
    {"id": "shares_fallback", "question": "does the shares fallback do as well as the option leg?",
     "registered": "2026-09-12", "countFrom": "2026-09-12", "minTrades": 20,
     "metric": "mean R of long-shares trades against long-option trades"},
    {"id": "short_puts_prime", "question": "do short puts pay in the prime windows, now that midday is off?",
     "registered": "2026-09-22", "countFrom": "2026-09-23", "minTrades": 20,
     "metric": "mean R of short trades entered in prime_open or prime_close"},
    {"id": "stop_vs_volatility", "question": "are stops that are small against the stock's own range stopped by noise?",
     "registered": "2026-09-22", "countFrom": "2026-09-23", "minTrades": 40,
     "metric": "share of stopped trades that later reached TP1, stop under 2 average 1-minute ranges vs 2 or more"},
    {"id": "one_touch_levels", "question": "do entries off a level touched only once lose disproportionately?",
     "registered": "2026-09-22", "countFrom": "2026-09-23", "minTrades": 15,
     "metric": "mean R of one-touch-level trades against the rest"},
    {"id": "rules_vs_model", "question": "does free rules-only preparation do no worse than the paid model review?",
     "registered": "2026-09-19", "countFrom": "2026-09-22", "minSessions": 20, "status": "decided",
     "decision": "2026-09-23: SUPERSEDED BY DECISION, not answered - EM is fully deterministic (both books prepare by rules). "
                 "The model-veto study (research/2026-09-23-MODEL-VETO-STUDY.md, 18 scored sessions) found no measurable value in "
                 "the veto: approved +0.26R vs vetoed +0.12R per filled trade, overlapping intervals."},
    {"id": "break_vs_level", "question": "do break triggers (ladder targets) lose against level-anchored bounce/reject triggers?",
     "registered": "2026-09-23", "countFrom": "2026-09-24", "minTrades": 30,
     "metric": "mean R of breakout/breakdown/wedge_break trades against bounce/reject trades (the veto study: -0.27R on 22 "
               "fills vs +0.40R on 54 over 2026-08-25..09-18, NOT confirmed out of sample - hence a test, not a rule)"},
]

_OCC = re.compile(r"\d{6}[CP]\d{8}$")


def is_option(symbol: str) -> bool:
    return bool(_OCC.search(str(symbol or "")))


def match_trades(executions: list, *, exit_kind_by_order: dict | None = None) -> tuple[list, dict]:
    """Closed round trips per book and symbol, first in first out. `executions` = dicts with
    id, order_id, portfolio_id, symbol, side, qty, price, commission, ts (epoch ms), sorted or not.
    Returns (trades, open_lots). A disputed fill is booked as recorded AND repriced alongside, never replaced."""
    ek = exit_kind_by_order or {}
    lots: dict = {}
    trades: dict = {}
    for x in sorted(executions, key=lambda r: (int(r["ts"]), str(r["id"]))):
        key = (x["portfolio_id"], x["symbol"])
        mult = 100.0 if is_option(x["symbol"]) else 1.0
        qty, price, fee = float(x["qty"]), float(x["price"]), float(x.get("commission") or 0.0)
        fair = (DISPUTED_FILLS.get(str(x["id"])) or {}).get("fairPrice")
        if str(x["side"]).upper() == "BUY":
            t = trades.setdefault(x["order_id"], {
                "entryOrder": x["order_id"], "book": x["portfolio_id"], "symbol": x["symbol"], "mult": mult,
                "qty": 0.0, "cost": 0.0, "fairCost": 0.0, "fees": 0.0, "legs": [], "entryTs": int(x["ts"]),
                "disputed": []})
            t["qty"] += qty
            t["cost"] += qty * price
            t["fairCost"] += qty * (float(fair) if fair is not None else price)
            t["fees"] += fee
            if fair is not None:
                t["disputed"].append(DISPUTED_FILLS[str(x["id"])]["why"])
            lots.setdefault(key, []).append({"trade": x["order_id"], "qty": qty, "price": price,
                                             "fair": float(fair) if fair is not None else price})
        else:
            q = qty
            while q > 1e-9 and lots.get(key):
                lot = lots[key][0]
                m = min(q, lot["qty"])
                t = trades[lot["trade"]]
                t["legs"].append({"kind": ek.get(x["order_id"], "unknown"), "qty": m, "price": price,
                                  "pnl": (price - lot["price"]) * m * mult,
                                  "fairPnl": (price - lot["fair"]) * m * mult,
                                  "fee": fee * m / qty, "ts": int(x["ts"]), "order": x["order_id"]})
                t["fees"] += fee * m / qty
                lot["qty"] -= m
                q -= m
                if lot["qty"] <= 1e-9:
                    lots[key].pop(0)
    out = []
    for t in trades.values():
        if not t["legs"]:
            continue
        closed = sum(l["qty"] for l in t["legs"])
        if abs(closed - t["qty"]) > 1e-6:
            continue                                    # still open at the cutoff: not a closed trade
        t["avgEntry"] = t["cost"] / t["qty"]
        t["gross"] = sum(l["pnl"] for l in t["legs"])
        t["fairGross"] = sum(l["fairPnl"] for l in t["legs"])
        t["net"] = t["gross"] - t["fees"]
        t["fairNet"] = t["fairGross"] - t["fees"]
        t["finalExit"] = t["legs"][-1]["kind"]
        t["instrument"] = "option" if t["mult"] == 100.0 else "shares"
        out.append(t)
    out.sort(key=lambda r: r["entryTs"])
    return out, {k: v for k, v in lots.items() if v}


def planned_risk(trade: dict, *, premium_stop_pct: float = 50.0) -> float | None:
    """The method's OWN risk unit for this trade - what it planned to lose - so R is not fitted to the outcomes.
    Shares: the entry-to-stop distance on the underlying times the size. Options: the premium stop, which is what the
    sizer budgets (premium x 100 x qty x premium_stop_pct)."""
    if trade.get("instrument") == "option":
        risk = float(trade["avgEntry"]) * 100.0 * float(trade["qty"]) * premium_stop_pct / 100.0
        return risk if risk > 0 else None
    e, s = trade.get("uEntry"), trade.get("uStop")
    if e is None or s is None:
        return None
    risk = abs(float(e) - float(s)) * float(trade["qty"])
    return risk if risk > 0 else None


def r_of(trade: dict, *, fair: bool = False, premium_stop_pct: float = 50.0) -> float | None:
    risk = planned_risk(trade, premium_stop_pct=premium_stop_pct)
    if not risk:
        return None
    return float(trade["fairNet" if fair else "net"]) / risk


def evaluable(trade: dict) -> bool:
    return (trade.get("session"), trade.get("book")) not in IMPAIRED


def dedupe(trades: list) -> list:
    """One row per (session, underlying, trigger): the experiment copying a baseline trade is one decision, not two."""
    seen, out = set(), []
    for t in trades:
        k = (t.get("session"), t.get("underlying") or t.get("symbol"), t.get("trigger"))
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def summary(trades: list, *, fair: bool = False, premium_stop_pct: float = 50.0) -> dict:
    net_key = "fairNet" if fair else "net"
    nets = [float(t[net_key]) for t in trades]
    rs = [r for r in (r_of(t, fair=fair, premium_stop_pct=premium_stop_pct) for t in trades) if r is not None]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    gw, gl = sum(wins), -sum(losses)
    return {"trades": len(trades), "net": round(sum(nets), 2), "fees": round(sum(float(t["fees"]) for t in trades), 2),
            "winRate": (round(len(wins) / len(nets), 3) if nets else None),
            "avgWin": (round(st.mean(wins), 2) if wins else None), "avgLoss": (round(st.mean(losses), 2) if losses else None),
            "profitFactor": (round(gw / gl, 2) if gl > 0 else None),
            "sumR": (round(sum(rs), 2) if rs else None), "meanR": (round(st.mean(rs), 3) if rs else None),
            "rCount": len(rs)}


def upper_mean_r(trades: list, *, draws: int = 5000, level: float = 0.95, seed: int = 20260922,
                 premium_stop_pct: float = 50.0) -> float | None:
    """The optimistic end of the average trade in R, resampling whole SESSIONS (trades on one day are not
    independent - they share a tape). Seeded, so the same data always gives the same answer."""
    by: dict = {}
    for t in trades:
        r = r_of(t, premium_stop_pct=premium_stop_pct)
        if r is not None:
            by.setdefault(t["session"], []).append(r)
    sessions = list(by.values())
    if len(sessions) < 2:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        pick = [rng.choice(sessions) for _ in sessions]
        flat = [r for s in pick for r in s]
        means.append(st.mean(flat))
    means.sort()
    return round(means[min(len(means) - 1, int(level * len(means)))], 3)


def stop_rule(trades: list, *, book: str = BASELINE_BOOK, premium_stop_pct: float = 50.0) -> dict:
    """The rule EM is held to. It does not stop anything by itself: it says whether the stop condition is met."""
    rule = STOP_RULE
    mine = [t for t in trades if t["book"] == book and t["session"] >= rule["countFrom"] and evaluable(t)]
    sessions = sorted({t["session"] for t in mine})
    s = summary(mine, premium_stop_pct=premium_stop_pct)
    upper = upper_mean_r(mine, premium_stop_pct=premium_stop_pct)
    enough = len(sessions) >= rule["minEvaluableSessions"]
    cum = s["sumR"] if s["sumR"] is not None else 0.0
    tripped = bool(enough and cum <= rule["maxCumulativeR"] and upper is not None and upper < rule["upperMeanRBelow"])
    if not enough:
        verdict = "collecting"
        why = f"{len(sessions)} of {rule['minEvaluableSessions']} evaluable sessions since {rule['countFrom']}"
    elif tripped:
        verdict = "tripped"
        why = (f"cumulative {cum:+.2f}R over {len(sessions)} sessions and the optimistic average trade is only "
               f"{upper:+.3f}R - {rule['action']}")
    else:
        verdict = "passing"
        why = f"cumulative {cum:+.2f}R, optimistic average {upper}R - the method has not been shown to have no edge"
    return {"rule": rule, "book": book, "evaluableSessions": len(sessions), "summary": s, "upperMeanR": upper,
            "verdict": verdict, "why": why}


def _mean_r(ts: list, premium_stop_pct: float) -> float | None:
    rs = [r for r in (r_of(t, premium_stop_pct=premium_stop_pct) for t in ts) if r is not None]
    return round(st.mean(rs), 3) if rs else None


def run_tests(trades: list, *, premium_stop_pct: float = 50.0) -> list:
    """Where every preregistered question stands. A reading is printed for transparency but is NOT a verdict until the
    test is `ready`; nobody decides on a partial sample, which is the whole point of fixing the threshold first."""
    ev = [t for t in dedupe(trades) if evaluable(t)]
    out = []
    for spec in TESTS:
        row = {k: v for k, v in spec.items()}
        if spec.get("status") == "decided":
            out.append(row)
            continue
        since = spec.get("countFrom", "0000")
        pool = [t for t in ev if t["session"] >= since]
        tid = spec["id"]
        if tid == "shares_fallback":
            a = [t for t in pool if t["instrument"] == "shares" and t.get("direction") == "long"]
            b = [t for t in pool if t["instrument"] == "option" and t.get("direction") == "long"]
            n = len(a)
            reading = {"sharesMeanR": _mean_r(a, premium_stop_pct), "optionsMeanR": _mean_r(b, premium_stop_pct),
                       "shares": len(a), "options": len(b)}
        elif tid == "short_puts_prime":
            a = [t for t in pool if t.get("direction") == "short" and t.get("window") in ("prime_open", "prime_close")]
            n = len(a)
            reading = {"meanR": _mean_r(a, premium_stop_pct), "net": round(sum(float(t["net"]) for t in a), 2)}
        elif tid == "stop_vs_volatility":
            a = [t for t in pool if t.get("finalExit") == "stop" and t.get("stopOverRange") is not None]
            tight = [t for t in a if t["stopOverRange"] < 2]
            wide = [t for t in a if t["stopOverRange"] >= 2]
            frac = lambda xs: (round(sum(1 for t in xs if t.get("laterReachedTp1")) / len(xs), 3) if xs else None)
            n = len(a)
            reading = {"tight": len(tight), "tightReachedTp1": frac(tight), "wide": len(wide), "wideReachedTp1": frac(wide)}
        elif tid == "one_touch_levels":
            a = [t for t in pool if t.get("levelTouches") == 1]
            b = [t for t in pool if (t.get("levelTouches") or 0) > 1]
            n = len(a)
            reading = {"oneTouchMeanR": _mean_r(a, premium_stop_pct), "restMeanR": _mean_r(b, premium_stop_pct),
                       "oneTouch": len(a), "rest": len(b)}
        elif tid == "break_vs_level":
            a = [t for t in pool if t.get("kind") in ("breakout", "breakdown", "wedge_break")]
            b = [t for t in pool if t.get("kind") in ("bounce", "reject")]
            n = len(a)
            reading = {"breakMeanR": _mean_r(a, premium_stop_pct), "levelMeanR": _mean_r(b, premium_stop_pct),
                       "breaks": len(a), "levels": len(b)}
        elif tid == "rules_vs_model":
            full = [t for t in trades if t["session"] >= since and evaluable(t)]
            both = sorted({t["session"] for t in full if t["book"] == EXPERIMENT_BOOK}
                          & {t["session"] for t in full if t["book"] == BASELINE_BOOK})
            xs = [t for t in full if t["book"] == EXPERIMENT_BOOK]
            bs = [t for t in full if t["book"] == BASELINE_BOOK]
            n = len({t["session"] for t in full})
            reading = {"experiment": summary(xs, premium_stop_pct=premium_stop_pct),
                       "baseline": summary(bs, premium_stop_pct=premium_stop_pct), "sessionsWithBoth": len(both)}
        else:
            n, reading = 0, {}
        need = spec.get("minTrades") or spec.get("minSessions")
        row.update({"n": n, "need": need, "status": ("ready" if need and n >= need else "collecting"),
                    "reading": reading, "readingIsVerdict": False})
        out.append(row)
    return out
