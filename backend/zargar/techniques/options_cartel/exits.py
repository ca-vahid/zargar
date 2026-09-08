"""Cartel's pure, fill-aware swing exit campaign (M5; D11 in TRADING-RULES).

Daily EMA decisions consume completed daily history. Target/extension exits may
use a closed intraday bar and PREVIOUS completed daily indicators. This module
never places an order. The runtime adapter must use PositionManager.close and
confirm actual fills through record_fill; a signal never advances a trim itself.
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...marketstructure.indicators import ema_series, true_range
from .data import DailyBar, completed_daily, require_contiguous


class ExitRung(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    id: str = Field(min_length=1)
    kind: Literal["target", "ema", "extension"]
    fraction: float = Field(gt=0, le=1)
    target: float | None = Field(default=None, gt=0)
    ema_period: int = Field(default=8, ge=1, le=252)
    atr_multiple: float = Field(default=3, gt=0)

    @model_validator(mode="after")
    def target_required(self):
        if self.kind == "target" and self.target is None:
            raise ValueError("target rung needs an underlying level")
        return self


class ExitCampaign(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    version: Literal["cartel-exits-1"] = "cartel-exits-1"
    profile: Literal["may_2026", "june_2026", "september_2026", "january_2026_volume", "reviewed"]
    source_refs: tuple[str, ...] = Field(min_length=1)
    allocation_note: str = Field(min_length=1)
    rungs: tuple[ExitRung, ...] = Field(min_length=2)
    atr_period: int = Field(default=14, ge=2, le=252)

    @model_validator(mode="after")
    def valid_allocation(self):
        if len({r.id for r in self.rungs}) != len(self.rungs):
            raise ValueError("exit rung ids must be unique")
        if abs(sum(r.fraction for r in self.rungs)-1) > 1e-9:
            raise ValueError("exit fractions must allocate exactly the original position")
        if self.rungs[0].kind != "target" or self.rungs[-1].kind != "ema":
            raise ValueError("campaign starts with a target and ends with a daily EMA runner")
        return self

    @classmethod
    def for_profile(cls, profile: str, targets: list[float], *, september_fractions=None):
        if not targets:
            raise ValueError("first target is required")
        if profile == 'january_2026_volume':
            if len(targets) < 3:
                raise ValueError('January volume example requires three reviewed targets')
            rungs = [ExitRung(id=f'target{i+1}', kind='target', fraction=.25, target=t)
                     for i, t in enumerate(targets[:3])]
            rungs.append(ExitRung(id='ema8', kind='ema', fraction=.25, ema_period=8))
            refs, note = ('S05',), 'Three strength targets and EMA8 runner in the January volume example; quarter allocations from its text.'
        elif profile == "may_2026":
            rungs = [ExitRung(id="target1", kind="target", fraction=.25, target=targets[0])]
            rungs += [ExitRung(id=f"ema{p}", kind="ema", fraction=.25, ema_period=p) for p in (8, 21, 50)]
            refs, note = ("S04",), "Source's four quarter-position exits."
        elif profile == "june_2026":
            if len(targets) < 2:
                raise ValueError("June profile requires two reviewed resistance targets")
            rungs = [ExitRung(id=f"target{i+1}", kind="target", fraction=.25, target=t)
                     for i, t in enumerate(targets[:2])]
            rungs += [ExitRung(id=f"ema{p}", kind="ema", fraction=.25, ema_period=p) for p in (8, 21)]
            refs, note = ("S02",), "Source's two strength quarters and two daily EMA quarters."
        elif profile == "september_2026":
            if september_fractions is None or len(september_fractions) != 5:
                raise ValueError("September needs five explicitly reviewed fractions: target, extension, 8/21/50 EMA")
            f = september_fractions
            if abs(f[0]-.25) > 1e-9:
                raise ValueError("September's first source trim is 25%")
            rungs = [ExitRung(id="target1", kind="target", fraction=f[0], target=targets[0]),
                     ExitRung(id="extension", kind="extension", fraction=f[1])]
            rungs += [ExitRung(id=f"ema{p}", kind="ema", fraction=q, ema_period=p)
                      for p, q in zip((8, 21, 50), f[2:])]
            refs = ("S01",)
            note = "First trim/3xATR/EMAs from S01; later fractions explicitly chosen by reviewer, not stated by Sean."
        else:
            raise ValueError("unknown source exit profile")
        return cls(profile=profile, source_refs=refs, allocation_note=note, rungs=tuple(rungs))


class ExitState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    position_id: str
    symbol: str
    direction: Literal["long", "short"]
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    initial_qty: int = Field(ge=1)
    remaining_qty: int = Field(ge=0)
    sold: dict[str, int] = Field(default_factory=dict)
    fill_ids: tuple[str, ...] = ()
    breakeven: bool = False

    @model_validator(mode="after")
    def quantity_balance(self):
        if any(q < 0 for q in self.sold.values()) or sum(self.sold.values()) + self.remaining_qty != self.initial_qty:
            raise ValueError("filled exit quantities must reconcile to the original position")
        return self


def allocations(campaign: ExitCampaign, initial_qty: int) -> dict[str, int]:
    """Whole-contract/share lots; keep final runner remainder, never oversell.

    Cumulative floor gives balanced partials (e.g. 3 contracts -> 0,1,1,1).
    Zero-sized rungs are skipped, not promoted to a forced one-contract trim.
    """
    cumulative, allocated = 0., 0
    out = {}
    for rung in campaign.rungs:
        cumulative += rung.fraction
        total = min(initial_qty, int(initial_qty*cumulative + 1e-9))
        out[rung.id] = total-allocated
        allocated = total
    return out


def decide_exits(campaign: ExitCampaign, state: ExitState, history: list[DailyBar], *,
                 as_of_ms: int, observed_price: float, daily_close: bool,
                 pending_qty: int = 0, dte: int | None = None, min_dte: int = 1) -> dict:
    """Protective closes first, then source rungs. Caller supplies a fresh price.

    Pending exits suppress new requests; mandatory exits request cancellation/
    replacement through the existing manager instead of stacking sell orders.
    """
    if observed_price <= 0 or not math.isfinite(observed_price):
        raise ValueError("a finite positive observed underlying price is required")
    if not 0 <= pending_qty <= state.remaining_qty:
        raise ValueError("pending exits exceed current holdings")
    out = {"positionId": state.position_id, "decisions": [], "warnings": []}
    if state.remaining_qty == 0:
        return out
    sign = 1 if state.direction == "long" else -1

    def decision(key, qty, reason, *, protective=False):
        return {"id": f"{state.position_id}:{key}", "rung": key, "qty": qty,
                "reason": reason,
                "replacePending": protective and pending_qty > 0,
                "reduceOnly": True}

    if (observed_price-state.stop)*sign <= 0:
        out["decisions"] = [decision("stop", state.remaining_qty, "Underlying crossed the active protective stop.", protective=True)]
        return out
    if dte is not None and dte <= max(1, min_dte):
        out["decisions"] = [decision("expiry", state.remaining_qty, "Contract reached the platform expiry floor.", protective=True)]
        return out
    if pending_qty:
        out["warnings"].append("An exit is pending; wait for fills or the manager's retry/cancel path.")
        return out
    # A broken indicator history must not prevent a protective stop/expiry exit.
    bars = completed_daily(history, as_of_ms)
    require_contiguous(bars)
    if bars and bars[-1].symbol != state.symbol:
        raise ValueError("exit history symbol mismatch")
    if daily_close and (not bars or bars[-1].closes_at != as_of_ms or bars[-1].close != observed_price):
        raise ValueError("daily EMA decisions require this completed session's close price and actual close boundary")
    sizes = allocations(campaign, state.initial_qty)
    ema_periods = {r.ema_period for r in campaign.rungs if r.kind in ("ema", "extension")}
    emas = {p: ema_series([b.close for b in bars], p)[-1] if bars else None for p in ema_periods}
    atr = None
    if len(bars) >= campaign.atr_period:
        tr = [true_range(b.high, b.low, bars[i-1].close if i else None) for i, b in enumerate(bars)]
        atr = sum(tr[:campaign.atr_period])/campaign.atr_period
        for value in tr[campaign.atr_period:]:
            atr = (atr*(campaign.atr_period-1)+value)/campaign.atr_period
    first = campaign.rungs[0]
    # For small lots with zero allocation at the first target, reaching the
    # target alone must not claim that a trim filled or move the stop to entry.
    first_done = state.sold.get(first.id, 0) >= sizes[first.id] and sizes[first.id] > 0
    remaining = state.remaining_qty
    for rung in campaign.rungs:
        qty = max(0, sizes[rung.id]-state.sold.get(rung.id, 0))
        if qty == 0:
            continue
        hit = False
        if rung.kind == "target":
            hit = (observed_price-rung.target)*sign >= 0
        elif rung.kind == "extension" and first_done:
            if atr is not None and emas[rung.ema_period] is not None:
                hit = (observed_price-emas[rung.ema_period])*sign >= rung.atr_multiple*atr
            else:
                out["warnings"].append("Insufficient daily history for the ATR-extension trim.")
        # Small lots still need an exit even if first trim rounded to zero.
        elif rung.kind == "ema" and daily_close and (first_done or sizes[first.id] == 0):
            if emas[rung.ema_period] is not None:
                hit = (bars[-1].close-emas[rung.ema_period])*sign < 0
            else:
                out["warnings"].append(f"Insufficient daily history for EMA {rung.ema_period}.")
        if hit:
            # A breach of the final EMA liquidates all leftover allocation,
            # including extension/target portions that were never reached.
            if rung == campaign.rungs[-1]:
                qty = remaining
            qty = min(qty, remaining)
            if qty:
                out["decisions"].append(decision(rung.id, qty, f"{rung.kind} exit {rung.id} confirmed."))
                remaining -= qty
    return out


def record_fill(campaign: ExitCampaign, state: ExitState, *, fill_id: str, rung: str, qty: int) -> ExitState:
    """Idempotent incremental actual-fill update; not called on signal/submission."""
    if fill_id in state.fill_ids:
        return state
    if not fill_id or qty <= 0 or qty > state.remaining_qty:
        raise ValueError("invalid incremental exit fill")
    if rung not in {r.id for r in campaign.rungs} | {"stop", "expiry", "manual"}:
        raise ValueError("unknown exit rung")
    sold = {**state.sold, rung: state.sold.get(rung, 0)+qty}
    first = campaign.rungs[0]
    first_qty = allocations(campaign, state.initial_qty)[first.id]
    breakeven = state.breakeven or (first_qty > 0 and sold.get(first.id, 0) >= first_qty)
    stop = max(state.stop, state.entry) if state.direction == "long" else min(state.stop, state.entry)
    return ExitState(**{**state.model_dump(), "sold": sold, "remaining_qty": state.remaining_qty-qty,
                        "fill_ids": (*state.fill_ids, fill_id), "breakeven": breakeven,
                        "stop": stop if breakeven else state.stop})
