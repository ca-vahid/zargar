"""Sizing modes for durable positions (phase 2b; techniques research A6).

Three first-class ways to size, all pure:

- risk-based (the session runner's mode): units = equity × risk% / risk-per-unit
- budget-based: "allocate at most $X to this position" (Tip's fixed budget)
- per-source budget: the cap is shared by everything open under one tag

The RiskGate day-notional caps (`risk.max_day_notional_per_technique/_tag`)
stay the hard backstop — these helpers size *within* them.
"""
from __future__ import annotations


def size_by_risk(equity: float, risk_pct: float, per_unit_risk: float, *, max_units: float,
                 multiplier: float = 1.0) -> int:
    """Units so that (units × per_unit_risk × multiplier) ≈ equity × risk%."""
    if per_unit_risk <= 0 or multiplier <= 0:
        return 0
    dollars = max(0.0, float(equity)) * max(0.0, float(risk_pct)) / 100.0
    units = int(dollars / (float(per_unit_risk) * float(multiplier)))
    return int(max(0, min(units, int(max_units))))


def size_by_budget(budget: float, unit_cost: float, *, max_units: float, multiplier: float = 1.0) -> int:
    """Units a fixed dollar budget buys (never exceeds it)."""
    if unit_cost <= 0 or multiplier <= 0:
        return 0
    units = int(max(0.0, float(budget)) / (float(unit_cost) * float(multiplier)))
    return int(max(0, min(units, int(max_units))))


def source_budget_left(source_budget: float, open_cost_for_tag: float) -> float:
    """Dollars a tag (e.g. source:discord-x) may still deploy given what it
    already has open. The caller computes `open_cost_for_tag` from the manager's
    open positions filtered by tag."""
    return max(0.0, float(source_budget) - max(0.0, float(open_cost_for_tag)))


def open_cost(positions: list[dict], tag: str | None = None) -> float:
    """Entry cost (per-unit basis × qty × multiplier, absolute) of open managed
    positions, optionally filtered by tag — the input to `source_budget_left`."""
    total = 0.0
    for p in positions:
        if p.get("status") not in ("open", "closing", "attention", "opening"):
            continue
        if tag is not None and tag not in (p.get("tags") or []):
            continue
        for l in p.get("legs") or []:
            qty = abs(float(l.get("qty") or 0))
            fill = float(l.get("avgFill") or 0)
            total += qty * fill * float(l.get("multiplier") or 1.0)
    return round(total, 2)
