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


def payoff_preview(*, qty: int, fractions: list[float], gains: list[float | None],
                   unit_loss: float | None, fee_per_unit: float = 0.0,
                   runner_gain: float | None = None, vehicle: str = "option") -> dict:
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
