"""OCC option symbology.

Canonical internal form is the **unpadded** OCC symbol — ``F260828C00014500``
— exactly what CBOE and Yahoo use, so chains, quotes and bars need no
translation. SnapTrade wants the padded 21-char form (root space-padded to 6
characters) in order legs: ``"F     260828C00014500"``; ``to_snaptrade`` /
``from_snaptrade`` convert at the venue boundary and nowhere else.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

MULTIPLIER = 100

_OCC_RE = re.compile(r"^(?P<root>[A-Z]{1,6})(?P<date>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")


@dataclass(frozen=True, slots=True)
class Occ:
    underlying: str
    expiry: dt.date
    right: str          # "C" | "P"
    strike: float

    @property
    def symbol(self) -> str:
        """Canonical unpadded form."""
        return f"{self.underlying}{self.expiry:%y%m%d}{self.right}{int(round(self.strike * 1000)):08d}"

    @property
    def snaptrade(self) -> str:
        """SnapTrade / OCC 21-char form: root padded with spaces to 6."""
        return f"{self.underlying:<6}{self.expiry:%y%m%d}{self.right}{int(round(self.strike * 1000)):08d}"

    @property
    def option_type(self) -> str:
        return "call" if self.right == "C" else "put"

    def dte(self, today: dt.date | None = None) -> int:
        return (self.expiry - (today or dt.date.today())).days

    def is_expired(self, today: dt.date | None = None) -> bool:
        return self.dte(today) < 0

    def display(self) -> str:
        """``F 28 Aug 26 14.5 C`` — what humans read in tickets and blotters."""
        return f"{self.underlying} {self.expiry:%d %b %y} {_fmt_strike(self.strike)} {self.right}"

    def short(self) -> str:
        """``F 14.5C 8/28`` — table-cell form."""
        return f"{self.underlying} {_fmt_strike(self.strike)}{self.right} {self.expiry.month}/{self.expiry.day}"

    def to_dict(self, today: dt.date | None = None) -> dict:
        return {
            "symbol": self.symbol,
            "underlying": self.underlying,
            "expiry": self.expiry.isoformat(),
            "strike": self.strike,
            "right": self.right,
            "optionType": self.option_type,
            "dte": self.dte(today),
            "display": self.display(),
            "short": self.short(),
            "multiplier": MULTIPLIER,
        }


def _fmt_strike(strike: float) -> str:
    return f"{strike:g}" if abs(strike - round(strike)) > 1e-9 else f"{int(round(strike))}"


def parse(symbol: str | None) -> Occ | None:
    """Parse padded or unpadded OCC; None when it isn't one (or the date is bogus)."""
    if not symbol:
        return None
    s = symbol.strip().upper().replace(" ", "")
    m = _OCC_RE.match(s)
    if not m:
        return None
    d = m.group("date")
    try:
        expiry = dt.date(2000 + int(d[0:2]), int(d[2:4]), int(d[4:6]))
    except ValueError:
        return None
    return Occ(m.group("root"), expiry, m.group("cp"), int(m.group("strike")) / 1000.0)


def is_occ(symbol: str | None) -> bool:
    return parse(symbol) is not None


def normalize(symbol: str) -> str:
    """Any OCC spelling → canonical; non-OCC strings pass through upper-cased."""
    o = parse(symbol)
    return o.symbol if o else symbol.strip().upper()


def to_snaptrade(symbol: str) -> str:
    o = parse(symbol)
    if o is None:
        raise ValueError(f"not an OCC option symbol: {symbol!r}")
    return o.snaptrade


def from_snaptrade(ticker: str) -> str | None:
    o = parse(ticker)
    return o.symbol if o else None


def display(symbol: str) -> str:
    o = parse(symbol)
    return o.display() if o else symbol


def make(underlying: str, expiry: dt.date | str, right: str, strike: float) -> Occ:
    if isinstance(expiry, str):
        expiry = dt.date.fromisoformat(expiry)
    r = right.strip().upper()[0]
    if r not in ("C", "P"):
        raise ValueError(f"right must be C or P, got {right!r}")
    return Occ(underlying.strip().upper(), expiry, r, float(strike))
