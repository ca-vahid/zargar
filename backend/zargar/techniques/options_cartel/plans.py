"""Reviewable Cartel plan data. No orders, database calls, or other desks' policies."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...marketstructure.market_calendar import is_trading_day
from ...marketstructure.sessions import session_bounds
from .rules import CartelRules


class EntryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    timeframe_minutes: Literal[5, 15, 30] = 15
    mode: Literal["breakout", "retest"] = "breakout"
    # S12 (July 2025): an opening gap must retest, never be chased. Opt-in
    # preserves the interpretation of already-saved plan snapshots.
    allow_gap_retest: bool = False
    stop_mode: Literal["session_extreme", "breakout_bar", "preplanned"] = "session_extreme"
    # Explicit engineering choices until calibrated, never claimed as author numbers.
    volume_multiple: float = Field(default=1.5, gt=0)
    min_close_location: float = Field(default=0.7, ge=0, le=1)
    retest_tolerance_pct: float = Field(default=0.25, ge=0, le=5)
    baseline_policy: Literal['full_session', 'covered_periods'] = 'full_session'
    min_target_r: float = Field(default=0, ge=0, le=10)  # legacy snapshots retain their old behavior
    max_chase_r: float = Field(default=0.5, ge=0, le=10)


class CartelPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    direction: Literal["long", "short"]
    setup: Literal["base", "flag", "pennant", "wedge", "inside_day", "ma_pullback", "breakout_retest", "ascending_triangle"]
    created_at: int = Field(ge=0)
    first_session: dt.date
    last_session: dt.date
    trigger: float = Field(gt=0)
    invalidation: float = Field(gt=0)
    targets: tuple[float, ...] = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    rules: CartelRules = Field(default_factory=CartelRules)
    entry: EntryPolicy = Field(default_factory=EntryPolicy)
    # A source-dated same-time-of-day baseline for each RTH bucket. No daily-total
    # shortcut: 09:45 volume must be compared with historical 09:45 volume.
    volume_baseline: dict[int, float] = Field(default_factory=dict)
    baseline_as_of: int = Field(ge=0)

    @model_validator(mode="after")
    def geometry_and_provenance(self):
        if not self.symbol.strip() or not self.id.strip() or not self.rationale.strip() \
                or any(not ref.strip() for ref in self.source_refs):
            raise ValueError("plan identity and source rationale must not be blank")
        sign = 1 if self.direction == "long" else -1
        if (self.trigger - self.invalidation) * sign <= 0:
            raise ValueError("invalidation must be on the loss side of the trigger")
        previous = self.trigger
        for target in self.targets:
            if target <= 0 or (target - previous) * sign <= 0:
                raise ValueError("targets must progress beyond trigger in the trade direction")
            previous = target
        if not is_trading_day(self.first_session) or not is_trading_day(self.last_session):
            raise ValueError("plan endpoints must be exchange sessions")
        if self.last_session < self.first_session:
            raise ValueError("plan horizon is reversed")
        if self.created_at >= session_bounds(self.last_session.isoformat())[1]:
            raise ValueError("plan was created after its horizon closed")
        if self.baseline_as_of > self.created_at:
            raise ValueError("volume baseline cannot come from the future")
        max_buckets = 390 // self.entry.timeframe_minutes
        if any(k < 0 or k >= max_buckets or v <= 0 for k, v in self.volume_baseline.items()):
            raise ValueError("volume baseline requires valid RTH bucket indices and positive volumes")
        return self

    def snapshot(self) -> dict:
        return {"technique": "options_cartel", "version": "cartel-plan-1",
                "plan": self.model_dump(mode="json"), "screenRules": self.rules.snapshot(),
                "entryInterpretation": {
                    "confirmation": "closed RTH bucket; no entry before plan creation",
                    "stop": "session_extreme freezes the RTH low/high seen at confirmation, not final daily low/high",
                    "engineering": ["volume_multiple", "min_close_location", "retest_tolerance_pct", "max_chase_r"],
                    "execution": "signal close is a reference, never a promise of a fill"}}
