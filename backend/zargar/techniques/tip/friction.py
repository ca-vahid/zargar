"""All-in friction and exposure diagnostics (S21-04, 2026-09-21 review). Pure arithmetic on recorded numbers.

* `all_in_friction`: entry fees paid + exit fees at the same per-unit basis + the spread at the fill-time (or decision)
  quote, in dollars and as a share of the debit - a FRICTION diagnostic for an immediate round trip at that quote, never a
  prediction of the eventual exit. Unknown inputs stay unknown (`unknown` lists them); nothing is invented.
* `target_to_fill`: for a target exit, the shortfall between the target price and the realised fill - arithmetic that
  measures how far the market exit landed from the touched target, NOT a claim that a resting limit at the target would
  have filled.
* `same_underlying_exposure`: the other open lots on the same underlying in the same book, so a card is judged on the
  combined position, not alone.
"""
from __future__ import annotations

FRICTION_VERSION = "friction-v1"


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def all_in_friction(*, qty: float, fill_price: float, multiplier: float, entry_fees: float | None,
                    fee_per_unit: float | None, bid: float | None, ask: float | None) -> dict:
    """Dollars and percent of the debit for entry fees + estimated exit fees + the quoted spread on the full size."""
    q, fp, m = float(qty or 0), _f(fill_price), float(multiplier or 1)
    unknown: list[str] = []
    debit = (fp * q * m) if (fp is not None and q > 0) else None
    if debit is None:
        unknown.append("debit")
    ef = _f(entry_fees)
    if ef is None:
        unknown.append("entryFees")
    xf = (float(fee_per_unit) * q) if fee_per_unit is not None else None
    if xf is None:
        unknown.append("exitFeesEstimate")
    b, a = _f(bid), _f(ask)
    spread = ((a - b) * q * m) if (b is not None and a is not None and a >= b > 0) else None
    if spread is None:
        unknown.append("spread")
    parts = [x for x in (ef, xf, spread) if x is not None]
    total = sum(parts) if parts and not unknown[:0] else (sum(parts) if parts else None)
    pct = (total / debit * 100.0) if (total is not None and debit) else None
    return {"version": FRICTION_VERSION, "debit": round(debit, 2) if debit is not None else None,
            "entryFees": round(ef, 2) if ef is not None else None,
            "exitFeesEstimate": round(xf, 2) if xf is not None else None,
            "spreadAtQuote": round(spread, 2) if spread is not None else None,
            "allInDollars": round(total, 2) if total is not None else None,
            "allInPctOfDebit": round(pct, 1) if pct is not None else None,
            "complete": not unknown, "unknown": unknown,
            "basis": "entry fees paid + exit fees at the same per-unit basis + (ask-bid) x size at the quoted price; "
                     "an immediate-round-trip friction diagnostic, not a forecast of the exit"}


def target_to_fill(*, target: float | None, fill_price: float | None, qty: float, multiplier: float,
                   direction: str = "long") -> dict:
    """Shortfall of a target exit's realised fill against the touched target price (positive = fill worse than target)."""
    t, fp = _f(target), _f(fill_price)
    if t is None or fp is None:
        return {"targetPrice": t, "fillPrice": fp, "shortfallPerUnit": None, "shortfallDollars": None,
                "unknown": [k for k, v in (("target", t), ("fill", fp)) if v is None]}
    sign = -1.0 if str(direction) == "short" else 1.0
    per = sign * (t - fp)
    return {"targetPrice": t, "fillPrice": fp, "shortfallPerUnit": round(per, 4),
            "shortfallDollars": round(per * float(qty or 0) * float(multiplier or 1), 2), "unknown": [],
            "claim": "arithmetic between the touched target and the realised fill; not evidence that a limit at the target would have filled"}


def same_underlying_exposure(open_lots: list[dict], *, underlying: str, exclude_symbol: str | None = None) -> dict:
    """Other open lots on the same underlying (options and shares alike): count, cost, symbols."""
    u = str(underlying or "").upper()
    others = [lot for lot in open_lots
              if _underlying_of(str(lot.get("symbol") or "")) == u and str(lot.get("symbol") or "") != (exclude_symbol or "")]
    return {"underlying": u, "otherLots": len(others),
            "otherCost": round(sum(float(lot.get("cost") or 0) for lot in others), 2),
            "symbols": sorted({str(lot.get("symbol")) for lot in others})}


def _underlying_of(symbol: str) -> str:
    s = symbol.strip().upper()
    if len(s) > 8 and s[-9] in ("C", "P") and s[-8:].isdigit() and s[-15:-9].isdigit():
        return s[:-15]
    return s


def rung_shortfall(*, is_option: bool, target: float | None, fill_price: float | None, underlying_at_fill: float | None,
                   qty: float, direction: str = "long") -> dict:
    """ADV-01 (2026-09-23): the target-to-fill shortfall of one exit rung in the units the target was set in.
    A share rung compares the target with the share fill. An OPTION rung's ladder target is an UNDERLYING price, so it is
    compared with the underlying's price at the fill minute - never with the premium (that produced $33,105 "shortfalls");
    its dollar value is not computable without the contract's delta, so it stays None and says so."""
    if not is_option:
        d = target_to_fill(target=target, fill_price=fill_price, qty=qty, multiplier=1.0, direction=direction)
        return {**d, "basis": "share fill vs target"}
    t, u = _f(target), _f(underlying_at_fill)
    if t is None or u is None:
        return {"targetPrice": t, "underlyingAtFill": u, "shortfallPerUnit": None, "shortfallDollars": None,
                "basis": "option rung: underlying at fill vs underlying target",
                "unknown": [k for k, v in (("target", t), ("underlyingAtFill", u)) if v is None]}
    sign = -1.0 if str(direction) == "short" else 1.0
    return {"targetPrice": t, "underlyingAtFill": u, "shortfallPerUnit": round(sign * (t - u), 4), "shortfallDollars": None,
            "basis": "option rung: underlying at fill vs underlying target; dollars need the contract's delta (not claimed)",
            "unknown": []}
