"""Pre-entry geometry + risk sizing — GEOMETRY-RISK-PLAN revision 2 (built
2026-09-14 on the reviewer's GO; implementation review before activation).

Principle: the trade that fills must be the trade the analyst evaluated.
Geometry is finalized BEFORE capital commits, the size is derived from the
FINAL stop against an approved dollar budget B, and every post-fill change is
a bounded, journaled exception (a widen is a trim-FIRST state machine — the
tighter stop stays armed until the trim is confirmed).

Everything in this module is PURE (no I/O, no clock): the proposal path and
the adoption path call it and journal what it decided. The mode knob
`techniques.tip.geometry_gate` is:

    off      — nothing computed (pre-revision behaviour)
    shadow   — computed + journaled with enforced=false, sizes untouched  (DEFAULT)
    enforce  — sizes/stops applied, review-gated proposals never auto-approve

Units are explicit: `entry_ref`, `stop`, `targets` are UNDERLYING prices;
option loss estimates are per CONTRACT in the contract's currency using the
multiplier from the contract metadata (never assumed 100 silently at the
call site — the caller passes it). The delta-linear estimator is an
ENGINEERING assumption (gamma / vol / time excluded), versioned on every
plan, floored at PREMIUM_LOSS_FLOOR × premium × multiplier, and never called
a loss cap: the full premium at risk (stress loss) is an independent number.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

ESTIMATOR_VERSION = "delta-linear-v1"
PREMIUM_LOSS_FLOOR = 0.25          # an option never "loses less than 25% of its premium" at the stop
MODES = ("off", "shadow", "enforce")
DEFAULT_MATERIALITY_PCT = 10.0     # classifies a widening as review-vs-log; never waives the invariant


@dataclass
class RiskPlan:
    mode: str
    phase: str = "pre-entry"
    estimatorVersion: str = ESTIMATOR_VERSION
    direction: str = "long"
    vehicle: str = "shares"                    # shares | option
    multiplier: float = 1.0
    currency: str = "USD"
    entryRef: float = 0.0
    originalStop: float | None = None
    finalStop: float | None = None
    stopDistance: float | None = None
    targets: list = field(default_factory=list)
    fractions: list = field(default_factory=list)
    repairs: list = field(default_factory=list)
    widenPct: float | None = None              # how much the FINAL stop widened vs the analyst's
    severity: str = "log"                      # log | review (materiality of a widening)
    unitLoss: float | None = None              # $ per unit at the final stop
    unitLossBasis: str = "none"                # stop-distance | delta-linear | premium-stop | full-premium | none
    stressUnitLoss: float = 0.0                # $ per unit, theoretical maximum
    budget: float = 0.0
    budgetSource: str = ""
    qtyRequested: int = 0
    qty: int = 0
    resized: bool = False
    resizeReason: str | None = None
    plannedRisk: float | None = None           # qty × unitLoss
    stressRisk: float = 0.0                    # qty × stressUnitLoss
    invariantOk: bool | None = None            # qty × unitLoss <= budget (None = no estimate)
    reviewRequired: str | None = None          # a reason means NO automatic entry
    enforced: bool = False
    quote: dict = field(default_factory=dict)  # {source, ageS, delayed, priced}
    greeks: dict = field(default_factory=dict) # {delta, asOf, source}
    decisions: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("entryRef", "originalStop", "finalStop", "stopDistance", "unitLoss",
                  "stressUnitLoss", "budget", "plannedRisk", "stressRisk", "widenPct"):
            if d.get(k) is not None:
                d[k] = round(float(d[k]), 4)
        return d


def gate_mode(settings) -> str:
    m = str(settings.get("techniques.tip.geometry_gate", "shadow") or "shadow").lower()
    return m if m in MODES else "shadow"


def risk_budget(settings, equity: float | None) -> tuple[float, str]:
    """B from APPROVED desk policy, never from a model's proposed quantity:
    `techniques.tip.risk_budget_per_tip` when > 0 (a fixed dollar budget),
    else `techniques.tip.risk_pct` % of the book's equity. (0, reason) when
    neither can be evaluated — the caller review-gates."""
    fixed = float(settings.get("techniques.tip.risk_budget_per_tip", 0.0) or 0.0)
    if fixed > 0:
        return fixed, "techniques.tip.risk_budget_per_tip"
    pct = float(settings.get("techniques.tip.risk_pct", 1.0) or 0.0)
    if equity is None or equity <= 0 or pct <= 0:
        return 0.0, "no budget: equity unknown or risk_pct <= 0"
    return round(equity * pct / 100.0, 2), f"techniques.tip.risk_pct {pct:g}% of ${equity:,.0f} equity"


def stop_distance(direction: str, entry_ref: float, stop: float | None) -> float | None:
    """Signed-correct distance from entry to stop for the thesis direction:
    long → entry − stop, short → stop − entry. None when there is no stop;
    a non-positive value is a SIGN failure (the geometry gate repairs those
    before sizing — a caller seeing <= 0 here must not size)."""
    if stop is None or entry_ref is None:
        return None
    sgn = 1.0 if direction != "short" else -1.0
    return sgn * (float(entry_ref) - float(stop))


def option_unit_loss(*, premium: float, delta: float | None, dist: float | None,
                     multiplier: float, option_type: str, direction: str,
                     premium_stop_pct: float | None = None) -> tuple[float | None, str, dict]:
    """$ loss per CONTRACT at the underlying stop. Delta-linear: the contract
    is assumed to lose |delta| × stop_distance per share of underlying move
    (a long call with a stop below entry, a long put with a stop above — the
    put's negative delta is taken in absolute value), floored at
    PREMIUM_LOSS_FLOOR × premium × multiplier. With NO underlying stop the
    declared premium stop (%) is the loss bound; without either the whole
    premium is. Returns (unit_loss, basis, meta); unit_loss None = cannot
    estimate (missing delta) — REVIEW, never a guess."""
    prem = float(premium or 0.0)
    mult = float(multiplier or 0.0)
    if prem <= 0 or mult <= 0:
        return None, "none", {"reason": "no premium/multiplier"}
    full = prem * mult
    meta: dict = {}
    if dist is None or dist <= 0:
        if premium_stop_pct and 0 < float(premium_stop_pct) < 100:
            return round(full * float(premium_stop_pct) / 100.0, 4), "premium-stop", {"premiumStopPct": float(premium_stop_pct)}
        return round(full, 4), "full-premium", {"note": "no underlying stop and no premium stop: the whole debit is the risk"}
    if delta is None:
        return None, "none", {"reason": "missing delta — no estimate invented"}
    d = abs(float(delta))
    thesis_ok = (option_type == "call" and direction != "short") or (option_type == "put" and direction == "short")
    meta = {"delta": round(d, 4), "thesisMatch": thesis_ok}
    est_drop = d * float(dist)                       # premium lost per contract-share
    est_at_stop = max(0.0, prem - est_drop)
    loss = (prem - est_at_stop) * mult
    floored = PREMIUM_LOSS_FLOOR * full
    if loss < floored:
        loss = floored
        meta["floorApplied"] = True
    loss = min(loss, full)                            # can never lose more than the debit
    return round(loss, 4), "delta-linear", meta


def size_to_budget(*, budget: float, unit_loss: float | None, qty_requested: int) -> tuple[int, str | None]:
    """qty = min(requested, floor(B / unit_loss)), rounded DOWN. (qty, note);
    qty 0 means no quantity satisfies B — the caller review-gates (a
    1-contract minimum never silently violates B)."""
    q = int(max(0, qty_requested))
    if unit_loss is None or unit_loss <= 0:
        return q, None
    if budget <= 0:
        return 0, "no budget available"
    fit = int(math.floor(budget / unit_loss + 1e-9))
    if fit >= q:
        return q, None
    if fit < 1:
        return 0, (f"no quantity satisfies the ${budget:,.0f} risk budget: one unit risks "
                   f"${unit_loss:,.0f} at the final stop")
    return fit, f"resized {q} → {fit} so that {fit} × ${unit_loss:,.0f} ≤ ${budget:,.0f} risk budget"


def plan_risk(*, mode: str, direction: str, vehicle: str, entry_ref: float,
              exit_plan: dict, bars: list, settings, limit: float, qty_requested: int,
              multiplier: float = 1.0, option_type: str | None = None,
              delta: float | None = None, greeks_meta: dict | None = None,
              budget: float, budget_source: str, quote_meta: dict | None = None,
              currency: str = "USD") -> tuple[dict, RiskPlan]:
    """The pre-entry plan: geometry gate (same rules as adoption — sign, width,
    structure) → FINAL stop → unit loss → size against B → invariant.
    Returns (final_exit_plan, RiskPlan). In 'shadow' mode the RiskPlan says
    what WOULD happen (enforced=False) and the caller keeps its sizes."""
    from .lifecycle import check_exit_geometry
    rp = RiskPlan(mode=mode, direction=direction, vehicle=vehicle, multiplier=float(multiplier),
                  currency=currency, entryRef=float(entry_ref), budget=float(budget),
                  budgetSource=budget_source, qtyRequested=int(qty_requested),
                  quote=dict(quote_meta or {}), greeks=dict(greeks_meta or {}))
    plan = dict(exit_plan or {})
    rp.originalStop = float(plan["underlyingStop"]) if plan.get("underlyingStop") else None
    final, repairs = check_exit_geometry(plan, direction=direction, entry_ref=float(entry_ref),
                                         bars=bars or [], settings=settings)
    rp.repairs = list(repairs)
    rp.finalStop = float(final["underlyingStop"]) if final.get("underlyingStop") else None
    rp.targets = list(final.get("targets") or [])
    rp.fractions = list(final.get("fractions") or [])
    dist = stop_distance(direction, entry_ref, rp.finalStop)
    rp.stopDistance = dist
    if rp.originalStop is not None and rp.finalStop is not None:
        d0 = stop_distance(direction, entry_ref, rp.originalStop)
        if d0 and d0 > 0 and dist and dist > d0:
            rp.widenPct = round((dist - d0) / d0 * 100.0, 2)
            mat = float(settings.get("techniques.tip.geometry_resize_threshold_pct", DEFAULT_MATERIALITY_PCT) or 0)
            rp.severity = "review" if rp.widenPct >= mat else "log"
    # ---- unit loss (explicit units) ------------------------------------------
    if vehicle == "option":
        rp.unitLoss, rp.unitLossBasis, meta = option_unit_loss(
            premium=float(limit), delta=delta, dist=dist, multiplier=float(multiplier),
            option_type=str(option_type or ("put" if direction == "short" else "call")),
            direction=direction, premium_stop_pct=plan.get("premiumStopPct"))
        rp.greeks = {**rp.greeks, **meta}
        rp.stressUnitLoss = round(float(limit) * float(multiplier), 4)
        if rp.unitLossBasis == "delta-linear" and not meta.get("thesisMatch", True):
            rp.decisions.append(f"vehicle/thesis mismatch: a {option_type} for a {direction} thesis")
    else:
        if dist is None:
            rp.unitLoss, rp.unitLossBasis = None, "none"
        elif dist <= 0:
            rp.unitLoss, rp.unitLossBasis = None, "none"
            rp.decisions.append("stop on the wrong side after repair — no size")
        else:
            rp.unitLoss, rp.unitLossBasis = round(float(dist), 4), "stop-distance"
        rp.stressUnitLoss = round(float(entry_ref), 4)      # theoretical maximum: to zero
    # ---- size against B ------------------------------------------------------
    if rp.unitLoss is None:
        rp.reviewRequired = ("no risk estimate: " + str(rp.greeks.get("reason") or "no stop"))
        rp.qty = int(qty_requested)
        rp.invariantOk = None
    else:
        qty, note = size_to_budget(budget=float(budget), unit_loss=rp.unitLoss, qty_requested=int(qty_requested))
        rp.qty = qty
        if note:
            rp.decisions.append(note)
        if qty < 1:
            rp.reviewRequired = note or "no quantity satisfies the risk budget"
            rp.resized = True
            rp.resizeReason = note
        elif qty < int(qty_requested):
            rp.resized = True
            rp.resizeReason = note
        rp.plannedRisk = round(rp.unitLoss * rp.qty, 4)
        rp.invariantOk = (rp.qty * rp.unitLoss <= float(budget) + 1e-9) if rp.qty >= 1 else None
    rp.stressRisk = round(rp.stressUnitLoss * rp.qty, 4)
    if rp.repairs:
        rp.decisions = [*rp.repairs, *rp.decisions]
    rp.enforced = mode == "enforce"
    return final, rp


def revalidate_for_submit(rp_dict: dict, *, new_limit: float) -> tuple[int, dict]:
    """Right before submission a refreshed quote may have IMPROVED the limit
    (never raised — the never-chase rule stands): re-derive the unit loss for
    the new premium and re-apply the invariant. Returns (qty, updated plan
    dict). Shares are unaffected by the limit (the stop distance is the
    unit loss). A plan without an estimate stays review-gated."""
    rp = dict(rp_dict or {})
    if not rp or rp.get("vehicle") != "option" or rp.get("unitLoss") is None:
        return int(rp.get("qty") or 0), rp
    old_limit = float(rp.get("quote", {}).get("limit") or 0) or None
    mult = float(rp.get("multiplier") or 1.0)
    basis = rp.get("unitLossBasis")
    if basis == "delta-linear" and old_limit and old_limit > 0:
        # the estimator is linear in the premium drop, capped by the (new) full premium
        unit = min(float(rp["unitLoss"]), float(new_limit) * mult)
        unit = max(unit, PREMIUM_LOSS_FLOOR * float(new_limit) * mult)
    elif basis == "premium-stop":
        pct = float(rp.get("greeks", {}).get("premiumStopPct") or 0)
        unit = float(new_limit) * mult * pct / 100.0 if pct else float(rp["unitLoss"])
    elif basis == "full-premium":
        unit = float(new_limit) * mult
    else:
        unit = float(rp["unitLoss"])
    qty, note = size_to_budget(budget=float(rp.get("budget") or 0), unit_loss=unit,
                               qty_requested=int(rp.get("qty") or 0))
    rp["unitLoss"] = round(unit, 4)
    rp["stressUnitLoss"] = round(float(new_limit) * mult, 4)
    rp["qty"] = qty
    rp["plannedRisk"] = round(unit * qty, 4)
    rp["stressRisk"] = round(float(new_limit) * mult * qty, 4)
    rp["invariantOk"] = (qty * unit <= float(rp.get("budget") or 0) + 1e-9) if qty >= 1 else None
    rp["quote"] = {**(rp.get("quote") or {}), "limit": float(new_limit), "revalidated": True}
    if note:
        rp["decisions"] = [*(rp.get("decisions") or []), f"at submission: {note}"]
        rp["resized"] = True
    if qty < 1:
        rp["reviewRequired"] = note or "no quantity satisfies the risk budget at submission"
    return qty, rp


# ---------------------------------------------------------------------------
# Post-fill exceptions: a bounded, explicit state machine (design §5). The
# position EXISTS; a stop change may only TIGHTEN immediately; a WIDEN is a
# trim-FIRST sequence with the tighter stop armed until the trim is confirmed.
POST_FILL_PHASES = ("tighten", "trim_pending", "widened", "kept_tight", "reconcile")


def post_fill_decision(*, direction: str, entry_ref: float, current_stop: float | None,
                       proposed_stop: float | None, qty: int, unit_loss_at_proposed: float | None,
                       budget: float) -> dict:
    """What the exception may do when the geometry gate proposes a different
    stop for a FILLED position. Pure.
      tighten     → apply now (journaled)
      keep        → nothing to do
      trim_first  → the widen is admissible only after a trim to `keepQty`
                    (qty × unit_loss_at_proposed ≤ B); the tight stop stays
      reconcile   → no estimate / budget: hold the tight stop, ask a person"""
    if proposed_stop is None or current_stop is None:
        return {"action": "keep", "why": "no stop change proposed"}
    d_cur = stop_distance(direction, entry_ref, current_stop)
    d_new = stop_distance(direction, entry_ref, proposed_stop)
    if d_new is None or d_cur is None:
        return {"action": "keep", "why": "no distances"}
    if d_new <= d_cur + 1e-9:
        return {"action": "tighten" if d_new < d_cur - 1e-9 else "keep",
                "stop": proposed_stop, "why": "a tighter stop reduces risk immediately"}
    if unit_loss_at_proposed is None or unit_loss_at_proposed <= 0 or budget <= 0:
        return {"action": "reconcile", "stop": current_stop,
                "why": "widen requested without a risk estimate or budget — tight stop held, review"}
    keep = int(math.floor(budget / unit_loss_at_proposed + 1e-9))
    if keep >= qty:
        return {"action": "widen", "stop": proposed_stop, "keepQty": qty, "trimQty": 0,
                "why": f"{qty} × ${unit_loss_at_proposed:,.0f} at the wider stop still fits ${budget:,.0f}"}
    if keep < 1:
        return {"action": "reconcile", "stop": current_stop,
                "why": (f"even one unit at the wider stop (${unit_loss_at_proposed:,.0f}) exceeds "
                        f"the ${budget:,.0f} budget — tight stop held, review")}
    return {"action": "trim_first", "stop": proposed_stop, "keepQty": keep, "trimQty": qty - keep,
            "why": (f"widen admissible only for {keep} of {qty} units: trim {qty - keep} FIRST, "
                    f"tight stop {current_stop:g} stays armed until the trim is confirmed")}


def advance_exception(state: dict, event: dict) -> dict:
    """Pure reducer for the trim-first sequence. `state` = {phase, tightStop,
    wideStop, trimQty, keepQty, filledQty, trimOrderId, ...}; `event` = one of
      {"kind": "trim_submitted", "orderId"}     → trim_pending
      {"kind": "trim_filled", "filledQty"}      → widened (full) | trim_pending (partial: bound recomputed by caller)
      {"kind": "trim_rejected"}                 → kept_tight
      {"kind": "trim_unknown"}                  → reconcile (no stop change until reconciled)
      {"kind": "reconciled", "filledQty"}       → widened | kept_tight
    Every transition is recorded in `history` for the journal."""
    st = dict(state or {})
    hist = list(st.get("history") or [])
    kind = event.get("kind")
    phase = st.get("phase") or "trim_pending"
    if kind == "trim_submitted":
        st.update(phase="trim_pending", trimOrderId=event.get("orderId"))
    elif kind == "trim_filled":
        fq = float(event.get("filledQty") or 0)
        st["filledQty"] = fq
        if fq + 1e-9 >= float(st.get("trimQty") or 0):
            st["phase"] = "widened"
        else:
            st["phase"] = "trim_pending"           # partial: the caller recomputes the residual bound
            st["partial"] = True
    elif kind == "trim_rejected":
        st["phase"] = "kept_tight"
    elif kind == "trim_unknown":
        st["phase"] = "reconcile"
    elif kind == "reconciled":
        fq = float(event.get("filledQty") or 0)
        st["filledQty"] = fq
        st["phase"] = "widened" if fq + 1e-9 >= float(st.get("trimQty") or 0) else "kept_tight"
    else:
        raise ValueError(f"unknown exception event {kind!r}")
    hist.append({"from": phase, "to": st["phase"], "event": kind,
                 **({"filledQty": event.get("filledQty")} if "filledQty" in event else {})})
    st["history"] = hist
    st["stopInForce"] = st.get("wideStop") if st["phase"] == "widened" else st.get("tightStop")
    return st


def risk_accounting(position: dict) -> dict:
    """Planned vs stress vs realized for a serialized position, with
    PROVENANCE (C95-02). `plannedRisk` is the risk of the trade that ACTUALLY
    executed — from an ENFORCED plan (its unit loss x the actual quantity), or
    computed from the executed protection plan (entry, live stop, legs) — and
    is marked `unavailable` when neither exists. A shadow / unenforced plan
    describes the size and stop that WOULD have been used: it is reported
    separately under `hypothetical` and is never compared with the realized
    loss as execution slippage."""
    cfg = position.get("config") or {}
    rp = ((position.get("extras") or {}).get("riskPlan")
          or (cfg.get("extras") or {}).get("riskPlan") or cfg.get("riskPlan") or {})
    state = position.get("state") or {}
    realized = float(position.get("realizedPnl") or state.get("realizedPnl") or 0.0)
    legs = [l for l in (position.get("legs") or []) if l]
    qty = sum(abs(float(l.get("qty") or 0)) for l in legs) or None
    entry = position.get("entry") or cfg.get("entry")
    policy = position.get("policy") or cfg.get("policy") or {}
    stop = (policy.get("stop") or {}).get("price")
    if stop is None:
        stop = (state.get("policyState") or {}).get("stop") or (position.get("state") or {}).get("stop")
    is_option = any((l.get("secType") or "STK") == "OPT" for l in legs)
    planned = None
    basis = "unavailable"
    stress = None
    if rp.get("enforced") and rp.get("unitLoss") is not None and qty:
        planned = round(float(rp["unitLoss"]) * qty, 4)
        basis = "enforced-plan"
    elif rp.get("enforced") and rp.get("plannedRisk") is not None and (qty is None or int(rp.get("qty") or 0) == int(qty)):
        planned = float(rp["plannedRisk"])
        basis = "enforced-plan"
    elif not is_option and entry and stop and qty:
        planned = round(abs(float(entry) - float(stop)) * qty, 4)
        basis = "executed-plan"
    if legs:
        stress = round(sum(abs(float(l.get("qty") or 0)) * float(l.get("avgFill") or 0) * float(l.get("multiplier") or (100.0 if (l.get("secType") == "OPT") else 1.0))
                           for l in legs), 4) or None
    if stress is None and rp.get("enforced"):
        stress = rp.get("stressRisk")
    out = {"plannedRisk": planned, "plannedRiskBasis": basis, "stressRisk": stress,
           "realizedPnl": round(realized, 2),
           "realizedLoss": round(-realized, 2) if realized < 0 else 0.0}
    if planned is not None and realized < 0:
        out["slippageVsPlanned"] = round(-realized - float(planned), 2)   # >0: lost more than planned
    if rp and not rp.get("enforced"):
        out["hypothetical"] = {"mode": rp.get("mode"), "enforced": False, "qtyRequested": rp.get("qtyRequested"),
                               "qty": rp.get("qty"), "plannedRisk": rp.get("plannedRisk"),
                               "stressRisk": rp.get("stressRisk"), "resized": rp.get("resized"),
                               "note": "what the gate WOULD have done — research only, not the executed trade"}
    return out
