"""What a fixed-target exit actually cost between the signal and the fill (`exit-latency-v1`, 2026-09-21).

DIAGNOSTIC ONLY. Nothing here changes an exit, a target, a price or a time. Protective exits are never
delayed by it and never consult it.

The case that prompted it: on 2026-09-21 the IREN TP2 exit was decided when the contract's bid was
2.42 and filled at 2.37 about 1.6 seconds later. Two contracts, five cents, ten dollars gross. The
temptation is to call that ten dollars recoverable. It is not, and this module is built to resist
exactly that: a price seen once is not a price you could have taken. Whether 2.42 was reachable
depends on whether that bid still stood when an order could have arrived, and for how much size -
questions that need CONTEMPORANEOUS evidence, because quotes are never journalled.

So the ledger records the stages that are durable (signal, evidence, pending, dispatch, fill) and
answers the money question only from evidence captured at the time. Where that evidence does not
exist, the answer is `unknown`, and unknown is a result, not a gap to be filled with the best price
in sight.
"""
from __future__ import annotations

VERSION = "exit-latency-v1"

# What a real order needs before it can be at the venue: the decision has to be turned into an intent,
# risk-checked, routed and acknowledged. Anything quoted inside this window was never actually available
# to us. Frozen 2026-09-21 from the observed dispatch path (order created -> filled in ~1.6 s).
REACHABLE_AFTER_MS = 750


def stages(*, signal_ts=None, evidence_ts=None, decided_ts=None, pending_ts=None,
           dispatch_ts=None, fill_ts=None) -> dict:
    """The exit's timeline, and the gaps between its steps. Missing stamps stay None: a stage that was
    never recorded is not the same as a stage that took no time."""
    order = [("signal", signal_ts), ("evidence", evidence_ts), ("decided", decided_ts),
             ("pending", pending_ts), ("dispatch", dispatch_ts), ("fill", fill_ts)]
    out = {"version": VERSION, "stamps": {k: (int(v) if v is not None else None) for k, v in order}, "gapsMs": {}}
    known = [(k, int(v)) for k, v in order if v is not None]
    for (k1, t1), (k2, t2) in zip(known, known[1:]):
        out["gapsMs"][f"{k1}->{k2}"] = t2 - t1
    if known and len(known) > 1:
        out["totalMs"] = known[-1][1] - known[0][1]
        out["spans"] = f"{known[0][0]} to {known[-1][0]}"
    return out


def realizable(observations, *, side: str, qty: float, after_ms: int,
               reachable_after_ms: int = REACHABLE_AFTER_MS) -> dict:
    """The best price that was genuinely REACHABLE for this quantity, from contemporaneous quotes.

    `observations` = [{ts, bid, ask, bidSize, askSize}] captured at the time - not reconstructed later.
    A sell is judged at the bid and a buy at the ask, only from observations at least
    `reachable_after_ms` after the signal, and only while the displayed size covers the quantity.

    Three deliberate refusals:
      * the best price in the whole window is NOT the answer; only what stood after the delay counts;
      * an observation without a size cannot support a claim about quantity, so it is counted apart
        and the depth answer stays unknown rather than assumed;
      * no observations at all means `unknown`. It never falls back to the fill price to look tidy.
    """
    rows = sorted([o for o in (observations or []) if o and o.get("ts") is not None], key=lambda o: int(o["ts"]))
    cutoff = int(after_ms) + int(reachable_after_ms)
    eligible = [o for o in rows if int(o["ts"]) >= cutoff]
    price_key, size_key = ("bid", "bidSize") if side.upper() == "SELL" else ("ask", "askSize")
    usable, sized, unsized = [], [], 0
    for o in eligible:
        px = o.get(price_key)
        if px is None or float(px) <= 0:
            continue
        usable.append(o)
        sz = o.get(size_key)
        if sz is None:
            unsized += 1
        elif float(sz) >= float(qty):
            sized.append(o)
    out = {"version": VERSION, "side": side.upper(), "qty": float(qty), "reachableAfterMs": int(reachable_after_ms),
           "observations": len(rows), "eligibleObservations": len(eligible), "pricedObservations": len(usable),
           "observationsWithoutSize": unsized}
    if not rows:
        out.update({"status": "unknown", "why": "no contemporaneous quote evidence was captured for this exit; "
                                                "quotes are never journalled, so this cannot be reconstructed later",
                    "bestReachable": None, "bestReachableWithSize": None})
        return out
    if not usable:
        out.update({"status": "unknown", "why": f"no priced observation at least {reachable_after_ms} ms after the signal",
                    "bestReachable": None, "bestReachableWithSize": None})
        return out
    best = max(usable, key=lambda o: float(o[price_key])) if side.upper() == "SELL" else min(usable, key=lambda o: float(o[price_key]))
    best_sized = None
    if sized:
        best_sized = max(sized, key=lambda o: float(o[price_key])) if side.upper() == "SELL" else min(sized, key=lambda o: float(o[price_key]))
    out.update({"status": "measured",
                "bestReachable": {"price": float(best[price_key]), "ts": int(best["ts"])},
                "bestReachableWithSize": ({"price": float(best_sized[price_key]), "ts": int(best_sized["ts"]),
                                           "size": float(best_sized[size_key])} if best_sized else None),
                "depth": ("covered" if best_sized else ("unknown" if unsized else "insufficient")),
                "why": ("the best price that still stood once an order could have reached the venue"
                        if best_sized else
                        "a price stood, but nothing shows it could absorb this quantity - depth unknown")})
    return out


def cost(fill_price, realizable_out: dict, *, qty: float, multiplier: float = 1.0) -> dict:
    """The difference between what we got and what was reachable - stated as a measurement, not a loss.

    A positive `gross` means a better price was genuinely standing after the dispatch delay. It is NOT
    money the desk would have kept: taking it needs the order to have been there, the size to have been
    there, and the same decision to have been made a moment earlier.
    """
    if fill_price is None or realizable_out.get("status") != "measured":
        return {"status": "unknown", "why": realizable_out.get("why") or "no fill price", "grossDifference": None}
    ref = (realizable_out.get("bestReachableWithSize") or realizable_out.get("bestReachable") or {}).get("price")
    if ref is None:
        return {"status": "unknown", "why": "no reachable reference price", "grossDifference": None}
    per_unit = float(ref) - float(fill_price)
    return {"status": "measured", "fillPrice": float(fill_price), "reachablePrice": float(ref),
            "perUnit": round(per_unit, 4), "grossDifference": round(per_unit * float(qty) * float(multiplier), 2),
            "depth": realizable_out.get("depth"),
            "note": "a measured difference, not recoverable money: it assumes the same decision, an order already at "
                    "the venue and that size standing - none of which is established by the price alone"}
