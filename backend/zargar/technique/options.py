"""T5 contract selection (EnhancedMarket §6) over the shared chain providers.

The providers themselves (CBOE default, Tradier optional) live in
``zargar.options.chain`` and are re-exported here so existing imports keep
working; ``parse_occ`` wraps ``zargar.options.occ``.

    T5.1 strike just OTM            T5.3 do not buy elevated IV
    T5.2 current-week Friday / 0DTE T5.4 avoid wide spreads, poor greeks
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

import httpx

from ..options import occ as _occ
from ..options.chain import (  # noqa: F401  (re-exports)
    CBOE_URL, TRADIER_PROD_BASE, TRADIER_SANDBOX_BASE, UA,
    CboeClient, OptionsError, TradierClient,
)

log = logging.getLogger("zargar.technique.options")

# T5.4 heuristics — the book gives no numbers; these are ours (spec §10).
MAX_SPREAD_PCT = 10.0       # (ask-bid)/mid
MIN_OPEN_INTEREST = 100
MIN_VOLUME = 10
LOW_DELTA = 0.25
ELEVATED_IV = 0.60          # absolute mid IV; percentile needs history we lack


@dataclass
class ContractPick:
    symbol: str
    underlying: str
    expiry: str
    strike: float
    option_type: str            # call | put
    bid: float
    ask: float
    mid: float
    spread_pct: float
    volume: int
    open_interest: int
    delta: float | None
    theta: float | None
    iv: float | None
    dte: int
    is_0dte: bool
    warnings: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "underlying": self.underlying, "expiry": self.expiry,
            "strike": self.strike, "optionType": self.option_type,
            "bid": self.bid, "ask": self.ask, "mid": round(self.mid, 4),
            "spreadPct": round(self.spread_pct, 2), "volume": self.volume,
            "openInterest": self.open_interest, "delta": self.delta, "theta": self.theta,
            "iv": self.iv, "dte": self.dte, "is0dte": self.is_0dte,
            "warnings": list(self.warnings), "rules": list(self.rules),
            "display": _occ.display(self.symbol),
        }


def parse_occ(symbol: str) -> tuple[str, str, str, float] | None:
    """'SPY260821C00360000' → ('SPY', '2026-08-21', 'call', 360.0)."""
    o = _occ.parse(symbol)
    if o is None:
        return None
    return o.underlying, o.expiry.isoformat(), o.option_type, o.strike


# --- selection (provider-agnostic) ------------------------------------------------

def choose_expiry(expirations: list[str], today: dt.date, *, avoid_0dte: bool = False) -> tuple[str | None, bool]:
    """T5.2 — same-day (0DTE) if listed, else the nearest expiry on/before this
    week's Friday, else the very next expiry. `avoid_0dte` skips the same-day
    expiry when any later one exists (used near the close, where a 0DTE premium
    is mostly spread and theta) — with no alternative it still returns 0DTE."""
    dates = []
    for s in expirations:
        try:
            dates.append(dt.date.fromisoformat(s))
        except ValueError:
            continue
    dates = sorted(d for d in dates if d >= today)
    if not dates:
        return None, False
    if dates[0] == today and not (avoid_0dte and len(dates) > 1):
        return dates[0].isoformat(), True
    later = [d for d in dates if d > today] or dates
    friday = today + dt.timedelta(days=(4 - today.weekday()) % 7)
    this_week = [d for d in later if d <= friday]
    pick = this_week[-1] if this_week else later[0]
    return pick.isoformat(), pick == today


def select_contract(chain: list[dict], spot: float, direction: str, *, expiry: str,
                    today: dt.date, is_0dte: bool, max_strike: float | None = None) -> ContractPick | None:
    """T5.1 — the first strike just OTM in the trade direction, with T5.3/T5.4
    warnings attached. `max_strike` (usually the plan's TP2) caps the pick: a
    call whose strike sits beyond the target would still be OTM when the plan
    says take profit — worthless leverage. If every OTM strike is beyond the
    cap, the nearest one is used with a warning. Returns None if the chain has
    no usable contract."""
    want = "call" if direction == "long" else "put"
    rows = [c for c in chain if (c.get("option_type") or "").lower() == want]
    if not rows:
        return None
    if want == "call":
        otm = [c for c in rows if float(c.get("strike", 0)) > spot]
        otm.sort(key=lambda c: float(c["strike"]))
    else:
        otm = [c for c in rows if float(c.get("strike", 0)) < spot]
        otm.sort(key=lambda c: -float(c["strike"]))
    if not otm:
        return None
    strike_warning = None
    c = otm[0]
    if max_strike is not None and want == "call" and float(c["strike"]) > max_strike:
        within = [x for x in otm if float(x["strike"]) <= max_strike]
        if within:
            c = within[0]                      # still the closest OTM, but inside the target
        else:
            strike_warning = (f"T5.1 strike {float(c['strike']):g} is beyond the plan's target cap "
                              f"{max_strike:g} — payoff at target is poor")
    bid = float(c.get("bid") or 0.0)
    ask = float(c.get("ask") or 0.0)
    mid = (bid + ask) / 2 if (bid or ask) else 0.0
    spread_pct = ((ask - bid) / mid * 100) if mid > 0 else 999.0
    g = c.get("greeks") or {}
    delta = g.get("delta")
    theta = g.get("theta")
    iv = g.get("mid_iv")
    try:
        exp_d = dt.date.fromisoformat(expiry)
        dte = (exp_d - today).days
    except ValueError:
        dte = -1

    warnings: list[str] = []
    if strike_warning:
        warnings.append(strike_warning)
    rules = ["T5.1", "T5.2"]
    if spread_pct > MAX_SPREAD_PCT:
        warnings.append(f"T5.4 wide spread {spread_pct:.1f}% (bid {bid} / ask {ask})")
    if int(c.get("open_interest") or 0) < MIN_OPEN_INTEREST:
        warnings.append(f"T5.4 thin open interest {c.get('open_interest')}")
    if int(c.get("volume") or 0) < MIN_VOLUME:
        warnings.append(f"T5.4 low volume today {c.get('volume')}")
    if delta is not None and abs(float(delta)) < LOW_DELTA:
        warnings.append(f"T5.4 low delta {float(delta):.2f}")
    if iv is not None and float(iv) >= ELEVATED_IV:
        warnings.append(f"T5.3 elevated IV {float(iv):.2f} — IV-crush risk")
    if is_0dte:
        warnings.append("T5.2 0DTE: use reduced size")
    if warnings:
        rules.extend(sorted({w.split()[0] for w in warnings}))

    return ContractPick(
        symbol=str(c.get("symbol")), underlying=str(c.get("underlying") or ""),
        expiry=expiry, strike=float(c["strike"]), option_type=want,
        bid=bid, ask=ask, mid=mid, spread_pct=spread_pct,
        volume=int(c.get("volume") or 0), open_interest=int(c.get("open_interest") or 0),
        delta=float(delta) if delta is not None else None,
        theta=float(theta) if theta is not None else None,
        iv=float(iv) if iv is not None else None,
        dte=dte, is_0dte=is_0dte, warnings=warnings, rules=sorted(set(rules)),
    )


async def pick_for_setup(client, symbol: str, spot: float, direction: str,
                         *, today: dt.date | None = None, max_strike: float | None = None,
                         avoid_0dte: bool = False) -> dict:
    """End-to-end: expirations → expiry choice → chain → contract. `client` is
    any provider exposing expirations()/chain() with normalized rows. Never
    raises for 'no contract'; returns a dict with `error` for hard failures."""
    today = today or dt.date.today()
    try:
        exps = await client.expirations(symbol)
        expiry, is_0dte = choose_expiry(exps, today, avoid_0dte=avoid_0dte)
        if not expiry:
            return {"error": "no expirations listed", "available": False,
                    "provider": getattr(client, "name", "?")}
        chain = await client.chain(symbol, expiry)
        pick = select_contract(chain, spot, direction, expiry=expiry, today=today, is_0dte=is_0dte,
                               max_strike=max_strike)
        if pick is None:
            return {"error": f"no {('call' if direction == 'long' else 'put')} just OTM at {expiry}",
                    "expiry": expiry, "available": True, "provider": getattr(client, "name", "?")}
        d = pick.to_dict()
        d["available"] = True
        d["chainSize"] = len(chain)
        d["provider"] = getattr(client, "name", "?")
        return d
    except OptionsError as exc:
        return {"error": str(exc), "available": False, "provider": getattr(client, "name", "?")}
    except httpx.HTTPError as exc:
        return {"error": f"network: {exc}", "available": False, "provider": getattr(client, "name", "?")}
