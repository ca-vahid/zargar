"""PROF-02 (2026-09-15): the WHOLE exit path in integer units, before admission.

A profitable first trim can still be a losing trade (RKT: +$16.36 on the trim,
-$46.51 on the rest). Fractional ladder weights cannot produce fractional
contracts: one contract cannot follow three partial exits. This module is pure
arithmetic - integer units per rung, the net result of the declared scenarios
(every target, first target then the stop, the stop alone), fee drag and the
coherent one-lot policy - labelled as an ESTIMATE. It never claims a profit:
target arithmetic is not evidence that targets get hit.
"""
from __future__ import annotations

import math

PAYOFF_VERSION = "payoff-v1"


def integer_ladder(qty: int, fractions: list[float], *, vehicle: str = "option") -> dict:
    """The EXECUTABLE unit sequence of a declared ladder - the same rule the
    position manager applies (PROF-F2, 2026-09-15): each rung's fraction is
    of the REMAINING size (`policies._ladder` converts the declared weights),
    an option rung sells round(remaining x fraction) and at least one contract
    for a positive fraction (`PositionManager.close`), a share rung sells what
    the venue normalizes (whole shares, rounded down). `declaredUnits` is what
    the fractions asked for (floor of fraction x qty); `executable` = every
    declared rung sells at least one unit; `collapsed` = the declared ladder
    cannot be followed at this size, and the executed sequence differs."""
    q = int(max(0, qty))
    fr = [float(f) for f in (fractions or []) if f is not None]
    declared = [int(math.floor(f * q + 1e-9)) for f in fr]
    units: list[int] = []
    remaining = q
    for i, f in enumerate(fr):
        rem_frac = 1.0 - sum(fr[:i])
        rel = min(1.0, f / rem_frac) if rem_frac > 1e-9 else 1.0
        want = remaining * rel
        if vehicle == "shares":
            u = int(math.floor(want + 1e-9))
        else:
            u = int(round(want)) or (1 if f > 0 else 0)
        u = max(0, min(u, remaining))
        units.append(u)
        remaining -= u
    runner = max(0, remaining)
    executable = bool(units) and all(u >= 1 for u in units)
    collapsed = bool(units) and (any(u == 0 for u in units) or (units != declared and any(d == 0 for d in declared)))
    note = None
    if q == 1 and len(fr) > 1:
        note = "one unit cannot follow a multi-rung ladder: the whole position exits at the first rung (execution sells at least one contract)"
    elif any(u == 0 for u in units):
        empty = [i + 1 for i, u in enumerate(units) if u == 0]
        note = f"rung(s) {empty} sell nothing at {q} unit(s) - the ladder is not executable as declared"
    elif units != declared:
        note = "execution rounds each rung against the remaining size: the executed sequence differs from the declared weights"
    return {"qty": q, "fractions": fr, "declaredUnits": declared, "units": units, "runner": runner,
            "executable": executable, "collapsed": collapsed, "vehicle": vehicle, "note": note}


def unit_gains(*, vehicle: str, entry_ref: float, targets: list[float], direction: str = "long",
               delta: float | None = None, multiplier: float = 1.0) -> list[float | None]:
    """$ gain per unit if the underlying reaches each target. Shares: the
    price distance. Options: delta-linear (|delta| x distance x multiplier) -
    an estimate that ignores gamma, theta and IV; None without a delta."""
    sgn = 1.0 if direction != "short" else -1.0
    out: list[float | None] = []
    for t in targets or []:
        dist = sgn * (float(t) - float(entry_ref))
        if vehicle == "shares":
            out.append(round(dist * float(multiplier or 1.0), 4))
        elif delta is None:
            out.append(None)
        else:
            out.append(round(abs(float(delta)) * dist * float(multiplier or 100.0), 4))
    return out


def break_even(*, option_type: str, strike: float | None, premium: float | None) -> dict:
    """INTRA-01 (2026-09-16): strike +/- premium is the EXPIRATION break-even - where the
    contract pays if HELD TO EXPIRY. It says nothing about an exit before expiry, which
    pays whenever the executable premium exceeds entry + costs (delta, time and IV decide
    that), whatever the underlying is versus this level."""
    if strike is None or premium is None:
        return {"expiration": None, "unknown": ["strike" if strike is None else "premium"],
                "note": "expiration break-even needs the strike and the premium"}
    is_call = str(option_type or "call").lower().startswith("c")
    be = float(strike) + float(premium) if is_call else float(strike) - float(premium)
    return {"expiration": round(be, 4), "basis": "strike + premium (call) / strike - premium (put) - HELD TO EXPIRY only",
            "note": "an exit BEFORE expiry pays when the executable bid exceeds entry + costs; the underlying need not "
                    "reach this level for that - the target scenarios above value exits before expiry (delta-linear)"}


def expiry_value(*, option_type: str, strike: float, underlying: float) -> float:
    """Intrinsic value per unit at expiry."""
    is_call = str(option_type or "call").lower().startswith("c")
    return max(0.0, (float(underlying) - float(strike)) if is_call else (float(strike) - float(underlying)))


def premium_exit(*, entry_premium: float | None, exit_premium: float | None, qty: float, fee_per_unit: float = 0.0,
                 multiplier: float = 100.0, evidence: str = "unknown") -> dict:
    """INTRA-01: the P&L of selling `qty` contracts at `exit_premium` (an EXECUTABLE bid,
    or a labelled synthetic one) after buying at `entry_premium` - independent of where
    the underlying sits versus the expiration break-even. Unknown without both premiums."""
    if entry_premium is None or exit_premium is None or not qty:
        return {"status": "unknown", "unknown": [k for k, v in (("entryPremium", entry_premium), ("exitPremium", exit_premium),
                                                                 ("qty", qty)) if not v],
                "evidence": evidence, "gross": None, "fees": None, "net": None}
    q = float(qty)
    gross = (float(exit_premium) - float(entry_premium)) * float(multiplier) * q
    fees = float(fee_per_unit) * q * 2.0
    net = gross - fees
    return {"status": "known", "evidence": evidence, "entryPremium": float(entry_premium), "exitPremium": float(exit_premium),
            "qty": q, "multiplier": float(multiplier), "gross": round(gross, 2), "fees": round(fees, 2), "net": round(net, 2),
            "perUnitNet": round(net / q, 4),
            "note": "profit on an EARLIER SALE depends on the premium then, not on the expiration break-even"}


def horizon_block(*, dte: int | None, hold_sessions: int | None, expiry_date: str | None = None, as_of=None,
                  exit_at_expiry: bool = False) -> dict:
    """I175-03: the MAXIMUM holding cap, the expiry date and the scenario's exit assumption
    are three different things. A hold cap never declares an expiry exit (targets, stops or
    the source can close earlier); only an explicit `exit_at_expiry` does. Trading sessions
    are converted to a calendar date on the exchange calendar; unknown stays unknown."""
    import datetime as _dt
    from ...marketstructure import market_calendar as _cal
    today = as_of or _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=-4))).date()
    if isinstance(today, _dt.datetime):
        today = today.date()
    hold_end = None
    if hold_sessions is not None and int(hold_sessions) > 0:
        d = today
        for _ in range(int(hold_sessions)):
            d = _cal.next_trading_day(d)
        hold_end = d.isoformat()
    exp = None
    if expiry_date:
        try:
            exp = _dt.date.fromisoformat(str(expiry_date)).isoformat()
        except ValueError:
            exp = None
    reaches = (hold_end is not None and exp is not None and hold_end >= exp)
    if exit_at_expiry:
        assumption = "declared: held to expiry"
    elif hold_sessions is not None or dte is not None:
        assumption = "before expiry (target / stop / premium exit) - a hold cap is a maximum, not an exit time"
    else:
        assumption = "unknown"
    return {"dte": dte, "expiryDate": exp, "maxHoldSessions": hold_sessions, "holdCapEndsOn": hold_end,
            "holdCapReachesExpiry": reaches, "exitAssumption": assumption,
            "note": ("the scenarios value exits BEFORE expiry (delta-linear at the target); intrinsic value applies only to a "
                     "DECLARED held-to-expiry exit (expiryScenario); the hold cap says when the desk stops waiting, not when it sells")}


def payoff_preview(*, qty: int, fractions: list[float], gains: list[float | None],
                   unit_loss: float | None, fee_per_unit: float = 0.0,
                   runner_gain: float | None = None, vehicle: str = "option",
                   strike: float | None = None, premium: float | None = None, option_type: str | None = None,
                   dte: int | None = None, hold_sessions: int | None = None, expiry_date: str | None = None,
                   as_of=None, exit_at_expiry: bool = False, underlying_targets: list[float] | None = None) -> dict:
    """The declared scenarios in $ and in R (R = the PLANNED stop loss for the
    whole size, an estimate, never a guaranteed maximum loss). Fees are paid
    per unit on entry and on every exit unit."""
    q = int(max(0, qty))
    lad = integer_ladder(q, fractions, vehicle=vehicle)
    units = lad["units"]
    fee_in = fee_per_unit * q
    planned_risk = (float(unit_loss) * q) if unit_loss is not None else None
    have_gains = bool(gains) and all(g is not None for g in gains[:len(units)])
    out = {"version": PAYOFF_VERSION, "qty": q, "ladder": lad, "unitLoss": unit_loss,
           "plannedRisk": round(planned_risk, 2) if planned_risk is not None else None,
           "feePerUnit": fee_per_unit, "gainsPerUnit": gains,
           "basis": "delta-linear estimate for options, price distance for shares; fees per unit in and out",
           "claim": "arithmetic on the declared plan - no statement that any target is reached"}
    if vehicle == "option":
        # INTRA-01: the expiration break-even printed BESIDE the before-expiry scenarios,
        # with the declared horizon, so the two are never confused
        out["breakEven"] = break_even(option_type=option_type or "call", strike=strike, premium=premium)
        out["horizon"] = horizon_block(dte=dte, hold_sessions=hold_sessions, expiry_date=expiry_date, as_of=as_of,
                                       exit_at_expiry=exit_at_expiry)
        if exit_at_expiry and strike is not None and premium is not None and underlying_targets:
            # I175-03: intrinsic value is used ONLY for an explicitly declared held-to-expiry exit
            fee_all = fee_per_unit * q * 2.0
            out["expiryScenario"] = {"declared": True, "basis": "intrinsic value at expiry minus premium and both sides' fees",
                                     "perTarget": [{"underlying": float(u), "intrinsic": expiry_value(option_type=option_type or "call", strike=strike, underlying=u),
                                                    "net": round((expiry_value(option_type=option_type or "call", strike=strike, underlying=u) - float(premium)) * 100.0 * q - fee_all, 2)}
                                                   for u in underlying_targets]}
    # INTRA-02: one lot is an EXIT-PLAN question - what a single contract can execute
    # versus the rungs the plan declares - never a rejection by itself
    if vehicle == "option" and q >= 1:
        # I175-02: the capability is DERIVED from the executed unit sequence, never from a
        # quantity-vs-rungs count: every positive rung must receive at least one unit to
        # "cover" the partials, and the weights are reproduced only when the integer split
        # equals the declared fractions
        pos = [(i, f) for i, f in enumerate(fractions or []) if f and f > 0]
        units = list(lad["units"])
        covered = bool(pos) and len(pos) > 1 and all(i < len(units) and units[i] > 0 for i, _f in pos)
        reproduced = covered and all(abs(units[i] / q - f) < 1e-9 for i, f in pos)
        uncovered = [i + 1 for i, _f in pos if not (i < len(units) and units[i] > 0)]
        out["singleLot"] = {"declaredRungs": len(pos), "executableRungs": len([u for u in units if u > 0]),
                            "executedUnits": units, "collapsed": bool(lad.get("collapsed")) or q == 1,
                            "canCopyPartials": covered, "reproducesWeights": reproduced,
                            "uncoveredRungs": uncovered,
                            "note": ("one contract executes ONE exit (the first target, or a premium-based exit); it cannot "
                                     "copy several partial scale-outs - judge that single-exit plan on its own net payoff "
                                     "(oneLot / tp1ThenStop), and skip only when the thesis DEPENDS on scaling or one unit "
                                     "does not fit the budget" if q == 1 else
                                     ("every declared rung receives at least one unit" + (" and the weights are reproduced exactly"
                                      if reproduced else " but the weights are NOT the declared fractions - see executedUnits")) if covered else
                                     f"rung(s) {uncovered} receive no unit at this size - the ladder is not copied; see executedUnits")}
    if not have_gains or unit_loss is None:
        out["scenarios"] = None
        out["reason"] = "no unit loss estimate" if unit_loss is None else "no gain estimate for every rung (missing delta or targets)"
        return out
    g = [float(x) for x in gains]
    runner = lad["runner"]
    last_gain = float(runner_gain) if runner_gain is not None else (g[-1] if g else 0.0)
    all_targets = sum(u * g[i] for i, u in enumerate(units)) + runner * last_gain - fee_in - fee_per_unit * q
    first_units = units[0] if units else 0
    tp1_then_stop = (first_units * g[0] if units else 0.0) - (q - first_units) * float(unit_loss) - fee_in - fee_per_unit * q
    stop_only = -q * float(unit_loss) - fee_in - fee_per_unit * q
    r = planned_risk if planned_risk else None

    def _r(v):
        return round(v / r, 2) if r else None
    out["scenarios"] = {
        "allTargets": {"net": round(all_targets, 2), "R": _r(all_targets)},
        "tp1ThenStop": {"net": round(tp1_then_stop, 2), "R": _r(tp1_then_stop),
                        "note": "first rung fills, the rest is stopped"},
        "stopOnly": {"net": round(stop_only, 2), "R": _r(stop_only)},
    }
    if q == 1 or lad["collapsed"]:
        # the coherent one-lot line: what actually executes at this size - the
        # same number as allTargets (PROF-F2: after the first rung sells the whole
        # lot, no later target or stop applies)
        exec_net = sum(u * g[i] for i, u in enumerate(units)) + runner * last_gain - fee_in - fee_per_unit * q
        out["oneLot"] = {"policy": ("single exit at the first target" if first_units == q
                                    else "executed sequence " + "/".join(str(u) for u in units)),
                         "net": round(exec_net, 2), "R": _r(exec_net),
                         "note": "the declared ladder cannot be followed at this size; this is what actually executes "
                                 "(an option rung sells at least one contract; a share rung sells whole shares)"}
    return out


def realized_from_fills(*, entry_qty: float, entry_price: float, fills: list[dict], multiplier: float = 1.0,
                        direction: str = "long") -> dict:
    """Reconcile a round trip from actual fills: sum over exits of units x
    (price - entry) for a long (reversed for a short). Excess exits beyond the
    entry quantity are reported separately - never scored as the idea."""
    sgn = 1.0 if direction != "short" else -1.0
    remaining = float(entry_qty)
    realized = 0.0
    excess = 0.0
    parts = []
    for f in fills:
        q = float(f.get("qty") or 0)
        px = float(f.get("price") or 0)
        take = min(q, remaining)
        pnl = sgn * (px - float(entry_price)) * take * float(multiplier)
        realized += pnl
        parts.append({"qty": take, "price": px, "pnl": round(pnl, 2), "kind": f.get("kind")})
        remaining -= take
        if q > take:
            excess += q - take
    return {"realized": round(realized, 2), "parts": parts, "unclosed": round(max(0.0, remaining), 4),
            "excessUnits": round(excess, 4)}
