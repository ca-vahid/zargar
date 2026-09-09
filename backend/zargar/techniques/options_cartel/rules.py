"""Versioned Cartel screening rules; never import another technique's rulebook."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

METHOD_SOURCES = {
    "september_2026": ["S01", "S02", "S06"],
    "june_2026": ["S02", "S06"],
    "june_2026_image": ["S02", "S06"],
    "september_2026_video": ["S24"],
    "may_2026": ["S04", "S06"],
    "may_2026_image": ["S04", "S06"],
}


ScreenProfile = Literal["september_2026", "september_2026_video", "june_2026", "june_2026_image", "may_2026", "may_2026_image"]


class CartelRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    version: Literal["cartel-screen-1"] = "cartel-screen-1"
    profile: ScreenProfile = "september_2026"
    min_price: float = Field(default=3.0, gt=0)
    min_market_cap: float = Field(default=300_000_000, gt=0)
    min_volume: int = Field(default=500_000, ge=0)
    # Legacy snapshots omitted these: preserve their last-session interpretation.
    volume_basis: Literal["last_session", "average"] = "last_session"
    volume_period: int = Field(default=10, ge=1, le=252)
    min_relative_volume: float | None = Field(default=None, ge=0)
    relative_volume_period: int = Field(default=10, ge=1, le=252)
    min_adr_pct: float = Field(default=3.0, gt=0)
    stock_ema_periods: tuple[int, ...] = (21, 50)
    market_alignment: Literal['strict', 'moderate'] = 'strict'
    market_ema_periods: tuple[int, ...] = (8, 21, 50)
    require_positive_change: bool = False
    industry_top_n: int = Field(default=10, ge=1)
    require_industry_rank: bool = True
    reviewed_etfs: tuple[str, ...] = ()
    focus_count: int = Field(default=5, ge=1, le=50)
    # Explicit engineering definitions, NOT numbers attributed to Sean.
    adr_period: int = Field(default=20, ge=2, le=252)
    atr_period: int = Field(default=14, ge=2, le=252)
    max_metadata_age_days: int = Field(default=7, ge=0, le=90)

    @model_validator(mode="before")
    @classmethod
    def profile_defaults(cls, data):
        if isinstance(data, dict):
            data = dict(data)
            profile = data.get('profile')
            defaults = {}
            if profile in ('may_2026', 'may_2026_image'):
                defaults.update(min_adr_pct=2., stock_ema_periods=(8, 21), market_ema_periods=(8, 21),
                                require_positive_change=True, require_industry_rank=False, focus_count=10)
            if profile == 'june_2026':
                defaults.update(require_industry_rank=False)
            if profile in ('june_2026_image', 'september_2026_video', 'may_2026_image'):
                defaults.update(min_adr_pct=2., volume_basis='average', volume_period=10,
                                require_industry_rank=False, stock_ema_periods=(21, 50), require_positive_change=False)
            if profile == 'september_2026_video':
                defaults.update(min_relative_volume=1.)
            for key, value in defaults.items():
                data.setdefault(key, value)
        return data

    @model_validator(mode="after")
    def validate_periods(self):
        for periods in (self.stock_ema_periods, self.market_ema_periods):
            if not periods or any(p < 1 or p > 252 for p in periods) or len(set(periods)) != len(periods):
                raise ValueError("EMA periods must be unique positive periods up to 252")
        return self

    @classmethod
    def for_profile(cls, profile: str, **overrides) -> CartelRules:
        values = {"profile": profile}
        values.update(overrides)
        return cls(**values)

    def snapshot(self) -> dict:
        return {
            "technique": "options_cartel", "rules": self.model_dump(mode="json"),
            "sources": METHOD_SOURCES[self.profile],
            "engineeringDefinitions": {
                "adr": "mean((high-low)/low*100) over completed daily bars",
                "atr": "Wilder ATR seeded by mean true range",
                "volume": (f"mean share volume of {self.volume_period} completed regular sessions"
                           if self.volume_basis == "average" else "last completed regular-session daily share volume"),
                "relativeVolume": f"completed session volume / mean of previous {self.relative_volume_period} sessions, excluding that session; not intraday relative volume at time",
                "sourceDiscrepancy": "June text states ADR >3%; screenshot states ADR >2% and 10-day average volume >500K.",
                "marketAgreement": ("Practice experiment: one index above 8/21/50; both above 50 for bullish alignment; bearish alignment remains strict" if self.market_alignment == "moderate" else "both SPY and QQQ must agree; mixed means watch-only"),
                "bearishScreen": "directional mirror for puts; no share shorting",
                "metadataAge": "calendar-day limit, source observation time required",
                "septemberScreen": "June numerical screen retained where September gives no replacement",
            },
        }
