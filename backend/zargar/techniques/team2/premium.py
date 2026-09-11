"""0DTE premium model — how a $0.50 same-day option moves along the underlying's path (E8/F1).

Black–Scholes on the remaining time to the 16:00 ET expiry with an IV input; used for
(1) picking the strike by TARGET PREMIUM (V1/F5: the first OTM strike whose ask ≈ $0.50–0.60),
(2) marking the position at every 2m close in the simulation (premium-% trims, the premium
hard stop), and (3) the calibration test against the author's documented trades (B3).
Fees and slippage (B4) are applied at fills. Pure: no I/O.

Honest limits: real 0DTE smiles are steeper than flat-IV BS, and the IV input is a proxy
(nightly chain IV or VIX) — the calibration test (`tests/test_team2_premium.py`) is what says
whether the model is close enough; results are stamped `premiumPathSimulated: "bs_flat_iv"`.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from ...marketstructure.sessions import ET

RISK_FREE = 0.04
# The premium band's upper edge, as a multiple of the target (F82, 2026-09-09). Must equal
# `options.pick.MAX_OVER_TARGET` so the modelled and live pickers accept the same band
# (`tests/test_team2_premium.py` asserts it); prose that STATES the band reads it from here.
MAX_OVER_TARGET = 1.5
EXPIRY_MIN = 16 * 60            # 0DTE expires at the 16:00 ET close
MIN_T_YEARS = 1.0 / (365.0 * 24 * 60)   # one minute


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, t_years: float, sigma: float, *, call: bool, rate: float = RISK_FREE) -> float:
    t = max(t_years, MIN_T_YEARS)
    if sigma <= 0:
        intrinsic = max(0.0, spot - strike) if call else max(0.0, strike - spot)
        return intrinsic
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    if call:
        return spot * _ncdf(d1) - strike * math.exp(-rate * t) * _ncdf(d2)
    return strike * math.exp(-rate * t) * _ncdf(-d2) - spot * _ncdf(-d1)


def bs_delta(spot: float, strike: float, t_years: float, sigma: float, *, call: bool, rate: float = RISK_FREE) -> float:
    t = max(t_years, MIN_T_YEARS)
    if sigma <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    return _ncdf(d1) if call else _ncdf(d1) - 1.0


def implied_vol(price: float, spot: float, strike: float, t_years: float, *, call: bool, lo: float = 0.01,
                hi: float = 5.0, tol: float = 1e-4) -> float | None:
    """Bisection on BS; None when the price is outside the no-arbitrage band."""
    intrinsic = max(0.0, spot - strike) if call else max(0.0, strike - spot)
    if price < intrinsic - 1e-9:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        p = bs_price(spot, strike, t_years, mid, call=call)
        if abs(p - price) < tol:
            return mid
        if p > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def years_to_expiry(ts_ms: int, expiry_date: dt.date | None = None) -> float:
    """Time from `ts_ms` to the 16:00 ET close of `expiry_date` (default: the bar's own ET date)."""
    t = dt.datetime.fromtimestamp(ts_ms / 1000, ET)
    d = expiry_date or t.date()
    close = dt.datetime(d.year, d.month, d.day, 16, 0, tzinfo=ET)
    secs = (close - t).total_seconds()
    return max(secs, 60.0) / (365.0 * 86400.0)


@dataclass(frozen=True)
class Fill:
    premium: float          # per contract price after slippage (per share; ×100 = dollars)
    fee_per_contract: float

    def cost(self, contracts: int) -> float:
        return contracts * (self.premium * 100.0 + self.fee_per_contract)


@dataclass
class PremiumModel:
    sigma: float                        # annualised IV used for the whole path (proxy)
    fee_per_contract: float = 1.04
    slippage_ticks: int = 1
    tick: float = 0.01
    rate: float = RISK_FREE

    def mark(self, spot: float, strike: float, ts_ms: int, *, call: bool, expiry: dt.date | None = None) -> float:
        return bs_price(spot, strike, years_to_expiry(ts_ms, expiry), self.sigma, call=call, rate=self.rate)

    def buy(self, mark: float) -> Fill:
        return Fill(premium=round(max(mark + self.slippage_ticks * self.tick, self.tick), 4),
                    fee_per_contract=self.fee_per_contract)

    def sell(self, mark: float) -> Fill:
        return Fill(premium=round(max(mark - self.slippage_ticks * self.tick, 0.0), 4),
                    fee_per_contract=self.fee_per_contract)

    def pick_strike(self, spot: float, ts_ms: int, direction: str, *, target_premium: float,
                    premium_floor: float, step: float = 1.0, expiry: dt.date | None = None,
                    max_steps: int = 40, mode: str = "closest",
                    strikes: list[float] | None = None) -> tuple[float, float] | None:
        """V1/F5: the "~$0.50 contract". `mode="closest"` (F36, default): of the OTM strikes whose
        mark lies in [floor, 1.5 x target], the one CLOSEST to the target — the same rule the live
        picker applies to real asks, so a contract priced within a cent of the target no longer
        sends the model one strike further out than the book (QQQ 2026-09-04 14:14: 716 @ 0.26 vs
        717 @ 0.59). `mode="first_under"` is the legacy walk. Returns (strike, mark) or None.

        F104/F108 (2026-09-10): the ladder walked is the venue's LISTED strikes when `strikes` is
        given (the runner captures today's listing from the chain and stamps it on the plan), and
        only otherwise the synthetic `step` grid — which cannot test IWM's 287.5 half strike and
        refused ten in-band entries on 2026-09-10. A grid walk is a stated limitation, not a listing."""
        call = direction == "long"
        ladder = otm_ladder(spot, call, step=step, strikes=strikes, max_steps=max_steps)
        if mode == "closest":
            cands: list[tuple[float, float]] = []
            for k in ladder:
                m = self.mark(spot, k, ts_ms, call=call, expiry=expiry)
                if premium_floor <= m <= target_premium * MAX_OVER_TARGET:
                    cands.append((k, m))
                if m < premium_floor:
                    break
            if not cands:
                return None
            return min(cands, key=lambda km: (abs(km[1] - target_premium), km[1]))
        best = None
        for k in ladder:
            m = self.mark(spot, k, ts_ms, call=call, expiry=expiry)
            if m <= target_premium:
                if m >= premium_floor:
                    return (k, m)
                # already under the floor: the previous (dearer) strike is acceptable only when
                # it is not far over the target — otherwise nothing prices in the wanted band
                if best is not None and best[1] <= target_premium * 1.5:
                    return best
                return None
            best = (k, m)
        return None


    def nearest_otm(self, spot: float, ts_ms: int, direction: str, *, step: float = 1.0,
                    expiry: dt.date | None = None, strikes: list[float] | None = None) -> tuple[float, float] | None:
        """The first OTM strike ON THIS LADDER and its modelled mark — diagnostic only (F101).

        `pick_strike` returning None says nothing about WHICH strikes it tried, and the ladder is
        a synthetic `step` grid, not the venue's listed strikes: IWM 2026-09-10 refused nine
        entries because the $1 ladder never tested the listed 287.5 put (real ask $0.21, inside
        the band). Quoting this strike in the refusal makes that visible without a chain fetch.
        """
        call = direction == "long"
        first = next(iter(otm_ladder(spot, call, step=step, strikes=strikes, max_steps=1)), None)
        if first is None:
            return None
        return (first, self.mark(spot, first, ts_ms, call=call, expiry=expiry))


def otm_ladder(spot: float, call: bool, *, step: float = 1.0, strikes: list[float] | None = None,
               max_steps: int = 40) -> list[float]:
    """The strikes an OTM walk visits, nearest first: the LISTED strikes strictly beyond spot when
    `strikes` is given (F104: the venue supplies the ladder, the model prices it), else the synthetic
    `step` grid (a limitation the read states as `strikeSource: grid`)."""
    if strikes:
        ks = sorted({float(k) for k in strikes if k is not None})
        otm = [k for k in ks if k > spot] if call else [k for k in reversed(ks) if k < spot]
        return otm[:max_steps]
    k = math.ceil(spot / step) * step if call else math.floor(spot / step) * step
    if (call and k <= spot) or (not call and k >= spot):
        k = k + step if call else k - step
    out = []
    for _ in range(max_steps):
        out.append(k)
        k = k + step if call else k - step
    return out


def pnl_pct(entry_fill: Fill, exit_fill: Fill) -> float:
    """Premium % gain/loss after fees, per contract."""
    cost = entry_fill.premium * 100.0 + entry_fill.fee_per_contract
    proceeds = exit_fill.premium * 100.0 - exit_fill.fee_per_contract
    return (proceeds - cost) / cost * 100.0 if cost > 0 else 0.0


__all__ = ["bs_price", "bs_delta", "implied_vol", "years_to_expiry", "Fill", "PremiumModel", "pnl_pct",
           "RISK_FREE"]
