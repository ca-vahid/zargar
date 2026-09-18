"""Lane A: long daily-base breakout with repeated ceiling tests — pure, order-free (2026-09-18).

Proposal revision 3 (docs/techniques/options-cartel/reviews/2026-09-17-proposal/PROPOSAL.md).
Nothing on the preparation, arming or entry path imports this module; it exists so the lane can
be evaluated offline over frozen analysis inputs and reviewed before any production wiring.

Definition (one setup, one entry mode):
  * direction long, strict bullish market (the caller passes the frozen market read);
  * the existing context gates unchanged (the analysis run's checks all pass);
  * the `base` family: trigger = ceiling of the 10-session base, reviewed invalidation = base low;
  * the ceiling must have been tested at least ``min_ceiling_touches`` times within
    ``touch_tolerance_pct`` (S02 "repeatedly rejected resistance"; count and tolerance are ours);
  * first target = nearest confirmed daily pivot above the trigger (no Fibonacci fallback);
  * the current 0.5% first-target distance floor stays active;
  * ``experimental_min_planning_r`` (default None = inactive) is an engineering reading of the S14
    checklist measured on the trigger-to-reviewed-invalidation basis; its verdict is *recorded*,
    never applied, until reviewed.

Feasibility is classified from a dated chain observation into the states agreed with the
reviewer: affordable / over_budget / spread_blocked / filtered_other / no_chain (``unknown_stale``
is the caller's verdict when no observation exists).
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .data import DailyBar, completed_daily
from .quality import target_room
from .setups import _targets

LANE = "A"
VERSION = "lane-a-review-1"
STAGES = ("direction", "context", "base_family", "ceiling_tests", "confirmed_target", "distance_floor", "qualified")


class LaneAParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    base_sessions: int = Field(default=10, ge=3, le=60)
    min_ceiling_touches: int = Field(default=2, ge=1, le=20)
    touch_tolerance_pct: float = Field(default=0.5, ge=0, le=5)
    min_target_distance_pct: float = Field(default=0.5, ge=0, le=10)
    experimental_min_planning_r: float | None = Field(default=None, ge=0, le=10)


def ceiling_tests(base: list[DailyBar], tolerance_pct: float) -> dict:
    """Sessions whose high came within ``tolerance_pct`` of the base ceiling (the ceiling itself counts)."""
    ceiling = max(b.high for b in base)
    touched = [b.session.isoformat() for b in base if (ceiling - b.high) / ceiling * 100 <= tolerance_pct]
    return {"ceiling": ceiling, "touches": len(touched), "touchSessions": touched}


def lane_a_review(analysis: dict, history: list[DailyBar], *, as_of_ms: int, direction: str,
                  market_direction: str | None, parameters: LaneAParameters | None = None) -> dict:
    """Evaluate one frozen analysis under the Lane A definition. Returns the first failing stage.

    ``analysis`` is the saved ``result.analysis`` of a Cartel analysis run (its ``checks`` and
    ``candidates``); ``history`` the daily bars that run used. No I/O, no orders.
    """
    p = parameters or LaneAParameters()
    out = {"lane": LANE, "version": VERSION, "parameters": p.model_dump(mode="json"), "qualified": False,
           "stage": None, "reasons": [], "candidate": None, "structuralR": None, "firstTargetPct": None,
           "experimental": {"minPlanningR": p.experimental_min_planning_r, "passes": None, "active": False}}

    def fail(stage, reason):
        out["stage"] = stage
        out["reasons"].append(reason)
        return out

    if direction != "long" or market_direction != "long":
        return fail("direction", f"Lane A plans only long setups on strict-bullish sessions (direction={direction}, market={market_direction}).")
    checks = analysis.get("checks") or []
    failed = [c["name"] for c in checks if c.get("status") != "pass"]
    if failed or not checks:
        return fail("context", "Context gates not all passed: " + (", ".join(failed) or "no checks recorded"))
    base_candidate = next((c for c in analysis.get("candidates") or [] if c.get("setup") == "base"), None)
    if base_candidate is None or not base_candidate.get("contextPassed"):
        return fail("base_family", "No context-passing `base` candidate in the frozen analysis.")
    bars = completed_daily(history, as_of_ms)
    if len(bars) < p.base_sessions:
        return fail("base_family", f"Fewer than {p.base_sessions} completed sessions available.")
    base = bars[-p.base_sessions:]
    tests = ceiling_tests(base, p.touch_tolerance_pct)
    trigger, invalidation = base_candidate["trigger"], base_candidate["invalidation"]
    if not math.isclose(tests["ceiling"], trigger, rel_tol=1e-9):
        return fail("base_family", f"Base ceiling {tests['ceiling']} does not match the candidate trigger {trigger}.")
    out["ceilingTests"] = tests
    if tests["touches"] < p.min_ceiling_touches:
        return fail("ceiling_tests", f"Ceiling tested {tests['touches']} time(s); Lane A requires {p.min_ceiling_touches}.")
    targets = _targets(bars, trigger, "long", p.touch_tolerance_pct)  # confirmed pivots only; no Fibonacci
    if not targets:
        return fail("confirmed_target", "No confirmed daily pivot above the trigger (Fibonacci fallback is off in Lane A).")
    room = target_room(trigger, invalidation, targets[0])
    out.update(structuralR=room["structuralTargetR"], firstTargetPct=room["firstTargetPct"],
               candidate={"setup": "base", "direction": "long", "trigger": trigger, "invalidation": invalidation,
                          "targets": targets[:3], "targetSource": "Confirmed historical price pivots from completed daily bars",
                          "structuralRBasis": "first target vs trigger-to-reviewed-invalidation"})
    if room["firstTargetPct"] < p.min_target_distance_pct:
        return fail("distance_floor", f"First target {room['firstTargetPct']:.2f}% away; floor {p.min_target_distance_pct}% (existing rule).")
    if p.experimental_min_planning_r is not None:
        out["experimental"]["passes"] = room["structuralTargetR"] >= p.experimental_min_planning_r
    out.update(qualified=True, stage="qualified")
    return out


class FeasibilityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    dte_min: int = 21
    dte_max: int = 90
    target_dte: int = 45
    min_abs_delta: float = 0.25
    max_spread_pct: float = 20.0
    min_open_interest: int = 100
    max_ask: float = 5.0            # the effective cap: min(policy max_ask, budget/(100*fx), equity*risk%/(100*fx))


FeasibilityState = Literal["affordable", "over_budget", "spread_blocked", "filtered_other", "no_chain"]


def feasibility_from_chain(rows: list[dict], *, direction: str, first_session: dt.date, policy: FeasibilityPolicy,
                           observed_at: str | None) -> dict:
    """Classify a dated chain observation (rows with expiry, option_type, delta, bid, ask, open_interest).

    Every row records its first failing filter; the state names why nothing passed. This is
    planning-time evidence only: a fresh quote is still required before any order.
    """
    right = "call" if direction == "long" else "put"
    numeric = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    first_fail: dict[str, int] = {}
    eligible, lowest_ask, examined = [], None, 0
    for r in rows:
        expiry = r.get("expiry")
        if isinstance(expiry, str):
            expiry = dt.date.fromisoformat(expiry)
        if r.get("option_type") not in (right, right[0].upper(), right[0]):
            continue
        dte = (expiry - first_session).days if expiry else None
        if dte is None or not policy.dte_min <= dte <= policy.dte_max:
            continue
        examined += 1
        bid, ask, delta, oi = r.get("bid"), r.get("ask"), r.get("delta"), r.get("open_interest")
        failures = []
        if not (numeric(bid) and numeric(ask) and 0 < bid <= ask):
            failures.append("quotes")
        if not (numeric(delta) and policy.min_abs_delta <= abs(delta) <= 1 and delta * (1 if direction == "long" else -1) > 0):
            failures.append("delta")
        if numeric(bid) and numeric(ask) and 0 < bid <= ask and (ask - bid) / ((ask + bid) / 2) * 100 > policy.max_spread_pct:
            failures.append("spread")
        if policy.min_open_interest and (not numeric(oi) or oi < policy.min_open_interest):
            failures.append("open_interest")
        if numeric(ask) and ask > policy.max_ask:
            failures.append("premium")
        if failures:
            first_fail[failures[0]] = first_fail.get(failures[0], 0) + 1
            if failures == ["premium"] and numeric(ask):
                lowest_ask = ask if lowest_ask is None else min(lowest_ask, ask)
            continue
        eligible.append({"symbol": r.get("occ"), "expiry": expiry.isoformat(), "dte": dte, "delta": delta, "bid": bid, "ask": ask,
                         "spreadPct": (ask - bid) / ((ask + bid) / 2) * 100, "openInterest": oi})
    if examined == 0:
        state = "no_chain"
    elif eligible:
        state = "affordable"
    elif first_fail and set(first_fail) == {"premium"}:
        state = "over_budget"
    elif first_fail and set(first_fail) == {"spread"}:
        state = "spread_blocked"
    else:
        state = "filtered_other"
    eligible.sort(key=lambda c: (abs(c["dte"] - policy.target_dte), abs(abs(c["delta"]) - 0.5), c["spreadPct"]))
    return {"state": state, "observedAt": observed_at, "rowsInRange": examined, "eligible": len(eligible),
            "firstFailingFilter": first_fail, "lowestOtherwiseEligibleAsk": lowest_ask, "best": eligible[0] if eligible else None,
            "policy": policy.model_dump(mode="json"),
            "note": "Planning-time chain evidence only; a fresh quote and full preflight remain required before any order."}
