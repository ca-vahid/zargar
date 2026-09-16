"""TMR-02 (2026-09-16): execution-cost diagnostic for a Tips idea - annotate/report only.

Honest execution economics beside feasibility and payoff: what does it cost to buy this
size at the ask and sell it back at the bid RIGHT NOW, on a QUALIFIED quote, with the
desk's real fee basis? The number is the instantaneous round-trip loss - the price of
being wrong immediately - not an expected profit and not a forecast.

    roundTrip = (ask - bid) x multiplier x qty + entryFees + exitFees

Rules (reviewer contract, 2026-09-16):
- only a qualified two-sided quote counts (cohort.qualify_quote: provenance, delayed flag,
  genuine source time, valid bid/ask, option session); stale / crossed / missing / one-sided
  evidence -> every money field is None and `status` says why - never a guess;
- the spread is charged ONCE here; a payoff scenario that already prices its future exit at
  the bid must not subtract it again (`payoffAlreadyAtBid` is informational);
- no midpoint fill is assumed; entry at the ask, exit at the bid;
- fees follow the venue basis: options per contract per side (+ regulatory per contract),
  shares a flat commission per order per side;
- fill-versus-quote: a realised fill compared with the quote the decision saw (limit, ask,
  mid) - the desk's own slippage record, per fill, never averaged into a claim.

Nothing here changes a quantity, a contract, a limit, a stop or a gate.
"""
from __future__ import annotations

import datetime as dt

DIAG_VERSION = "execcost-v1"


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def round_trip(*, quote: dict | None, quote_status: str | None, qty: float, sec_type: str,
               multiplier: float | None = None, fee_per_contract: float = 0.0, reg_per_contract: float = 0.0,
               stock_commission: float = 0.0, now: dt.datetime | None = None) -> dict:
    """The instantaneous round-trip cost of `qty` units on a qualified quote record
    (the cohort's `_snap_quote` shape: bid/ask/bidSize/askSize/sourceTs/receivedTs/
    ageSeconds/source/delayed/sampledAt/eligibility). `quote_status` is the
    qualification verdict ('fresh' | 'stale' | 'ineligible' | 'missing')."""
    is_opt = str(sec_type).upper() in ("OPT", "SPREAD")
    mult = float(multiplier) if multiplier else (100.0 if is_opt else 1.0)
    q = quote or {}
    qty = float(qty or 0)
    out = {"version": DIAG_VERSION, "secType": sec_type, "qty": qty, "multiplier": mult,
           "quoteStatus": quote_status or ("missing" if not q else "unknown"),
           "bid": _f(q.get("bid")), "ask": _f(q.get("ask")),
           "bidSize": _f(q.get("bidSize")) if q.get("bidSize") is not None else None,
           "askSize": _f(q.get("askSize")) if q.get("askSize") is not None else None,
           "sourceTs": q.get("sourceTs"), "receivedTs": q.get("receivedTs"), "sampledAt": q.get("sampledAt"),
           "quoteAgeS": q.get("ageSeconds"), "quoteSource": q.get("source"), "delayed": q.get("delayed"),
           "feeBasis": ("per contract per side" + (" + regulatory per contract" if reg_per_contract else "")) if is_opt
                       else "flat commission per order per side",
           "spreadPerUnit": None, "spread": None, "entryFees": None, "exitFees": None, "roundTrip": None,
           "purchaseValue": None, "costShareOfPurchase": None, "spreadPctOfAsk": None,
           "status": "unknown", "reasons": [], "unknown": [],
           "payoffAlreadyAtBid": "a payoff scenario that exits at the bid already carries this spread - do not subtract it twice",
           "meaning": "cost of buying at the ask and selling at the bid immediately, plus both sides' fees - not expected profit"}
    reasons: list[str] = []
    if not q:
        reasons.append("no quote")
    else:
        if quote_status != "fresh":
            reasons.append(f"quote not qualified ({quote_status})" + (": " + "; ".join(q.get("eligibility") or [])
                                                                       if q.get("eligibility") else ""))
        bid, ask = out["bid"], out["ask"]
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            reasons.append("one-sided or empty quote")
        elif ask < bid:
            reasons.append("crossed quote")
    if qty <= 0:
        reasons.append("no quantity")
    if reasons:
        out["status"] = "unknown"
        out["reasons"] = reasons
        out["unknown"] = ["spread", "entryFees", "exitFees", "roundTrip", "purchaseValue", "costShareOfPurchase"]
        return out
    bid, ask = out["bid"], out["ask"]
    spread_unit = ask - bid
    spread = spread_unit * mult * qty
    if is_opt:
        unit_fee = float(fee_per_contract) + float(reg_per_contract)
        entry_fees = unit_fee * qty
        exit_fees = unit_fee * qty
    else:
        entry_fees = float(stock_commission)
        exit_fees = float(stock_commission)
    purchase = ask * mult * qty
    total = spread + entry_fees + exit_fees
    out.update(spreadPerUnit=round(spread_unit, 4), spread=round(spread, 2), entryFees=round(entry_fees, 2),
               exitFees=round(exit_fees, 2), roundTrip=round(total, 2), purchaseValue=round(purchase, 2),
               costShareOfPurchase=(round(total / purchase, 4) if purchase > 0 else None),
               spreadPctOfAsk=(round(spread_unit / ask, 4) if ask > 0 else None),
               status="known", reasons=[])
    if out["bidSize"] is None and out["askSize"] is None:
        out["unknown"] = ["quotedSize"]
    return out


def fill_vs_quote(*, fill_price: float | None, fill_qty: float | None, limit: float | None,
                  decision_quote: dict | None, sec_type: str, multiplier: float | None = None,
                  side: str = "BUY") -> dict:
    """One realised fill against the quote the decision saw. Positive `vsAsk`/`vsMid`
    means paid MORE than that reference (worse for a buy). Never averaged here."""
    is_opt = str(sec_type).upper() in ("OPT", "SPREAD")
    mult = float(multiplier) if multiplier else (100.0 if is_opt else 1.0)
    q = decision_quote or {}
    bid, ask = _f(q.get("bid")), _f(q.get("ask"))
    mid = (bid + ask) / 2 if (bid and ask and bid > 0 and ask > 0 and ask >= bid) else None
    fp = _f(fill_price)
    fq = _f(fill_qty) or 0.0
    sign = 1.0 if str(side).upper() == "BUY" else -1.0
    out = {"version": DIAG_VERSION, "fillPrice": fp, "fillQty": fq, "limit": _f(limit),
           "quoteBid": bid, "quoteAsk": ask, "quoteMid": (round(mid, 4) if mid is not None else None),
           "quoteSourceTs": q.get("sourceTs"), "quoteSampledAt": q.get("sampledAt"), "quoteStatus": q.get("quoteStatus"),
           "vsLimit": None, "vsAsk": None, "vsMid": None, "vsAskDollars": None, "unknown": []}
    if fp is None or fq <= 0:
        out["unknown"] = ["fill"]
        return out
    if out["limit"] is not None:
        out["vsLimit"] = round(sign * (fp - out["limit"]), 4)
    if ask is not None and ask > 0:
        out["vsAsk"] = round(sign * (fp - ask), 4)
        out["vsAskDollars"] = round(sign * (fp - ask) * mult * fq, 2)
    else:
        out["unknown"].append("ask")
    if mid is not None:
        out["vsMid"] = round(sign * (fp - mid), 4)
    else:
        out["unknown"].append("mid")
    return out


def fees_from_settings(settings) -> dict:
    def g(k, d):
        try:
            v = settings.get(k, d)
        except Exception:
            v = d
        return float(v if v is not None else d)
    return {"feePerContract": g("options.fee_per_contract", 0.0), "regPerContract": g("sim.reg_fee_per_contract", 0.0),
            "stockCommission": g("sim.stock_commission", 0.0)}


def diagnose(eng, *, symbol: str, qty: float, sec_type: str, multiplier: float | None = None,
             kind: str = "execcost") -> dict:
    """Engine convenience: qualify the CURRENT quote for `symbol` through the cohort's
    rules and price the round trip on it. Read-only; never fetches anew."""
    from . import cohort as _cohort
    max_age = 300.0
    try:
        max_age = float(eng.settings.get("techniques.tip.entry_cohort_quote_max_age_seconds", 300.0) or 300.0)
    except Exception:
        pass
    is_opt = str(sec_type).upper() in ("OPT", "SPREAD")
    quote, status = _cohort._snap_quote(eng, symbol, max_age_s=max_age, kind=kind, is_option=is_opt)
    fees = fees_from_settings(eng.settings)
    out = round_trip(quote=quote, quote_status=status, qty=qty, sec_type=sec_type, multiplier=multiplier,
                     fee_per_contract=fees["feePerContract"], reg_per_contract=fees["regPerContract"],
                     stock_commission=fees["stockCommission"])
    out["symbol"] = symbol
    return out
