"""PROF-01 (2026-09-15): can the book EXECUTE this expression within the
approved risk budget - judged BEFORE the analyst's verdict, not after the card
is refused.

Five of nine recent TAKE cards could not fit one contract inside the approved
planned-risk budget. The thesis may be right; the expression does not fit.
This module separates the two: `feasibility()` answers "how many units fit"
from the same unit-loss estimator the geometry gate uses, and the alternatives
are RESEARCH records at equal dollar risk (shares, or another strike of the
same expiry) - labelled, never a silent substitution, never a raised limit.
"""
from __future__ import annotations

import math

from . import geometry as _geo

FEASIBILITY_VERSION = "feasibility-v1"


def unit_risk(*, vehicle: str, entry_ref: float | None, stop: float | None, direction: str,
              premium: float | None = None, delta: float | None = None, option_type: str | None = None,
              multiplier: float = 100.0, premium_stop_pct: float | None = None) -> tuple[float | None, str, dict]:
    """$ risk per unit at the declared stop: shares = |entry - stop|; options
    = the geometry gate's delta-linear estimate (premium stop / full premium
    when there is no underlying stop). None = cannot estimate (never guessed)."""
    if vehicle == "shares":
        dist = _geo.stop_distance(direction, entry_ref, stop) if (entry_ref is not None and stop is not None) else None
        if dist is None:
            return None, "none", {"reason": "no stop - share risk cannot be bounded"}
        if dist <= 0:
            return None, "none", {"reason": "stop on the wrong side of the entry"}
        return round(float(dist), 4), "stop-distance", {}
    dist = _geo.stop_distance(direction, entry_ref, stop) if (entry_ref is not None and stop is not None) else None
    return _geo.option_unit_loss(premium=float(premium or 0), delta=delta, dist=dist, multiplier=multiplier,
                                 option_type=str(option_type or ""), direction=direction,
                                 premium_stop_pct=premium_stop_pct)


def feasibility(*, budget: float, unit_loss: float | None, unit_cost: float | None = None,
                allocation_limit: float | None = None) -> dict:
    """How many units fit the approved risk budget (and the purchase
    allocation when known). qty 0 = an honest no-trade for this expression."""
    out = {"version": FEASIBILITY_VERSION, "budget": (round(float(budget), 2) if budget is not None else None),
           "unitLoss": unit_loss, "unitCost": unit_cost, "allocationLimit": allocation_limit}
    # PROF-F1: None = unknown (never capital), numeric zero = none available;
    # a negative or non-finite number is an invalid input, not a budget
    for name, v in (("budget", budget), ("unit_loss", unit_loss), ("unit_cost", unit_cost), ("allocation_limit", allocation_limit)):
        if v is not None and (not math.isfinite(float(v)) or float(v) < 0):
            out.update(feasible=None, qty=None, reason=f"invalid {name} ({v!r}) - review, not a trade")
            return out
    if budget is None:
        out.update(feasible=None, qty=None, reason="risk budget unknown - review, not a trade")
        return out
    if unit_loss is None:
        out.update(feasible=None, qty=None, reason="no unit-loss estimate (missing delta or stop) - review, not a trade")
        return out
    if float(budget) <= 0:
        out.update(feasible=False, qty=0, qtyByRisk=0, qtyByAllocation=None, reason="no approved risk budget")
        return out
    if allocation_limit is not None and float(allocation_limit) <= 0:
        out.update(feasible=False, qty=0, qtyByRisk=None, qtyByAllocation=0, reason="no purchase allocation ($0)")
        return out
    fit = int(math.floor(float(budget) / float(unit_loss) + 1e-9)) if float(unit_loss) > 0 else 0
    alloc_fit = None
    if allocation_limit is not None and unit_cost is not None and float(unit_cost) > 0:
        alloc_fit = int(math.floor(float(allocation_limit) / float(unit_cost) + 1e-9))
    qty = fit if alloc_fit is None else min(fit, alloc_fit)
    out.update(qtyByRisk=fit, qtyByAllocation=alloc_fit, qty=int(max(0, qty)), feasible=bool(qty >= 1))
    if qty < 1:
        if fit < 1:
            out["reason"] = f"one unit risks ${float(unit_loss):,.2f} at the declared stop - above the ${float(budget):,.2f} risk budget"
        else:
            out["reason"] = f"one unit costs ${float(unit_cost):,.2f} - above the ${float(allocation_limit):,.2f} purchase allocation"
    else:
        out["reason"] = None
    return out


def share_alternative(*, entry: float | None, stop: float | None, direction: str, budget: float,
                      allocation_limit: float | None, commission: float = 0.0) -> dict | None:
    """RESEARCH comparison at the same dollar risk: shares sized so that
    qty x |entry - stop| <= budget (and qty x entry <= allocation). Never for a
    bearish thesis (share shorting is never proposed)."""
    if direction == "short" or not entry or stop is None or budget is None:
        return None
    if allocation_limit is not None and float(allocation_limit) <= 0:
        return None                                     # PROF-F1: a $0 allocation buys nothing
    dist = _geo.stop_distance(direction, entry, stop)
    if dist is None or dist <= 0:
        return None
    qty = int(math.floor(float(budget) / dist + 1e-9))
    if allocation_limit is not None:
        qty = min(qty, int(math.floor(float(allocation_limit) / float(entry) + 1e-9)))
    if qty < 1:
        return None
    return {"kind": "shares", "label": "research alternative - shares at equal risk", "qty": qty,
            "entry": float(entry), "stop": float(stop), "unitLoss": round(dist, 4),
            "plannedRisk": round(qty * dist, 2), "cost": round(qty * float(entry) + commission, 2),
            "note": "not a substitution: the original expression stays the card; this is a labelled comparison"}


def chain_alternatives(rows: list[dict], *, direction: str, entry_ref: float | None, stop: float | None,
                       budget: float, allocation_limit: float | None, multiplier: float = 100.0,
                       premium_stop_pct: float | None = None, limit: int = 3,
                       exclude_symbol: str | None = None) -> list[dict]:
    """RESEARCH comparison at the same dollar risk: strikes of the SAME expiry
    (from a chain window the analyst already fetched) whose one-unit risk fits
    the budget. Requires a delta and a two-sided quote per row; rows without
    them are skipped, never estimated."""
    side = "put" if direction == "short" else "call"
    out = []
    for r in rows or []:
        c = (r or {}).get(side) or {}
        ask = float(c.get("ask") or 0)
        delta = c.get("delta")
        sym = c.get("symbol")
        if ask <= 0 or delta is None or not sym or sym == exclude_symbol:
            continue
        ul, basis, meta = unit_risk(vehicle="option", entry_ref=entry_ref, stop=stop, direction=direction,
                                    premium=ask, delta=float(delta), option_type=side, multiplier=multiplier,
                                    premium_stop_pct=premium_stop_pct)
        f = feasibility(budget=budget, unit_loss=ul, unit_cost=ask * multiplier, allocation_limit=allocation_limit)
        if f.get("feasible"):
            out.append({"kind": "option", "label": "research alternative - same expiry, fits the risk budget",
                        "symbol": sym, "strike": r.get("strike"), "ask": ask, "delta": float(delta),
                        "unitLoss": ul, "unitLossBasis": basis, "qty": f["qty"],
                        "plannedRisk": round(f["qty"] * float(ul), 2), "cost": round(f["qty"] * ask * multiplier, 2)})
    out.sort(key=lambda x: (abs(float(x.get("strike") or 0) - float(entry_ref or 0)), -x["delta"]))
    return out[:limit]


def apply_gate(opinion: dict, expression: dict, mode: str) -> dict:
    """Record the expression assessment on the opinion. `annotate` (default)
    keeps the analyst's verdict and adds the typed result; `downgrade` turns a
    TAKE whose expression does not fit into WATCH with the reason - the thesis
    verdict is kept separately so nothing is lost."""
    op = dict(opinion)
    op["thesisVerdict"] = op.get("verdict")
    op["expression"] = expression
    if mode == "downgrade" and op.get("verdict") == "take" and expression.get("feasible") is False:
        op["verdict"] = "watch"
        op["rationale"] = (str(op.get("rationale") or "") +
                           f" [expression does not fit the approved risk budget: {expression.get('reason')}]").strip()
        op["expressionGate"] = "downgraded"
    else:
        op["expressionGate"] = "annotated"
    return op
