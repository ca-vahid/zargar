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

VERSION = "first-sale-v2"   # v2 (IR-01, 2026-09-19): validated executable underlying bound, unrounded comparison, fail-closed enforce
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


def r_raw(*, direction: str, entry, stop, target) -> tuple[float | None, str | None]:
    """UNROUNDED reward:risk, signed for the side (long reward = target - entry, short = entry - target). Admission always
    compares this raw value: 2.9996 is below 3.0 (IR-01). Rounding is for display only (`r_multiple`)."""
    e, s, t = _f(entry), _f(stop), _f(target)
    if e is None or s is None or t is None:
        return None, "missing_geometry"
    short = direction == "short"
    risk = (s - e) if short else (e - s)
    reward = (e - t) if short else (t - e)
    if risk <= 0:
        return None, "stop_wrong_side"
    if reward <= 0:
        return reward / risk, "target_wrong_side"
    return reward / risk, None


def r_multiple(*, direction: str, entry, stop, target) -> tuple[float | None, str | None]:
    """DISPLAY form of `r_raw` (three decimals). Never used for a comparison."""
    r, problem = r_raw(direction=direction, entry=entry, stop=stop, target=target)
    return (round(r, 3) if r is not None else None), problem


def normalize_mode(raw) -> str:
    """off | observe | enforce, or `invalid`. An unrecognised value is NEVER read as off: a typo must not silently disable
    an enforcement someone believes is on - the caller refuses entries with an explicit policy error until it is fixed."""
    v = str(raw if raw is not None else "off").strip().lower()
    return v if v in MODES else "invalid"


ADMISSIBLE_OPTION_SOURCES = ("opra", "ibkr")


def validate_underlier(ev: dict | None, *, symbol: str, direction: str, now_ms: int, max_age_ms: int = 10_000) -> dict:
    """The CURRENT executable underlying bound that owns admission, validated causally. `ev` = the raw quote evidence
    {symbol, bid, ask, last, quoteTs, lastTs, receivedTs, source, halted}; `quoteTs` / `lastTs` are the VENUE times of
    those fields (never a receipt time). Policy (declared, per direction): the bound is the side that HURTS the trade -
    a long is judged at the ASK, a short (puts) at the BID - from a fresh, uncrossed, two-sided venue quote. When no such
    quote exists but a fresh venue PRINT does, the print is the bound (basis `last`). Anything else is not evidence.
    PRINT FALLBACK (`underlier-print-fallback-v1`, declared and validated apart): a print is NOT an executable quote and
    is never called one - `boundClass` says `venue_print_fallback`. It needs its OWN fresh venue print time (`lastTs`), a
    named non-derived, non-delayed source and the symbol's identity. It can only make admission STRICTER than the runner's
    entry (admission takes the worse of the two); the order-free candidate stage does not accept it for its chase bound."""
    out = {"status": "missing", "price": None, "basis": None, "boundClass": None, "problems": [], "source": None, "ageMs": None}
    if not ev:
        out["problems"] = ["no_underlier_evidence"]
        return out
    probs = []
    src = str(ev.get("source") or "").strip()
    out["source"] = src or None
    if str(ev.get("symbol") or "").upper() != str(symbol or "").upper():
        probs.append("symbol_mismatch")
    if not src:
        probs.append("source_unknown")
    elif src.startswith("derived:") or src == "chain" or ev.get("delayed") or ev.get("transform"):
        probs.append("source_not_executable")               # derived, transformed or delayed evidence is never an executable bound
    if ev.get("halted"):
        probs.append("halted")
    bid, ask, last = _f(ev.get("bid")), _f(ev.get("ask")), _f(ev.get("last"))
    qts, lts = int(ev.get("quoteTs") or 0), int(ev.get("lastTs") or 0)

    def fresh(ts):
        return ts > 0 and -1000 <= (int(now_ms) - ts) <= int(max_age_ms)
    price = basis = ts_used = None
    if bid is not None and ask is not None and bid > 0 and ask >= bid and fresh(qts):
        price, basis, ts_used = (bid if direction == "short" else ask), ("bid" if direction == "short" else "ask"), qts
    elif last is not None and last > 0 and fresh(lts):
        price, basis, ts_used = last, "last", lts
    else:
        if qts <= 0 and lts <= 0:
            probs.append("venue_time_unknown")
        elif max(qts, lts) - int(now_ms) > 1000:
            probs.append("venue_time_in_future")
        else:
            probs.append("stale_underlier")
    out["problems"] = probs
    if price is not None:
        out["ageMs"] = int(now_ms) - int(ts_used)
    if price is not None and not probs:
        out.update({"status": "valid", "price": price, "basis": basis,
                    "boundClass": ("executable_quote" if basis in ("bid", "ask") else "venue_print_fallback"),
                    "policy": (None if basis in ("bid", "ask") else "underlier-print-fallback-v1")})
    else:
        out["status"] = "invalid" if probs else "missing"
    return out


def build_record(*, stage: str, symbol: str, run_id: str, trigger_id: str, family: str, direction: str,
                 session: str | None, plan_entry, runner_entry, stop, targets, underlier_evidence: dict | None,
                 instrument: str, qty: float | None, multiplier: float, limit_price, single_exit: str,
                 pinned_gate_target: str | None, pin_source: str, min_rr: float, contract: dict | None,
                 option_quote: dict | None, fee_per_contract: float, stock_commission: float,
                 affordable_qty: float | None, plan_gate: dict | None, mode: str, now_ms: int, trims_done: int = 0,
                 max_underlier_age_ms: int = 10_000) -> dict:
    """The record. `underlier_evidence` = the raw underlying quote evidence (see `validate_underlier`) or None - NEVER
    inferred. `pin_source` = where the policy-defining `rr_gate_target` came from: `run_config` (the plan's frozen
    settings) | `unresolved`. `plan_gate` = what the plan-time R2 measured.

    Two DIFFERENT things are reported and never conflated (IR-01):
      gate target            where the DOCUMENTED R2 rule measures: a 1-2 contract option position -> the rung it leaves
                             whole at (`single_contract_exit`); three or more contracts and shares -> the book's TP3;
                             an explicit pin wins. This delivery does not change the multi-contract rule.
      first production sale  the rung production sells at FIRST (a ladder position trims at TP1) - reported, never gated.
    Admission price: the worse for the trade of the runner's entry and the validated current executable underlying
    bound (and, for shares, the order's own limit). Comparison is on the UNROUNDED R."""
    tg = [x for x in (_f(t) for t in (targets or [])) if x is not None]
    n = len(tg)
    g_idx, g_label, g_basis = gate_rung(instrument=instrument, qty=qty, single_exit=single_exit,
                                        pinned=pinned_gate_target, n_targets=n)
    s_idx, s_label, s_qty = next_production_rung(instrument=instrument, qty=qty, single_exit=single_exit,
                                                 trims_done=trims_done, n_targets=n)
    short = direction == "short"
    uv = validate_underlier(underlier_evidence, symbol=symbol, direction=direction, now_ms=now_ms, max_age_ms=max_underlier_age_ms)
    run_e, lim = _f(runner_entry), _f(limit_price)
    bounds = [x for x in (run_e, uv["price"]) if x is not None]
    if instrument == "shares" and lim is not None and not short:
        bounds.append(lim)                                 # a share BUY can fill up to its own limit
    adm_entry = (min(bounds) if short else max(bounds)) if bounds else None

    def raw_to(i, entry):
        if i is None:
            return None, "no_gate_rung"
        return r_raw(direction=direction, entry=entry, stop=stop, target=tg[i])

    def disp(x):
        return round(x, 3) if x is not None else None
    r_plan, _p = raw_to(g_idx, plan_entry)
    r_run, p_run = raw_to(g_idx, run_e)
    r_cur, p_cur = raw_to(g_idx, uv["price"]) if uv["price"] is not None else (None, "underlier_not_validated")
    r_adm, p_adm = raw_to(g_idx, adm_entry)
    r_first, _p2 = raw_to(s_idx, adm_entry)
    missing = []
    if g_idx is None:
        missing.append(g_basis)
    if uv["status"] != "valid":
        missing.append("underlier_" + uv["status"])
    if pin_source != "run_config":
        missing.append("gate_pin_unresolved")
    if r_adm is None:
        missing.append(p_adm or "missing_geometry")
    # verdict on the UNROUNDED admission R; evidence problems make it `unknown` (observe: non-authoritative; enforce: defer)
    if p_adm == "target_wrong_side" and g_idx is not None:
        verdict, reason = "fail", "target_wrong_side"
    elif missing:
        verdict, reason = "unknown", missing[0]
    elif r_adm < float(min_rr):
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
    if instrument == "options" and delta is not None and s_idx is not None and qty is not None and adm_entry is not None:
        gross = abs(delta) * abs(tg[s_idx] - adm_entry) * float(multiplier) * float(s_qty or 0)
        proxy = {"kind": "delta_linear", "grossAtFirstSale": round(gross, 2),
                 "netOfFeesAndSpread": (round(gross - (fees_rt or 0) - spread_cost, 2) if spread_cost is not None else None),
                 "caveat": "delta proxy at entry: no gamma/theta/IV path - not a payoff guarantee"}
    elif instrument == "shares" and s_idx is not None and qty is not None and adm_entry is not None:
        gross = abs(tg[s_idx] - adm_entry) * float(s_qty or 0)
        proxy = {"kind": "linear_shares", "grossAtFirstSale": round(gross, 2),
                 "netOfFeesAndSpread": round(gross - (fees_rt or 0), 2),
                 "caveat": "underlying move x shares sold at the first rung"}
    src_ts = int(oq.get("sourceTs") or 0)
    ckeys = ("symbol", "display", "expiry", "strike", "optionType", "dte", "delta", "openInterest", "volume",
             "spreadPct", "priced", "warnings")
    ue = dict(underlier_evidence or {})
    return {
        "version": VERSION, "stage": stage, "mode": mode, "ts": int(now_ms),
        "runId": run_id, "symbol": symbol, "trigger": trigger_id, "family": family, "direction": direction,
        "session": session,
        "underlying": {"planEntry": _f(plan_entry), "runnerEntry": run_e, "stop": _f(stop), "targets": tg,
                       "evidence": ({k: ue.get(k) for k in ("symbol", "bid", "ask", "last", "quoteTs", "lastTs", "receivedTs", "source", "halted")} if underlier_evidence else None),
                       "validated": uv,
                       "observed": ({"price": uv["price"], "basis": uv["basis"], "ageMs": uv["ageMs"], "source": uv["source"]} if uv["status"] == "valid" else None)},
        "vehicle": {"instrument": instrument, "quantity": (float(qty) if qty is not None else None),
                    "quantityKnown": qty is not None, "multiplier": float(multiplier), "limitPrice": lim,
                    "affordableQuantity": (float(affordable_qty) if affordable_qty is not None else None),
                    "contract": ({k: contract.get(k) for k in ckeys} if contract else None)},
        "quote": ({"bid": bid, "ask": ask, "bidSize": oq.get("bidSize"), "askSize": oq.get("askSize"),
                   "sourceTs": src_ts or None, "ageMs": (int(now_ms) - src_ts if src_ts else None),
                   "source": oq.get("source") or None, "derived": bool(oq.get("derived")), "twoSided": two_sided}
                  if option_quote is not None else None),
        "fees": {"roundTrip": fees_rt, "perContract": float(fee_per_contract), "stockFlat": float(stock_commission)},
        "spreadCost": spread_cost,
        "gate": {"rule": "R2 is measured to the GATE TARGET of the final quantity, from the worse of the runner's entry and the validated current executable underlying bound; unrounded comparison (first-sale-v2)",
                 "rungIndex": g_idx, "rung": g_label, "rungBasis": g_basis, "pinSource": pin_source, "minRiskReward": float(min_rr),
                 "admissionEntry": adm_entry, "admissionBasis": ({"runnerEntry": run_e, "executableBound": uv["price"], "boundBasis": uv["basis"], "boundClass": uv.get("boundClass"),
                                                                   "shareLimit": (lim if instrument == "shares" else None)}),
                 "rAdmission": disp(r_adm), "rAdmissionRaw": r_adm,
                 "rPlanEntry": disp(r_plan), "rRunnerEntry": disp(r_run), "rObservedUnderlier": disp(r_cur),
                 "observedProblem": p_cur, "missingEvidence": missing, "verdict": verdict, "reason": reason, "planTime": plan_gate or None,
                 "differsFromPlanTime": bool(plan_gate and plan_gate.get("targetIndex") is not None
                                             and g_idx is not None and int(plan_gate["targetIndex"]) != int(g_idx))},
        "firstSale": {"rungIndex": s_idx, "rung": s_label, "quantitySold": s_qty, "rAdmission": disp(r_first),
                      "note": "the first PRODUCTION sale - reported beside the gate target, never gated, never assumed to be the same rung"},
        "payoffProxy": proxy,
    }


def decide(rec: dict | None, mode: str, *, error: str | None = None) -> dict:
    """The ADMISSION disposition. observe: never authoritative. enforce: FAIL CLOSED - a failed gate refuses, and a missing
    record, missing / invalid evidence, unknown geometry or a hook error DEFERS the entry (nothing is sent) with a reason.
    invalid mode: refuse with a policy error. Exits never come here."""
    m = normalize_mode(mode)
    g = (rec or {}).get("gate") or {}
    if m == "off":
        return {"allow": True, "disposition": "off", "reason": None}
    if m == "invalid":
        return {"allow": False, "disposition": "policy_error",
                "reason": f"first-sale gate: setting first_sale_rr_gate={mode!r} is not off|observe|enforce - entry refused until it is corrected (never silently off)"}
    if m == "observe":
        return {"allow": True, "disposition": ("observed_error" if (error or rec is None) else f"observed_{g.get('verdict')}"), "reason": None}
    if error or rec is None:
        return {"allow": False, "disposition": "deferred_error", "reason": f"first-sale gate: the record could not be built ({error or 'no record'}) - entry deferred, nothing sent"}
    if g.get("verdict") == "pass":
        return {"allow": True, "disposition": "passed", "reason": None}
    if g.get("verdict") == "unknown":
        return {"allow": False, "disposition": "deferred_missing_evidence",
                "reason": "first-sale gate: required evidence is missing or invalid (" + ", ".join(g.get("missingEvidence") or [str(g.get("reason"))]) + ") - entry deferred, nothing sent"}
    if g.get("reason") == "target_wrong_side":
        return {"allow": False, "disposition": "refused", "reason": f"first-sale gate: the {g.get('rung')} target is on the wrong side of the admission price for this direction"}
    q = (rec.get("vehicle") or {}).get("quantity")
    return {"allow": False, "disposition": "refused",
            "reason": (f"first-sale gate: {g.get('rAdmissionRaw'):.4f}R to {g.get('rung')} at the final quantity {q:g} from {g.get('admissionEntry'):g} is below the "
                       f"{g.get('minRiskReward'):g}R minimum (R2 is measured where the position exits)")}


def refusal_reason(rec: dict) -> str | None:
    """Back-compat for the retrospective tools: the refusal text `enforce` would give for this record, or None."""
    d = decide(rec, "enforce")
    return None if d["allow"] else d["reason"]


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
