"""Currency helpers: per-symbol currency inference and live FX conversion.

FX rates arrive through the normal quote pipeline as Yahoo-style pairs
(``USDCAD=X``). When no fresh rate exists the converter falls back to 1:1 —
for our CAD-account risk caps that *under*-counts USD position values, which
fails conservative (caps bind sooner, never later).
"""
from __future__ import annotations

import logging

from .domain import now_ms
from .marketdata import QuoteCache

log = logging.getLogger("zargar.fx")

# Yahoo-style suffix conventions in use across the app.
_CAD_SUFFIXES = (".TO", ".V", ".NE", ".CN")

MAX_RATE_AGE_MS = 6 * 60 * 60 * 1000  # FX barely moves intraday; 6h is plenty


def currency_for_symbol(symbol: str) -> str:
    s = symbol.upper()
    return "CAD" if s.endswith(_CAD_SUFFIXES) else "USD"


def fx_pair_symbol(frm: str, to: str) -> str:
    return f"{frm.upper()}{to.upper()}=X"


class FxService:
    """Converts amounts between currencies using rates from the QuoteCache."""

    def __init__(self, quotes: QuoteCache) -> None:
        self._quotes = quotes
        self._warned: set[tuple[str, str]] = set()

    def rate(self, frm: str, to: str) -> float | None:
        frm, to = frm.upper(), to.upper()
        if frm == to:
            return 1.0
        q = self._quotes.get(fx_pair_symbol(frm, to))
        if q is not None and q.last > 0 and now_ms() - q.ts < MAX_RATE_AGE_MS:
            return q.last
        q = self._quotes.get(fx_pair_symbol(to, frm))  # inverse pair
        if q is not None and q.last > 0 and now_ms() - q.ts < MAX_RATE_AGE_MS:
            return 1.0 / q.last
        return None

    def convert(self, amount: float, frm: str, to: str) -> float:
        r = self.rate(frm, to)
        if r is None:
            key = (frm.upper(), to.upper())
            if key not in self._warned and key[0] != key[1]:
                self._warned.add(key)
                log.warning("no live FX rate %s->%s — converting 1:1 (undercounts)", *key)
            return amount
        return amount * r

    @property
    def watch_symbols(self) -> list[str]:
        """Pairs the quote feed should keep live for CAD/USD accounts."""
        return [fx_pair_symbol("USD", "CAD")]
