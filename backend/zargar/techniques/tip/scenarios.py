"""TMR-03 (2026-09-16): time / volatility scenarios for a long option - RESEARCH PROTOTYPE.

The desk's risk estimator (`geometry.py`, delta-linear-v1) answers "what does the stop cost?";
this module answers a different, narrower question for research reports: "how would elapsed
time and a declared change in implied volatility move this contract's value if the underlying
sat still, or reached the target soon versus later?" It is a LOCAL model on the evidence the
desk already holds (spot, strike, days to expiry, implied volatility, a rate assumption) -
Black-Scholes-Merton for a European option without dividends - and it is labelled as such:

- every output carries the model version, the inputs, their sources and timestamps;
- a missing input (no IV, no spot, no DTE) makes the whole scenario `unknown` - never a guess;
- the local approximation is NOT a calibrated forecast for a large move, an event day, an
  early-exercise / dividend situation, or a thin strike: it is arithmetic on today's IV;
- nothing here sizes, gates, times or places anything; the existing risk estimator and the
  execution gate are untouched.
"""
from __future__ import annotations

import datetime as dt
import math

MODEL_VERSION = "bsm-local-v1"
DEFAULT_RATE = 0.04            # a flat risk-free rate assumption; declared on every output
DAY = 365.0


def _n_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _n_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def price_and_greeks(*, spot: float, strike: float, dte_days: float, iv: float, kind: str = "call",
                     rate: float = DEFAULT_RATE) -> dict:
    """Black-Scholes-Merton value and Greeks per ONE unit of underlying (multiply by the
    contract multiplier for dollars per contract). theta is per calendar DAY, vega per
    1.00 (100 points) of IV - divide by 100 for a 1-point change. Raises ValueError on
    inputs the model cannot use."""
    if spot is None or strike is None or dte_days is None or iv is None:
        raise ValueError("spot, strike, dte and iv are all required")
    s, k, t, v = float(spot), float(strike), max(float(dte_days), 0.0) / DAY, float(iv)
    if s <= 0 or k <= 0 or v <= 0:
        raise ValueError("spot, strike and iv must be positive")
    is_call = str(kind).lower().startswith("c")
    if t <= 0:
        intrinsic = max(0.0, (s - k) if is_call else (k - s))
        return {"model": MODEL_VERSION, "value": round(intrinsic, 6), "delta": (1.0 if (is_call and s > k) else (-1.0 if (not is_call and s < k) else 0.0)),
                "gamma": 0.0, "theta": 0.0, "vega": 0.0, "expired": True}
    sq = math.sqrt(t)
    d1 = (math.log(s / k) + (rate + 0.5 * v * v) * t) / (v * sq)
    d2 = d1 - v * sq
    disc = math.exp(-rate * t)
    if is_call:
        value = s * _n_cdf(d1) - k * disc * _n_cdf(d2)
        delta = _n_cdf(d1)
        theta = (-(s * _n_pdf(d1) * v) / (2 * sq) - rate * k * disc * _n_cdf(d2)) / DAY
    else:
        value = k * disc * _n_cdf(-d2) - s * _n_cdf(-d1)
        delta = _n_cdf(d1) - 1.0
        theta = (-(s * _n_pdf(d1) * v) / (2 * sq) + rate * k * disc * _n_cdf(-d2)) / DAY
    gamma = _n_pdf(d1) / (s * v * sq)
    vega = s * _n_pdf(d1) * sq
    return {"model": MODEL_VERSION, "value": round(value, 6), "delta": round(delta, 6), "gamma": round(gamma, 6),
            "theta": round(theta, 6), "vega": round(vega, 6), "expired": False}


def scenario_grid(*, spot: float | None, strike: float | None, dte_days: float | None, iv: float | None,
                  kind: str, premium_paid: float | None, target: float | None = None, multiplier: float = 100.0,
                  qty: float = 1.0, rate: float = DEFAULT_RATE, iv_shifts: tuple[float, ...] = (-0.05, 0.0, 0.05),
                  hold_days: tuple[float, ...] = (1.0, 5.0, 10.0), inputs_meta: dict | None = None) -> dict:
    """A small grid of value changes for ONE long option position:
      - flat: the underlying sits at `spot` after each of `hold_days`, at each IV shift;
      - target soon / later: the underlying reaches `target` after 1 day / after half the
        remaining time, at each IV shift.
    Dollars = (model value - premium paid) x multiplier x qty. `premium_paid` is the
    position's own entry (or the current mid for a candidate); the model's own value at
    t0 is reported beside it so the model's mispricing of TODAY is visible, not hidden."""
    out = {"model": MODEL_VERSION, "rate": rate, "inputs": {"spot": spot, "strike": strike, "dteDays": dte_days, "iv": iv,
                                                         "kind": kind, "premiumPaid": premium_paid, "target": target,
                                                         "multiplier": multiplier, "qty": qty, **(inputs_meta or {})},
           "status": "unknown", "unknown": [], "limits": [
               "European Black-Scholes-Merton without dividends on TODAY's implied volatility - a local approximation, "
               "not a calibrated forecast for a large move, an event day, early exercise or a thin strike",
               "the underlying path between now and the scenario time is ignored (no stop hit is modelled here)",
               "the exit is valued at the model value, not at a bid: execution cost is the execcost diagnostic's job"]}
    missing = [k for k, v in (("spot", spot), ("strike", strike), ("dteDays", dte_days), ("iv", iv), ("premiumPaid", premium_paid)) if v is None]
    if missing:
        out["unknown"] = missing
        return out
    try:
        t0 = price_and_greeks(spot=spot, strike=strike, dte_days=dte_days, iv=iv, kind=kind, rate=rate)
    except ValueError as exc:
        out["unknown"] = [str(exc)]
        return out
    per = float(multiplier) * float(qty)
    out["today"] = {**t0, "premiumPaid": premium_paid, "modelMinusPaid": round(t0["value"] - float(premium_paid), 4),
                    "thetaPerDayDollars": round(t0["theta"] * per, 2), "vegaPerIvPointDollars": round(t0["vega"] / 100.0 * per, 2)}
    rows = []
    for shift in iv_shifts:
        v2 = float(iv) + shift
        if v2 <= 0:
            continue
        for h in hold_days:
            r = price_and_greeks(spot=spot, strike=strike, dte_days=max(0.0, float(dte_days) - h), iv=v2, kind=kind, rate=rate)
            rows.append({"scenario": "flat", "holdDays": h, "ivShift": shift, "iv": round(v2, 4), "spot": spot,
                         "value": r["value"], "pnlDollars": round((r["value"] - float(premium_paid)) * per, 2)})
        if target is not None:
            for label, h in (("target-soon", 1.0), ("target-later", max(1.0, float(dte_days) / 2.0))):
                r = price_and_greeks(spot=target, strike=strike, dte_days=max(0.0, float(dte_days) - h), iv=v2, kind=kind, rate=rate)
                rows.append({"scenario": label, "holdDays": round(h, 1), "ivShift": shift, "iv": round(v2, 4), "spot": target,
                             "value": r["value"], "pnlDollars": round((r["value"] - float(premium_paid)) * per, 2)})
    out["grid"] = rows
    out["status"] = "known"
    out["computedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return out
