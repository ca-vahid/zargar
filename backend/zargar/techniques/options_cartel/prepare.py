"""Compose a screened, reviewed setup into an immutable entry plan.

Volume references use complete historical RTH buckets on already-closed
sessions. This service is pure; persistence and user authorization are separate.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from statistics import median

from ...domain import Bar
from ...marketstructure.market_calendar import is_trading_day, next_trading_day
from ...marketstructure.sessions import ET, next_session_date, session_bounds
from .data import DailyBar
from .plans import CartelPlan, EntryPolicy
from .rules import CartelRules
from .screen import ListingFacts, screen_listing
from .setups import SetupParameters, analyze_setups

MINUTE = 60_000


def build_volume_baseline(minutes: list[Bar], symbol: str, timeframe_minutes: int,
                          as_of_ms: int, *, sessions: int = 20, min_samples: int = 5) -> dict:
    if timeframe_minutes not in (5, 15, 30) or sessions < 1 or not 1 <= min_samples <= sessions:
        raise ValueError("invalid baseline window")
    days = defaultdict(dict)
    for bar in minutes:
        day = dt.datetime.fromtimestamp(bar.ts/1000, ET).date()
        if not is_trading_day(day):
            continue
        start, end = session_bounds(day.isoformat())
        if end > as_of_ms or not start <= bar.ts < end:
            continue
        if bar.symbol != symbol or bar.tf != "1m" or bar.ts % MINUTE:
            raise ValueError("baseline requires aligned symbol-matched regular-session minutes")
        if not math.isfinite(bar.volume) or bar.volume < 0:
            raise ValueError("invalid baseline volume")
        if bar.ts in days[day] and days[day][bar.ts] != bar.volume:
            raise ValueError("conflicting baseline minute volume")
        days[day][bar.ts] = bar.volume
    samples = defaultdict(list)
    for day in sorted(days)[-sessions:]:
        start, end = session_bounds(day.isoformat())
        for bucket in range(start, end, timeframe_minutes*MINUTE):
            timestamps = range(bucket, bucket+timeframe_minutes*MINUTE, MINUTE)
            if all(ts in days[day] for ts in timestamps):
                samples[(bucket-start)//(timeframe_minutes*MINUTE)].append(sum(days[day][ts] for ts in timestamps))
    usable = {k: float(median(v)) for k, v in samples.items() if len(v) >= min_samples and median(v) > 0}
    return {"asOfMs": as_of_ms, "timeframeMinutes": timeframe_minutes, "symbol": symbol,
            "sessions": sessions, "minSamples": min_samples, "aggregation": "median",
            "baselines": usable, "sampleCounts": {k: len(v) for k, v in samples.items()},
            "sourceSessions": [d.isoformat() for d in sorted(days)[-sessions:]],
            "minuteCoverage": {d.isoformat(): {"present": len(days[d]), "expected": (session_bounds(d.isoformat())[1]-session_bounds(d.isoformat())[0])//MINUTE} for d in sorted(days)[-sessions:]},
            "definition": "Engineering: median of complete same-time buckets; excludes unfinished sessions."}


def prepare_plan(*, plan_id: str, history: list[DailyBar], indices: dict[str, list[DailyBar]],
                 facts: ListingFacts, rules: CartelRules, parameters: SetupParameters,
                 entry_policy: EntryPolicy, minute_history: list[Bar], as_of_ms: int,
                 direction: str, setup: str, horizon_sessions: int,
                 reviewed_targets: tuple[float, ...] | None = None,
                 review_note: str, target_source: str | None = None) -> dict:
    if horizon_sessions < 1 or horizon_sessions > 60:
        raise ValueError("plan horizon must be 1–60 trading sessions")
    if not review_note.strip():
        raise ValueError("setup review note is required")
    screen = screen_listing(history, facts, indices, rules, as_of_ms, direction=direction)
    analysis = analyze_setups(history, indices.get("SPY", []), screen, parameters, as_of_ms, direction=direction)
    candidates = [c for c in analysis["candidates"] if c["setup"] == setup]
    if not candidates:
        raise ValueError("selected setup is not present in this analysis")
    candidate = candidates[0]
    if not candidate["contextPassed"]:
        failed = [c["name"] for c in analysis["checks"] if c["status"] != "pass"]
        raise ValueError("setup context did not pass: " + ", ".join(failed))
    targets = reviewed_targets if reviewed_targets is not None else tuple(candidate["targets"])
    if not targets:
        raise ValueError("no confirmed historical targets; supply reviewed levels with a source")
    if reviewed_targets is not None and not (target_source or "").strip():
        raise ValueError("reviewed target levels require a source/rationale")
    baseline = build_volume_baseline(minute_history, facts.symbol, entry_policy.timeframe_minutes, as_of_ms)
    first = dt.date.fromisoformat(next_session_date(as_of_ms))
    last = first
    for _ in range(horizon_sessions-1):
        last = next_trading_day(last)
    refs = tuple(analysis["sources"]) + ((target_source,) if target_source else ())
    plan = CartelPlan(id=plan_id, symbol=facts.symbol, direction=direction, setup=setup,
                      created_at=as_of_ms, first_session=first, last_session=last,
                      trigger=candidate["trigger"], invalidation=candidate["invalidation"], targets=targets,
                      source_refs=refs, rationale=review_note, rules=rules, entry=entry_policy,
                      volume_baseline=baseline["baselines"], baseline_as_of=as_of_ms)
    return {"plan": plan.snapshot(), "screen": screen, "analysis": analysis,
            "volumeBaseline": baseline, "review": {"note": review_note, "targetSource": target_source,
                                                     "targetsOverridden": reviewed_targets is not None},
            "warnings": [] if baseline["baselines"] else ["No complete historical volume baseline; entry stays watch-only."]}
