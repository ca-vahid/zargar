"""Read-only collection through shared history, with a scoped HTTP client.

No fabricated fundamentals or industry ranks. Those are independently sourced
point-in-time inputs and remain visibly missing until supplied/collected.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
from typing import Literal

import httpx
from pydantic import Field

from ...marketstructure.history import UA, fetch_window
from ...marketstructure.sessions import ET
from .data import DailyBar, completed_daily
from .rules import CartelRules, ScreenProfile
from .service import FactsInput, MinuteInput, ResearchInput, WireModel
from .setups import SetupParameters

log = logging.getLogger("zargar.options_cartel.collect")


class CollectInput(WireModel):
    membership_snapshot_id: str | None = Field(default=None, max_length=64)
    fundamentals_snapshot_id: str | None = Field(default=None, max_length=64)
    industry_snapshot_id: str | None = Field(default=None, max_length=64)
    symbol: str = Field(min_length=1, max_length=12, pattern=r"^[A-Za-z][A-Za-z0-9.\-]{0,11}$")
    as_of_ms: int | None = Field(default=None, ge=0)
    facts: FactsInput | None = None
    profile: ScreenProfile = "september_2026"
    direction: Literal["long", "short"] = "long"
    daily_lookback_days: int = Field(default=550, ge=180, le=1500)
    minute_lookback_days: int = Field(default=19, ge=7, le=20)


def normalize_daily(bars, symbol, at):
    result = []
    for b in bars:
        if b.symbol != symbol or b.tf != "1d":
            raise ValueError("history provider returned a different daily series")
        opened = dt.datetime.fromtimestamp(b.ts/1000, ET)
        # Shared daily history currently comes from Yahoo, with exchange-open
        # timestamps. Fail visibly if that convention changes instead of shifting
        # a UTC-midnight bar to the prior ET session.
        if (opened.hour, opened.minute) != (9, 30):
            raise ValueError("daily provider timestamp is not the expected US exchange open")
        result.append(DailyBar(symbol=symbol, session=opened.date(), open=b.open, high=b.high,
                               low=b.low, close=b.close, volume=b.volume))
    return completed_daily(result, at)


async def collect_inputs(body: CollectInput, *, fetch=fetch_window, now_ms=None) -> tuple[ResearchInput, dict]:
    now = now_ms if now_ms is not None else int(dt.datetime.now(dt.UTC).timestamp()*1000)
    at = body.as_of_ms if body.as_of_ms is not None else now
    if at > now:
        raise ValueError("cannot collect market data from a future as-of time")
    symbol = body.symbol.upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", symbol):
        raise ValueError("unsupported US equity symbol")
    rules = CartelRules.for_profile(body.profile)
    warnings = []
    facts = body.facts
    if facts is not None and facts.symbol.upper() != symbol:
        raise ValueError("metadata symbol must match requested symbol")
    if facts is None:
        facts = FactsInput(symbol=symbol, observed_at=at, source="Missing fundamental/industry snapshot")
        missing = "Market cap and industry rankings" if rules.require_industry_rank else "Market cap"
        if body.fundamentals_snapshot_id:
            warnings.append('Selected capitalization capture will be checked separately; industry evidence is missing.')
        else:
            warnings.append(f"{missing} missing; screen remains watch-only.")
    else:
        facts = facts.model_copy(update={"symbol": symbol})
    start = at-body.daily_lookback_days*86_400_000
    symbols = list(dict.fromkeys([symbol, "SPY", "QQQ"]))
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": UA}, follow_redirects=True) as client:
        daily = await asyncio.gather(*(fetch(s, "1d", start, at, client=client) for s in symbols),
                                     return_exceptions=True)
        normalized = {}
        for s, values in zip(symbols, daily):
            if isinstance(values, Exception):
                if s == symbol:
                    raise ValueError(f"daily history unavailable for {symbol}: {values}") from values
                warnings.append(f"{s} market context unavailable: {values}")
                normalized[s] = []
            else:
                normalized[s] = normalize_daily(values, s, at)
        if not normalized[symbol]:
            raise ValueError("no completed daily history available for this symbol/as-of time")
        try:
            minute_bars = await fetch(symbol, "1m", at-body.minute_lookback_days*86_400_000, at, client=client)
        except Exception as exc:
            log.exception("Cartel intraday collection failed for %s", symbol)
            warnings.append(f"Intraday history unavailable; entry volume baseline will be missing: {exc}")
            minute_bars = []
    minutes = []
    for b in minute_bars:
        if b.ts+60_000 > at:
            continue
        if b.symbol != symbol or b.tf != "1m":
            raise ValueError("history provider returned a different minute series")
        minutes.append(MinuteInput(symbol=b.symbol, ts=b.ts, open=b.open, high=b.high, low=b.low,
                                   close=b.close, volume=b.volume))
    source = "Shared history: Yahoo daily; configured Alpaca SIP intraday with Yahoo fallback. Metadata: " + facts.source
    if body.fundamentals_snapshot_id:
        source += '. Capitalization: selected saved provider capture ' + body.fundamentals_snapshot_id
    research = ResearchInput(membership_snapshot_id=body.membership_snapshot_id,
                             fundamentals_snapshot_id=body.fundamentals_snapshot_id,
                             industry_snapshot_id=body.industry_snapshot_id,
                             history=normalized[symbol], indices={s: normalized[s] for s in ("SPY", "QQQ")},
                             facts=facts, rules=rules, parameters=SetupParameters(), minute_history=minutes,
                             as_of_ms=at, direction=body.direction, data_source=source)
    provenance = {"collectedAt": now, "asOfMs": at, "source": source, "warnings": warnings,
                  "counts": {"daily": {s: len(bs) for s, bs in normalized.items()}, "minutes": len(minutes)},
                  "requestedDays": {"daily": body.daily_lookback_days, "minute": body.minute_lookback_days},
                  "historicalMetadataProvided": body.facts is not None,
                  "note": "Provider lookback limits can reduce minute coverage; missing data is never synthesized."}
    return research, provenance
