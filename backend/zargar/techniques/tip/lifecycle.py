"""Tip proposal → managed position, under the analyst's exit plan.

Charter: docs/techniques/tip/ANALYST.md §5. The analyst authors the exit
campaign at appraisal time (scale-out targets/fractions on the underlying, a
stop or a declared premium-stop guard, a hold cap); the proposal carries it as
`context.exitPlan`; when the approved order FILLS, `adopt_when_filled` hands
the position to the durable PositionManager with that plan translated into the
shared policy document (`execution/policies.py`) — so an LLM plans the exits
but deterministic, journaled, backtestable code executes them.

Fail-safe: an exit plan that does not validate falls back to the technique's
default policy (journaled); a proposal whose order never fills adopts nothing.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

log = logging.getLogger("zargar.tip.lifecycle")

FILL_WAIT_S = 4 * 3600          # a resting LMT gets the session, not forever
POLL_S = 3.0


def build_exit_plan(signal_row, sig, analyst: dict, policy) -> dict:
    """The exit campaign for this tip: the analyst's plan when it wrote one,
    else the tip's own stop/targets, else technique defaults. Plain dict —
    rides on the proposal (`context.exitPlan`) and is translated to a policy
    at adoption time."""
    from .horizon import hold_sessions_cap, tip_expiry

    analyst = analyst or {}
    targets = [float(t) for t in (analyst.get("exit_targets") or []) if t]
    fractions = [float(f) for f in (analyst.get("exit_fractions") or []) if f is not None]
    author = "analyst"
    if not targets:
        author = "tip"
        stated = ((signal_row.extraction or {}).get("signal") or {}).get("target_prices") or []
        targets = [float(t) for t in stated if t] or \
                  ([float(sig.target_price)] if sig.target_price else [])
        fractions = []
    stop = analyst.get("underlying_stop")
    if stop is None and sig.stop_price:
        stop = float(sig.stop_price)

    today = dt.datetime.now(dt.timezone.utc).date()
    expiry = tip_expiry(signal_row.expiry, signal_row.dte_hint_days, today)
    cap = hold_sessions_cap(expiry=expiry, today=today,
                            fallback=int(policy.horizon_sessions or 10))
    hold = int(analyst.get("max_hold_sessions") or 0) or cap
    catalyst = (signal_row.catalyst or "").lower()
    return {
        "author": author,
        "targets": targets,
        "fractions": fractions,
        "underlyingStop": float(stop) if stop else None,
        "premiumStopPct": (float(analyst["premium_stop_pct"])
                           if analyst.get("premium_stop_pct") else None),
        "maxHoldSessions": min(hold, cap),      # never outlive the contract
        "avoidEarnings": "earnings" not in catalyst,
        "note": analyst.get("exit_rationale") or None,
    }


def policy_from_exit_plan(plan: dict, *, is_option: bool, settings) -> dict:
    """Exit plan → the shared policy document. Ladder fractions normalise to
    <= 1.0 (a remainder rides the structure trail); a stop-less plan becomes an
    explicit no-stop policy with the premium-stop guard declared."""
    plan = plan or {}
    policy: dict = {"timeframe": "15m"}
    stop = plan.get("underlyingStop")
    if stop:
        policy["stop"] = {"kind": "fixed", "price": float(stop)}
    else:
        policy["stop"] = {"kind": "none",
                          "guard": "premium stop + per-tip budget cap (analyst-declared; "
                                   "long options only — max loss is the debit)"}
    targets = [float(t) for t in (plan.get("targets") or []) if t]
    if targets:
        fractions = [max(0.0, float(f)) for f in (plan.get("fractions") or [])][:len(targets)]
        total = sum(fractions)
        if total > 1.0:
            fractions = [f / total for f in fractions]
        policy["ladder"] = {"targets": targets,
                            "fractions": [round(f, 4) for f in fractions]}
    policy["trailing"] = {"mode": "structure",
                          "after_r": float(settings.get("techniques.tip.trailing_after_r", 1.0))}
    policy["time_stop_sessions"] = max(1, int(plan.get("maxHoldSessions") or 10))
    if is_option:
        policy["premium_stop_pct"] = float(plan.get("premiumStopPct") or 50.0)
        policy["dte_close"] = max(1, int(settings.get("execution.min_dte", 1)))
    if plan.get("avoidEarnings", True):
        policy["flatten_before"] = {"event": "earnings", "days": 1}
    return policy


def default_policy(*, stop: float | None, targets: list[float],
                   hold: int, is_option: bool, settings) -> dict:
    """The technique's fallback (mirrors the armed path's handoff policy) for
    when the analyst plan fails validation."""
    return policy_from_exit_plan(
        {"targets": targets[:2], "fractions": [], "underlyingStop": stop,
         "maxHoldSessions": hold, "avoidEarnings": True},
        is_option=is_option, settings=settings)


async def _order_row(eng, order_id: str) -> dict | None:
    from ...models import Order
    async with eng.sf() as session:
        row = await session.get(Order, order_id)
    if row is None:
        return None
    return {"status": row.status, "avgFillPrice": row.avg_fill_price,
            "filledQty": row.filled_qty, "symbol": row.symbol,
            "secType": row.sec_type, "qty": row.qty}


async def adopt_when_filled(eng, proposal: dict, order: dict) -> dict | None:
    """Wait for the approved tip proposal's order to FILL, then hand the
    position to the durable manager under the analyst's exit plan. Runs as a
    background task; every outcome is journaled under the proposal."""
    from ... import events as ev

    oid = str(order.get("id") or "")
    pid = str(proposal.get("id") or "")
    ctx = proposal.get("context") or {}

    async def note(kind: str, payload: dict) -> None:
        try:
            await eng.journal.append(kind, {"proposalId": pid, "orderId": oid, **payload},
                                     aggregate_type="proposal", aggregate_id=pid,
                                     portfolio_id=proposal.get("portfolioId"))
        except Exception:
            log.exception("journal failed for proposal %s", pid)

    # ---- wait for the fill (sim fills in ms; a live LMT may rest a while)
    deadline = asyncio.get_event_loop().time() + FILL_WAIT_S
    row = None
    while True:
        row = await _order_row(eng, oid)
        st = (row or {}).get("status") or ""
        if st == "FILLED":
            break
        if st in ("CANCELLED", "REJECTED", "REJECTED_RISK", "EXPIRED", "ERROR"):
            log.info("proposal %s order %s ended %s — nothing to manage", pid, oid, st)
            await note(ev.TIP_POSITION_NOT_ADOPTED, {"reason": f"order {st}"})
            return None
        if asyncio.get_event_loop().time() > deadline:
            log.warning("proposal %s order %s unfilled after %.0fh — not adopted",
                        pid, oid, FILL_WAIT_S / 3600)
            await note(ev.TIP_POSITION_NOT_ADOPTED, {"reason": "fill wait timed out"})
            return None
        await asyncio.sleep(POLL_S)

    mgr = getattr(eng, "position_manager", None)
    if mgr is None:
        await note(ev.TIP_POSITION_NOT_ADOPTED, {"reason": "position manager not attached"})
        return None

    is_opt = (proposal.get("secType") or row.get("secType")) == "OPT"
    vehicle = ctx.get("vehicle") or {}
    underlying = str(vehicle.get("underlying") or proposal.get("symbol") or "").upper()
    # direction = the UNDERLYING idea's side: a long put profits on the way down
    direction = "short" if (is_opt and vehicle.get("optionType") == "put") else "long"
    fill = float(row.get("avgFillPrice") or proposal.get("limitPrice") or 0)
    qty = float(row.get("filledQty") or proposal.get("qty") or 0)
    if qty <= 0 or fill <= 0:
        await note(ev.TIP_POSITION_NOT_ADOPTED, {"reason": f"bad fill qty={qty} px={fill}"})
        return None

    plan = ctx.get("exitPlan") or {}
    await eng.ensure_symbol(underlying)
    q = eng.quotes.get(underlying)
    entry_ref = (float(q.last) if q and q.last > 0 else None) \
        or float((ctx.get("signalPrices") or {}).get("entry") or 0) \
        or (float(plan.get("underlyingStop") or 0) or None)
    if not entry_ref:
        await note(ev.TIP_POSITION_NOT_ADOPTED,
                   {"reason": f"no underlying reference price for {underlying}"})
        return None
    stop = plan.get("underlyingStop")
    risk = abs(entry_ref - float(stop)) if stop else entry_ref * 0.05

    policy = policy_from_exit_plan(plan, is_option=is_opt, settings=eng.settings)
    leg = ({"symbol": proposal.get("symbol"), "secType": "OPT", "qty": qty,
            "avgFill": fill, "multiplier": 100.0, "entryOrderId": oid,
            "origin": "adoption"}
           if is_opt else
           {"symbol": underlying, "secType": "STK", "qty": qty, "avgFill": fill,
            "entryOrderId": oid, "origin": "adoption"})
    spec = {
        "portfolioId": proposal.get("portfolioId"), "symbol": underlying,
        "direction": direction, "techniqueId": "tip",
        "tags": [f"source:{ctx.get('sourceName') or 'unknown'}", "proposal"],
        "runId": ctx.get("analystRunId") or pid,     # the reasoning that opened it
        "entry": entry_ref, "risk": risk, "legs": [leg],
        "overnight": "app_managed" if is_opt else "venue_stop",
        "overnightAck": True if is_opt else False,
        "policy": policy,
        "guardAccepted": (policy.get("stop") or {}).get("kind") == "none",
    }
    try:
        pos = await mgr.adopt(spec)
    except ValueError as exc:
        # the analyst's plan didn't validate — fall back to the technique default
        log.warning("analyst exit plan invalid for proposal %s (%s) — default policy", pid, exc)
        spec["policy"] = default_policy(stop=stop, targets=plan.get("targets") or [],
                                        hold=int(plan.get("maxHoldSessions") or 10),
                                        is_option=is_opt, settings=eng.settings)
        spec["guardAccepted"] = (spec["policy"].get("stop") or {}).get("kind") == "none"
        try:
            pos = await mgr.adopt(spec)
        except ValueError as exc2:
            await note(ev.TIP_POSITION_NOT_ADOPTED,
                       {"reason": f"policy invalid twice: {exc2}"})
            return None
        await note(ev.TIP_POSITION_ADOPTED,
                   {"positionId": pos["id"], "policy": spec["policy"],
                    "fallback": f"analyst plan invalid: {exc}"})
        return pos
    await note(ev.TIP_POSITION_ADOPTED,
               {"positionId": pos["id"], "policy": policy,
                "exitPlan": plan, "runId": spec["runId"]})
    log.info("proposal %s adopted as managed position %s (%s, %s)",
             pid, pos["id"], underlying, "OPT" if is_opt else "STK")
    return pos
