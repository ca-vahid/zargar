"""The final entry-quality predicate over the CURRENT quote (FC-01, reviewer closure 2026-09-14).

Pure and synchronous: no I/O, no awaits, no mutation. `PlanRunner._entry_guard` calls the technique's
`judge_entry_quote` hook inside `OrderManager.place(before_submit=)`, after the manager's last await and
immediately before `executor.submit`; the hook returns the refusal reason or None. The captured contract
dict is only the fallback when there is NO current observation for the order symbol (or only the delayed
chain row): eligibility is never derived solely from that earlier, mutable warning list.
"""
from __future__ import annotations

from ..domain import Quote


def judge_entry_quote(contract: dict | None, quote: Quote | None, *, max_spread_pct: float,
                      max_age_s: float, refuse_wide: bool, now_ms: int) -> str | None:
    """Refusal reason for an OPTION entry judged on the current cached NBBO, else None.

    - two-sided, uncrossed book required (a one-sided or crossed book is not executable evidence)
    - the observation must be fresher than `max_age_s` (0 = no age limit), by its source timestamp
    - the current spread must be within `max_spread_pct` when `refuse_wide` (the per-arm T5.4 skip)
    - no quote / a delayed chain row: the captured contract's own T5.4 verdict is the only evidence
    """
    if not contract:
        return None
    warnings = [str(w) for w in (contract.get("warnings") or [])]
    captured = next((w for w in warnings if "T5.4 wide spread" in w), None)
    if quote is None or quote.delayed:
        return captured if (refuse_wide and captured) else None
    sym = quote.symbol
    bid, ask = float(quote.bid or 0), float(quote.ask or 0)
    if bid <= 0 or ask <= 0 or ask < bid:
        return f"current book for {sym} is not two-sided (bid {bid:g} / ask {ask:g})"
    ts = int(quote.source_ts or quote.ts or 0)
    if max_age_s > 0 and ts > 0 and (now_ms - ts) > max_age_s * 1000:
        return f"current quote for {sym} is {(now_ms - ts) / 1000:.0f}s old (limit {max_age_s:g}s)"
    sp = float(quote.spread_pct)
    if refuse_wide and sp > float(max_spread_pct):
        return (f"T5.4 wide spread {sp:.1f}% on the current NBBO (bid {bid:g} / ask {ask:g}) "
                f"is over the {float(max_spread_pct):g}% limit")
    return None
