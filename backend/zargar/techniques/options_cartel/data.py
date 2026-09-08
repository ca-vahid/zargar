"""Causal regular-session daily inputs with explicit exchange dates.

Providers must map their UTC/daily timestamp convention to a session date at
the boundary. Never infer a session by adding 24h to a daily candle timestamp.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...marketstructure.market_calendar import is_trading_day
from ...marketstructure.sessions import session_bounds


class DailyBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    symbol: str = Field(min_length=1)
    session: dt.date
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: int = Field(ge=0)

    @model_validator(mode="after")
    def valid_candle(self):
        if self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close):
            raise ValueError("invalid OHLC geometry")
        if not is_trading_day(self.session):
            raise ValueError("daily bar session is not an exchange trading day")
        return self

    @property
    def closes_at(self) -> int:
        return session_bounds(self.session.isoformat())[1]


def completed_daily(bars: list[DailyBar], as_of_ms: int) -> list[DailyBar]:
    """Ignore unfinished/future sessions; reject ambiguous inputs instead of guessing."""
    seen: dict[dt.date, DailyBar] = {}
    for bar in bars:
        if bar.closes_at > as_of_ms:
            continue
        if bar.session in seen and seen[bar.session] != bar:
            raise ValueError(f"conflicting daily bars for {bar.session}")
        seen[bar.session] = bar
    result = sorted(seen.values(), key=lambda b: b.session)
    if len({b.symbol for b in result}) > 1:
        raise ValueError("daily history must contain one symbol")
    return result


def complete_weeks(bars: list[DailyBar], as_of_ms: int) -> list[dict]:
    """Aggregate only closed, fully represented exchange weeks (including half days)."""
    groups: dict[dt.date, list[DailyBar]] = defaultdict(list)
    for bar in completed_daily(bars, as_of_ms):
        monday = bar.session - dt.timedelta(days=bar.session.weekday())
        groups[monday].append(bar)
    out = []
    for monday, group in sorted(groups.items()):
        sessions = [monday + dt.timedelta(days=n) for n in range(5)
                    if is_trading_day(monday + dt.timedelta(days=n))]
        if not sessions or session_bounds(sessions[-1].isoformat())[1] > as_of_ms:
            continue
        if [b.session for b in group] != sessions:
            continue  # A partial provider week is not a lower-volume/tighter real week.
        out.append({"week": monday.isoformat(), "lastSession": sessions[-1].isoformat(),
                    "open": group[0].open, "high": max(b.high for b in group),
                    "low": min(b.low for b in group), "close": group[-1].close,
                    "volume": sum(b.volume for b in group), "sessions": len(group)})
    return out


def require_contiguous(bars: list[DailyBar]) -> None:
    for left, right in pairwise(bars):
        day = left.session + dt.timedelta(days=1)
        while day < right.session:
            if is_trading_day(day):
                raise ValueError(f"missing regular-session bar: {day}")
            day += dt.timedelta(days=1)
