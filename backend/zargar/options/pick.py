"""Premium-targeted strike selection (platform options layer; 2026-09-03, Team2 desk — PLAN E7).

`select_by_premium(chain, spot, direction, *, target_premium, premium_floor, expiry, today,
is_0dte)` walks OUT of the money from the first strike beyond spot and returns the first
contract whose ASK is at or under `target_premium` but not under `premium_floor`. If the first
contract under the target is already under the floor, the previous (dearer) strike is taken
when its ask is within 1.5× the target; otherwise nothing in the wanted band exists → None.
This is how Team2 expresses "the ~$0.50 contract" (METHOD V1/F5); EM's just-OTM picker in
`technique/options.py::select_contract` is untouched — this module only reuses its
`ContractPick` shape so downstream code (reprice, risk, UI) sees the same fields.
"""
from __future__ import annotations

import datetime as dt

from ..technique.options import ContractPick, ELEVATED_IV, LOW_DELTA, MAX_SPREAD_PCT, MIN_OPEN_INTEREST, MIN_VOLUME


def select_by_premium(chain: list[dict], spot: float, direction: str, *, target_premium: float,
                      premium_floor: float, expiry: str, today: dt.date, is_0dte: bool,
                      max_over_target: float = 1.5) -> ContractPick | None:
    want = "call" if direction == "long" else "put"
    rows = [c for c in chain if (c.get("option_type") or "").lower() == want]
    if want == "call":
        otm = sorted((c for c in rows if float(c.get("strike", 0)) > spot), key=lambda c: float(c["strike"]))
    else:
        otm = sorted((c for c in rows if float(c.get("strike", 0)) < spot), key=lambda c: -float(c["strike"]))
    if not otm:
        return None
    chosen = None
    prev = None
    for c in otm:
        ask = float(c.get("ask") or 0.0)
        if ask <= 0:
            continue                                   # no quote → cannot judge the premium
        if ask <= target_premium:
            if ask >= premium_floor:
                chosen = c
            elif prev is not None and float(prev.get("ask") or 0.0) <= target_premium * max_over_target:
                chosen = prev
            break
        prev = c
    if chosen is None:
        return None
    c = chosen
    bid = float(c.get("bid") or 0.0)
    ask = float(c.get("ask") or 0.0)
    mid = (bid + ask) / 2 if (bid or ask) else 0.0
    spread_pct = ((ask - bid) / mid * 100) if mid > 0 else 999.0
    g = c.get("greeks") or {}
    delta, theta, iv = g.get("delta"), g.get("theta"), g.get("mid_iv")
    try:
        dte = (dt.date.fromisoformat(expiry) - today).days
    except ValueError:
        dte = -1
    warnings: list[str] = [f"V1 premium-targeted strike: ask ${ask:.2f} for target ${target_premium:.2f}"]
    if spread_pct > MAX_SPREAD_PCT:
        warnings.append(f"T5.4 wide spread {spread_pct:.1f}% (bid {bid} / ask {ask})")
    if int(c.get("open_interest") or 0) < MIN_OPEN_INTEREST:
        warnings.append(f"T5.4 thin open interest {c.get('open_interest')}")
    if int(c.get("volume") or 0) < MIN_VOLUME:
        warnings.append(f"T5.4 low volume today {c.get('volume')}")
    if delta is not None and abs(float(delta)) < LOW_DELTA:
        warnings.append(f"T5.4 low delta {float(delta):.2f}")
    if iv is not None and float(iv) >= ELEVATED_IV:
        warnings.append(f"T5.3 elevated IV {float(iv):.2f}")
    if is_0dte:
        warnings.append("0DTE: premium-targeted, flatten by the technique's flatten time")
    rules = sorted({"V1", *(w.split()[0] for w in warnings)})
    return ContractPick(
        symbol=str(c.get("symbol")), underlying=str(c.get("underlying") or ""), expiry=expiry,
        strike=float(c["strike"]), option_type=want, bid=bid, ask=ask, mid=mid, spread_pct=spread_pct,
        volume=int(c.get("volume") or 0), open_interest=int(c.get("open_interest") or 0),
        delta=float(delta) if delta is not None else None, theta=float(theta) if theta is not None else None,
        iv=float(iv) if iv is not None else None, dte=dte, is_0dte=is_0dte, warnings=warnings, rules=rules,
    )


__all__ = ["select_by_premium"]
