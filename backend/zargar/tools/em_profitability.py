"""EM profitability cohorts - ORDER-FREE per-session report (reviewers' P-01..P-03, frozen 2026-09-15; PF-01..03 and the
planned-vs-actual entry label corrected the same day).

Nothing here arms, sizes, trades or changes a setting. It reads the journal, the plans, the executions and the
stored bars for ONE session and writes a baseline-versus-candidate report. Unknowns stay unknown. The P-02 and P-03
sections are PROVISIONAL until the reviewers accept the measurement corrections.

Frozen definitions (`profitability-cohorts-v1`; change = new version, never a silent edit):

P-01 setup cohort `long_bounce_next_resistance`: an EM trigger of kind `bounce`, direction `long`, whose SAVED first
    target has basis `next_resistance`. It is reported BESIDE the full baseline (every EM fill of the session); it
    never switches another family off. Strata: entry confirmation (`observed_reclaim` = the firing bar CLOSED on the
    trade's side of the level, else `anticipated`), PLANNED room (TP1 distance / planned risk from the plan's intended
    underlying entry: <1R, 1-3R, >=3R - the room at the ACTUAL underlying entry is unknown unless an underlying
    observation at dispatch exists; an option premium is never plugged into underlying geometry), quantity, and
    `sourceSymbolDirectionMatch` (symbol + direction present in the day's source ledger - NOT agreement on level,
    timeframe, conditions or horizon).
P-02 small-position exit `small-position-exit-v1` (SPX-1): eligible = option position, ORIGINAL filled quantity <= 2,
    first PRODUCTION sale >= 2.0R away (planned underlying geometry; for <3 contracts the first sale is the
    single-contract-exit rung). Alternative on IDENTICAL entry, contract and quantity: 2 contracts -> sell ONE at the
    first fresh, COVERED, executable bid observed at or after the underlying touches the plan's TP1 and keep the other
    on the production policy; 1 contract -> the whole position at that observation. Evidence = `TechniqueExitShadow`
    records with rung `tp1-candidate` from the (disabled) observer: disposition `observed`, `modeled.scorable`,
    `modeled.coveredQty` >= the alternative's quantity, `modeled.bid`, bound to the trade instance (entry order),
    the same contract and the position's lifetime. No such observation = UNKNOWN - never a candle high or a print.
    Fees (PF-02): the alternative's sold contract keeps its ACTUAL entry fee and pays the declared modeled exit fee
    (`feePerContractSide`); the retained contracts keep their ACTUAL production result; production components must
    reconcile with the execution-backed net or the pair is unknown. Profit forgone on a big winner is counted on the
    same fee basis. Faster execution at UNCHANGED targets is the separate shadow-exit-v1 experiment.
P-03 contract economics: EVERY entry intent (filled OR refused) stays in the table; friction = (fill or ask - bid at the
    intent) x qty x multiplier + round-trip fees as a share of paid premium (unknown when no quote was captured);
    `hurdle >= 8%` is a RANKING MARKER, never a gate; the payoff proxy to TP1 is SIGNED delta x SIGNED move
    (a put's negative delta on a downside move is a positive proxy; delta missing/zero/invalid = unknown) - a local
    first-order sensitivity, not a forecast; `riskBudgetQty` = contracts the UNCHANGED risk budget affords at the
    premium stop (risk % x book equity at the fire / (premium x 100 x premium_stop_pct)) - a budget bound only, not
    admission feasibility (caps, cash and exposure are not included).

    python -m zargar.tools.em_profitability report --date 2026-09-15 [--cutoff 16:00]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
from collections import defaultdict
from zoneinfo import ZoneInfo

VERSION = "profitability-cohorts-v1"
COHORT_P01 = "long_bounce_next_resistance"
P02_POLICY = "small-position-exit-v1"
P02_MAX_QTY = 2
P02_MIN_FIRST_SALE_R = 2.0
P03_HURDLE_MARK = 0.08                      # ranking marker (share of paid premium), never a gate
COHORTS_ADDENDUM = "p04-p05-2026-09-17; p06-2026-09-18"
P06_POLICY = "tp1-reclaim-runner-exit-v1"     # frozen additions (PFU-02/03 corrected): P-04 descriptive strata + PAIRED confirmation comparison, P-05 clock/event labels
SESSION_CLOCK = "sessions-v1: prime_open 09:30-10:30, midday 10:30-14:45, prime_close 14:45-16:00 ET"   # marketstructure.sessions.session_window
# Event provenance is HAND-KEPT (the app's macro calendar is empty): a date without an entry has UNKNOWN coverage, never
# "ordinary". Entries added after the session are retrospective and say so. Time is the event's ET clock time.
EVENT_CALENDAR = {"2026-09-16": {"label": "FOMC", "atEt": "14:00", "source": "hand-kept 2026-09-16 (statement 14:00, presser 14:30 ET)", "retrospective": True}}
P04_CONFIRM_WINDOW_BARS = 10                # paired comparison: a confirming completed close must arrive within this many 1m bars after the touch bar
P04_MIN_RR = 3.0                            # frozen copy of the R2 bar (technique.min_risk_reward at freeze time) - never read live, the comparison must not drift
ROOM_BINS = (("<1R", 0.0, 1.0), ("1-3R", 1.0, 3.0), (">=3R", 3.0, float("inf")))
NY = ZoneInfo("America/New_York")
EM_BOOK = "045d8c35b3f149628ea001ae90a58edb"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT_DIR = os.path.join(ROOT, "docs", "techniques", "enhanced-market", "research", "profitability")
LEDGER = os.path.join(ROOT, "docs", "techniques", "enhanced-market", "research", "source-candidates.json")


# ----------------------------------------------------------------------------------------------- pure definitions
def cohort_of(kind: str | None, direction: str | None, first_target_basis: str | None) -> str | None:
    """P-01 membership: long bounce with a saved next_resistance first target."""
    if kind == "bounce" and direction == "long" and first_target_basis == "next_resistance":
        return COHORT_P01
    return None


def room_r(entry: float | None, stop: float | None, tp1: float | None, direction: str) -> float | None:
    """Room from an underlying entry: signed TP1 distance over the entry-to-stop distance (planned when fed the plan's
    intended entry; actual only when fed an observed underlying entry)."""
    if entry is None or stop is None or tp1 is None:
        return None
    risk = abs(float(entry) - float(stop))
    if risk <= 0:
        return None
    move = (float(tp1) - float(entry)) if direction == "long" else (float(entry) - float(tp1))
    return round(move / risk, 3)


def room_bin(r: float | None) -> str:
    if r is None:
        return "unknown"
    if r <= 0:
        return "behind"
    for label, lo, hi in ROOM_BINS:
        if lo <= r < hi:
            return label
    return "unknown"


def confirmation_class(bar_close: float | None, level: float | None, direction: str) -> str:
    """`observed_reclaim` when the firing bar CLOSED on the trade's side of the level; else `anticipated`."""
    if bar_close is None or level is None:
        return "unknown"
    ok = float(bar_close) > float(level) if direction == "long" else float(bar_close) < float(level)
    return "observed_reclaim" if ok else "anticipated"


def friction(fill_or_ask: float | None, bid: float | None, qty: float | None, multiplier: float, fee_side: float) -> dict:
    """P-03 friction: price concession to the contemporaneous bid plus round-trip fees, as a share of paid premium."""
    if fill_or_ask is None or qty is None or float(qty) <= 0:
        return {"concession": None, "fees": None, "total": None, "pctOfPremium": None, "known": False}
    q = float(qty); m = float(multiplier)
    concession = (round(max(0.0, float(fill_or_ask) - float(bid)) * q * m, 2)) if bid is not None else None
    fees = 2 * fee_side * q if m > 1 else 0.0                # share fees are 0 on this book's schedule
    premium = float(fill_or_ask) * q * m
    total = (round(concession + fees, 2)) if concession is not None else None
    return {"concession": concession, "fees": fees, "total": total,
            "pctOfPremium": (round(total / premium, 4) if total is not None and premium > 0 else None),
            "known": concession is not None}


def payoff_to_tp1(delta: float | None, entry: float | None, tp1: float | None, qty: float | None, multiplier: float = 100.0) -> float | None:
    """P-03 attainable payoff proxy to the plan's TP1 in premium dollars: SIGNED delta x SIGNED underlying move x qty x
    multiplier (PF-03: a put's negative delta on a downside target is a positive proxy; an adverse move stays
    negative). None when delta is missing, zero or invalid (the stored 0.0 means unknown, never zero payoff)."""
    try:
        d = float(delta) if delta is not None else None
        if d is None or d == 0 or d != d or entry is None or tp1 is None or not qty:
            return None
        return round(d * (float(tp1) - float(entry)) * float(qty) * float(multiplier), 2)
    except (TypeError, ValueError):
        return None


def _ev_ms(ts) -> int:
    return int(ts.timestamp() * 1000) if hasattr(ts, "timestamp") else int(ts)


def _minute(ts_ms: int) -> int:
    return (int(ts_ms) // 60000) * 60000


def runner_protection(direction: str, tp1: float | None, entry: float | None, stop: float | None, exits: list[dict], executions: list,
                      bars: list[dict], cutoff_ms: int, *, filled_qty: float, multiplier: float, instrument: str | None,
                      avg_fill: float | None = None, entry_fee_per_unit: float | None = None, fee_side: float = 0.0,
                      observations: list[dict] | None = None) -> dict:
    """P-06 `tp1-reclaim-runner-exit-v1` (frozen 2026-09-18; ED-02 corrections 2026-09-17 evening). Bound to ONE trade
    instance: `exits` are that trade's own exit records (kind, orderId, ...) and `executions` the fills of those orders
    (order_id, side, qty, price, commission, ts). Rules:
    - eligible only after a CONFIRMED TP1 fill (executions of the tp1 exit order; a cancelled / unfilled trim is not a trim);
      the remaining quantity is the ORIGINAL fill minus every execution at or before the signal (partial trims and
      intermediate trims reduce it);
    - the reclaim signal = the first 1m bar COMPLETED after the TP1 fill (the fill minute's own bar included) whose close is
      back through the saved TP1 (long: close < TP1; short: close > TP1); bars must be consecutive minutes (a gap = unknown) and only bars
      completed BEFORE the production runner's next execution are visible (a stop or trim that filled first wins:
      `not_triggered`);
    - the candidate exits the remainder at the FIRST fresh covered executable quote after the signal when a
      `tp1-reclaim` observation exists (options: dollars = k x (bid - fill) x m - actual entry fee - modeled exit fee);
      otherwise the NEXT bar's open is an UNDERLYING PROXY for shares and options alike - no dollars;
    - production = the actual executions of the remainder after the signal (VWAP, allocated fees), to its terminal event;
      a remainder still open at the cutoff is `partial`.
    Never chosen after the fact: TP1 is the plan's saved first target."""
    out = {"policy": P06_POLICY, "outcome": "unknown", "why": None, "tp1": tp1, "remainingAtSignal": None, "tp1FilledQty": None,
           "tp1FillTs": None, "reclaimTs": None, "signalTs": None, "modeledExitTs": None, "modeledExitPx": None, "modeledBasis": None,
           "productionRunner": None, "underlyingDeltaR": None, "dollarDelta": None, "alternativeRealized": None, "productionRealized": None}
    if tp1 is None or entry is None or stop is None or abs(float(entry) - float(stop)) <= 0:
        out["why"] = "geometry missing"; return out
    long = direction != "short"; risk = abs(float(entry) - float(stop))
    ex_by_order: dict[str, list] = {}
    for e in executions or []:
        ex_by_order.setdefault(str(e["order_id"]), []).append({"ts": _ev_ms(e["ts"]), "qty": float(e["qty"] or 0), "price": float(e["price"] or 0),
                                                                "commission": float(e["commission"] or 0), "side": str(e["side"] or "")})
    exit_orders = [(x, ex_by_order.get(str(x.get("orderId") or ""), [])) for x in (exits or []) if x.get("orderId")]
    tp1_fills = [f for x, fl in exit_orders if x.get("kind") == "tp1" for f in fl if f["side"] == "SELL" and f["qty"] > 0]
    if not any(x.get("kind") == "tp1" for x, _ in exit_orders):
        out["outcome"] = "not_eligible"; out["why"] = "no TP1 trim order"; return out
    if not tp1_fills:
        out["outcome"] = "not_eligible"; out["why"] = "TP1 trim never filled (cancelled or pending) - not a completed trim"; return out
    tp1_ts = max(f["ts"] for f in tp1_fills); out["tp1FillTs"] = tp1_ts
    out["tp1FilledQty"] = sum(f["qty"] for f in tp1_fills)
    all_sells = sorted((f for _, fl in exit_orders for f in fl if f["side"] == "SELL" and f["qty"] > 0), key=lambda f: f["ts"])
    later = [f for f in all_sells if f["ts"] > tp1_ts]
    first_later_ts = later[0]["ts"] if later else None
    # bars completed strictly after the TP1 fill minute, consecutive, and completed before the production runner's next fill
    # bars that COMPLETE strictly after the TP1 fill (the fill minute's own bar included), consecutive minutes, and only
    # those completed before the production runner's next fill
    path = sorted((b for b in bars if int(b["ts"]) >= _minute(tp1_ts) and int(b["ts"]) + 60000 > tp1_ts and int(b["ts"]) + 60000 <= cutoff_ms), key=lambda b: b["ts"])
    prev = _minute(tp1_ts) - 60000; reclaim = None
    for b in path:
        ts = int(b["ts"])
        if first_later_ts is not None and ts + 60000 > first_later_ts:
            break                                                   # this bar completes after production already sold: invisible
        if ts - prev != 60000:
            out["why"] = f"bar gap after the TP1 fill ({dt.datetime.fromtimestamp(prev / 1000, NY).strftime('%H:%M')} -> {dt.datetime.fromtimestamp(ts / 1000, NY).strftime('%H:%M')})"; return out
        prev = ts
        if (float(b["close"]) < float(tp1)) if long else (float(b["close"]) > float(tp1)):
            reclaim = b; break
    if reclaim is None:
        if first_later_ts is not None:
            kinds = [x.get("kind") for x, fl in exit_orders if any(f["ts"] == first_later_ts for f in fl)]
            out["outcome"] = "not_triggered"; out["why"] = f"production exited first ({', '.join(k for k in kinds if k) or 'exit'}) before any close back through TP1"
        elif path and int(path[-1]["ts"]) + 60000 >= cutoff_ms - 60000:
            out["outcome"] = "not_triggered"; out["why"] = "no completed close back through TP1 before the session's end"
        else:
            out["outcome"] = "partial"; out["why"] = "runner still open and no reclaim observed at the cutoff"
        return out
    signal_ts = int(reclaim["ts"]) + 60000
    out.update({"reclaimTs": int(reclaim["ts"]), "signalTs": signal_ts})
    sold_before = sum(f["qty"] for f in all_sells if f["ts"] <= signal_ts)
    remaining = float(filled_qty) - sold_before
    out["remainingAtSignal"] = remaining
    if remaining <= 0:
        out["outcome"] = "not_eligible"; out["why"] = "nothing left to protect at the signal (trims took the whole position)"; return out
    # production branch: the remainder's actual executions after the signal, to its terminal event
    prod = [f for f in all_sells if f["ts"] > signal_ts]
    prod_qty = sum(f["qty"] for f in prod)
    if prod_qty + 1e-9 < remaining:
        out["outcome"] = "partial"; out["why"] = f"production still holds {remaining - prod_qty:g} of the remainder at the cutoff"; return out
    prod_vwap = sum(f["qty"] * f["price"] for f in prod) / prod_qty
    prod_fees = sum(f["commission"] for f in prod)
    out["productionRunner"] = {"qty": prod_qty, "vwap": round(prod_vwap, 4), "fees": round(prod_fees, 2),
                               "kinds": sorted({x.get("kind") for x, fl in exit_orders if any(f["ts"] > signal_ts for f in fl) if x.get("kind")})}
    # candidate branch: first fresh covered executable quote after the signal, else the next bar's open as an underlying proxy
    nxt = next((b for b in path if int(b["ts"]) == signal_ts), None)
    obs = None
    for o in observations or []:
        if o.get("rung") != "tp1-reclaim":
            continue
        m = o.get("modeled") or {}
        if m.get("scorable") and m.get("bid") and float(o.get("observedAt") or 0) >= signal_ts:
            obs = o; break
    if obs is not None and instrument == "options" and avg_fill is not None:
        bid = float(obs["modeled"]["bid"]); k = min(remaining, float(obs["modeled"].get("coveredQty") or 0))
        if k >= remaining - 1e-9:
            entry_fee = float(entry_fee_per_unit if entry_fee_per_unit is not None else fee_side)
            alt = remaining * ((bid - float(avg_fill)) * float(multiplier) - entry_fee - fee_side)
            prod_real = remaining * ((prod_vwap - float(avg_fill)) * float(multiplier) - entry_fee) - prod_fees
            out.update({"outcome": "compared", "modeledBasis": "covered executable bid at the first fresh observation after the signal",
                        "modeledExitTs": int(obs.get("observedAt")), "modeledExitPx": bid,
                        "alternativeRealized": round(alt, 2), "productionRealized": round(prod_real, 2), "dollarDelta": round(alt - prod_real, 2)})
            return out
        out["why"] = "reclaim observation covers only part of the remainder"
    if nxt is None:
        out["outcome"] = "unknown"; out["why"] = (out["why"] or "no completed bar after the signal minute to exit at"); return out
    px = float(nxt["open"])
    # the production reference must be an UNDERLYING price too: shares fill on the underlying (VWAP); an option's fills are
    # premiums, so the underlying close of the bar containing production's first runner fill stands in (labelled)
    if instrument == "options":
        pb = next((b for b in sorted(bars, key=lambda x: x["ts"]) if int(b["ts"]) <= prod[0]["ts"] < int(b["ts"]) + 60000), None)
        if pb is None:
            out["outcome"] = "unknown"; out["why"] = "no underlying bar at production's runner fill"; return out
        prod_ref = float(pb["close"]); out["productionRunner"]["underlyingRef"] = prod_ref
    else:
        prod_ref = prod_vwap
    favour = (px - prod_ref) if long else (prod_ref - px)
    out.update({"outcome": "underlying_proxy_only", "modeledBasis": "next bar's open (underlying proxy - no executable quote, no fees)",
                "modeledExitTs": int(nxt["ts"]), "modeledExitPx": px, "underlyingDeltaR": round(favour / risk, 3),
                "why": out["why"] or ("no covered tp1-reclaim observation" if instrument == "options" else "shares: no executable quote evidence - proxy only")})
    return out


def never_tp1_diag(direction: str, entry: float | None, stop: float | None, opened_ts, closed_ts, exits: list, bars: list[dict]) -> dict | None:
    """Review B diagnostic for winners that never reached TP1: the best underlying excursion (R) during the completed
    holding minutes versus the exit. Descriptive only - no threshold is derived from it."""
    if any((p.get("kind") == "tp1") for _, p in exits) or entry is None or stop is None or not opened_ts or not closed_ts:
        return None
    risk = abs(float(entry) - float(stop))
    if risk <= 0:
        return None
    o, c = int(opened_ts), int(closed_ts)
    held = [b for b in bars if int(b["ts"]) > o and int(b["ts"]) + 60000 <= c]
    if not held:
        return {"mfeR": None, "why": "no completed holding minute"}
    long = direction != "short"
    mfe = max(((float(b["high"]) - float(entry)) if long else (float(entry) - float(b["low"]))) for b in held)
    return {"mfeR": round(mfe / risk, 3), "heldBars": len(held)}


def affordable_qty(risk_budget: float, premium: float, premium_stop_pct: float, multiplier: float = 100.0) -> int:
    """Contracts the UNCHANGED risk budget affords at the premium stop (FIX-03: the budget is a bound)."""
    per = float(premium) * float(multiplier) * float(premium_stop_pct) / 100.0
    return int(float(risk_budget) // per) if per > 0 else 0


def p02_eligible(instrument: str | None, filled_qty: float | None, first_sale_r: float | None) -> bool:
    return (instrument == "options" and filled_qty is not None and 0 < float(filled_qty) <= P02_MAX_QTY
            and first_sale_r is not None and float(first_sale_r) >= P02_MIN_FIRST_SALE_R)


def _observation(o: dict, trade: dict, k: int) -> tuple[float | None, int | None, str | None]:
    """Normalise one TechniqueExitShadow payload into (bid, observed ms, reason-if-unusable). Accepts the observer's
    actual shape (disposition observed + modeled.scorable/coveredQty/bid + observedAt) and the documented reducer
    shape (disposition covered + bid + observedTs). Binds to the trade instance, the contract and the position's life."""
    if o.get("rung") != "tp1-candidate":
        return None, None, "other rung"
    inst = o.get("tradeInstance"); eid = trade.get("entryOrderId")
    if inst is not None and eid is not None and str(inst) != str(eid):
        return None, None, "other trade instance"
    csym = ((o.get("contract") or {}).get("symbol")); tsym = ((trade.get("contract") or {}).get("symbol"))
    if csym and tsym and csym != tsym:
        return None, None, "other contract"
    at = o.get("observedAt", o.get("observedTs"))
    if at is not None:
        if trade.get("openedTs") is not None and at < trade["openedTs"]:
            return None, None, "before the position opened"
        if trade.get("closedTs") is not None and at > trade["closedTs"]:
            return None, None, "after the position closed"
    modeled = o.get("modeled") or {}
    if o.get("disposition") == "observed" and modeled:
        if not modeled.get("scorable"):
            return None, at, f"unscorable ({modeled.get('why') or 'no coverage'})"
        if float(modeled.get("coveredQty") or 0) + 1e-9 < k:
            return None, at, f"coverage {modeled.get('coveredQty')} below the alternative's {k}"
        return (float(modeled["bid"]) if modeled.get("bid") else None), at, None
    if o.get("disposition") == "covered" and o.get("bid"):
        return float(o["bid"]), at, None
    return None, at, (o.get("disposition") or "unusable")


def p02_compare(trade: dict, observations: list[dict], fee_side: float) -> dict:
    """SPX-1 on identical entry/contract/quantity. `trade`: filledQty, avgFill, multiplier, productionRealized (closed
    net $ or None while open), productionPerContract (per-contract realized $ in exit order, ACTUAL fees; or None),
    entryFeePerContract (actual; defaults to fee_side), entryOrderId, contract, openedTs, closedTs.
    Alternative = k x ((bid - fill) x m - actual entry fee - modeled exit fee) + production realized on the retained
    contracts. Unknown without a usable covered observation or without reconcilable production components."""
    q = int(float(trade.get("filledQty") or 0)); fill = trade.get("avgFill"); m = float(trade.get("multiplier") or 100)
    k = 1 if q == 2 else q
    out = {"policy": P02_POLICY, "quantity": q, "soldByAlternative": k, "outcome": "unknown", "why": None,
           "alternativeRealized": None, "productionRealized": trade.get("productionRealized"), "delta": None, "forgoneOnWinner": None,
           "feeBasis": {"entry": "actual", "modeledExit": fee_side, "retained": "actual"}}
    usable, reasons = [], []
    for o in observations or []:
        bid, at, why = _observation(o, trade, k)
        if bid is not None:
            usable.append((at or 0, bid, o))
        elif why:
            reasons.append(why)
    if not usable:
        out["why"] = ("no covered executable-bid observation at the TP1 touch" + (f" ({'; '.join(sorted(set(reasons)))})" if reasons else " (observer records absent)"))
        return out
    if fill is None or q <= 0:
        out["why"] = "entry fill unknown"; return out
    at, bid, o = sorted(usable, key=lambda x: x[0])[0]                   # the FIRST covered opportunity
    entry_fee = float(trade.get("entryFeePerContract", fee_side))
    alt_sold = k * ((bid - float(fill)) * m - entry_fee - fee_side)
    out.update({"observedAt": at, "bid": bid})
    if trade.get("productionRealized") is None:
        out["outcome"] = "partial"; out["why"] = "production position still open - the retained runner is unresolved"
        out["alternativeRealized"] = round(alt_sold, 2); return out
    per = trade.get("productionPerContract") or []
    if len(per) != q:
        out["why"] = "production per-contract realized not reconstructible"; return out
    if abs(sum(per) - float(trade["productionRealized"])) > 0.01:
        out["why"] = "production components do not reconcile with the execution-backed net"; return out
    prod_on_sold = sum(per[:k])
    alt_total = alt_sold + sum(per[k:])
    out.update({"outcome": "compared", "alternativeRealized": round(alt_total, 2), "delta": round(alt_total - float(trade["productionRealized"]), 2),
                "forgoneOnWinner": round(max(0.0, prod_on_sold - alt_sold), 2)})
    return out


# ----------------------------------------------------------------------------------------------- session assembly
def _ms(d: dt.date, hh: int, mm: int) -> int:
    return int(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=NY).timestamp() * 1000)


def session_close_of(ts_ms: int) -> int:
    """The regular-session close (16:00 ET) of the day `ts_ms` falls on - the only clock that closes an intraday horizon.
    Early-close days are not modelled here: a 13:00 ET close leaves horizons pending until 16:00, never the reverse."""
    d = dt.datetime.fromtimestamp(ts_ms / 1000, tz=NY).date()
    return _ms(d, 16, 0)


def underlying_proxy(bars: list[dict], fired_ts: int, entry: float, stop: float, tp1: float, direction: str, cutoff_ms: int) -> str:
    """Underlying-only diagnostic for a fired trigger that produced no position: which came first after the firing bar,
    a TP1 touch or a close through the stop, by the cutoff. Not dollars, not an option outcome."""
    long = direction == "long"
    path = [b for b in bars if fired_ts < int(b["ts"]) and int(b["ts"]) + 60000 <= cutoff_ms]
    prev_ts = None
    for b in sorted(path, key=lambda x: x["ts"]):
        if prev_ts is not None and int(b["ts"]) - prev_ts != 60000:
            return "unknown (bar gap)"
        prev_ts = int(b["ts"])
        stopped = b["close"] < stop if long else b["close"] > stop
        hit = b["high"] >= tp1 if long else b["low"] <= tp1
        if hit and stopped:
            return "unknown (same-bar target and stop)"
        if hit:
            return "tp1_first"
        if stopped:
            return "stop_first"
    return "unresolved"


def session_labels(fired_ts: int, date: str) -> dict:
    """PFU-03: timezone-aware fire time, the versioned session window from the shared clock, and event provenance with
    pre / post / unknown - a date without a calendar entry is `unknown_calendar`, never ordinary."""
    from ..marketstructure.sessions import session_window
    fired = dt.datetime.fromtimestamp(fired_ts / 1000, NY)
    ev = EVENT_CALENDAR.get(date)
    if not ev:
        phase = "unknown_calendar"
    else:
        hh, mm = (int(x) for x in ev["atEt"].split(":"))
        at = fired.replace(hour=hh, minute=mm, second=0, microsecond=0)
        phase = ("pre_event:" if fired < at else "post_event:") + ev["label"]
    return {"firedAtIso": fired.isoformat(), "sessionWindow": session_window(fired_ts), "sessionClock": SESSION_CLOCK,
            "eventPhase": phase, "eventProvenance": (ev["source"] if ev else "no calendar entry"), "eventRetrospective": (bool(ev.get("retrospective")) if ev else None)}


def confirmation_pair(bars: list[dict], fired_ts: int, direction: str, level: float | None, stop: float | None, tp1: float | None, tp2: float | None,
                      cutoff_ms: int, *, window_bars: int = P04_CONFIRM_WINDOW_BARS, min_rr: float = P04_MIN_RR,
                      session_close_ms: int | None = None) -> dict:
    """PFU-02 (corrected after the 2026-09-17 re-review): the PAIRED, order-free confirmation variant of one touch
    attempt - a GEOMETRY-ONLY UNDERLYING PROXY, not an admitted entry. Frozen rules:
    - the firing (touch) bar itself never qualifies as the confirming close; the scan starts at the first bar AFTER it
      (a firing bar that closed beyond the level is the `observed_reclaim` stratum of P-04a, and the paired variant
      still waits for the NEXT completed close);
    - confirmation = first COMPLETED 1m close beyond the level within `window_bars`; entry = the OPEN of the following bar
      (no same-close hindsight fill);
    - re-run the geometry gates only: stop side, room to TP1, R2 >= `min_rr` at the exit rung (TP2 when present) - a frozen
      copy of the bar. NOT evaluated (unknown, never assumed passed): quote quality / freshness, premium sizing and the
      quantity-dependent exit rung, the never-chase cap, timing windows, admission and daily-loss budgets;
    - follow the underlying FROM THE ENTRY BAR (inclusive): TP1 touch vs stop close, first come; both on one bar = unknown;
    - an incomplete horizon (fewer than `window_bars` bars observed and the session not over) is `pending`, not
      `no_confirmation`; ONLY the session's actual last bar closes the horizon (`session_close_ms`, default 16:00 ET on
      the firing day) - the REPORT cutoff (`cutoff_ms`, e.g. a 10:02 ET intraday report) never does: fewer bars because
      the report ran early is pending, not a non-confirmation.
    Underlying-only R (full-size proxy at TP1, -1R at the stop); option premium at the delayed time is UNKNOWN.
    Outcomes: no_confirmation, pending (...), refused_stop_side, refused_no_room, refused_r2, unknown (...), tp1_first,
    stop_first, unresolved."""
    out = {"policy": "geometry_only_underlying_proxy:confirmed_close_then_next_open", "windowBars": window_bars, "minRr": min_rr,
           "gatesNotEvaluated": ["quote quality/freshness", "premium sizing / quantity-dependent exit rung", "never-chase cap", "timing window", "admission and daily-loss budgets"],
           "outcome": None, "resultR": None, "confirmTs": None, "entryTs": None, "entry": None, "riskPerUnit": None, "rr": None, "barsWaited": None}
    if level is None or stop is None or tp1 is None:
        out["outcome"] = "unknown (level, stop or target missing)"; return out
    long = direction == "long"
    path = sorted([b for b in bars if int(b["ts"]) > fired_ts and int(b["ts"]) + 60000 <= cutoff_ms], key=lambda x: x["ts"])
    prev = fired_ts; confirm_i = None
    for i, b in enumerate(path[:window_bars]):
        if int(b["ts"]) - prev != 60000:
            out["outcome"] = "unknown (bar gap before confirmation)"; return out
        prev = int(b["ts"])
        if (b["close"] > level) if long else (b["close"] < level):
            confirm_i = i; break
    if confirm_i is None:
        observed = min(len(path), window_bars); out["barsWaited"] = observed
        close_ms = session_close_ms if session_close_ms is not None else session_close_of(fired_ts)
        session_over = bool(path) and int(path[-1]["ts"]) + 60000 >= close_ms         # the last observed bar IS the session's last bar
        if observed < window_bars and not session_over:
            out["outcome"] = f"pending (horizon incomplete: {observed} of {window_bars} bars observed)"; return out
        out["outcome"] = "no_confirmation"; return out
    if confirm_i + 1 >= len(path) or int(path[confirm_i + 1]["ts"]) - int(path[confirm_i]["ts"]) != 60000:
        out["outcome"] = "unknown (no executable bar after the confirming close)"; return out
    eb = path[confirm_i + 1]
    entry = float(eb["open"])
    out.update({"confirmTs": int(path[confirm_i]["ts"]), "entryTs": int(eb["ts"]), "entry": round(entry, 4), "barsWaited": confirm_i + 1})
    risk = (entry - stop) if long else (stop - entry)
    if risk <= 0:
        out["outcome"] = "refused_stop_side"; return out
    out["riskPerUnit"] = round(risk, 4)
    room1 = (tp1 - entry) if long else (entry - tp1)
    if room1 <= 0:
        out["outcome"] = "refused_no_room"; return out
    rung = tp2 if tp2 is not None else tp1
    rr = ((rung - entry) if long else (entry - rung)) / risk
    out["rr"] = round(rr, 2)
    if rr < min_rr:
        out["outcome"] = "refused_r2"; return out
    prev = int(eb["ts"]) - 60000
    for b in path[confirm_i + 1:]:                       # FROM the entry bar: the fill minute itself can reach TP1 or the stop
        if int(b["ts"]) - prev != 60000:
            out["outcome"] = "unknown (bar gap after entry)"; return out
        prev = int(b["ts"])
        stopped = (b["close"] < stop) if long else (b["close"] > stop)
        hit = (b["high"] >= tp1) if long else (b["low"] <= tp1)
        if hit and stopped:
            out["outcome"] = "unknown (same-bar target and stop)"; return out
        if hit:
            out["outcome"] = "tp1_first"; out["resultR"] = round(room1 / risk, 2); return out
        if stopped:
            out["outcome"] = "stop_first"; out["resultR"] = -1.0; return out
    out["outcome"] = "unresolved"; return out


async def _budget_inputs(c, fired_ts: int) -> tuple[float | None, float | None, str]:
    """Book equity at the fire (last persisted equity point at or before it) and the premium-stop % from settings.
    Any failure = unknown (the report never blocks on a diagnostic)."""
    equity = None; stop_pct = None; basis = "equity_points at the fire; settings premium_stop_pct"
    try:
        r = await c.fetchrow("select equity from equity_points where portfolio_id=$1 and ts <= $2 order by ts desc limit 1", EM_BOOK, int(fired_ts))
        equity = float(r["equity"]) if r and r["equity"] is not None else None
        rows = await c.fetch("select key, value from settings where key = any($1::text[])",
                             ["techniques.enhanced_market.premium_stop_pct", "execution.premium_stop_pct", "technique.arm.premium_stop_pct"])
        vals = {x["key"]: x["value"] for x in rows}
        for key in ("techniques.enhanced_market.premium_stop_pct", "execution.premium_stop_pct", "technique.arm.premium_stop_pct"):
            if key in vals:
                v = vals[key]; v = json.loads(v) if isinstance(v, str) else v
                stop_pct = float(v.get("v") if isinstance(v, dict) else v); basis = f"equity_points at the fire; {key}"; break
        if stop_pct is None:
            stop_pct = 50.0; basis = "equity_points at the fire; settings default premium_stop_pct=50"
    except Exception:
        return equity, None, "unknown (budget inputs unavailable)"
    return equity, stop_pct, basis


async def build(date: str, cutoff: str = "16:00") -> dict:
    import asyncpg
    from .. import config as _config
    session = dt.date.fromisoformat(date)
    hh, mm = (int(x) for x in cutoff.split(":"))
    cutoff_ms = _ms(session, hh, mm); day0 = _ms(session, 9, 30)
    url = _config.AppConfig().database_url.replace("postgresql+asyncpg://", "postgresql://")
    c = await asyncpg.connect(url)
    await c.execute("set transaction read only")
    try:
        armed = await c.fetch("""select a.run_id, a.symbol, a.config, a.state, r.result->'plan' as plan
            from technique_armed a join technique_runs r on r.id = a.run_id
            where a.technique='enhanced_market' and a.plan_for=$1""", date)
        ledger = []
        if os.path.exists(LEDGER):
            d = json.load(open(LEDGER, encoding="utf-8"))
            ledger = [r for r in (d if isinstance(d, list) else d.get("rows", [])) if r.get("date") == date]
        matched = {(r["symbol"], r.get("direction", "long")) for r in ledger}
        fee_rows = await c.fetch("""select commission, symbol, qty from executions where portfolio_id=$1 and ts >= to_timestamp($2/1000.0) and ts < to_timestamp($3/1000.0)""",
                                 EM_BOOK, day0 - 3600_000, cutoff_ms)
        opt_fees = sorted(float(r["commission"] or 0) / float(r["qty"] or 1) for r in fee_rows if len(r["symbol"]) > 6 and r["qty"])
        fee_side = opt_fees[len(opt_fees) // 2] if opt_fees else 1.04
        trades, refused, attempts = [], [], []       # attempts = the fire-attempt census from immutable events (DE-02)
        for a in armed:
            plan = a["plan"] if isinstance(a["plan"], dict) else json.loads(a["plan"] or "{}")
            state = a["state"] if isinstance(a["state"], dict) else json.loads(a["state"] or "{}")
            cfg = a["config"] if isinstance(a["config"], dict) else (json.loads(a["config"]) if a["config"] else {})
            trig = {t["id"]: t for t in (plan or {}).get("triggers", [])}
            ev = await c.fetch("""select ts, type, payload from events where aggregate_id=$1 and ts < to_timestamp($2/1000.0) order by ts""", a["run_id"], cutoff_ms)
            evs = [(e["ts"], e["type"], (e["payload"] if isinstance(e["payload"], dict) else json.loads(e["payload"] or "{}"))) for e in ev]
            bars = [dict(b) for b in await c.fetch("""select ts, open, high, low, close from bars where symbol=$1 and tf='1m' and ts >= $2 and ts < $3 order by ts""",
                                                    a["symbol"], day0, cutoff_ms)]
            # CR-02: the attempt census comes from THIS run's immutable fire events - every attempt, whether or not a trade
            # row survived (a refused attempt has no row) - keyed once per (run, trigger, decision / bar)
            for ts, ty, p in evs:
                if ty != "TechniquePlanTriggerFired":
                    continue
                did = (p.get("decision") or {}).get("decisionId")
                if any(x.get("runId") == a["run_id"] and x.get("trigger") == p.get("trigger") and ((did and x.get("decisionId") == did) or (not did and x.get("ts") == ts))
                       for x in attempts):
                    continue
                attempts.append({"runId": a["run_id"], "symbol": a["symbol"], "trigger": p.get("trigger"),
                                 "policyVersion": ((p.get("decision") or {}).get("decisionVersion") or "legacy-critic:" + str(p.get("criticMode") or "?")),
                                 "decisionId": did, "disposition": p.get("decisionDisposition") or p.get("criticDisposition"), "ts": ts})
            for tr in (state.get("trades") or []):
                tid = tr.get("triggerId"); t = trig.get(tid, {})
                fired_ts = tr.get("firedTs")
                if not fired_ts or fired_ts >= cutoff_ms:
                    continue
                first_basis = ((t.get("targets") or [{}])[0]).get("basis") if t.get("targets") else None
                direction = tr.get("direction") or t.get("direction") or "long"
                level = ((t.get("level") or {}).get("price")) if isinstance(t.get("level"), dict) else t.get("levelPrice")
                fire_bar = next((b for b in bars if int(b["ts"]) == int(fired_ts)), None) or next((b for b in bars if int(b["ts"]) == int(fired_ts) - 60000), None)
                tp1 = (tr.get("targets") or [None])[0]
                # DE-02: bind THIS attempt's events by decision identity (deterministic) or by the attempt's own time window
                # (legacy: the fire event at/after this trade's firing bar) - never the first same-trigger event of the day
                tdec = tr.get("decision") or {}
                fired_evs = [(ts, p) for ts, ty, p in evs if ty == "TechniquePlanTriggerFired" and p.get("trigger") == tid]
                intent_evs = [(ts, p) for ts, ty, p in evs if ty == "TechniquePlanOrderIntent" and p.get("trigger") == tid]

                def _same_attempt(p):
                    d = p.get("decision") or {}
                    if tdec.get("decisionId"):
                        return d.get("decisionId") == tdec.get("decisionId")
                    return not d.get("decisionId")           # a legacy trade never claims a deterministic attempt's event

                def _at_or_after_fire(ts):
                    try:
                        return int(ts.timestamp() * 1000) >= int(fired_ts) - 1
                    except Exception:
                        return True
                cand = [p for ts, p in fired_evs if _same_attempt(p) and _at_or_after_fire(ts)]
                fired_ev = cand[0] if cand else {}
                icand = [p for ts, p in intent_evs if _same_attempt(p) and _at_or_after_fire(ts)]
                intent = icand[0] if icand else None
                decision = (fired_ev.get("decision") or tdec) or {}
                policy_version = (decision.get("decisionVersion") or ("legacy-critic:" + str(fired_ev.get("criticMode") or "?") if fired_ev else "unknown"))
                td = next((p for _, ty, p in evs if ty == "TechniqueTargetDistance" and p.get("trigger") == tid and p.get("stage") == "fill"), None)
                eid = tr.get("entryOrderId")
                shadow = [p for _, ty, p in evs if ty == "TechniqueExitShadow" and p.get("trigger") == tid
                          and (p.get("tradeInstance") is None or eid is None or str(p.get("tradeInstance")) == str(eid))]
                contract = (intent or {}).get("contract") or tr.get("contract") or {}
                planned_room = room_r(tr.get("entry"), tr.get("stop"), tp1, direction)
                row = {"runId": a["run_id"], "symbol": a["symbol"], "trigger": tid, "kind": tr.get("kind") or t.get("kind"), "direction": direction,
                       "cohort": cohort_of(tr.get("kind") or t.get("kind"), direction, first_basis), "firstTargetBasis": first_basis,
                       "firedAt": dt.datetime.fromtimestamp(fired_ts / 1000, NY).strftime("%H:%M:%S"),
                       "confirmation": confirmation_class(fire_bar["close"] if fire_bar else None, level, direction),
                       "sourceSymbolDirectionMatch": (a["symbol"], direction) in matched, "status": tr.get("status"), "instrument": tr.get("instrument"),
                       "intendedEntry": tr.get("entry"), "stop": tr.get("stop"), "targets": tr.get("targets"),
                       "window": fired_ev.get("window") or tr.get("window"),
                       **session_labels(int(fired_ts), date), "firedTs": int(fired_ts), "level": level, "tp2": ((tr.get("targets") or [None, None])[1] if len(tr.get("targets") or []) > 1 else None),
                       "policyVersion": policy_version, "decisionId": decision.get("decisionId"), "decisionVerdict": decision.get("verdict"),
                       "fireDecisionMode": fired_ev.get("fireDecisionMode") or ("legacy" if fired_ev else None), "timing": fired_ev.get("timing"),
                       "quoteRefresh": (intent or {}).get("quoteRefresh"),
                       "roomPlannedR": planned_room, "roomAtActualEntryR": None,      # no underlying observation at dispatch is recorded
                       "roomBin": room_bin(planned_room),
                       "contract": {k: contract.get(k) for k in ("symbol", "bid", "ask", "mid", "spreadPct", "delta", "dte")} if contract else None}
                equity, stop_pct, budget_basis = await _budget_inputs(c, int(fired_ts))
                risk_pct = float((intent or {}).get("riskPct") or (cfg or {}).get("riskPct") or 0)
                premium_ref = contract.get("ask") or contract.get("mid")
                if equity and stop_pct and risk_pct and premium_ref and (intent or {}).get("secType", "OPT") == "OPT":
                    row["riskBudgetQty"] = affordable_qty(equity * risk_pct / 100.0, float(premium_ref), stop_pct)
                    row["riskBudgetBasis"] = f"{risk_pct:g}% x equity {equity:,.0f}; premium stop {stop_pct:g}%; {budget_basis}"
                else:
                    row["riskBudgetQty"] = None; row["riskBudgetBasis"] = "unknown (equity, premium or premium-stop input missing)"
                if tr.get("status") in ("open", "closed") and tr.get("filledQty"):
                    q = float(tr["filledQty"]); m = float(tr.get("multiplier") or (100 if tr.get("instrument") == "options" else 1))
                    oids = [eid] + [x.get("orderId") for x in (tr.get("exits") or []) if x.get("orderId")]
                    ex = await c.fetch("""select order_id, side, qty, price, commission, ts from executions where order_id = any($1::text[]) and ts < to_timestamp($2/1000.0) order by ts""",
                                       [o for o in oids if o], cutoff_ms)
                    buys = [e for e in ex if e["side"] == "BUY"]; sells = [e for e in ex if e["side"] == "SELL"]
                    bought_q = sum(float(e["qty"]) for e in buys); sold_q = sum(float(e["qty"]) for e in sells)
                    fees = sum(float(e["commission"] or 0) for e in ex)
                    entry_fees = sum(float(e["commission"] or 0) for e in buys)
                    avg_fill = tr.get("avgFill") or (sum(float(e["qty"]) * float(e["price"]) for e in buys) / max(1e-9, bought_q) if buys else None)
                    closed = sold_q >= q - 1e-9
                    gross = sum(float(e["qty"]) * (float(e["price"]) - float(avg_fill)) * m for e in sells) if avg_fill is not None else None
                    net = (gross - fees) if (closed and gross is not None) else None
                    entry_fee_pc = (entry_fees / bought_q) if bought_q > 0 else None
                    per_contract = []
                    if closed and m > 1 and avg_fill is not None and entry_fee_pc is not None:
                        for e in sells:                                       # ACTUAL fees allocated per filled contract (PF-02)
                            n = int(round(float(e["qty"]))); exit_fee_pc = float(e["commission"] or 0) / max(n, 1)
                            for _ in range(n):
                                per_contract.append((float(e["price"]) - float(avg_fill)) * m - entry_fee_pc - exit_fee_pc)
                        if net is None or abs(sum(per_contract) - net) > 0.01:
                            per_contract = []                                 # not reconcilable -> the pair stays unknown
                    first_sale_r = (td or {}).get("nextRungDistanceR")
                    row.update({"filledQty": q, "avgFill": avg_fill, "multiplier": m, "closed": closed, "netRealized": (round(net, 2) if net is not None else None),
                                "paidPremium": (round(float(avg_fill) * q * m, 2) if avg_fill is not None else None),
                                "entryFees": entry_fees, "fees": fees, "entryOrderId": eid, "openedTs": tr.get("openedTs"), "closedTs": tr.get("closedTs"),
                                "exitKinds": [x.get("kind") for x in (tr.get("exits") or [])],
                                "firstSaleDistanceR": first_sale_r, "fullExitRung": (td or {}).get("fullExitRung"),
                                "friction": friction(avg_fill, contract.get("bid"), q, m, fee_side),
                                "p02Eligible": p02_eligible(tr.get("instrument"), q, first_sale_r)})
                    if row["p02Eligible"]:
                        row["p02"] = p02_compare({"filledQty": q, "avgFill": avg_fill, "multiplier": m, "productionRealized": row["netRealized"],
                                                  "productionPerContract": per_contract or None, "entryFeePerContract": (entry_fee_pc if entry_fee_pc is not None else fee_side),
                                                  "entryOrderId": eid, "contract": {"symbol": contract.get("symbol") or tr.get("orderSymbol")},
                                                  "openedTs": tr.get("openedTs"), "closedTs": tr.get("closedTs")}, shadow, fee_side)
                    row["p06"] = runner_protection(direction, tp1, tr.get("entry"), tr.get("stop"), list(tr.get("exits") or []), list(ex), bars, cutoff_ms,
                                                   filled_qty=q, multiplier=m, instrument=tr.get("instrument"), avg_fill=avg_fill,
                                                   entry_fee_per_unit=entry_fee_pc, fee_side=fee_side,
                                                   observations=[p for p in shadow if p.get("rung") == "tp1-reclaim"])
                    row["neverTp1"] = never_tp1_diag(direction, tr.get("entry"), tr.get("stop"), tr.get("openedTs"), tr.get("closedTs"),
                                                     [(0, x) for x in (tr.get("exits") or []) if (x.get("filledQty") or 0) > 0], bars) if closed else None
                    if row.get("cohort") == COHORT_P01:
                        row["confirmationPair"] = confirmation_pair(bars, int(fired_ts), direction, level, tr.get("stop"), tp1, row.get("tp2"), cutoff_ms)
                    trades.append(row)
                else:
                    result = next((p for _, ty, p in evs if ty == "TechniquePlanOrderResult" and p.get("trigger") == tid), None)
                    skip = next((p for _, ty, p in evs if ty == "TechniquePlanTriggerSkipped" and p.get("trigger") == tid and p.get("event") in ("contract_quality", "size_zero")), None)
                    reason = (result or {}).get("reason") or (skip or {}).get("reason") or tr.get("reason") or "no order result"
                    ask = contract.get("ask"); qty = (intent or {}).get("qty")
                    row.update({"refusal": reason, "intendedQty": qty, "multiplier": (100.0 if (intent or {}).get("secType", "OPT") == "OPT" else 1.0),
                                "friction": (friction(ask, contract.get("bid"), qty, 100.0 if (intent or {}).get("secType") == "OPT" else 1.0, fee_side) if contract else None),
                                "underlyingProxy": underlying_proxy(bars, int(fired_ts), float(tr.get("entry") or 0), float(tr.get("stop") or 0), float(tp1), direction, cutoff_ms) if tp1 and tr.get("stop") else "unknown"})
                    if row.get("cohort") == COHORT_P01:
                        row["confirmationPair"] = confirmation_pair(bars, int(fired_ts), direction, level, tr.get("stop"), tp1, row.get("tp2"), cutoff_ms)
                    refused.append(row)
        return {"version": VERSION, "date": date, "cutoff": cutoff, "feePerContractSide": fee_side, "trades": trades, "refused": refused,
                "attempts": [{k: v for k, v in x.items() if k != "ts"} for x in attempts], "sourceLedgerRows": len(ledger)}
    finally:
        await c.close()


# ----------------------------------------------------------------------------------------------- report rendering
def summarize(data: dict) -> dict:
    trades, refused = data.get("trades", []), data.get("refused", [])

    def block(rows):
        closed = [r for r in rows if r.get("closed")]
        opened = [r for r in rows if not r.get("closed")]
        return {"fills": len(rows), "closed": len(closed), "netRealized": round(sum(r["netRealized"] for r in closed if r.get("netRealized") is not None), 2),
                "winners": sum(1 for r in closed if (r.get("netRealized") or 0) > 0), "losers": sum(1 for r in closed if (r.get("netRealized") or 0) < 0),
                "open": len(opened), "openExposure": round(sum((r.get("paidPremium") or 0) + (r.get("entryFees") or 0) for r in opened), 2),
                "largestWinner": max([r["netRealized"] for r in closed if r.get("netRealized") is not None] or [0.0]),
                "feesPaid": round(sum(r.get("fees") or 0 for r in rows), 2)}

    base = block(trades)
    coh = [r for r in trades if r.get("cohort") == COHORT_P01]
    removed = [r for r in trades if r.get("cohort") != COHORT_P01]
    missed = [r for r in refused if r.get("cohort") == COHORT_P01]
    strata = defaultdict(lambda: {"n": 0, "net": 0.0, "open": 0})
    for r in coh:
        match = r.get("sourceSymbolDirectionMatch", r.get("sourceAligned"))
        for key in (f"confirmation={r.get('confirmation')}", f"roomPlanned={r.get('roomBin')}", f"qty={int(r.get('filledQty') or 0)}", f"sourceSymbolDirectionMatch={match}"):
            s = strata[key]; s["n"] += 1
            if r.get("closed"): s["net"] += r.get("netRealized") or 0
            else: s["open"] += 1
    p02 = [r for r in trades if r.get("p02Eligible")]
    p06 = [r for r in trades if (r.get("p06") or {}).get("outcome") not in (None, "not_eligible")]
    never = [r for r in trades if r.get("closed") and r.get("neverTp1") and (r.get("netRealized") or 0) != 0]

    def econ(r):
        f = r.get("friction") or {}
        pct = f.get("pctOfPremium"); qty = r.get("filledQty") or r.get("intendedQty")
        return {"symbol": r.get("symbol"), "trigger": r.get("trigger"), "filled": "filledQty" in r, "qty": qty, "direction": r.get("direction"),
                "hurdlePct": pct, "hurdle": (round(f["total"], 2) if f.get("total") is not None else None),
                "hurdleWhy": (None if pct is not None else ("no contract quote captured at the intent" if not r.get("contract") else "bid missing at the intent")),
                "firstSaleDistanceR": r.get("firstSaleDistanceR"), "flag": (pct is not None and pct >= P03_HURDLE_MARK),
                "delta": (r.get("contract") or {}).get("delta"),
                "payoffTp1": payoff_to_tp1((r.get("contract") or {}).get("delta"), r.get("intendedEntry"), (r.get("targets") or [None])[0], qty, r.get("multiplier") or 100.0),
                # 2026-09-18 (BMNR): the first-order premium edge at TP1 after friction - payoff proxy minus the hurdle. A thin or
                # negative cushion means an underlying target reached does not imply a premium profit; a marker, never a gate.
                "edgeAtTp1": (round(payoff_to_tp1((r.get("contract") or {}).get("delta"), r.get("intendedEntry"), (r.get("targets") or [None])[0], qty, r.get("multiplier") or 100.0) - f["total"], 2)
                              if (f.get("total") is not None and payoff_to_tp1((r.get("contract") or {}).get("delta"), r.get("intendedEntry"), (r.get("targets") or [None])[0], qty, r.get("multiplier") or 100.0) is not None) else None),
                "riskBudgetQty": r.get("riskBudgetQty"), "riskBudgetBasis": r.get("riskBudgetBasis"), "refusal": r.get("refusal")}
    p03 = [econ(r) for r in trades + refused]
    p03.sort(key=lambda e: (e["hurdlePct"] is None, -(e["hurdlePct"] or 0)))
    # P-04 (frozen 2026-09-16): touch (`anticipated`) vs confirmed reaction (`observed_reclaim`) over EVERY attempt of the
    # cohort - fills, rejected opportunities (refused rows) and sacrificed winners (refused rows whose underlying proxy
    # reached TP1). Order-free; nothing is switched on or off by it.
    def _cohort_split(rows_t, rows_r, keyf):
        out = defaultdict(lambda: {"fills": 0, "net": 0.0, "open": 0, "winners": 0, "losers": 0, "rejected": 0, "underlyingTp1FirstRefused": 0, "unknownProxy": 0})
        for r in rows_t:
            b = out[keyf(r)]; b["fills"] += 1
            if r.get("closed"):
                b["net"] += r.get("netRealized") or 0
                if (r.get("netRealized") or 0) > 0: b["winners"] += 1
                elif (r.get("netRealized") or 0) < 0: b["losers"] += 1
            else: b["open"] += 1
        for r in rows_r:
            b = out[keyf(r)]; b["rejected"] += 1
            proxy = str(r.get("underlyingProxy") or "")
            if proxy.startswith("tp1"): b["underlyingTp1FirstRefused"] += 1     # PFU-02: an underlying-only fact, NOT a sacrificed net winner
            elif proxy == "" or proxy.startswith(("unresolved", "unknown")): b["unknownProxy"] += 1
        return {k: {**v, "net": round(v["net"], 2)} for k, v in sorted(out.items())}
    p04 = _cohort_split(coh, missed, lambda r: f"confirmation={r.get('confirmation') or 'unknown'}")
    # P-04 PAIRED (PFU-02): baseline touch attempt vs its confirmation variant on the SAME setup; both baseline winners and
    # losers stay in the sample; refusals of the variant are distinct outcomes; option dollars at the delayed entry are unknown.
    paired = []
    agg = defaultdict(int); r_sum = 0.0; r_n = 0
    for r in coh + missed:
        cp = r.get("confirmationPair")
        if not cp:
            continue
        bl = ({"kind": "fill", "net": r.get("netRealized"), "closed": r.get("closed")} if "filledQty" in r
              else {"kind": "refused", "refusal": (r.get("refusal") or "")[:80], "underlyingProxy": r.get("underlyingProxy")})
        paired.append({"symbol": r.get("symbol"), "trigger": r.get("trigger"), "instrument": r.get("instrument"), "baseline": bl, "confirmation": cp,
                       "dollarsAtDelayedEntry": ("unknown (no option quote at the delayed time)" if r.get("instrument") == "options" else "shares: underlying R applies")})
        agg[cp["outcome"].split(" (")[0]] += 1
        if cp.get("resultR") is not None:
            r_sum += cp["resultR"]; r_n += 1
    p04_paired = {"rows": paired, "outcomes": dict(sorted(agg.items())), "resolvedR": {"n": r_n, "sumR": round(r_sum, 2)},
                  "baselineWinnersInSample": sum(1 for r in coh if (r.get("netRealized") or 0) > 0 and r.get("confirmationPair")),
                  "baselineLosersInSample": sum(1 for r in coh if (r.get("netRealized") or 0) < 0 and r.get("confirmationPair")),
                  "definition": f"GEOMETRY-ONLY UNDERLYING PROXY: touch baseline vs first completed close beyond the level within {P04_CONFIRM_WINDOW_BARS} bars after the touch bar, entry at the next bar OPEN, geometry gates only (stop side, room, R2 >= {P04_MIN_RR} at the exit rung); quote quality, sizing/exit rung, chase, timing windows and admission budgets NOT evaluated; underlying TP1-touch vs stop-close from the entry bar; incomplete horizons pending; descriptive/exploratory until >= 30 paired rows"}
    # P-05 (frozen 2026-09-16): afternoon (prime_close / midday) vs morning (prime_open) and event-day vs ordinary day,
    # over every EM attempt (not only the P-01 cohort) - rejected opportunities and sacrificed winners included.
    def _session_key(r):
        return f"{r.get('sessionWindow') or 'unknown_window'}|{r.get('eventPhase') or 'unknown_calendar'}"
    p05 = _cohort_split(trades, refused, _session_key)
    p05_diag = _cohort_split(trades, refused, lambda r: f"runnerWindowLabel={r.get('window') or 'unknown'}")   # the runner's own label, kept as a diagnostic
    # execution-policy cohorts (deterministic-entry-v1 vs legacy critic): actual fills, refusals and net by policy version
    by_policy = defaultdict(lambda: {"attempts": 0, "fills": 0, "refused": 0, "net": 0.0, "open": 0, "refreshOk": 0, "refreshAttempted": 0})
    census = data.get("attempts") or []
    REFUSED_DISPOSITIONS = ("vetoed", "refused", "deferred", "policy_error", "critic_unavailable", "failure-budget-paused")
    counted, refused_keys = set(), set()
    for x in census:                                  # CR-02: one attempt per (run, trigger, decision) from the immutable events
        key = (x.get("runId"), x.get("trigger"), x.get("decisionId"))
        if key in counted and x.get("decisionId"):
            continue
        counted.add(key)
        b = by_policy[x.get("policyVersion") or "unknown"]; b["attempts"] += 1
        if str(x.get("disposition") or "") in REFUSED_DISPOSITIONS:
            b["refused"] += 1; refused_keys.add(key)  # an unknown / allowed disposition stays unclassified here
    for r in trades + refused:
        b = by_policy[r.get("policyVersion") or "unknown"]
        key = (r.get("runId"), r.get("trigger"), r.get("decisionId"))
        if not census or key not in counted:
            b["attempts"] += 1                        # a row without a census event (older records) still counts once
        if "filledQty" in r:
            b["fills"] += 1
            if r.get("closed"): b["net"] += r.get("netRealized") or 0
            else: b["open"] += 1
        elif key not in refused_keys:
            b["refused"] += 1                         # a downstream refusal (quote / risk / contract) of an allowed attempt
        qr = r.get("quoteRefresh") or {}
        if qr.get("attempted"): b["refreshAttempted"] += 1
        if qr.get("ok"): b["refreshOk"] += 1
    return {"byPolicy": {k: {**v, "net": round(v["net"], 2)} for k, v in sorted(by_policy.items())}, "baseline": base, "cohort": block(coh),
            "removed": [{"symbol": r.get("symbol"), "trigger": r.get("trigger"), "kind": r.get("kind"), "direction": r.get("direction"),
                         "basis": r.get("firstTargetBasis"), "net": r.get("netRealized"), "closed": r.get("closed")} for r in removed],
            "missedWinnersCandidates": [{"symbol": r.get("symbol"), "trigger": r.get("trigger"), "refusal": (r.get("refusal") or "")[:90],
                                         "underlyingProxy": r.get("underlyingProxy"), "roomPlanned": r.get("roomBin")} for r in missed],
            "strata": {k: {"n": v["n"], "net": round(v["net"], 2), "open": v["open"]} for k, v in sorted(strata.items())},
            "p06": [{"symbol": r.get("symbol"), "trigger": r.get("trigger"), "instrument": r.get("instrument"), "qty": r.get("filledQty"), **{k: (r["p06"] or {}).get(k) for k in ("outcome", "why", "remainingAtSignal", "tp1FilledQty", "reclaimTs", "modeledBasis", "modeledExitPx", "productionRunner", "underlyingDeltaR", "dollarDelta", "alternativeRealized", "productionRealized")}} for r in p06],
            "neverTp1": [{"symbol": r.get("symbol"), "trigger": r.get("trigger"), "netRealized": r.get("netRealized"), "exitKinds": r.get("exitKinds"), **(r.get("neverTp1") or {})} for r in never],
            "p02": [{"symbol": r.get("symbol"), "trigger": r.get("trigger"), "qty": r.get("filledQty"), "firstSaleDistanceR": r.get("firstSaleDistanceR"), **r["p02"]} for r in p02],
            "p03": p03,
            "p04": p04, "p04Paired": p04_paired, "p05": p05, "p05RunnerLabels": p05_diag, "sessionClock": SESSION_CLOCK, "cohortsAddendum": COHORTS_ADDENDUM,
            "unknown": {"p02WithoutObservation": sum(1 for r in p02 if r["p02"]["outcome"] == "unknown"),
                        "refusedUnresolvedOrGap": sum(1 for r in refused if str(r.get("underlyingProxy", "")).startswith(("unresolved", "unknown"))),
                        "frictionUnknown": sum(1 for e in p03 if e["hurdlePct"] is None),
                        "payoffInPremiumTermsUnknown": sum(1 for e in p03 if e["payoffTp1"] is None),
                        "riskBudgetQtyUnknown": sum(1 for e in p03 if e["riskBudgetQty"] is None),
                        "roomAtActualEntry": "unknown for every fill (no underlying observation at dispatch is recorded)"}}


def _f(x, fmt="{:+.2f}", dash="-"):
    return fmt.format(x) if x is not None else dash


def render(data: dict, s: dict) -> str:
    L = [f"# EM profitability report {data['date']} (cutoff {data['cutoff']} ET, {VERSION})", "",
         "Order-free research. Baseline = every EM fill of the session; candidate P-01 = long bounce with a saved next_resistance first target. Dollars are net of fees from the book's executions; open positions are exposure, never a mark; unknowns stay unknown. **P-02 and P-03 are PROVISIONAL** (measurement corrections PF-01..03 under review); no strategy conclusion is drawn from them.", "",
         "| Block | Fills | Closed | Net realized | Winners | Losers | Open | Open exposure (premium+entry fees) | Largest winner | Fees |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, b in (("Baseline (all EM fills)", s["baseline"]), (f"P-01 `{COHORT_P01}`", s["cohort"])):
        L.append(f"| {name} | {b['fills']} | {b['closed']} | {b['netRealized']:+.2f} | {b['winners']} | {b['losers']} | {b['open']} | {b['openExposure']:.2f} | {b['largestWinner']:+.2f} | {b['feesPaid']:.2f} |")
    L += ["", "**Execution-policy cohorts (actual fills/refusals by decision version; no equivalence claim between policies):**",
          "| Policy | Attempts | Fills | Refused | Open | Net (closed) | Quote refresh attempted / ok |", "|---|---:|---:|---:|---:|---:|---:|"]
    L += [f"| {k} | {v['attempts']} | {v['fills']} | {v['refused']} | {v['open']} | {v['net']:+.2f} | {v['refreshAttempted']} / {v['refreshOk']} |" for k, v in s.get("byPolicy", {}).items()] or ["| (none) | | | | | | |"]
    L += ["", "**Removed by the candidate (baseline fills outside the cohort):** " + (", ".join(f"{r['symbol']} {r['trigger']} {r['kind']}/{r['direction']}/{r['basis']} net {('%+.2f' % r['net']) if r['net'] is not None else 'open'}" for r in s["removed"]) or "none"), ""]
    L += ["**Cohort-eligible fires that produced no position (missed-winner candidates; underlying-only proxy, not dollars):**"]
    L += [f"- {r['symbol']} {r['trigger']}: {r['refusal']} -> underlying {r['underlyingProxy']}, planned room {r['roomPlanned']}" for r in s["missedWinnersCandidates"]] or ["- none"]
    L += ["", "**P-01 strata (cohort fills; `roomPlanned` = TP1 room from the plan's intended underlying entry - the room at the actual entry is unknown; `sourceSymbolDirectionMatch` = symbol + direction in the source ledger only, not agreement on level/timeframe/conditions/horizon):**",
          "| Stratum | n | Net (closed) | Open |", "|---|---:|---:|---:|"]
    L += [f"| {k} | {v['n']} | {v['net']:+.2f} | {v['open']} |" for k, v in s["strata"].items()] or ["| (no cohort fills) | 0 | 0 | 0 |"]
    L += ["", f"**P-02 `{P02_POLICY}` - PROVISIONAL (identical entry/contract/quantity; actual entry and retained fees, modeled exit fee {data.get('feePerContractSide', 0):.2f}/contract on the hypothetical sale; unknown without a covered TP1 bid observation bound to the trade instance):**",
          "| Position | Qty | First sale (R) | Outcome | Production net | Alternative net | Delta | Forgone on winner | Why |", "|---|---:|---:|---|---:|---:|---:|---:|---|"]
    L += [f"| {r['symbol']} {r['trigger']} | {int(r['qty'] or 0)} | {r['firstSaleDistanceR']} | {r['outcome']} | {r['productionRealized'] if r['productionRealized'] is not None else 'open'} | {_f(r['alternativeRealized'], '{:.2f}')} | {_f(r['delta'])} | {_f(r['forgoneOnWinner'], '{:.2f}')} | {r['why'] or ''} |" for r in s["p02"]] or ["| (no eligible small position) | | | | | | | | |"]
    L += ["", f"**P-06 `{P06_POLICY}` - PROSPECTIVE, frozen 2026-09-18, ED-02 accounting (eligible only after a CONFIRMED TP1 fill; signal = first completed 1m close back through the saved TP1, consecutive minutes, only bars completed before production's next fill; candidate = covered executable bid at the first fresh `tp1-reclaim` observation (options, dollars with actual entry fee + modeled exit fee) else the next bar's open as an UNDERLYING PROXY for shares and options alike (no dollars); production = the remainder's actual fills after the signal, VWAP with allocated fees):**",
          "| Position | Instr | TP1 filled | Remainder | Outcome | Signal (ET) | Modeled exit | Basis | Production runner | Underlying delta (R) | Alt $ | Prod $ | Delta $ | Why |", "|---|---|---:|---:|---|---|---:|---|---|---:|---:|---:|---:|---|"]
    L += [f"| {r['symbol']} {r['trigger']} | {r.get('instrument')} | {_f(r.get('tp1FilledQty'), '{:g}')} | {_f(r.get('remainingAtSignal'), '{:g}')} | {r['outcome']} | {dt.datetime.fromtimestamp(r['reclaimTs'] / 1000 + 60, NY).strftime('%H:%M') if r.get('reclaimTs') else '-'} | {_f(r.get('modeledExitPx'), '{:.2f}')} | {(r.get('modeledBasis') or '-')[:40]} | {(f"{r['productionRunner']['qty']:g} @ {r['productionRunner']['vwap']:.2f} ({', '.join(r['productionRunner'].get('kinds') or [])})" if r.get('productionRunner') else '-')} | {_f(r.get('underlyingDeltaR'), '{:+.2f}')} | {_f(r.get('alternativeRealized'), '{:+.2f}')} | {_f(r.get('productionRealized'), '{:+.2f}')} | {_f(r.get('dollarDelta'), '{:+.2f}')} | {r.get('why') or ''} |" for r in s["p06"]] or ["| (no position completed a TP1 trim) | | | | | | | | | | | | | |"]
    L += ["", "**Closed positions WITHOUT a TP1 trim (descriptive, winners and losers alike - single-contract full exits included; best underlying excursion during the completed holding minutes vs the exit; no threshold is derived):**",
          "| Position | Net | MFE (R) | Held bars | Exits |", "|---|---:|---:|---:|---|"]
    L += [f"| {r['symbol']} {r['trigger']} | {_f(r.get('netRealized'), '{:+.2f}')} | {_f(r.get('mfeR'), '{:.2f}')} | {r.get('heldBars', '-')} | {', '.join(r.get('exitKinds') or [])} |" for r in s["neverTp1"]] or ["| (none) | | | | |"]
    L += ["", f"**P-03 contract economics - PROVISIONAL (every intent, filled or refused; hurdle = concession to the intent bid + round-trip fees as a share of paid premium, `flag` = >= {int(P03_HURDLE_MARK*100)}% ranking marker, never a gate; payoff = signed delta x signed move, a local sensitivity; `riskBudgetQty` = budget bound only, not admission feasibility):**",
          "| Intent | Filled | Dir | Qty | Hurdle $ | Hurdle % | First sale (R) | Flag | Payoff to TP1 (delta proxy) | Hurdle / payoff | Risk-budget qty | Refusal |", "|---|---|---|---:|---:|---:|---:|---|---:|---:|---:|---|"]
    for r in s["p03"]:
        hp = _f(r["hurdlePct"] * 100, "{:.2f}%") if r["hurdlePct"] is not None else f"unknown ({r['hurdleWhy']})"
        pay = _f(r["payoffTp1"], "{:.2f}", "unknown (no delta)")
        ratio = ("%.0f%%" % (100 * r["hurdle"] / r["payoffTp1"])) if (r["payoffTp1"] and r["hurdle"] is not None) else "-"
        L.append(f"| {r['symbol']} {r['trigger']} | {'yes' if r['filled'] else 'no'} | {r.get('direction') or '-'} | {r['qty'] if r['qty'] is not None else '-'} | {_f(r['hurdle'], '{:.2f}')} | {hp} | {r['firstSaleDistanceR'] if r['firstSaleDistanceR'] is not None else '-'} | {'thin' if r['flag'] else ''} | {pay} | {ratio} | {r['riskBudgetQty'] if r['riskBudgetQty'] is not None else 'unknown'} | {(r['refusal'] or '')[:60]} |")
    if not s["p03"]:
        L.append("| (none) | | | | | | | | | | | |")
    L += ["", f"**P-04 entry strata - DESCRIPTIVE ({COHORTS_ADDENDUM}; P-01 attempts split by the FIRING bar's close: `anticipated` = touch, `observed_reclaim` = the firing bar closed on the trade's side; `underlyingTp1FirstRefused` = refused rows whose underlying-only proxy reached TP1 first - not a net winner, not a policy sacrifice):**",
          "| Firing-bar class | Fills | Winners | Losers | Open | Net (closed) | Rejected | Underlying TP1-first refused | Proxy unknown |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    L += [f"| {k} | {v['fills']} | {v['winners']} | {v['losers']} | {v['open']} | {v['net']:+.2f} | {v['rejected']} | {v['underlyingTp1FirstRefused']} | {v['unknownProxy']} |" for k, v in s.get("p04", {}).items()] or ["| (no cohort attempts) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |"]
    pp = s.get("p04Paired") or {}
    L += ["", f"**P-04 PAIRED confirmation comparison - order-free, {pp.get('definition', '')}. Not an admitted entry: the gates listed as not evaluated are unknown for every variant row:**",
          f"outcomes {json.dumps(pp.get('outcomes', {}))}; resolved underlying R: n={pp.get('resolvedR', {}).get('n', 0)} sum={pp.get('resolvedR', {}).get('sumR', 0):+.2f}; baseline winners/losers kept in the paired sample: {pp.get('baselineWinnersInSample', 0)}/{pp.get('baselineLosersInSample', 0)}",
          "| Attempt | Baseline | Confirmation variant | Dollars at the delayed entry |", "|---|---|---|---|"]
    for r in pp.get("rows", []):
        b = r["baseline"]; c = r["confirmation"]
        bl = (f"fill net {b['net']:+.2f}" if b["kind"] == "fill" and b.get("net") is not None else (f"fill open" if b["kind"] == "fill" else f"refused ({b.get('refusal')}) proxy {b.get('underlyingProxy')}"))
        cv = f"{c['outcome']}" + (f" entry {c['entry']} after {c['barsWaited']} bar(s), R2 {c['rr']}, result {c['resultR']:+.2f}R" if c.get("resultR") is not None else (f" (entry {c['entry']}, R2 {c['rr']})" if c.get("entry") is not None else ""))
        L.append(f"| {r['symbol']} {r['trigger']} ({r.get('instrument')}) | {bl} | {cv} | {r['dollarsAtDelayedEntry']} |")
    if not pp.get("rows"):
        L.append("| (no P-01 attempts) | | | |")
    L += ["", f"**P-05 session-window / event-phase cohort ({COHORTS_ADDENDUM}; every EM attempt; window from `{s.get('sessionClock')}` on the tz-aware fire time; event phase from the hand-kept calendar - `unknown_calendar` when the date has no entry; DESCRIPTIVE, never a trading-window rule):**",
          "| Window | Event phase | Fills | Winners | Losers | Open | Net (closed) | Rejected | Underlying TP1-first refused | Proxy unknown |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for k, v in s.get("p05", {}).items():
        w, _, ph = k.partition("|")
        L.append(f"| {w} | {ph} | {v['fills']} | {v['winners']} | {v['losers']} | {v['open']} | {v['net']:+.2f} | {v['rejected']} | {v['underlyingTp1FirstRefused']} | {v['unknownProxy']} |")
    if not s.get("p05"):
        L.append("| (no attempts) | | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |")
    L += ["", "Runner window labels as recorded at fire (diagnostic): " + json.dumps({k: v['fills'] + v['rejected'] for k, v in (s.get('p05RunnerLabels') or {}).items()})]
    L += ["", "**Unknowns:** " + json.dumps(s["unknown"]), "",
          f"Fees per contract per side observed: {data.get('feePerContractSide', 0):.2f}. Source ledger rows for the day: {data.get('sourceLedgerRows', 0)}. Refused/skipped EM fires: {len(data.get('refused', []))}.", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report"); r.add_argument("--date", required=True); r.add_argument("--cutoff", default="16:00"); r.add_argument("--stdout", action="store_true")
    a = ap.parse_args(argv)
    data = asyncio.run(build(a.date, a.cutoff)); s = summarize(data); md = render(data, s)
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump({**data, "summary": s, "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat()}, open(os.path.join(OUT_DIR, f"{a.date}.json"), "w", encoding="utf-8"), indent=1, default=str)
    open(os.path.join(OUT_DIR, f"{a.date}.md"), "w", encoding="utf-8", newline="\n").write(md)
    print(md if a.stdout else f"wrote {OUT_DIR}/{a.date}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
