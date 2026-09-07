"""Evaluate missed daily closes against a verified unchanged execution state.

Produces requirements, never fills. The caller must establish that the supplied
state held throughout the interval; a current state with later fills is invalid.
"""
from __future__ import annotations

from .data import DailyBar, completed_daily, require_contiguous
from .exits import ExitCampaign, ExitState, decide_exits


def review_missed_closes(campaign: ExitCampaign, state: ExitState, daily: list[DailyBar],
                         missed: list[int], *, state_since_ms: int, as_of_ms: int):
    closes = sorted(set(missed))
    if not closes or state_since_ms > closes[0] or closes[-1] > as_of_ms:
        raise ValueError("catch-up needs missed closes after the verified state cutoff and before the as-of time")
    history = completed_daily(daily, as_of_ms)
    require_contiguous(history)
    by_close = {b.closes_at: b for b in history}
    if any(at not in by_close for at in closes):
        raise ValueError("every missed close needs its completed daily candle")
    if any(b.symbol != state.symbol for b in history):
        raise ValueError("catch-up history symbol mismatch")
    warmup = max(campaign.atr_period, *(r.ema_period for r in campaign.rungs))
    if len([b for b in history if b.closes_at <= closes[0]]) < warmup:
        raise ValueError("catch-up lacks indicator warm-up")
    trace, requirements, warnings = [], {}, []
    for at in closes:
        result = decide_exits(campaign, state, history, as_of_ms=at,
                              observed_price=by_close[at].close, daily_close=True)
        warnings.extend(result["warnings"])
        trace.append({"at": at, "decisions": result["decisions"]})
        for decision in result["decisions"]:
            key = decision["rung"]
            prior = requirements.get(key)
            if prior is None or decision["qty"] > prior["qty"]:
                requirements[key] = {**decision, "observedAt": at}
        # A protective breach takes precedence over earlier profit requirements.
        if "stop" in requirements:
            requirements = {"stop": requirements["stop"]}
            break
    # Each rung is a cumulative requirement, not one fresh allocation per day.
    # A final EMA can cover remaining allocations; cap the complete action set.
    remaining = state.remaining_qty
    bounded = []
    for decision in requirements.values():
        qty = min(remaining, decision["qty"])
        if qty:
            bounded.append({**decision, "qty": qty})
            remaining -= qty
    return {"positionId": state.position_id, "stateSinceMs": state_since_ms,
            "asOfMs": as_of_ms, "missedCloses": closes, "requirements": bounded,
            "trace": trace, "warnings": sorted(set(warnings)), "placesOrders": False,
            "fillsCreated": False, "state": state.model_dump(mode="json")}
