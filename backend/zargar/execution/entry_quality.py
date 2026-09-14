"""The final entry-quality predicate over the CURRENT quote (FC-01 / FC-02, reviewer closure 2026-09-14).

Pure and synchronous: no I/O, no awaits, no mutation. `PlanRunner._entry_guard` calls the technique's
`judge_entry_quote` hook inside `OrderManager.place(before_submit=)`, after the manager's last await and
immediately before `executor.submit`; the hook returns the refusal reason or None.

Contract (FC-02): an OPTION entry needs CURRENT executable evidence at dispatch. The captured contract
dict (the earlier refresh) never substitutes for it - a clean old warning list cannot admit an entry whose
current observation disappeared or was replaced by a delayed row after RiskGate looked. The freshness limit
is the ENTRY policy (`risk.stale_quote_seconds`, the same number RiskGate applies), never an exit-mark age.
"""
from __future__ import annotations

from ..domain import Quote


def judge_entry_quote(contract: dict | None, quote: Quote | None, *, max_spread_pct: float,
                      max_age_s: float, refuse_wide: bool, now_ms: int, require_current: bool = True) -> str | None:
    """Refusal reason for an OPTION entry judged on the current cached NBBO, else None.

    - no quote at all: refused (there is no current executable evidence for the order symbol)
    - `require_current` (a real-time option source is configured, `RiskGate.live_option_quotes_expected`):
      a delayed chain row is refused; the age is the SOURCE age; a quote without a timestamp is refused
    - otherwise (no real-time source configured, the chain is the only book): the chain row is judged
      like RiskGate judges it - by its receipt age - and its spread still applies
    - two-sided, uncrossed book required; the current spread must be within `max_spread_pct` when
      `refuse_wide` (the per-arm T5.4 skip)
    - shares entries carry no contract and are not judged here
    """
    if not contract:
        return None
    if quote is None:
        return f"no current quote for {contract.get('symbol') or 'the contract'} - current executable evidence is required"
    sym = quote.symbol
    if require_current and quote.delayed:
        return (f"current quote for {sym} is the delayed chain row (source ~{_age(now_ms, quote.source_ts):.0f}s old) "
                f"- not current executable evidence")
    bid, ask = float(quote.bid or 0), float(quote.ask or 0)
    if bid <= 0 or ask <= 0 or ask < bid:
        return f"current book for {sym} is not two-sided (bid {bid:g} / ask {ask:g})"
    ts = int((quote.source_ts if require_current else 0) or quote.ts or 0)
    if ts <= 0:
        return f"current quote for {sym} carries no timestamp - not executable evidence"
    age = _age(now_ms, ts)
    if max_age_s > 0 and age > max_age_s:
        return f"current quote for {sym} is {age:.0f}s old (entry limit {max_age_s:g}s)"
    sp = float(quote.spread_pct)
    if refuse_wide and sp > float(max_spread_pct):
        return (f"T5.4 wide spread {sp:.1f}% on the current NBBO (bid {bid:g} / ask {ask:g}) "
                f"is over the {float(max_spread_pct):g}% limit")
    return None


def _age(now_ms: int, ts: int | None) -> float:
    return max(0.0, (now_ms - int(ts or 0)) / 1000.0) if ts else 0.0
