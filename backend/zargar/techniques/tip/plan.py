"""Tip → SessionPlan: one trigger, kind="tip", the shared machinery does the rest.

Entry policy is per-source (user decision 2026-08-27): `level_touch` (default —
the plan waits for price to trade to a structural level on the tip's side) or
`tip_time` (earned — enter on the next bar). Both produce the same plan shape
EM produces, so the tracker, `simulate_plan`, the runner and the outcome
scorer consume a tip without knowing it is one:

    level_touch -> kind "bounce"/"reject", entry_basis "at_level"
                   (the tracker's touch-fire mechanics; volume optional via
                   the tip rules' volume_floor_mult=0 — these ARE armable)
    tip_time    -> kind "tip", entry_basis "on_break" (fills at the decision
                   bar's close in simulate_plan; live tip-time tips go through
                   the immediate-proposal path, not the runner)

Pure function — no I/O, no settings reads; the caller resolves the policy.
"""
from __future__ import annotations

from ...domain import Bar
from ...marketstructure import atr, detect_levels, nearest_level, next_session_date, session_bounds, session_date
from ...technique.plans import Condition, SessionPlan, Trigger

# Ladder used by the tip exit policy in Phase B: 50/50 across two targets.
TIP_LADDER = (0.5, 0.5)


def _fallback_atr(bars: list[Bar], reference_price: float) -> float:
    a = atr(bars)
    return a if a > 0 else reference_price * 0.005


def build_tip_plan(
    *,
    symbol: str,
    direction: str,                      # long | short
    reference_price: float,              # live price the plan is judged against
    bars: list[Bar],                     # trigger-tf history (levels + ATR); may be short
    as_of_ms: int,
    entry_mode: str = "level_touch",     # level_touch | tip_time (from the source policy)
    tip_entry: float | None = None,
    tip_stop: float | None = None,
    tip_targets: tuple[float, ...] | list[float] = (),
    horizon_sessions: int = 10,
    stop_atr_mult: float = 1.0,
    target_r: tuple[float, ...] | list[float] = (1.5, 3.0),
    signal_id: str | None = None,
    source: str | None = None,
    thesis: str = "",
    instrument_hint: str = "unspecified",
    confidence: float = 0.5,
) -> SessionPlan:
    if direction not in ("long", "short"):
        raise ValueError(f"direction must be long|short, got {direction!r}")
    if reference_price <= 0:
        raise ValueError("reference_price must be positive")
    long = direction == "long"
    sgn = 1.0 if long else -1.0
    tf = bars[0].tf if bars else "5m"
    a = _fallback_atr(bars, reference_price)
    levels = detect_levels(bars, timeframe=tf) if len(bars) >= 3 else []
    notes: list[str] = []

    # --- entry -----------------------------------------------------------------
    if entry_mode == "tip_time":
        entry = reference_price
        basis = "on_break"                       # simulate_plan/tracker: immediate fill
        level = None
        notes.append("tip-time entry (source has earned it)")
    else:
        basis = "at_level"
        # the tip's own entry wins when it sits on the correct side of price
        # (long: at/below; short: at/above) — otherwise the nearest structural
        # level on that side; otherwise a shallow ATR pullback, flagged.
        tip_ok = tip_entry is not None and (
            tip_entry <= reference_price * 1.001 if long else tip_entry >= reference_price * 0.999)
        level = nearest_level(levels, reference_price,
                              kind="support" if long else "resistance",
                              side="below" if long else "above")
        if tip_ok:
            entry = float(tip_entry)
            notes.append("entry from the tip itself")
        elif level is not None:
            entry = float(level.price)
            notes.append(f"entry at the nearest {'support' if long else 'resistance'} "
                         f"({level.touches} touches)")
        else:
            entry = reference_price - sgn * 0.5 * a
            notes.append("no structural level found — shallow ATR pullback entry")

    # --- stop ------------------------------------------------------------------
    tip_stop_ok = tip_stop is not None and (tip_stop < entry if long else tip_stop > entry)
    if tip_stop_ok:
        stop = float(tip_stop)
        stop_ref = "tip"
    else:
        stop = entry - sgn * stop_atr_mult * a
        stop_ref = f"atr_x{stop_atr_mult:g}"
        if tip_stop is not None:
            notes.append(f"tip stop {tip_stop:g} is on the wrong side of entry — ATR stop used")
    risk = sgn * (entry - stop)

    # --- targets ---------------------------------------------------------------
    stated = [float(t) for t in tip_targets
              if (t > entry if long else t < entry)]
    if stated:
        targets = sorted(stated)[:3] if long else sorted(stated, reverse=True)[:3]
        tgt_note = "targets from the tip"
    else:
        targets = [entry + sgn * r * risk for r in target_r]
        tgt_note = f"R-multiple targets ({'/'.join(f'{r:g}R' for r in target_r)})"
    notes.append(tgt_note)
    target_dicts = [{"price": round(t, 4), "label": f"TP{i + 1}"} for i, t in enumerate(targets)]

    # R:R measured where the position exits: the 50/50 ladder's weighted exit
    # across the first two targets (or the single target when there is one).
    exits = targets[:2]
    weighted_exit = sum(exits) / len(exits)
    rr = (sgn * (weighted_exit - entry) / risk) if risk > 0 else 0.0
    rr_last = (sgn * (targets[-1] - entry) / risk) if risk > 0 else 0.0

    valid = risk > 0 and bool(targets)
    no_trade = [] if valid else ["degenerate plan: stop on the wrong side of entry or no targets"]

    who = source or "unknown source"
    conditions = [
        Condition("TIP.1", f"tip from {who}" + (f": {thesis}" if thesis else ""), "touch"),
        Condition("TIP.2", f"valid for {horizon_sessions} sessions from receipt", "window"),
    ]
    # level-touch tips ride the tracker's bounce/reject (touch-fire) mechanics;
    # tip-time keeps the neutral kind (simulate-only immediate fill)
    kind = ("tip" if entry_mode == "tip_time"
            else ("bounce" if long else "reject"))
    trigger = Trigger(
        id=f"tip-{(signal_id or 'manual')[:12]}",
        kind=kind,
        direction=direction,
        level_price=entry if level is None else float(level.price),
        level=level.to_dict() if level is not None else {"price": round(entry, 4), "kind": "tip",
                                                         "touches": 0, "sources": ["TIP"]},
        entry_price=round(entry, 4),
        entry_basis=basis,
        stop_price=round(stop, 4),
        stop_reference=stop_ref,
        targets=target_dicts,
        risk_reward=round(rr, 2),
        conditions=conditions,
        void_if=[f"not filled within {horizon_sessions} sessions"],
        confluences=[],
        confidence=float(confidence),
        rules=["TIP.1", "TIP.2"],
        valid=valid,
        no_trade_reasons=no_trade,
        notes="; ".join(notes),
        risk_reward_tp3=round(rr_last, 2),
    )

    # a tip armed after the close plans for the NEXT session — a plan for a
    # session that is already over would expire the moment it armed
    plan_day = session_date(as_of_ms)
    if as_of_ms >= session_bounds(plan_day)[1]:
        plan_day = next_session_date(as_of_ms)

    return SessionPlan(
        symbol=symbol.upper(),
        plan_for=plan_day,
        built_from_ms=as_of_ms,
        built_from_session=session_date(bars[-1].ts) if bars else session_date(as_of_ms),
        structure_tfs=[tf],
        trigger_tf=tf,
        last_close=float(bars[-1].close) if bars else reference_price,
        levels=[lv.to_dict() for lv in levels[:8]],
        context={"technique": "tip", "source": who, "signalId": signal_id,
                 "instrumentHint": instrument_hint, "entryMode": entry_mode,
                 "horizonSessions": horizon_sessions},
        triggers=[trigger],
        invalidations=[{"rule": "TIP.2", "text": f"expires after {horizon_sessions} sessions"}],
        gap_policy={"policy": "ignore", "rule": "TIP",
                    "note": "tips carry no gap rule — the level either fills or it doesn't"},
        notes=notes,
        bottom_line=(f"{'Long' if long else 'Short'} {symbol.upper()} on a tip from {who}: "
                     f"{'wait for' if basis == 'at_level' else 'enter at'} "
                     f"{entry:.2f}, stop {stop:.2f}, "
                     f"targets {', '.join(f'{t:.2f}' for t in targets)}"),
        reference_price=reference_price,
    )
