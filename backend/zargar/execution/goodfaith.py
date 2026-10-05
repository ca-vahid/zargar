"""Good-faith guard for CASH accounts (Tips v0.9 V1.7, 2026-10-05; research R4 #7).

A cash account may only pay for a buy with SETTLED money. Buying with the proceeds of a same-day sale (US equities
settle T+1) is allowed, but SELLING that new position before those proceeds settle is a good-faith violation
(IBKR / FINRA Reg T: repeated violations restrict the account to settled cash up front for 90 days).

Assumptions (deliberately simple and conservative; documented in PLATFORM-RULES 2026-10-05):
- Settlement is T+1 business day. Proceeds of any sale made on an EARLIER trading day are settled by today; only
  TODAY's (ET) sales are unsettled. So only positions bought TODAY can be at risk, and the risk ends at the next
  trading day.
- The day's starting settled cash is reconstructed from the book's current cash and today's executions:
  start = cash_now + today's buy cost - today's sell proceeds. Buys spend settled cash first (in fill order); only
  the part a buy could not pay from settled cash, up to the unsettled proceeds available at that moment, is
  "funded by unsettled proceeds".
- Protective exits (stops, premium stops, the venue GTC stop, event/expiry flattens, a rollback, a person's manual
  close) always go: losing more money to avoid a violation is never the trade. They are journaled and alerted.
- Everything else (ladder trims / targets, time stops, source-exit mirrors, the geometry trim) is DEFERRED to the
  next trading day for a position funded by unsettled proceeds.

Pure helpers only; the PositionManager does the I/O.
"""
from __future__ import annotations

PROTECTIVE_KINDS = frozenset({"stop", "premium_stop", "venue_stop", "event", "dte", "expiry", "rollback",
                              "flatten"})


def is_protective(kind: str | None, reason: str | None = None) -> bool:
    """A sale that protects capital (always sent, even when it is a good-faith violation)."""
    k = str(kind or "").lower()
    if k in PROTECTIVE_KINDS:
        return True
    # a person's explicit close is their decision (journaled as a violation risk, never blocked)
    return k == "close" and str(reason or "").lower().startswith("manual")


def unsettled_funded(executions: list[dict], *, cash_now: float) -> dict[str, float]:
    """{buy order id: $ of its cost paid from unsettled same-day proceeds} for TODAY's executions on one book.

    `executions`: [{orderId, side, qty, price, commission, ts}] - today's fills only, any order; `cash_now` = the
    book's current cash (after those fills)."""
    rows = sorted(executions or [], key=lambda e: (e.get("ts") or 0))

    def amount(e: dict) -> float:
        gross = abs(float(e.get("qty") or 0) * float(e.get("price") or 0)) * float(e.get("multiplier") or 1.0)
        fee = float(e.get("commission") or 0)
        return gross + fee if str(e.get("side")).upper() == "BUY" else gross - fee

    buys = sum(amount(e) for e in rows if str(e.get("side")).upper() == "BUY")
    sells = sum(amount(e) for e in rows if str(e.get("side")).upper() == "SELL")
    settled = float(cash_now) + buys - sells          # what the day started with: all settled under T+1
    unsettled = 0.0
    out: dict[str, float] = {}
    for e in rows:
        a = amount(e)
        if str(e.get("side")).upper() == "SELL":
            unsettled += max(0.0, a)
            continue
        use = min(a, max(0.0, settled))
        settled -= use
        short = a - use
        if short > 0.01 and unsettled > 0.0:
            take = min(short, unsettled)
            unsettled -= take
            oid = str(e.get("orderId") or "")
            out[oid] = out.get(oid, 0.0) + take
    return out
