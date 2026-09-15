"""Execution READINESS of a proposal card (Tips desk, 2026-09-15).

A card used to carry one prose label ("AUTO: NOT YET EARNED") that conflated
the analyst's opinion, the automatic-trading qualification of the source and
the execution checks. Readiness separates them:

- the analyst's verdict stays on `context.analyst` (an opinion),
- `context.readiness` is the typed, persisted result of the LAST validation:
  state, the actual blocking reasons (each with a code, a label, the evidence
  detail, whether a labeled human override may acknowledge it, and whether it
  only concerns AUTOMATIC approval), the final plan the desk would submit and
  a fingerprint of that plan so a click can prove it approved what it saw.

Pure functions only: no engine, no I/O. The service (`proposals.py::assess`)
gathers the evidence; this module classifies and formats it.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

READINESS_VERSION = "readiness-v1"

# code -> (label, overridable by a labeled human override, scope)
# scope "all"  = blocks EVERY approval (manual included) until refreshed / overridden
# scope "auto" = only explains why the card was not approved automatically
CATALOG: dict[str, tuple[str, bool, str]] = {
    "expired": ("Card expired", False, "all"),
    "source_not_qualified": ("Source has not qualified for automatic trading", False, "auto"),
    "risk_budget_exceeded": ("Planned risk exceeds the approved budget", True, "all"),
    "quote_missing": ("Missing reference quote", False, "all"),
    "quote_stale": ("Stale reference quote", False, "all"),
    "quote_delayed": ("Delayed reference quote", False, "all"),
    "contract_metadata": ("Contract metadata missing", False, "all"),
    "risk_evidence_unavailable": ("Risk evidence unavailable", False, "all"),
    "plan_review": ("Exit plan needs review", True, "all"),
    "integrity_incident": ("Active execution-integrity incident", True, "all"),
    "integrity_unavailable": ("Execution-integrity state unavailable", False, "all"),
    "unsupported_instrument": ("Unsupported instrument - review required", True, "all"),
    "no_enforced_plan": ("No enforced risk plan on the card", False, "all"),
}

# typed evidence problems the risk-plan computation reports (RiskPlan.evidence)
EVIDENCE_CODES = {"quote_missing", "quote_stale", "quote_delayed", "contract_metadata"}


def blocker(code: str, detail: str | None = None) -> dict:
    label, overridable, scope = CATALOG.get(code, (code.replace("_", " "), False, "all"))
    return {"code": code, "label": label, "detail": (str(detail or "")[:300] or None),
            "overridable": bool(overridable), "scope": scope}


def plan_blockers(rp: dict | None, *, enforced_scope: bool) -> list[dict]:
    """The blockers a computed risk plan implies. `rp` is `RiskPlan.to_dict()`
    (or None when nothing was computed under an enforcing scope)."""
    out: list[dict] = []
    if not enforced_scope:
        return out
    if not rp or not rp.get("enforced"):
        return [blocker("no_enforced_plan", "the geometry gate produced no enforced plan for this card")]
    seen: set[str] = set()
    for e in rp.get("evidence") or []:
        code = str((e or {}).get("code") or "")
        if code in EVIDENCE_CODES and code not in seen:
            seen.add(code)
            out.append(blocker(code, (e or {}).get("detail")))
    review = rp.get("reviewRequired")
    if review:
        cls = rp.get("reviewClass")
        if cls == "budget":
            out.append(blocker("risk_budget_exceeded", rp.get("resizeReason") or review))
        elif cls == "plan":
            out.append(blocker("plan_review", review))
        elif not seen:
            # an evidence-class review with no typed problem = the computation
            # itself could not produce evidence (never admission by absence)
            out.append(blocker("risk_evidence_unavailable", review))
    return out


def classify_refusal(reason: str | None) -> str | None:
    """A code for the prose reasons the AUTOMATED paths already produce
    (kept so a refused card shows the same typed state as a refreshed one)."""
    r = str(reason or "").lower()
    if not r:
        return None
    if "execution-integrity" in r:
        return "integrity_unavailable" if "unavailable" in r else "integrity_incident"
    if "not yet earned" in r or "not earned" in r or "hit rate" in r:
        return "source_not_qualified"
    if "risk evidence unavailable" in r:
        return "risk_evidence_unavailable"
    if "no enforced risk plan" in r:
        return "no_enforced_plan"
    if "vehicle not covered" in r or "spread vehicle" in r:
        return "unsupported_instrument"
    if "no live" in r and "quote" in r:
        return "quote_missing"
    if "risk budget" in r:
        return "risk_budget_exceeded"
    return None


def plan_summary(pdict: dict, rp: dict | None, *, limit: float | None, qty: float) -> dict:
    """The FINAL plan a click would submit, in the fields a person needs to
    judge it (never the analyst's narrative - that stays on `context.analyst`)."""
    ctx = pdict.get("context") or {}
    sizing = ctx.get("sizing") or {}
    rp = rp or {}
    sec_type = pdict.get("secType")
    mult = float(rp.get("multiplier") or (100.0 if sec_type in ("OPT", "SPREAD") else 1.0))
    lim = float(limit) if limit else (float(pdict.get("limitPrice") or 0) or None)
    unit = rp.get("unitLoss")
    planned = (round(float(unit) * float(qty), 2) if unit is not None and rp.get("enforced") else None)
    q = rp.get("quote") or {}
    return {
        "qty": int(qty),
        "planQty": int(rp.get("qty") or 0) if rp else None,
        "requestedQty": int(rp.get("qtyRequested") or 0) if rp else None,
        "limit": lim,
        "cost": (round(lim * float(qty) * mult, 2) if lim else None),
        "allocationLimit": sizing.get("budget"),          # "purchase allocation limit"
        "riskBudget": rp.get("budget"),
        "riskBudgetSource": rp.get("budgetSource"),
        "unitLoss": unit,
        "unitLossBasis": rp.get("unitLossBasis"),
        "plannedRisk": planned,
        "stressRisk": (round(float(rp.get("stressUnitLoss") or 0) * float(qty), 2)
                       if rp.get("stressUnitLoss") else None),
        "withinBudget": (None if planned is None or not rp.get("budget")
                         else bool(planned <= float(rp["budget"]) + 1e-6)),
        "finalStop": rp.get("finalStop"),
        "originalStop": rp.get("originalStop"),
        "quoteAgeS": q.get("ageS", q.get("underlyingAgeS")),
        "quoteSource": q.get("source") or q.get("underlyingSource"),
        "quoteDelayed": q.get("delayed", q.get("underlyingDelayed")),
        "adjustments": list(rp.get("decisions") or []),
        "estimatorVersion": rp.get("estimatorVersion"),
        "multiplier": mult,
    }


def fingerprint(plan: dict, blockers: list[dict]) -> str:
    """What a click must match: the plan's GEOMETRY (final stop, the admissible
    quantity) and the blocker set. The limit is deliberately excluded: the
    service only ever LOWERS it (a live ask may improve the entry, never raise
    it), so the submitted limit is always at or below the one displayed; a
    change that matters - a moved stop, a different size, a new failed check -
    changes this value and the click is refused. The requested quantity is
    not part of it either: "half size" halves the same displayed plan."""
    core = {"finalStop": plan.get("finalStop"), "planQty": plan.get("planQty"),
            "blockers": sorted({b["code"] for b in blockers})}
    raw = json.dumps(core, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build(*, pdict: dict, rp: dict | None, blockers: list[dict], info: list[dict],
          limit: float | None, qty: float, scope_mode: str | None, phase: str, via: str,
          valid_for_s: float, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    hard = [b for b in blockers if b["scope"] == "all"]
    if any(b["code"] == "expired" for b in hard):
        state = "expired"
    elif hard:
        state = "blocked"
    elif scope_mode == "enforce" and rp and rp.get("enforced"):
        state = "ready"
    else:
        # shadow / off gate or a non-Practice book: nothing was enforced, the
        # card is a human decision on the evidence shown (never claims "ready")
        state = "unverified"
    plan = plan_summary(pdict, rp, limit=limit, qty=qty)
    return {
        "version": READINESS_VERSION,
        "state": state,
        "blockers": hard,
        "info": info,
        "overridable": bool(hard) and all(b["overridable"] for b in hard),
        "plan": plan,
        "fingerprint": fingerprint(plan, hard),
        "computedAt": now.isoformat(),
        "validUntil": (now + dt.timedelta(seconds=float(valid_for_s))).isoformat(),
        "phase": phase,
        "via": via,
        "scopeMode": scope_mode,
    }


def validate_override(readiness: dict, override: dict | None) -> tuple[list[dict], str]:
    """A labeled override must name EVERY blocker it accepts and carry a
    substantive reason; a non-overridable blocker cannot be accepted at all.
    Returns (accepted blockers, reason) or raises ValueError."""
    hard = list(readiness.get("blockers") or [])
    if not hard:
        return [], ""
    if not override:
        raise ValueError("blocked: " + "; ".join(f"{b['label']}" + (f" ({b['detail']})" if b.get("detail") else "")
                                                 for b in hard)
                         + " - refresh the card, or submit an explicit override naming each check")
    checks = {str(c) for c in (override.get("checks") or [])}
    reason = str(override.get("reason") or "").strip()
    non = [b for b in hard if not b["overridable"]]
    if non:
        raise ValueError("cannot be overridden: " + "; ".join(b["label"] for b in non))
    missing = [b["code"] for b in hard if b["code"] not in checks]
    if missing:
        raise ValueError("the override must acknowledge every failed check: " + ", ".join(missing))
    unknown = checks - {b["code"] for b in hard}
    if unknown:
        raise ValueError("override names checks that are not failing: " + ", ".join(sorted(unknown)))
    if len(reason) < 20:
        raise ValueError("an override needs a substantive reason (>= 20 characters)")
    return hard, reason[:400]
