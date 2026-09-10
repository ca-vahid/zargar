"""One causal entry read for live observation and replay. Returns signals, not fills.

Call on the available minute history; a stable event id lets the live adapter
persist consumption before routing. Completeness and post-creation crossing are
required. A later candle cannot supply a better earlier stop or trigger.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from ...domain import Bar
from ...marketstructure.market_calendar import is_trading_day
from ...marketstructure.sessions import ET, session_bounds
from .plans import CartelPlan

MINUTE = 60_000


def read_entry(plan: CartelPlan, minutes: list[Bar], as_of_ms: int, *, entry_after: int | None = None) -> dict:
    """An observation cutoff suppresses missed entries, never prior invalidations.

    Live recovery supplies its durable resume timestamp. Historical replay leaves
    it unset. Both paths still use the same closed-bar decision logic.
    """
    trace = []

    def result(status, signal=None):
        return {"planId": plan.id, "status": status, "signal": signal, "trace": trace}

    if as_of_ms < plan.created_at:
        return result("not_created")
    days: dict[dt.date, dict[int, Bar]] = defaultdict(dict)
    for bar in minutes:
        if bar.ts + MINUTE > as_of_ms:
            continue
        day = dt.datetime.fromtimestamp(bar.ts / 1000, ET).date()
        if day < plan.first_session or day > plan.last_session or not is_trading_day(day):
            continue
        opens, closes = session_bounds(day.isoformat())
        if bar.ts < opens or bar.ts >= closes:
            continue
        if bar.symbol != plan.symbol or bar.tf != "1m" or bar.ts % MINUTE:
            raise ValueError("entry read requires symbol-matched, minute-aligned 1m bars")
        values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
        if not all(math.isfinite(v) for v in values) or min(values[:4]) <= 0 or bar.volume < 0:
            raise ValueError("invalid entry candle values")
        if bar.high < max(values[:4]) or bar.low > min(values[:4]):
            raise ValueError("invalid entry candle geometry")
        if bar.ts in days[day] and days[day][bar.ts] != bar:
            raise ValueError("conflicting minute bars")
        days[day][bar.ts] = bar

    sign = 1 if plan.direction == "long" else -1
    broke_at = None
    missing = False
    step = plan.entry.timeframe_minutes
    for day, day_bars in sorted(days.items()):
        opens, closes = session_bounds(day.isoformat())
        previous_close = None
        broke_at = None  # a new session needs a new observed break; gap opens aren't assumed entries
        gap_at = None
        for start in range(opens, min(closes, as_of_ms), step * MINUTE):
            end = start + step * MINUTE
            if end > min(closes, as_of_ms):
                continue
            expected = list(range(start, end, MINUTE))
            if not all(ts in day_bars for ts in expected):
                missing = True
                previous_close = None
                broke_at = None
                gap_at = None
                trace.append({"at": end, "rule": "DATA", "decision": "missing_bucket",
                              "reason": "Incomplete confirmation bucket; no crossing inferred across a data gap."})
                continue
            bucket = [day_bars[ts] for ts in expected]
            high, low = max(b.high for b in bucket), min(b.low for b in bucket)
            close, opening = bucket[-1].close, bucket[0].open
            before = previous_close if previous_close is not None else opening
            previous_close = close
            if start < plan.created_at:
                continue  # an old/partly elapsed bucket cannot become a newly armed entry
            if (close - plan.invalidation) * sign <= 0:
                trace.append({"at": end, "rule": "M4", "decision": "invalidated",
                              "reason": "Closed confirmation bar broke the plan's pre-entry invalidation."})
                return result("invalidated")
            if entry_after is not None and start < entry_after:
                broke_at = gap_at = None
                continue  # keep session extremes and invalidations, but require a new observed setup
            if start == opens and plan.entry.mode == "retest" and plan.entry.allow_gap_retest \
                    and (opening-plan.trigger)*sign > 0:
                gap_at = opens
                trace.append({"at": opens, "rule": "S12", "decision": "gap_observed",
                              "reason": "Opened beyond the planned level; require a completed retest, never chase the gap."})
            crossed = (before - plan.trigger) * sign <= 0 < (close - plan.trigger) * sign
            baseline = plan.volume_baseline.get((start - opens) // (step * MINUTE))
            volume = sum(b.volume for b in bucket)
            location = ((close - low) if sign == 1 else (high - close)) / (high - low) if high > low else 0
            if crossed and baseline is not None and volume >= baseline * plan.entry.volume_multiple \
                    and location >= plan.entry.min_close_location:
                broke_at = end
                if plan.entry.mode == "retest":
                    trace.append({"at": end, "rule": "M4", "decision": "break_confirmed",
                                  "reason": "Volume-supported break observed; await a later retest candle."})
            elif crossed and plan.entry.mode == "retest":
                trace.append({"at": end, "rule": "M3/M4", "decision": "break_unconfirmed",
                              "reason": "Crossing lacks the required volume/close quality; retest not armed."})
            if plan.entry.mode == "retest":
                tolerance = plan.trigger * plan.entry.retest_tolerance_pct / 100
                touched = low <= plan.trigger + tolerance and high >= plan.trigger - tolerance
                anchor = gap_at if gap_at is not None else broke_at
                ready = anchor is not None and end > anchor and touched and (close - plan.trigger) * sign > 0
            else:
                ready = crossed
            if not ready:
                if (close-plan.targets[0])*sign >= 0:
                    trace.append({"at": end, "rule": "M4", "decision": "target_passed",
                                  "reason": "First target is already behind the current price; no new qualifying crossing. Reassess the next plan."})
                continue
            reasons = []
            if baseline is None:
                reasons.append("No historical same-time confirmation-volume baseline.")
            elif volume < baseline * plan.entry.volume_multiple:
                reasons.append("Breakout volume is below the snapshotted confirmation threshold.")
            if location < plan.entry.min_close_location:
                reasons.append("Close is not near the directional edge of the confirmation candle.")
            risk_at_trigger = abs(plan.trigger - plan.invalidation)
            if (close - plan.trigger) * sign > risk_at_trigger * plan.entry.max_chase_r:
                reasons.append("Confirmation exceeded the plan's never-chase distance.")
            if (plan.targets[0] - close) * sign <= 0:
                reasons.append("First target has already been reached before entry.")
            stop = plan.invalidation
            if plan.entry.stop_mode == "breakout_bar":
                stop = low if sign == 1 else high
            elif plan.entry.stop_mode == "session_extreme":
                session_minutes = list(range(opens, end, MINUTE))
                if not all(ts in day_bars for ts in session_minutes):
                    reasons.append("Cannot determine the session extreme with missing minutes since the open.")
                else:
                    seen = [day_bars[ts] for ts in session_minutes]
                    stop = min(b.low for b in seen) if sign == 1 else max(b.high for b in seen)
            if (close - stop) * sign <= 0:
                reasons.append("No positive entry-to-stop risk.")
            actual_risk = (close-stop)*sign
            target_r = (plan.targets[0]-close)*sign/actual_risk if actual_risk > 0 else 0
            if target_r < plan.entry.min_target_r:
                reasons.append(f"First target offers {target_r:.3f}R from confirmation; requires {plan.entry.min_target_r:g}R.")
            if reasons:
                trace.append({"at": end, "rule": "M4/M3", "decision": "watch_only", "reason": " ".join(reasons),
                              "measurements": {"close": close, "trigger": plan.trigger, "volume": volume,
                                  "baselineVolume": baseline, "requiredVolumeMultiple": plan.entry.volume_multiple,
                                  "volumeRatio": volume/baseline if baseline else None,
                                  "closeLocation": location, "requiredCloseLocation": plan.entry.min_close_location, "firstTargetR": target_r, "requiredTargetR": plan.entry.min_target_r}})
                continue
            event_id = f"{plan.id}:entry:{end}"
            trace.append({"at": end, "rule": "M4", "decision": "triggered",
                          "reason": "Planned level confirmed by a complete closed candle and relative volume."})
            return result("triggered", {"id": event_id, "at": end, "direction": plan.direction,
                                        "referencePrice": close, "stop": stop, "risk": abs(close-stop),
                                        "targets": list(plan.targets), "volume": volume,
                                        "volumeRatio": volume / baseline, "closeLocation": location,
                                        "stopMode": plan.entry.stop_mode})
    if as_of_ms >= session_bounds(plan.last_session.isoformat())[1]:
        return result("expired")
    return result("missing_data" if missing else "waiting")
