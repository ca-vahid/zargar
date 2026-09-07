"""Dated industry captures with honest rank uncertainty; no provider/order I/O."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from .service import WireModel


class IndustryPerformance(WireModel):
    industry: str = Field(min_length=1, max_length=160)
    week_pct: float | None = None
    month_pct: float | None = None


class IndustrySnapshot(WireModel):
    source: str = Field(min_length=1, max_length=2000)
    observed_at: int = Field(ge=0)
    data_as_of_ms: int | None = Field(default=None, ge=0)
    freshness_basis: Literal['provider_time', 'publisher_observation'] = 'provider_time'
    expected_count: int = Field(ge=1, le=500)
    week_definition: str = Field(min_length=1, max_length=300)
    month_definition: str = Field(min_length=1, max_length=300)
    rows: list[IndustryPerformance] = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def coherent_capture(self):
        if self.data_as_of_ms is not None and self.data_as_of_ms > self.observed_at:
            raise ValueError('data timestamp cannot follow its observation time')
        names = [r.industry.strip().casefold() for r in self.rows]
        if len(self.rows) != self.expected_count or len(set(names)) != len(names) or any(not n for n in names):
            raise ValueError('capture must contain the expected number of unique named industries')
        if any(not value.strip() for value in (self.source, self.week_definition, self.month_definition)):
            raise ValueError('source and period definitions cannot be blank')
        return self


def rank_bounds(snapshot: IndustrySnapshot, row: IndustryPerformance, period: Literal['week', 'month'], direction):
    value = getattr(row, period+'_pct')
    if value is None:
        return None
    values = [getattr(r, period+'_pct') for r in snapshot.rows]
    sign = 1 if direction == 'long' else -1
    better = sum(v is not None and v*sign > value*sign for v in values)
    equal = sum(v == value for v in values)
    unknown = sum(v is None for v in values)
    return {'best': better+1, 'worst': better+equal+unknown}


def captured_ranks(snapshot: IndustrySnapshot):
    """Descriptive ordering within a capture, independent of trading eligibility."""
    return {row.industry: {label: {
        'weekRank': rank_bounds(snapshot, row, 'week', direction),
        'monthRank': rank_bounds(snapshot, row, 'month', direction)}
        for label, direction in (('bullish', 'long'), ('bearish', 'short'))}
        for row in snapshot.rows}


def read_industry(snapshot: IndustrySnapshot, industry: str, *, at: int, direction='long', top_n=10, max_age_days=7):
    if direction not in ('long', 'short') or top_n < 1 or max_age_days < 0:
        raise ValueError('invalid industry rank policy')
    out = {'industry': industry, 'status': 'unknown', 'weekRank': None, 'monthRank': None,
           'freshnessBasis': snapshot.freshness_basis,
           'source': snapshot.source, 'observedAt': snapshot.observed_at, 'dataAsOfMs': snapshot.data_as_of_ms}
    effective_time = snapshot.observed_at if snapshot.freshness_basis == 'publisher_observation' else snapshot.data_as_of_ms
    age_limit = min(max_age_days, 1) if snapshot.freshness_basis == 'publisher_observation' else max_age_days
    if effective_time is None:
        return {**out, 'reason': 'Source data timestamp is unavailable; freshness cannot be established.'}
    if not snapshot.observed_at <= at or at-effective_time > age_limit*86_400_000:
        return {**out, 'reason': 'Snapshot was not yet available or its underlying data is stale.'}
    row = next((r for r in snapshot.rows if r.industry.strip().casefold() == industry.strip().casefold()), None)
    if row is None:
        return {**out, 'reason': 'Industry is absent from the captured universe.'}
    week, month = (rank_bounds(snapshot, row, period, direction) for period in ('week', 'month'))
    status = 'fail' if any(b and b['best'] > top_n for b in (week, month)) else \
        'pass' if all(b and b['worst'] <= top_n for b in (week, month)) else 'unknown'
    return {**out, 'status': status, 'weekRank': week, 'monthRank': month,
            'reason': 'Rank intervals include displayed ties and industries with missing values.'}


async def save_snapshot(service, body: IndustrySnapshot, *, now_ms=None):
    now = now_ms if now_ms is not None else int(dt.datetime.now(dt.UTC).timestamp()*1000)
    if body.observed_at > now:
        raise ValueError('snapshot observation cannot be in the future')
    inputs = body.model_dump(mode='json')
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    return await service._store(mode='industry', symbol='MULTI', at=body.observed_at, verdict='snapshot',
        config={'inputs': inputs, 'inputSha256': digest, 'dataSource': body.source, 'codeVersion': 'cartel-industry-1'},
        result={'placesOrders': False, 'count': len(body.rows),
                'warnings': ['User-supplied capture; source accuracy and stock membership require verification.'],
                'rows': [{'industry': row.industry, 'weekPct': row.week_pct, 'monthPct': row.month_pct,
                          'bullish': read_industry(body, row.industry, at=body.observed_at),
                          'bearish': read_industry(body, row.industry, at=body.observed_at, direction='short')}
                         for row in body.rows]})
