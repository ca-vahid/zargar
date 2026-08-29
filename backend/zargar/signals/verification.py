"""Deterministic verification of extracted signals against live market data.

Runs after extraction + grounding and before any proposal is created.

v2 (tip technique): checks are either **fatal** (ungrounded, non-actionable,
unresolvable ticker, halted, penny stock, wide spread, incoherent prices) or
**parking** (price has moved away from the stated entry / already reached the
target). A signal failing only parking checks is not killed — it is *parked*:
the tip technique watches for price to come back to its level and re-judges
then. The old behaviour killed a tip 4% off its entry forever, which is
exactly wrong for a technique whose default entry is "wait for the level".
"""
from __future__ import annotations

from ..marketdata import QuoteCache
from .schemas import TradeSignal

# Failing ONLY these parks the signal instead of killing it. `ticker_resolves`
# is parking (2026-08-28, the AMZN case): a cold symbol with no quote yet is a
# FEED state, not a bad tip — parked tips are re-judged when data arrives; a
# truly bogus ticker just expires unfilled.
PARKING_CHECKS = {"price_deviation", "not_past_target", "ticker_resolves"}

# Failing ONLY these (plus parking) demotes the signal to SHADOW-ONLY instead of
# killing it: the shadow books trade it and the source's scorecard learns from
# it, but no proposal is ever created. Decision 2026-08-28 (the PeloSwing CRM
# case): implied-but-directional chart tips are the commonest real-world tip
# shape, and killing them left the books blind to exactly the sources we are
# trying to measure. Shadow costs nothing; explicit calls still gate proposals.
SHADOW_CHECKS = {"actionable"}


async def verify_signal(
    signal: TradeSignal,
    quotes: QuoteCache,
    settings,
    *,
    grounding: dict | None = None,
) -> dict:
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": passed, "detail": detail,
                       "fatal": name not in PARKING_CHECKS and name not in SHADOW_CHECKS})

    # 0. grounding (from the extraction stage)
    if grounding is not None:
        add("quote_grounding", bool(grounding.get("passed")),
            "" if grounding.get("passed") else "evidence quotes not found in source text")

    # 1. actionability — SHADOW-gating, not fatal: an implied directional lean
    # still trades in the shadow books; it just never becomes a proposal
    require_actionable = bool(settings.get("verification.require_actionable", True))
    add("actionable", signal.is_actionable or not require_actionable,
        "" if signal.is_actionable
        else "no explicit call to act — shadow books only, no proposal")
    add("explicit_or_implied", signal.confidence != "commentary_only",
        "commentary-only content is never traded" if signal.confidence == "commentary_only" else "")

    # 2. ticker resolves / quote available
    symbol = signal.ticker.upper()
    quote = quotes.get(symbol)
    add("ticker_resolves", quote is not None,
        f"no market data for {symbol} yet — parked until the feed warms"
        if quote is None else "")

    if quote is not None:
        # 3. halt
        add("not_halted", not quote.halted, "instrument is halted" if quote.halted else "")

        # 4. price sanity
        min_price = float(settings.get("verification.min_price", 1.0))
        add("min_price", quote.last >= min_price,
            f"price {quote.last:.2f} below minimum {min_price:.2f} (penny-stock filter)"
            if quote.last < min_price else "")

        # 5. spread (liquidity proxy)
        max_spread = float(settings.get("verification.max_spread_pct", 1.5))
        add("spread", quote.spread_pct <= max_spread,
            f"spread {quote.spread_pct:.2f}% exceeds {max_spread:.2f}%"
            if quote.spread_pct > max_spread else "")

        # 6. price deviation vs claimed entry — PARKING, not fatal: the tip
        # technique waits for the level instead of chasing or dying
        if signal.entry_price:
            max_dev = float(settings.get("verification.max_price_deviation_pct", 3.0))
            dev = abs(quote.last - signal.entry_price) / signal.entry_price * 100
            add("price_deviation", dev <= max_dev,
                f"live price {quote.last:.2f} is {dev:.1f}% from claimed entry "
                f"{signal.entry_price:.2f} (max {max_dev:.1f}%)" if dev > max_dev else "")
        # already past target = the move already happened (both directions)
        first_target = signal.target_price or (signal.target_prices[0] if signal.target_prices else None)
        if first_target:
            if signal.direction == "long":
                add("not_past_target", quote.last < first_target,
                    f"live price {quote.last:.2f} already at/past target {first_target:.2f}"
                    if quote.last >= first_target else "")
            else:
                add("not_past_target", quote.last > first_target,
                    f"live price {quote.last:.2f} already at/past target {first_target:.2f}"
                    if quote.last <= first_target else "")

    # 7. internal price ordering (direction-aware)
    if signal.entry_price:
        ok = True
        detail = ""
        if signal.direction == "long":
            if signal.stop_price and signal.stop_price >= signal.entry_price:
                ok, detail = False, f"stop {signal.stop_price} not below entry {signal.entry_price}"
            if signal.target_price and signal.target_price <= signal.entry_price:
                ok, detail = False, f"target {signal.target_price} not above entry {signal.entry_price}"
        else:
            if signal.stop_price and signal.stop_price <= signal.entry_price:
                ok, detail = False, f"stop {signal.stop_price} not above entry {signal.entry_price}"
            if signal.target_price and signal.target_price >= signal.entry_price:
                ok, detail = False, f"target {signal.target_price} not below entry {signal.entry_price}"
        add("price_ordering", ok, detail)

    passed = all(c["passed"] for c in checks)
    fatal_passed = all(c["passed"] for c in checks if c["fatal"])
    parking_failed = any(not c["passed"] for c in checks if c["name"] in PARKING_CHECKS)
    shadow_failed = any(not c["passed"] for c in checks if c["name"] in SHADOW_CHECKS)
    return {
        "passed": passed,
        # price-position failed → wait for the level (wins over shadow: a tip
        # whose price already ran away should not be bought immediately either)
        "park": (not passed) and fatal_passed and parking_failed,
        # not an explicit call (and price is fine) → books trade it, no proposal
        "shadow_only": (not passed) and fatal_passed and shadow_failed and not parking_failed,
        "checks": checks,
    }
