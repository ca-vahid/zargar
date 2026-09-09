"""Pure Cartel market/universe screen. A screen pass is NOT permission to trade."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...marketstructure.indicators import ema_series, true_range
from ...marketstructure.market_calendar import is_trading_day, previous_trading_day
from ...marketstructure.sessions import ET, session_bounds
from .data import DailyBar, complete_weeks, completed_daily, require_contiguous
from .rules import CartelRules


class ListingFacts(BaseModel):
    """Timestamped input; absence of a historical snapshot is not zero market cap."""
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    symbol: str
    observed_at: int = Field(ge=0)
    source: str = Field(min_length=1)
    market_cap: float | None = Field(default=None, gt=0)
    cap_observed_at: int | None = Field(default=None, ge=0)
    cap_data_as_of_ms: int | None = Field(default=None, ge=0)
    cap_source: str | None = None
    fundamentals_snapshot_id: str | None = None
    security_type: Literal["stock", "dr", "etf"] = "stock"
    industry: str | None = None
    membership_observed_at: int | None = Field(default=None, ge=0)
    membership_source: str | None = None
    membership_snapshot_id: str | None = None
    week_rank: int | None = Field(default=None, ge=1)
    month_rank: int | None = Field(default=None, ge=1)
    rank_direction: Literal["long", "short"] = "long"
    week_rank_best: int | None = Field(default=None, ge=1)
    month_rank_best: int | None = Field(default=None, ge=1)
    rank_observed_at: int | None = Field(default=None, ge=0)
    rank_data_as_of_ms: int | None = Field(default=None, ge=0)
    rank_source: str | None = Field(default=None, min_length=1)
    rank_freshness_basis: Literal['provider_time', 'publisher_observation'] = 'provider_time'
    industry_snapshot_id: str | None = None

    @model_validator(mode='after')
    def rank_evidence(self):
        if self.cap_data_as_of_ms is not None and self.cap_data_as_of_ms > (
                self.cap_observed_at if self.cap_observed_at is not None else self.observed_at):
            raise ValueError('capitalization data timestamp cannot follow its observation time')
        for best, worst in ((self.week_rank_best, self.week_rank), (self.month_rank_best, self.month_rank)):
            if best is not None and worst is not None and best > worst:
                raise ValueError('best industry rank cannot exceed worst rank')
        if self.rank_data_as_of_ms is not None and self.rank_data_as_of_ms > (
                self.rank_observed_at if self.rank_observed_at is not None else self.observed_at):
            raise ValueError('rank data timestamp cannot follow its observation time')
        return self


def _history(bars: list[DailyBar], at: int) -> list[DailyBar]:
    result = completed_daily(bars, at)
    require_contiguous(result)
    return result


def _latest_session(at: int) -> dt.date:
    today = dt.datetime.fromtimestamp(at / 1000, ET).date()
    if is_trading_day(today) and session_bounds(today.isoformat())[1] <= at:
        return today
    return previous_trading_day(today)


def _emas(bars: list[DailyBar], periods: tuple[int, ...]) -> dict[int, float | None]:
    return {p: ema_series([b.close for b in bars], p)[-1] if bars else None for p in periods}


def market_regime(indices: dict[str, list[DailyBar]], rules: CartelRules, at: int) -> dict:
    reads = {}
    for symbol in ("SPY", "QQQ"):
        bars = _history(indices.get(symbol, []), at)
        if bars and bars[-1].symbol != symbol:
            raise ValueError(f"{symbol} input contains a different symbol")
        emas = _emas(bars, rules.market_ema_periods)
        state = "unknown"
        if bars and bars[-1].session == _latest_session(at) and all(v is not None for v in emas.values()):
            above = all(bars[-1].close > v for v in emas.values())
            below = all(bars[-1].close < v for v in emas.values())
            state = "long" if above else "short" if below else "mixed"
        reads[symbol] = {"direction": state, "emas": {str(k): v for k, v in emas.items()},
                         "session": bars[-1].session.isoformat() if bars else None,
                         "close": bars[-1].close if bars else None,
                         "aboveEmas": {str(p): (bars[-1].close > value if bars and value is not None else None) for p, value in emas.items()}}
    directions = {v["direction"] for v in reads.values()}
    direction = "unknown" if "unknown" in directions else next(iter(directions)) if len(directions) == 1 else "mixed"
    return {"direction": direction, "indices": reads, "asOfMs": at,
            "sourceRules": ["M1", "S02", "S06"],
            "reason": "Require both indices on the same side of every selected EMA; otherwise watch-only."}


def screen_listing(bars: list[DailyBar], facts: ListingFacts, indices: dict[str, list[DailyBar]],
                   rules: CartelRules, at: int, *, direction: Literal["long", "short"] = "long") -> dict:
    if direction not in ("long", "short"):
        raise ValueError("direction must be long or short")
    history = _history(bars, at)
    if history and history[-1].symbol != facts.symbol:
        raise ValueError("listing facts and price history symbol mismatch")
    regime = market_regime(indices, rules, at)
    gates = []

    def gate(rule, label, passed, value=None):
        gates.append({"rule": rule, "label": label,
                      "status": "unknown" if passed is None else "pass" if passed else "fail",
                      "value": value})

    last = history[-1] if history else None
    periods = tuple(sorted({*rules.stock_ema_periods, 8, 21, 50}))
    emas = _emas(history, periods)
    adr = (sum((b.high - b.low) / b.low * 100 for b in history[-rules.adr_period:]) / rules.adr_period
           if len(history) >= rules.adr_period else None)
    ranges = [true_range(b.high, b.low, history[i-1].close if i else None) for i, b in enumerate(history)]
    atr = None
    if len(ranges) >= rules.atr_period:
        atr = sum(ranges[:rules.atr_period]) / rules.atr_period
        for value in ranges[rules.atr_period:]:
            atr = (atr * (rules.atr_period - 1) + value) / rules.atr_period
    age = at - facts.observed_at
    valid_facts = 0 <= age <= rules.max_metadata_age_days * 86_400_000
    mapping_at = facts.membership_observed_at if facts.membership_observed_at is not None else facts.observed_at
    valid_mapping = 0 <= at-mapping_at <= rules.max_metadata_age_days*86_400_000
    cap_observed = facts.cap_observed_at if facts.cap_observed_at is not None else facts.observed_at
    cap_data = facts.cap_data_as_of_ms if facts.cap_data_as_of_ms is not None else \
        None if facts.fundamentals_snapshot_id else cap_observed
    valid_cap = cap_data is not None and cap_observed <= at \
        and 0 <= at-cap_data <= rules.max_metadata_age_days*86_400_000
    observed = facts.rank_observed_at if facts.rank_observed_at is not None else facts.observed_at
    data_at = facts.rank_data_as_of_ms if facts.rank_data_as_of_ms is not None else \
        None if facts.industry_snapshot_id else observed
    rank_time = observed if facts.rank_freshness_basis == 'publisher_observation' else data_at
    rank_age_limit = min(rules.max_metadata_age_days, 1) if facts.rank_freshness_basis == 'publisher_observation' else rules.max_metadata_age_days
    valid_ranks = valid_mapping and rank_time is not None and observed <= at \
        and 0 <= at-rank_time <= rank_age_limit*86_400_000
    gate("M1", "Market agrees with direction", regime["direction"] == direction
         if regime["direction"] != "unknown" else None, regime["direction"])
    gate("DATA", "Latest completed exchange session present", last.session == _latest_session(at) if last else None)
    gate("M2", "Price above minimum", last.close > rules.min_price if last else None, last.close if last else None)
    if facts.security_type == 'etf':
        gate("M2", "Explicitly reviewed ETF with current classification (stock market cap not applicable)",
             facts.symbol in rules.reviewed_etfs and valid_facts, facts.symbol)
    else:
        gate("M2", "Source-dated market capitalization above minimum",
             facts.market_cap > rules.min_market_cap if valid_cap and facts.market_cap is not None else None,
             facts.market_cap if valid_cap else None)
    liquidity_volume = (sum(b.volume for b in history[-rules.volume_period:])/rules.volume_period
                        if len(history) >= rules.volume_period else None) if rules.volume_basis == "average" \
                        else last.volume if last else None
    volume_label = (f"{rules.volume_period}-session average volume above minimum"
                    if rules.volume_basis == "average" else "Completed session volume above minimum")
    gate("M2", volume_label, liquidity_volume > rules.min_volume if liquidity_volume is not None else None,
         liquidity_volume)
    relative_volume = None
    if len(history) > rules.relative_volume_period:
        previous_volume = sum(b.volume for b in history[-rules.relative_volume_period-1:-1])/rules.relative_volume_period
        if previous_volume > 0:
            relative_volume = last.volume/previous_volume
    if rules.min_relative_volume is not None:
        gate("M2", "Completed-session relative volume above minimum",
             relative_volume > rules.min_relative_volume if relative_volume is not None else None,
             relative_volume)
    gate("M2", "ADR above minimum", adr > rules.min_adr_pct if adr is not None else None, adr)
    trend = None
    if last and all(emas[p] is not None for p in rules.stock_ema_periods):
        trend = all((last.close - emas[p]) * (1 if direction == "long" else -1) > 0
                    for p in rules.stock_ema_periods)
    gate("M2", "Stock on direction side of selected EMAs", trend)
    if rules.require_positive_change:
        gate("M2", "Daily change agrees with direction", (history[-1].close - history[-2].close)
             * (1 if direction == "long" else -1) > 0 if len(history) >= 2 else None)
    if rules.require_industry_rank and facts.security_type != 'etf':
        known = valid_ranks and facts.industry and facts.rank_direction == direction
        periods = []
        for best, worst in ((facts.week_rank_best, facts.week_rank), (facts.month_rank_best, facts.month_rank)):
            periods.append(None if not known or worst is None else False if (best or worst) > rules.industry_top_n
                           else True if worst <= rules.industry_top_n else None)
        agreement = False if False in periods else True if all(p is True for p in periods) else None
        gate("M1", "Industry ranks in both weekly and monthly top list",
             agreement,
             {"industry": facts.industry if valid_mapping else None,
              "weekRank": facts.week_rank if valid_ranks else None,
              "monthRank": facts.month_rank if valid_ranks else None,
              "weekRankBest": facts.week_rank_best if valid_ranks else None,
              "monthRankBest": facts.month_rank_best if valid_ranks else None,
              "direction": facts.rank_direction, "source": facts.rank_source or facts.source,
              "observedAt": observed, "dataAsOfMs": data_at, "snapshotId": facts.industry_snapshot_id})
    facts_view = facts.model_dump(mode='json') if valid_facts else {
        'symbol': facts.symbol, 'source': facts.source, 'observed_at': facts.observed_at, 'available': False}
    facts_view.update(market_cap=facts.market_cap if valid_cap else None,
                      cap_observed_at=cap_observed, cap_data_as_of_ms=cap_data,
                      cap_source=facts.cap_source or facts.source,
                      fundamentals_snapshot_id=facts.fundamentals_snapshot_id)
    if not valid_facts and not valid_cap:
        facts_view.pop('market_cap', None)
    if facts.membership_snapshot_id:
        facts_view.update(industry=facts.industry if valid_mapping else None,
                          membership_snapshot_id=facts.membership_snapshot_id,
                          membership_observed_at=mapping_at, membership_source=facts.membership_source)
    if valid_facts and not valid_ranks:
        for key in ('week_rank', 'month_rank', 'week_rank_best', 'month_rank_best'):
            facts_view[key] = None
    return {"symbol": facts.symbol, "direction": direction, "asOfMs": at,
            "screenPassed": all(g["status"] == "pass" for g in gates),
            "researchPassed": all(g["status"] == "pass" for g in gates if g["label"] != "Market agrees with direction"),
            "gates": gates, "market": regime, "config": rules.snapshot(),
            "facts": facts_view,
            "metrics": {"adrPct": adr, "atr": atr, "dailyVolume": last.volume if last else None,
                        "liquidityVolume": liquidity_volume, "volumeBasis": rules.volume_basis,
                        "relativeVolume": relative_volume, "relativeVolumePeriod": rules.relative_volume_period,
                        "volumePeriod": rules.volume_period if rules.volume_basis == "average" else 1,
                        "emas": {str(k): v for k, v in sorted(emas.items())},
                        "completeWeeks": complete_weeks(history, at)},
            "nextStep": "Assess weekly/daily setup, entry, invalidation and expression; screen is not an arm."}


def focus_list(reads: list[dict], rules: CartelRules) -> list[dict]:
    """Screen shortlist only: volume order from S02, stable symbol tie-break."""
    if len({r["symbol"] for r in reads}) != len(reads):
        raise ValueError("duplicate symbols in focus-list input")
    return sorted((r for r in reads if r["screenPassed"]),
                  key=lambda r: (-r["metrics"]["dailyVolume"], r["symbol"]))[:rules.focus_count]
