"""Deterministic verification of extracted signals against live market data.

Runs after extraction + grounding and before any proposal is created.
"""
from __future__ import annotations

from ..marketdata import QuoteCache
from .schemas import TradeSignal


async def verify_signal(
    signal: TradeSignal,
    quotes: QuoteCache,
    settings,
    *,
    grounding: dict | None = None,
) -> dict:
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    # 0. grounding (from the extraction stage)
    if grounding is not None:
        add("quote_grounding", bool(grounding.get("passed")),
            "" if grounding.get("passed") else "evidence quotes not found in source text")

    # 1. actionability
    require_actionable = bool(settings.get("verification.require_actionable", True))
    add("actionable", signal.is_actionable or not require_actionable,
        "" if signal.is_actionable else "signal marked non-actionable by extraction")
    add("explicit_or_implied", signal.confidence != "commentary_only",
        "commentary-only content is never traded" if signal.confidence == "commentary_only" else "")

    # 2. ticker resolves / quote available
    symbol = signal.ticker.upper()
    quote = quotes.get(symbol)
    add("ticker_resolves", quote is not None,
        f"no market data for {symbol}" if quote is None else "")

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

        # 6. price deviation vs claimed entry (staleness / chasing guard)
        if signal.entry_price:
            max_dev = float(settings.get("verification.max_price_deviation_pct", 3.0))
            dev = abs(quote.last - signal.entry_price) / signal.entry_price * 100
            add("price_deviation", dev <= max_dev,
                f"live price {quote.last:.2f} is {dev:.1f}% from claimed entry "
                f"{signal.entry_price:.2f} (max {max_dev:.1f}%)" if dev > max_dev else "")
            # already past target = chasing a move that happened
            if signal.target_price and signal.direction == "long":
                add("not_past_target", quote.last < signal.target_price,
                    f"live price {quote.last:.2f} already at/past target {signal.target_price:.2f}"
                    if quote.last >= signal.target_price else "")

    # 7. internal price ordering
    if signal.direction == "long" and signal.entry_price:
        ok = True
        detail = ""
        if signal.stop_price and signal.stop_price >= signal.entry_price:
            ok, detail = False, f"stop {signal.stop_price} not below entry {signal.entry_price}"
        if signal.target_price and signal.target_price <= signal.entry_price:
            ok, detail = False, f"target {signal.target_price} not above entry {signal.entry_price}"
        add("price_ordering", ok, detail)

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks}
