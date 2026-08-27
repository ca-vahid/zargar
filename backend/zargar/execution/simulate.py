"""simulate_position — the durable-position policy evaluated over history
(phase 2b, plan §2.4). Runs the SAME `policies.evaluate`/`apply_moves` the live
`PositionManager` runs, bar for bar, so a policy is backtested by the code that
will trade it (the chaos suite asserts the parity).

Options are simulated on the UNDERLYING, exactly like EM's outcome scoring:
targets, stops and trims fill at underlying prices; premium-path effects
(theta, IV) are deliberately NOT modelled and the result says so
(`premiumPathSimulated: false`) — per the techniques research (A8), an options
pricing model is out of scope.

    res = simulate_position(policy, bars, direction="long", entry=100.0, risk=1.0,
                            legs=[{"secType": "OPT", "expiry": "2026-09-18", "qty": 1}],
                            days_to_event=lambda date: None)

Bars must be CLOSED bars of the policy's timeframe, in order. Fill model
(conservative, mirrors `marketstructure.outcome.simulate_plan`'s conventions):
stops and forced closes fill at the bar CLOSE (the live manager decides on the
close and sends market); trims fill AT the target price when the bar's range
covers it.
"""
from __future__ import annotations

import datetime as dt
from typing import Callable

from ..domain import Bar
from ..marketstructure.sessions import session_date
from .policies import DEFAULT_TIMEFRAME, PolicyState, PositionView, apply_moves, evaluate, stop_price


def simulate_position(policy: dict, bars: list[Bar], *, direction: str = "long", entry: float,
                      risk: float, entry_mark: float | None = None,
                      mark_of_close: Callable[[float], float] | None = None,
                      legs: list[dict] | None = None,
                      days_to_event: Callable[[str], int | None] | None = None,
                      min_dte_floor: int = 1) -> dict:
    """Walk closed policy-tf bars forward and apply the policy. Returns:
    {closed, exitKind, exitReason, exits: [...], barsHeld, sessionsHeld,
     realizedR, remainingFraction, finalStop, state, premiumPathSimulated,
     decisions: [per-bar record]} — plus `state` for the parity assertion."""
    short = direction == "short"
    risk = max(float(risk), 1e-9)
    state = PolicyState(stop=stop_price(policy, PolicyState()))
    expiries: list[dt.date] = []
    for l in legs or []:
        e = l.get("expiry")
        if e:
            expiries.append(dt.date.fromisoformat(str(e)))
    sessions: list[str] = []
    exits: list[dict] = []
    decisions_log: list[dict] = []
    remaining = 1.0
    realized_r = 0.0
    exit_kind = None
    exit_reason = None
    bars_held = 0
    for bar in bars:
        if remaining <= 1e-9:
            break
        bars_held += 1
        day = session_date(bar.ts)
        if day not in sessions:
            sessions.append(day)
        dte_min = min(((e - dt.date.fromisoformat(day)).days for e in expiries), default=None) if expiries else None
        view = PositionView(
            direction=direction, entry=entry, risk=risk, bar=bar, bars=bars[max(0, bars_held - 40):bars_held],
            net_mark=(mark_of_close(bar.close) if mark_of_close else None), entry_mark=entry_mark,
            dte_min=dte_min, sessions_held=max(0, len(sessions) - 1),
            days_to_event=(days_to_event(day) if days_to_event else None), min_dte_floor=min_dte_floor,
        )
        decs, moves = evaluate(policy, state, view)
        state = apply_moves(state, view, decs, moves)
        for d in decs:
            if d.kind == "trim":
                # fills at the target price the bar reached
                targets = [float(t) for t in ((policy.get("ladder") or {}).get("targets") or [])]
                idx = state.trims_done - 1
                px = targets[idx] if 0 <= idx < len(targets) else bar.close
            else:
                px = bar.close
            qty = remaining * d.fraction
            r = ((px - entry) / risk) if not short else ((entry - px) / risk)
            realized_r += r * qty
            remaining -= qty
            exits.append({"ts": bar.ts, "kind": d.kind, "price": px, "fraction": round(qty, 6),
                          "r": round(r, 4), "reason": d.reason})
            decisions_log.append({"ts": bar.ts, "kind": d.kind, "reason": d.reason})
            if d.fraction >= 1.0 - 1e-9 or remaining <= 1e-9:
                exit_kind, exit_reason = d.kind, d.reason
                remaining = 0.0
                break
    return {
        "closed": remaining <= 1e-9,
        "exitKind": exit_kind, "exitReason": exit_reason,
        "exits": exits, "decisions": decisions_log,
        "barsHeld": bars_held, "sessionsHeld": max(0, len(sessions) - 1),
        "realizedR": round(realized_r, 4), "remainingFraction": round(remaining, 6),
        "finalStop": state.stop, "state": state.to_dict(),
        "premiumPathSimulated": False if (legs and any((l.get("secType") or "STK") == "OPT" for l in legs)) else None,
    }
