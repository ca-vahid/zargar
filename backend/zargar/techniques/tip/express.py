"""Tip expression — which contract carries the tip (BUILD-PLAN.md T1).

The per-tip vehicle rule: a tip that NAMES an option (instrument call/put, a
strike, an expiry, or a DTE hint) is expressed as that option in BOTH shadow
books; anything else is shares. Contract choice honors the tip first:

  strike + expiry stated  -> that exact contract (existence-checked)
  expiry only             -> just-OTM strike at that expiry
  strike only / neither   -> the source policy's DTE window (10-30d default,
                             never 0DTE), exact strike when listed

Shorts are puts with the min_strike mirror (a put struck below the downside
target is worthless leverage — same rule as EM's T5.1 cap). Reuses the shared
chain plumbing (`technique.options.select_contract`) so the warning vocabulary
(spread / OI / volume / delta / IV) is the one the runner's gates already read.
"""
from __future__ import annotations

import datetime as dt

from ...options import occ as occ_mod
from ...options.chain import OptionsError
from ...technique.options import (
    ELEVATED_IV,
    LOW_DELTA,
    MAX_SPREAD_PCT,
    MIN_OPEN_INTEREST,
    MIN_VOLUME,
    select_contract,
)


def tip_is_option(sig) -> bool:
    """The vehicle rule. `sig` is a Signal row or anything with the v2 fields."""
    instrument = getattr(sig, "instrument", None) or "unspecified"
    if instrument in ("call", "put"):
        return True
    if instrument == "shares":
        return False
    return bool(getattr(sig, "strike", None) or getattr(sig, "expiry", None)
                or getattr(sig, "dte_hint_days", None))


def choose_expiry_window(expirations: list[str], today: dt.date, *,
                         dte_min: int, dte_max: int,
                         stated: str | None = None) -> tuple[str | None, list[str]]:
    """The tip's expiry: the stated one when listed and not yet past; else the
    FIRST listed expiry inside [dte_min, dte_max] (enough runway, least theta
    bought); else the nearest beyond dte_max (warned); never below dte_min."""
    warnings: list[str] = []
    dates: list[dt.date] = []
    for s in expirations:
        try:
            dates.append(dt.date.fromisoformat(s))
        except ValueError:
            continue
    dates = sorted(d for d in dates if d >= today)
    if stated:
        try:
            sd = dt.date.fromisoformat(stated)
        except ValueError:
            sd = None
        if sd is not None:
            if sd < today:
                return None, [f"stated expiry {stated} has passed"]
            if sd in dates:
                return sd.isoformat(), []
            warnings.append(f"stated expiry {stated} is not listed — using the policy window")
    if not dates:
        return None, warnings + ["no expirations listed"]
    in_window = [d for d in dates if dte_min <= (d - today).days <= dte_max]
    if in_window:
        return in_window[0].isoformat(), warnings
    beyond = [d for d in dates if (d - today).days > dte_max]
    if beyond:
        warnings.append(f"no expiry inside {dte_min}-{dte_max} DTE — using {beyond[0].isoformat()}")
        return beyond[0].isoformat(), warnings
    warnings.append(f"every listed expiry is under {dte_min} DTE — the thesis outlives the chain")
    return None, warnings


def _row_pick(row: dict, expiry: str, today: dt.date, want: str) -> dict:
    """A stated-strike row -> the contract dict the runner consumes, with the
    shared warning vocabulary (mirrors select_contract's checks)."""
    bid = float(row.get("bid") or 0.0)
    ask = float(row.get("ask") or 0.0)
    mid = (bid + ask) / 2 if (bid or ask) else 0.0
    spread_pct = ((ask - bid) / mid * 100) if mid > 0 else 999.0
    g = row.get("greeks") or {}
    delta, theta, iv = g.get("delta"), g.get("theta"), g.get("mid_iv")
    dte = (dt.date.fromisoformat(expiry) - today).days
    warnings: list[str] = []
    if spread_pct > MAX_SPREAD_PCT:
        warnings.append(f"T5.4 wide spread {spread_pct:.1f}% (bid {bid} / ask {ask})")
    if int(row.get("open_interest") or 0) < MIN_OPEN_INTEREST:
        warnings.append(f"T5.4 thin open interest {row.get('open_interest')}")
    if int(row.get("volume") or 0) < MIN_VOLUME:
        warnings.append(f"T5.4 low volume today {row.get('volume')}")
    if delta is not None and abs(float(delta)) < LOW_DELTA:
        warnings.append(f"T5.4 low delta {float(delta):.2f}")
    if iv is not None and float(iv) >= ELEVATED_IV:
        warnings.append(f"T5.3 elevated IV {float(iv):.2f} — IV-crush risk")
    return {
        "symbol": str(row.get("symbol")), "underlying": str(row.get("underlying") or ""),
        "expiry": expiry, "strike": float(row.get("strike") or 0), "optionType": want,
        "bid": bid, "ask": ask, "mid": round(mid, 4), "spreadPct": round(spread_pct, 2),
        "volume": int(row.get("volume") or 0), "openInterest": int(row.get("open_interest") or 0),
        "delta": float(delta) if delta is not None else None,
        "theta": float(theta) if theta is not None else None,
        "iv": float(iv) if iv is not None else None,
        "dte": dte, "is0dte": dte == 0, "warnings": warnings,
        "display": occ_mod.display(str(row.get("symbol") or "")),
        "available": True, "statedContract": True,
    }


async def pick_tip_contract(engine, *, symbol: str, direction: str,
                            dte_min: int, dte_max: int,
                            strike: float | None = None, expiry: str | None = None,
                            spot: float | None = None,
                            min_strike: float | None = None,
                            max_strike: float | None = None,
                            today: dt.date | None = None) -> dict:
    """The tip's contract, or {'available': False, 'error': ...}. Never raises
    for 'no contract' — callers decide the fallback (shares)."""
    today = today or dt.date.today()
    want = "call" if direction == "long" else "put"
    opts = getattr(engine, "options", None)
    if opts is None:
        return {"available": False, "error": "options service not attached"}
    client = opts.provider()
    if spot is None:
        q = engine.quotes.get(symbol.upper())
        spot = float(q.last) if q and q.last > 0 else None
    try:
        if spot is None:
            spot = await client.spot(symbol)
        if not spot:
            return {"available": False, "error": "no spot price"}
        exps = await client.expirations(symbol)
        chosen, warnings = choose_expiry_window(exps, today, dte_min=dte_min,
                                                dte_max=dte_max, stated=expiry)
        if not chosen:
            return {"available": False, "error": "; ".join(warnings) or "no usable expiry"}
        chain = await client.chain(symbol, chosen)
        if strike is not None:
            # the tip named its strike: use it verbatim when listed
            rows = [c for c in chain
                    if (c.get("option_type") or "").lower() == want
                    and abs(float(c.get("strike") or 0) - float(strike)) < 1e-9]
            if rows:
                pick = _row_pick(rows[0], chosen, today, want)
                pick["warnings"] = warnings + pick["warnings"]
                return pick
            warnings.append(f"stated strike {strike:g} not listed at {chosen} — using just-OTM")
        pick = select_contract(chain, float(spot), direction, expiry=chosen, today=today,
                               is_0dte=False, max_strike=max_strike, min_strike=min_strike)
        if pick is None:
            return {"available": False, "expiry": chosen,
                    "error": f"no {want} just OTM at {chosen}"}
        d = pick.to_dict()
        d["available"] = True
        d["warnings"] = warnings + d["warnings"]
        return d
    except OptionsError as exc:
        return {"available": False, "error": str(exc)}
    except Exception as exc:  # network etc. — the caller falls back to shares
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
