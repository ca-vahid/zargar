"""EM first-sale geometry / economics record (`first-sale-v1`, 2026-09-18; integrated plan workstream D).

ONE versioned record for the question "what does this position earn, in R, where it is FIRST sold - at the FINAL
quantity and price?". It exists because of SBUX 2026-09-18 (event 165135): the plan was admitted at plan time with
R2 measured to TP3 (3.63R; `technique.rr_gate_target=auto` resolves to TP3 when sizing is risk-based and the
quantity is unknown), the sizer then bought ONE contract, and a one-contract position leaves in full at TP2 =
1.316R. The documented rule is "R2 is measured where the position exits" - it was never re-applied at the final
quantity. This module applies it there.

Pure: no I/O, no clock, no settings read. The caller freezes every input. Units are kept apart - the R rule is an
UNDERLYING rule (never silently turned into a premium rule); the option economics are a labelled proxy
(`payoffProxy`), unknown without a delta and a two-sided quote. A missing observation stays `None`/"unknown".
"""
from __future__ import annotations

VERSION = "first-sale-v1"
LADDER = (0.30, 0.40, 0.15)
MODES = ("off", "observe", "enforce")


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def gate_rung(*, instrument: str, qty: float | None, single_exit: str = "tp2", pinned: str | None = None,
              n_targets: int = 3) -> tuple[int | None, str, str]:
    """The rung R2 is measured to under the DOCUMENTED rule, for the FINAL quantity.
    Returns (index | None, label, basis). `pinned` = an explicit `technique.rr_gate_target` of tp1|tp2|tp3."""
    p = str(pinned or "auto").strip().lower()
    if p in ("tp1", "tp2", "tp3"):
        idx, label, basis = int(p[2]) - 1, p, "pinned"
    elif qty is None:
        return None, "unknown", "quantity_unknown"
    elif instrument == "options" and 0 < float(qty) < 3:
        s = single_exit if single_exit in ("tp1", "tp2", "tp3") else "tp2"
        idx, label, basis = int(s[2]) - 1, f"{s}-full", "single_contract_exit"
    else:
        idx, label, basis = 2, "tp3", "book_tp3"
    if idx >= n_targets:
        return None, label, "no_such_target"
    return idx, label, basis


def next_production_rung(*, instrument: str, qty: float | None, single_exit: str = "tp2", trims_done: int = 0,
                         n_targets: int = 3) -> tuple[int | None, str, float | None]:
    """The rung production SELLS at first (`exits.plan_exit`): a small option position leaves whole at
    `single_exit`; everything else trims its ladder share at the next target. Returns (index, label, qty sold)."""
    if qty is None:
        return None, "unknown", None
    q = float(qty)
    if instrument == "options" and 0 < q < 3:
        s = single_exit if single_exit in ("tp1", "tp2", "tp3") else "tp2"
        idx = max(int(s[2]) - 1, int(trims_done or 0))
        return (idx if idx < n_targets else None), f"{s}-full", q
    idx = int(trims_done or 0)
    if idx >= n_targets:
        return None, f"tp{idx + 1}-ladder", None
    share = LADDER[idx] if idx < len(LADDER) else 1.0
    return idx, f"tp{idx + 1}-ladder", float(int(round(q * share)))


def r_multiple(*, direction: str, entry, stop, target) -> tuple[float | None, str | None]:
    """Signed for the side: long reward = target - entry, short reward = entry - target. Returns (R, problem)."""
    e, s, t = _f(entry), _f(stop), _f(target)
    if e is None or s is None or t is None:
        return None, "missing_geometry"
    short = direction == "short"
    risk = (s - e) if short else (e - s)
    reward = (e - t) if short else (t - e)
    if risk <= 0:
        return None, "stop_wrong_side"
    if reward <= 0:
        return round(reward / risk, 3), "target_wrong_side"
    return round(reward / risk, 3), None


def build_record(*, stage: str, symbol: str, run_id: str, trigger_id: str, family: str, direction: str,
                 session: str | None, plan_entry, runner_entry, stop, targets, observed_underlier: dict | None,
                 instrument: str, qty: float | None, multiplier: float, limit_price, single_exit: str,
                 pinned_gate_target: str | None, min_rr: float, contract: dict | None, option_quote: dict | None,
                 fee_per_contract: float, stock_commission: float, affordable_qty: float | None,
                 plan_gate: dict | None, mode: str, now_ms: int, trims_done: int = 0) -> dict:
    """The record. `observed_underlier` = {price, sourceTs, receivedTs, source} of the underlying at admission, or None
    (NEVER inferred). `option_quote` = {bid, ask, bidSize, askSize, sourceTs, source, derived} or None.
    `plan_gate` = what the plan-time R2 measured ({targetIndex, rr, min}) when the saved plan carries it."""
    tg = [x for x in (_f(t) for t in (targets or [])) if x is not None]
    n = len(tg)
    g_idx, g_label, g_basis = gate_rung(instrument=instrument, qty=qty, single_exit=single_exit,
                                        pinned=pinned_gate_target, n_targets=n)
    s_idx, s_label, s_qty = next_production_rung(instrument=instrument, qty=qty, single_exit=single_exit,
                                                 trims_done=trims_done, n_targets=n)
    obs_px = _f((observed_underlier or {}).get("price"))

    def r_to(i, entry):
        if i is None:
            return None, "no_gate_rung"
        return r_multiple(direction=direction, entry=entry, stop=stop, target=tg[i])

    r_plan, _p = r_to(g_idx, plan_entry)
    r_run, p_run = r_to(g_idx, runner_entry)
    r_obs, p_obs = r_to(g_idx, obs_px) if obs_px is not None else (None, "underlier_unobserved")
    r_first, _p2 = r_to(s_idx, runner_entry)
    # verdict: the documented UNDERLYING rule on the entry the runner manages against (for a break family that IS the
    # confirming close). Unknown geometry never passes and never fails - it is `unknown`.
    if g_idx is None:
        verdict, reason = "unknown", g_basis
    elif r_run is None:
        verdict, reason = "unknown", p_run or "missing_geometry"
    elif p_run == "target_wrong_side":
        verdict, reason = "fail", "target_wrong_side"
    elif r_run + 1e-9 < float(min_rr):
        verdict, reason = "fail", "first_sale_rr_below_min"
    else:
        verdict, reason = "pass", None
    fees_rt = None
    if qty is not None:
        fees_rt = round(2 * (float(fee_per_contract) * float(qty) if instrument == "options" else float(stock_commission)), 4)
    oq = dict(option_quote or {})
    bid, ask = _f(oq.get("bid")), _f(oq.get("ask"))
    two_sided = bid is not None and ask is not None and ask > 0 and ask >= bid > 0
    spread_cost = round((ask - bid) * float(multiplier) * float(qty), 4) if (two_sided and qty is not None) else None
    delta = _f((contract or {}).get("delta"))
    proxy = None
    run_e = _f(runner_entry)
    if instrument == "options" and delta is not None and s_idx is not None and qty is not None and run_e is not None:
        gross = abs(delta) * abs(tg[s_idx] - run_e) * float(multiplier) * float(s_qty or 0)
        proxy = {"kind": "delta_linear", "grossAtFirstSale": round(gross, 2),
                 "netOfFeesAndSpread": (round(gross - (fees_rt or 0) - spread_cost, 2) if spread_cost is not None else None),
                 "caveat": "delta proxy at entry: no gamma/theta/IV path - not a payoff guarantee"}
    elif instrument == "shares" and s_idx is not None and qty is not None and run_e is not None:
        gross = abs(tg[s_idx] - run_e) * float(s_qty or 0)
        proxy = {"kind": "linear_shares", "grossAtFirstSale": round(gross, 2),
                 "netOfFeesAndSpread": round(gross - (fees_rt or 0), 2),
                 "caveat": "underlying move x shares sold at the first rung"}
    src_ts = int(oq.get("sourceTs") or 0)
    ou = observed_underlier or {}
    ckeys = ("symbol", "display", "expiry", "strike", "optionType", "dte", "delta", "openInterest", "volume",
             "spreadPct", "priced", "warnings")
    return {
        "version": VERSION, "stage": stage, "mode": mode, "ts": int(now_ms),
        "runId": run_id, "symbol": symbol, "trigger": trigger_id, "family": family, "direction": direction,
        "session": session,
        "underlying": {"planEntry": _f(plan_entry), "runnerEntry": run_e, "stop": _f(stop), "targets": tg,
                       "observed": ({"price": obs_px, "sourceTs": int(ou.get("sourceTs") or 0) or None,
                                     "receivedTs": int(ou.get("receivedTs") or 0) or None,
                                     "source": ou.get("source") or None} if obs_px is not None else None)},
        "vehicle": {"instrument": instrument, "quantity": (float(qty) if qty is not None else None),
                    "quantityKnown": qty is not None, "multiplier": float(multiplier), "limitPrice": _f(limit_price),
                    "affordableQuantity": (float(affordable_qty) if affordable_qty is not None else None),
                    "contract": ({k: contract.get(k) for k in ckeys} if contract else None)},
        "quote": ({"bid": bid, "ask": ask, "bidSize": oq.get("bidSize"), "askSize": oq.get("askSize"),
                   "sourceTs": src_ts or None, "ageMs": (int(now_ms) - src_ts if src_ts else None),
                   "source": oq.get("source") or None, "derived": bool(oq.get("derived")), "twoSided": two_sided}
                  if option_quote is not None else None),
        "fees": {"roundTrip": fees_rt, "perContract": float(fee_per_contract), "stockFlat": float(stock_commission)},
        "spreadCost": spread_cost,
        "gate": {"rule": "R2 measured where the position exits, at the FINAL quantity (first-sale-v1)",
                 "rungIndex": g_idx, "rung": g_label, "rungBasis": g_basis, "minRiskReward": float(min_rr),
                 "rPlanEntry": r_plan, "rRunnerEntry": r_run, "rObservedUnderlier": r_obs,
                 "observedProblem": p_obs, "verdict": verdict, "reason": reason, "planTime": plan_gate or None,
                 "differsFromPlanTime": bool(plan_gate and plan_gate.get("targetIndex") is not None
                                             and g_idx is not None and int(plan_gate["targetIndex"]) != int(g_idx))},
        "firstSale": {"rungIndex": s_idx, "rung": s_label, "quantitySold": s_qty, "rRunnerEntry": r_first},
        "payoffProxy": proxy,
    }


def refusal_reason(rec: dict) -> str | None:
    """The entry-refusal text for an `enforce` run; None when the record does not fail. `unknown` never refuses."""
    g = (rec or {}).get("gate") or {}
    if g.get("verdict") != "fail":
        return None
    if g.get("reason") == "target_wrong_side":
        return f"first-sale gate: the {g.get('rung')} target is on the wrong side of the entry for this direction"
    q = (rec.get("vehicle") or {}).get("quantity")
    return (f"first-sale gate: {g.get('rRunnerEntry')}R to {g.get('rung')} at the final quantity {q:g} is below the "
            f"{g.get('minRiskReward'):g}R minimum (R2 is measured where the position exits)")


def compare_vehicles(*, setup: dict, contracts: list, share_quote: dict | None, budget: float, risk_budget: float,
                     fee_per_contract: float, stock_commission: float = 0.0, friction_marker_pct: float = 8.0,
                     allow_shares: bool = True) -> dict:
    """Order-free vehicle comparison at ONE setup on contemporaneous rows. `setup` = {symbol, direction, entry, stop,
    targets, singleExit}. Contract row = {symbol, strike, expiry, dte, delta, bid, ask, bidSize, askSize,
    openInterest, sourceTs}. Nothing here is a gate: the 8% friction marker and open interest are reported only."""
    rows = []
    e, s = _f(setup.get("entry")), _f(setup.get("stop"))
    direction = str(setup.get("direction") or "long")
    tg = [x for x in (_f(t) for t in (setup.get("targets") or [])) if x is not None]
    risk = abs(e - s) if (e is not None and s is not None) else None
    single = str(setup.get("singleExit") or "tp2")
    for c in contracts or []:
        bid, ask, delta = _f(c.get("bid")), _f(c.get("ask")), _f(c.get("delta"))
        unknown = []
        quoted = bid is not None and ask is not None and ask > 0 and ask >= bid
        if not quoted:
            unknown.append("no_two_sided_quote")
        if delta is None:
            unknown.append("no_delta")
        if c.get("bidSize") in (None, 0) or c.get("askSize") in (None, 0):
            unknown.append("depth_unknown")
        qty = int(budget // (ask * 100)) if quoted else 0
        if risk and delta is not None and qty:
            per = abs(delta) * risk * 100
            if per > 0:
                qty = max(0, min(qty, int(risk_budget // per)))
        idx, label, sold = next_production_rung(instrument="options", qty=(qty or None), single_exit=single, n_targets=len(tg))
        fees = round(2 * fee_per_contract * qty, 2) if qty else None
        spread = round((ask - bid) * 100 * qty, 2) if (qty and quoted) else None
        friction = round(((ask - bid) * 100 + 2 * fee_per_contract) / (ask * 100) * 100, 2) if quoted else None
        gross = (round(abs(delta) * abs(tg[idx] - e) * 100 * (sold or 0), 2)
                 if (delta is not None and idx is not None and e is not None and qty) else None)
        rows.append({"vehicle": "option", "symbol": c.get("symbol"), "strike": c.get("strike"), "expiry": c.get("expiry"),
                     "dte": c.get("dte"), "affordableQty": qty, "firstSaleRung": label, "firstSaleQty": sold,
                     "spreadCost": spread, "feesRoundTrip": fees, "frictionPct": friction,
                     "overFrictionMarker": (friction is not None and friction > friction_marker_pct),
                     "openInterest": c.get("openInterest"), "sourceTs": c.get("sourceTs"), "payoffProxyGross": gross,
                     "payoffProxyNet": (round(gross - (fees or 0) - spread, 2) if (gross is not None and spread is not None) else None),
                     "unknown": unknown,
                     "status": ("unknown" if ("no_two_sided_quote" in unknown or "no_delta" in unknown)
                                else ("unaffordable" if not qty else "scored"))})
    if allow_shares and direction != "short":
        sq = share_quote or {}
        px = _f(sq.get("ask")) or _f(sq.get("last"))
        unknown = [] if px else ["no_share_quote"]
        if share_quote is not None and sq.get("askSize") in (None, 0):
            unknown.append("depth_unknown")
        qty = int(min(budget // px, (risk_budget // risk) if risk else 0)) if px else 0
        idx, label, sold = next_production_rung(instrument="shares", qty=(qty or None), n_targets=len(tg))
        gross = round(abs(tg[idx] - e) * (sold or 0), 2) if (idx is not None and e is not None and qty) else None
        rows.append({"vehicle": "shares", "symbol": setup.get("symbol"), "affordableQty": qty, "firstSaleRung": label,
                     "firstSaleQty": sold, "spreadCost": None, "feesRoundTrip": round(2 * stock_commission, 2),
                     "frictionPct": None, "overFrictionMarker": False, "payoffProxyGross": gross,
                     "payoffProxyNet": (round(gross - 2 * stock_commission, 2) if gross is not None else None),
                     "unknown": unknown,
                     "status": ("unknown" if "no_share_quote" in unknown else ("unaffordable" if not qty else "scored"))})
    elif allow_shares:
        rows.append({"vehicle": "shares", "status": "not_permitted", "unknown": [],
                     "why": "short ideas trade puts only - no share shorting"})
    return {"version": "vehicle-compare-v1", "setup": {**setup, "riskPerShare": risk}, "rows": rows,
            "note": "order-free; a delta proxy is not a payoff; the friction marker and open interest are never gates"}
