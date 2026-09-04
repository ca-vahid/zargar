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
                    max_steps: int = 40) -> tuple[float, float] | None:
        """V1/F5: walk OTM from the first strike beyond spot until the model ask <= target;
        stop before dropping under the floor. Returns (strike, mark) or None."""
        call = direction == "long"
        k = math.ceil(spot / step) * step if call else math.floor(spot / step) * step
        if (call and k <= spot) or (not call and k >= spot):
            k = k + step if call else k - step
        best = None
        for _ in range(max_steps):
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
            k = k + step if call else k - step
        return None


def pnl_pct(entry_fill: Fill, exit_fill: Fill) -> float:
    """Premium % gain/loss after fees, per contract."""
    cost = entry_fill.premium * 100.0 + entry_fill.fee_per_contract
    proceeds = exit_fill.premium * 100.0 - exit_fill.fee_per_contract
    return (proceeds - cost) / cost * 100.0 if cost > 0 else 0.0


__all__ = ["bs_price", "bs_delta", "implied_vol", "years_to_expiry", "Fill", "PremiumModel", "pnl_pct",
           "RISK_FREE"]
