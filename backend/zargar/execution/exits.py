"""Pure exit logic — no broker, no I/O, fully unit-testable.

The decision (stop → ladder → flatten) and the *reduce-only* intent that carries
it out. Reduce-only is the safety guarantee: an exit built here always sets
`reduce_only=True`, so RiskGate runs its safety-only list and the position can
always be closed — even with the kill switch on (per `risk.halt_allows_exits`)
or after the daily-loss halt.
"""
from __future__ import annotations

from dataclasses import dataclass

from .book import EXIT_LADDER, EXIT_REPRICE_BARS

# how a single-contract options position exits when the 30/40/15 ladder can't split
_SINGLE_EXIT_INDEX = {"tp1": 0, "tp2": 1, "tp3": 2}


@dataclass
class ExitDecision:
    kind: str                 # tp1 | tp2 | tp3 | stop | flatten
    qty: float
    new_trims_done: int       # what the caller should set trade.trims_done to
    reason: str = ""


def plan_exit(trade, bar, *, close_ms: int, flatten_minutes: int,
              ladder: tuple[float, ...] = EXIT_LADDER, single_exit: str = "tp2",
              stop_on: str = "low", direction: str | None = None) -> ExitDecision | None:
    """Decide the next exit on a *closed* bar. One exit per bar. Returns None when
    nothing should be sent (nothing hit, or a working exit is still pending).

    `stop_on`: "low" = the bar traded to the stop (touch); "close" = the bar
    CLOSED through it (the book's watch-the-reaction stop, T4.3 — a wick through
    the level is a test; the quote-breach brake covers a crash in between).

    `trade` needs: remaining, filled_qty, trims_done, targets, stop, sec_type,
    pending_exit_qty (all present on execution.book.ManagedTrade and the
    technique Trade)."""
    if trade.remaining <= 0:
        return None
    if getattr(trade, "pending_exit_qty", 0.0) > 1e-9:
        return None                                   # wait for the working exit to resolve
    short = (direction or getattr(trade, "direction", "long")) == "short"
    # 1) stop first — conservative
    ref = bar.close if stop_on == "close" else (bar.high if short else bar.low)
    if (ref >= trade.stop) if short else (ref <= trade.stop):
        return ExitDecision("stop", trade.remaining, len(trade.targets),
                            "bar closed through the stop" if stop_on == "close" else "price traded to the stop")
    # 2) flatten before the close — no overnight risk
    flatten_at = close_ms - flatten_minutes * 60_000
    if bar.ts >= flatten_at:
        return ExitDecision("flatten", trade.remaining, len(trade.targets), "flatten before the close")
    # 3) the 30/40/15 scale-out ladder at the targets
    k = trade.trims_done
    if k < len(trade.targets) and ((bar.low <= trade.targets[k]) if short else (bar.high >= trade.targets[k])):
        single_contract = trade.sec_type == "OPT" and trade.filled_qty < 3
        if single_contract:
            want = _SINGLE_EXIT_INDEX.get(single_exit, 1)
            if k >= want:
                return ExitDecision(f"tp{k + 1}", trade.remaining, len(trade.targets),
                                    f"single contract exits in full at {single_exit.upper()}")
            return None                               # advance handled by caller via next_trim below
        share = ladder[k] if k < len(ladder) else 1.0
        qty = float(int(round(trade.filled_qty * share)))
        qty = min(qty, trade.remaining)
        if k == len(trade.targets) - 1 and trade.remaining - qty < 1:
            qty = trade.remaining                     # no fractional runner left behind
        if qty >= 1:
            return ExitDecision(f"tp{k + 1}", qty, k + 1, f"scale out {int(share * 100)}% at TP{k + 1}")
        return ExitDecision(f"tp{k + 1}", 0.0, k + 1, "target reached, nothing to trim")
    return None


def quote_stop_breach(trade, last: float, *, excess_r: float = 0.25, direction: str | None = None) -> str | None:
    """Intra-minute disaster check on the *underlying's live quote*: the price is
    not merely at the stop (bar-close logic owns that call, per the book's
    mental-stop discipline) but **decisively through it** — beyond the stop by
    `excess_r` × the planned risk (entry − stop). Exits can only become earlier
    and safer through this rule, never entries — so it needs no historical data
    to validate. Returns the reason string, or None."""
    if last is None or last <= 0 or trade.remaining <= 0:
        return None
    if getattr(trade, "pending_exit_qty", 0.0) > 1e-9:
        return None                                   # an exit is already working
    short = (direction or getattr(trade, "direction", "long")) == "short"
    risk = max(abs(float(trade.entry) - float(trade.stop)), 1e-9)
    line = float(trade.stop) + excess_r * risk if short else float(trade.stop) - excess_r * risk
    if (last >= line) if short else (last <= line):
        return (f"live quote {last:.4f} is decisively through the stop {trade.stop:.4f} "
                f"(> {excess_r:g}R beyond) — exiting now instead of waiting for the bar close")
    return None


def premium_stop_breach(trade, bid: float | None, *, stop_pct: float) -> str | None:
    """Options only: the position's own premium has bled past `stop_pct`% of what
    was paid — theta/IV can do this while the underlying never touches its stop
    (the gap the underlying-based ladder cannot see). Exit-only, like the quote
    stop. Returns the reason, or None."""
    if stop_pct <= 0 or getattr(trade, "sec_type", "STK") != "OPT":
        return None
    if bid is None or bid < 0 or trade.remaining <= 0:   # bid == 0 IS a (total) bleed
        return None
    if getattr(trade, "pending_exit_qty", 0.0) > 1e-9:
        return None
    paid = float(getattr(trade, "avg_fill", 0) or 0)
    if paid <= 0:
        return None
    floor = paid * (1.0 - stop_pct / 100.0)
    if bid <= floor:
        lost = (paid - bid) / paid * 100.0
        return (f"premium stop: bid {bid:.2f} is {lost:.0f}% below the {paid:.2f} paid "
                f"(limit {stop_pct:g}%) — theta/IV bleed the underlying stop cannot see")
    return None


def next_trim_only(trade, bar) -> bool:
    """A single-contract position that reached a target below its exit target:
    advance trims_done but send nothing. Returns True when the caller should
    bump trims_done without an order."""
    k = trade.trims_done
    short = getattr(trade, "direction", "long") == "short"
    if k >= len(trade.targets) or ((bar.low > trade.targets[k]) if short else (bar.high < trade.targets[k])):
        return False
    if trade.sec_type == "OPT" and trade.filled_qty < 3:
        want = _SINGLE_EXIT_INDEX.get(getattr(trade, "single_exit", "tp2"), 1)
        return k < want
    return False


def stale_working_exit(trade, bar_index: int, *, reprice_bars: int = EXIT_REPRICE_BARS) -> dict | None:
    """The working exit that has not filled within `reprice_bars` closed bars —
    the price has moved past our limit. Returns the exit record to cancel and
    re-send at market, or None."""
    for e in trade.exits:
        st = e.get("status")
        if st in ("REJECTED", "REJECTED_RISK", "CANCELLED", "EXPIRED", "ERROR", "FILLED"):
            continue
        if not e.get("orderId"):
            continue
        remaining = float(e.get("qty") or 0) - float(e.get("filledQty") or 0)
        if remaining <= 1e-9:
            continue
        sent_at = e.get("barIndex")
        if sent_at is not None and bar_index - sent_at > reprice_bars:
            return e
    return None


def reduce_only_exit_intent(*, portfolio_id: str, symbol: str, sec_type: str, qty: float,
                            bid: float | None = None, force_market: bool = False, source: str = "technique"):
    """Build the SELL order that closes `qty`. Reduce-only, so RiskGate can't
    trap it. Options: marketable limit at the live bid when we have one, else
    market; force_market skips the limit (used when re-pricing a stuck exit).
    Shares: market."""
    from ..orders import OrderIntent
    qty = float(int(qty))
    if sec_type == "OPT" and not force_market and bid and bid > 0:
        return OrderIntent(portfolio_id=portfolio_id, symbol=symbol, sec_type="OPT", side="SELL",
                           qty=qty, order_type="LMT", limit_price=round(float(bid), 2), tif="DAY",
                           source=source, reduce_only=True)
    return OrderIntent(portfolio_id=portfolio_id, symbol=symbol, sec_type=sec_type, side="SELL",
                       qty=qty, order_type="MKT", tif="DAY", source=source, reduce_only=True)
