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
NATIVE_FILL_WAIT_S = 90.0       # native mleg: both legs must fill inside this or unwind


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
    lotto = bool(expiry is not None and 0 <= (expiry - today).days <= 3
                 and str(getattr(signal_row, "instrument", "")) in ("call", "put"))
    return {
        "author": author,
        "targets": targets,
        "fractions": fractions,
        "underlyingStop": float(stop) if stop else None,
        "premiumStopPct": (float(analyst["premium_stop_pct"])
                           if analyst.get("premium_stop_pct") else None),
        "maxHoldSessions": min(hold, cap),      # never outlive the contract
        # the lotto lane: held INTO expiry day, flattened before its close
        "lotto": lotto,
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
        # premium stop: the plan's own figure, else the technique's knob
        # (resolver semantics: techniques.tip.premium_stop_pct → execution.*)
        fallback_ps = settings.get("techniques.tip.premium_stop_pct",
                                   settings.get("execution.premium_stop_pct", 50.0))
        policy["premium_stop_pct"] = float(plan.get("premiumStopPct") or fallback_ps or 50.0)
        if plan.get("lotto"):
            # the lotto lane: held into expiry day, flattened at the lotto time
            # (never THROUGH the close — the platform invariant, restated)
            policy["dte_close"] = 0
            policy["expiry_day_flatten_et"] = str(settings.get("techniques.tip.lotto_flatten_et", "15:45"))
        else:
            policy["dte_close"] = max(1, int(settings.get("execution.min_dte", 1)))
    if plan.get("avoidEarnings", True):
        policy["flatten_before"] = {"event": "earnings", "days": 1}
    return policy


# The technique's standard exit ladder — THE single executable source (plan.py's
# RR arithmetic mirrors it; the shadow books always run it for comparability).
DEFAULT_TIP_FRACTIONS = (0.5, 0.5)


def default_policy(*, stop: float | None, targets: list[float],
                   hold: int, is_option: bool, settings,
                   avoid_earnings: bool = True) -> dict:
    """The technique's standard policy (50/50 across the first two targets +
    structure trail): shadow-book fills, and the fallback when an analyst plan
    is absent or fails validation."""
    return policy_from_exit_plan(
        {"targets": targets[:2],
         "fractions": list(DEFAULT_TIP_FRACTIONS)[:max(1, len(targets[:2]))],
         "underlyingStop": stop,
         "maxHoldSessions": hold, "avoidEarnings": avoid_earnings},
        is_option=is_option, settings=settings)


async def open_spread(eng, *, portfolio_id: str, underlying: str, direction: str,
                      legs: list[dict], qty: int, exit_plan: dict | None = None,
                      source: str = "unknown", analyst_run_id: str | None = None,
                      signal_id: str | None = None) -> dict:
    """Defined-risk spread entry (ARM-PLAN P5). Sequenced so risk stays defined
    at every instant: the LONG leg is placed and must FILL first; only then the
    short leg goes out (tagged spread:<gid> — the risk gate accepts a short leg
    only when the covering long is already held). A rejected/unfilled short leg
    rolls the long back at market. The pair is adopted as ONE managed position
    (net-credit positions use the credit-target policy the engine already has)."""
    import uuid

    from ...orders import OrderIntent

    long_leg = next((l for l in legs if l.get("side") == "BUY"), None)
    short_leg = next((l for l in legs if l.get("side") == "SELL"), None)
    if long_leg is None or short_leg is None or len(legs) != 2:
        raise ValueError("a defined-risk spread is exactly one long and one short leg")
    gid = uuid.uuid4().hex[:8]
    tags = [f"source:{source}", f"spread:{gid}"]
    qty = max(1, int(qty))

    # ---- native multi-leg first (NEXT-GAPS M2): one combined venue order,
    # atomic legs, one risk verdict on the structure's max loss. Any native
    # failure falls back to the verified leg-sequencing below.
    if _mleg_supported(eng, portfolio_id):
        try:
            return await _open_spread_native(
                eng, portfolio_id=portfolio_id, underlying=underlying,
                direction=direction, long_leg=long_leg, short_leg=short_leg,
                qty=qty, gid=gid, tags=tags, exit_plan=exit_plan, source=source,
                analyst_run_id=analyst_run_id, signal_id=signal_id)
        except Exception as exc:
            log.warning("native mleg spread %s failed (%s) — falling back to leg sequencing",
                        gid, exc)

    # ---- leg 1: the LONG leg, and wait for the fill (defined risk needs it held)
    o1 = await eng.orders.place(OrderIntent(
        portfolio_id=portfolio_id, symbol=long_leg["symbol"], sec_type="OPT",
        side="BUY", qty=qty, order_type="LMT",
        limit_price=round(float(long_leg.get("ask") or 0), 2) or None,
        tif="DAY", source="technique", technique_id="tip", tags=tags,
        signal_id=signal_id))
    if o1.get("status") in ("REJECTED", "REJECTED_RISK", "ERROR"):
        raise ValueError(f"long leg rejected: {o1.get('rejectReason') or o1.get('status')}")
    deadline = asyncio.get_event_loop().time() + 90
    row1 = None
    while True:
        row1 = await _order_row(eng, o1["id"])
        if (row1 or {}).get("status") == "FILLED":
            break
        if (row1 or {}).get("status") in ("CANCELLED", "REJECTED", "EXPIRED"):
            raise ValueError(f"long leg ended {(row1 or {}).get('status')}")
        if asyncio.get_event_loop().time() > deadline:
            with contextlib_suppress():
                await eng.orders.cancel(o1["id"])
            raise ValueError("long leg did not fill in time — spread abandoned")
        await asyncio.sleep(0.5)

    # ---- leg 2: the short leg (covered now); rollback the long if it dies.
    # The rollback is VERIFIED (ARM-GAPS B3): retried, its fill awaited, and a
    # final failure alerts + adopts the naked long as an attention position —
    # a naked leg must never exist outside the PositionManager's view.
    o2 = await eng.orders.place(OrderIntent(
        portfolio_id=portfolio_id, symbol=short_leg["symbol"], sec_type="OPT",
        side="SELL", qty=qty, order_type="LMT",
        limit_price=round(float(short_leg.get("bid") or 0), 2) or None,
        tif="DAY", source="technique", technique_id="tip", tags=tags,
        signal_id=signal_id))
    if o2.get("status") in ("REJECTED", "REJECTED_RISK", "ERROR"):
        why = f"short leg rejected ({o2.get('rejectReason') or o2.get('status')})"
        await _unwind_or_adopt_naked_long(
            eng, portfolio_id=portfolio_id, underlying=underlying, direction=direction,
            long_leg=long_leg, qty=qty, fill=float(row1.get("avgFillPrice") or 0),
            entry_order_id=o1["id"], tags=tags, gid=gid, why=why,
            signal_id=signal_id, analyst_run_id=analyst_run_id)
        raise ValueError(f"{why} — long leg unwound (or adopted for attention)")
    deadline = asyncio.get_event_loop().time() + 90
    while True:
        row2 = await _order_row(eng, o2["id"])
        if (row2 or {}).get("status") == "FILLED":
            break
        if (row2 or {}).get("status") in ("CANCELLED", "REJECTED", "EXPIRED") \
                or asyncio.get_event_loop().time() > deadline:
            with contextlib_suppress():
                await eng.orders.cancel(o2["id"])
            why = "short leg did not fill"
            await _unwind_or_adopt_naked_long(
                eng, portfolio_id=portfolio_id, underlying=underlying, direction=direction,
                long_leg=long_leg, qty=qty, fill=float(row1.get("avgFillPrice") or 0),
                entry_order_id=o1["id"], tags=tags, gid=gid, why=why,
                signal_id=signal_id, analyst_run_id=analyst_run_id)
            raise ValueError(f"{why} — long leg unwound (or adopted for attention)")
        await asyncio.sleep(0.5)

    fill1 = float(row1.get("avgFillPrice") or long_leg.get("ask") or 0)
    fill2 = float(row2.get("avgFillPrice") or short_leg.get("bid") or 0)
    return await _adopt_spread_position(
        eng, portfolio_id=portfolio_id, underlying=underlying, direction=direction,
        long_leg=long_leg, short_leg=short_leg, qty=qty, fill1=fill1, fill2=fill2,
        o1_id=o1["id"], o2_id=o2["id"], tags=tags, exit_plan=exit_plan,
        analyst_run_id=analyst_run_id)


def _mleg_supported(eng, portfolio_id: str) -> bool:
    """Can this portfolio's venue take a native multi-leg order? Sim/shadow:
    yes (the sim executor accepts them). SnapTrade: only accounts explicitly
    verified via the impact probe (`options.mleg_accounts`; Webull CA probes
    clean, Wealthsimple is 1156). Everything else: leg sequencing."""
    pf = eng.positions.portfolio(portfolio_id) or {}
    kind, venue = pf.get("kind"), pf.get("venue")
    if kind in ("sim", "shadow"):
        return True
    if venue == "snaptrade":
        sync = getattr(eng, "snaptrade_sync", None)
        account = sync.account_for(portfolio_id) if sync is not None else None
        allowed = [str(a) for a in (eng.settings.get("options.mleg_accounts") or [])]
        return account is not None and str(account) in allowed
    return False


async def _open_spread_native(eng, *, portfolio_id: str, underlying: str, direction: str,
                              long_leg: dict, short_leg: dict, qty: int, gid: str,
                              tags: list[str], exit_plan: dict | None, source: str,
                              analyst_run_id: str | None, signal_id: str | None) -> dict:
    """NEXT-GAPS M2: ONE combined venue order for both legs — write-ahead rows,
    one RiskGate verdict on the structure's max loss, atomic venue execution.
    Raises on any failure (the caller falls back to leg sequencing) after
    unwinding whatever partially filled."""
    from ...orders import OrderIntent

    long_px = round(float(long_leg.get("ask") or 0), 2)
    short_px = round(float(short_leg.get("bid") or 0), 2)
    net = long_px - short_px                                # +debit / -credit
    width = abs(float(long_leg.get("strike", 0)) - float(short_leg.get("strike", 0)))
    max_loss = (net if net > 0 else max(width - abs(net), 0.01)) * 100 * qty
    mtags = tags + ["mleg"]
    li = OrderIntent(portfolio_id=portfolio_id, symbol=long_leg["symbol"], sec_type="OPT",
                     side="BUY", qty=qty, order_type="LMT",
                     limit_price=long_px or None, tif="DAY", source="technique",
                     technique_id="tip", tags=mtags, signal_id=signal_id)
    si = OrderIntent(portfolio_id=portfolio_id, symbol=short_leg["symbol"], sec_type="OPT",
                     side="SELL", qty=qty, order_type="LMT",
                     limit_price=short_px or None, tif="DAY", source="technique",
                     technique_id="tip", tags=mtags, signal_id=signal_id)
    res = await eng.orders.place_spread(li, si, net_limit=net, max_loss=max_loss, gid=gid)
    if res.get("status") != "SUBMITTED":
        raise ValueError(f"native mleg refused: {res.get('reason') or res.get('status')}")
    ids = [leg["id"] for leg in res["legs"]]
    deadline = asyncio.get_event_loop().time() + NATIVE_FILL_WAIT_S
    rows: dict[str, dict] = {}
    while True:
        rows = {oid: (await _order_row(eng, oid)) or {} for oid in ids}
        sts = [r.get("status") for r in rows.values()]
        if all(s == "FILLED" for s in sts):
            break
        if any(s in ("CANCELLED", "REJECTED", "REJECTED_RISK", "EXPIRED", "ERROR") for s in sts) \
                or asyncio.get_event_loop().time() > deadline:
            # abort: cancel what rests, close what filled (reduce-only)
            for oid, r in rows.items():
                if r.get("status") not in ("FILLED", "CANCELLED", "REJECTED",
                                           "REJECTED_RISK", "EXPIRED", "ERROR"):
                    with contextlib_suppress():
                        await eng.orders.cancel(oid)
                filled = float(r.get("filledQty") or 0)
                if filled > 0:
                    from ...orders import OrderIntent as _OI
                    with contextlib_suppress():
                        await eng.orders.place(_OI(
                            portfolio_id=portfolio_id, symbol=r.get("symbol") or "",
                            sec_type="OPT",
                            side=("SELL" if r.get("qty") and rows and oid == ids[0] else "BUY"),
                            qty=filled, order_type="MKT", tif="DAY", source="technique",
                            technique_id="tip", tags=mtags, reduce_only=True))
            raise ValueError(f"native mleg legs ended {sts} — unwound")
        await asyncio.sleep(0.5)
    fill1 = float(rows[ids[0]].get("avgFillPrice") or long_px)
    fill2 = float(rows[ids[1]].get("avgFillPrice") or short_px)
    log.info("native mleg spread %s filled: %s/%s x%d", gid,
             long_leg.get("strike"), short_leg.get("strike"), qty)
    return await _adopt_spread_position(
        eng, portfolio_id=portfolio_id, underlying=underlying, direction=direction,
        long_leg=long_leg, short_leg=short_leg, qty=qty, fill1=fill1, fill2=fill2,
        o1_id=ids[0], o2_id=ids[1], tags=mtags, exit_plan=exit_plan,
        analyst_run_id=analyst_run_id)


async def _adopt_spread_position(eng, *, portfolio_id: str, underlying: str, direction: str,
                                 long_leg: dict, short_leg: dict, qty: int,
                                 fill1: float, fill2: float, o1_id: str, o2_id: str,
                                 tags: list[str], exit_plan: dict | None,
                                 analyst_run_id: str | None) -> dict:
    """Both legs filled (either path): the pair becomes ONE managed position
    with the structural max-loss guard declared."""
    mgr = eng.position_manager
    q = eng.quotes.get(underlying.upper())
    entry_ref = float(q.last) if q and q.last > 0 else float(long_leg.get("strike") or 0)
    width = abs(float(long_leg.get("strike", 0)) - float(short_leg.get("strike", 0)))
    net = fill1 - fill2                                    # +debit / -credit
    policy = {"timeframe": "15m",
              # a defined-risk spread's max loss is structural — declare it
              "stop": {"kind": "none",
                       "guard": f"defined-risk spread: max loss = "
                                f"{'debit paid' if net > 0 else 'width - credit'} "
                                f"(${(net if net > 0 else width - abs(net)) * 100 * qty:,.0f})"},
              "time_stop_sessions": int((exit_plan or {}).get("maxHoldSessions") or 10),
              "dte_close": max(1, int(eng.settings.get("execution.min_dte", 1)))}
    if net < 0:
        policy["profit_target_pct_of_credit"] = 60.0
    elif (exit_plan or {}).get("targets"):
        policy["ladder"] = {"targets": [float(t) for t in exit_plan["targets"]],
                            "fractions": [float(f) for f in (exit_plan.get("fractions") or [])]}
    pos = await mgr.adopt({
        "portfolioId": portfolio_id, "symbol": underlying.upper(),
        "direction": direction, "techniqueId": "tip",
        "tags": tags + ([f"exit:analyst:{str(analyst_run_id)[:8]}"] if analyst_run_id
                        else ["exit:default"]),
        "runId": analyst_run_id, "entry": entry_ref,
        "risk": max((net if net > 0 else width - abs(net)), 0.01),
        "legs": [
            {"symbol": long_leg["symbol"], "secType": "OPT", "qty": qty,
             "avgFill": fill1, "multiplier": 100.0, "entryOrderId": o1_id,
             "origin": "adoption"},
            {"symbol": short_leg["symbol"], "secType": "OPT", "qty": -qty,
             "avgFill": fill2, "multiplier": 100.0, "entryOrderId": o2_id,
             "origin": "adoption"},
        ],
        "overnight": "app_managed", "overnightAck": True,
        "policy": policy, "guardAccepted": True,
    })
    log.info("spread opened: %s %s/%s x%d net %+.2f (%s) -> position %s",
             underlying, long_leg.get("strike"), short_leg.get("strike"), qty, net,
             "debit" if net > 0 else "credit", pos["id"])
    return pos


def contextlib_suppress():
    import contextlib
    return contextlib.suppress(Exception)


async def _note_on_run(eng, run_id: str | None, text: str) -> None:
    """Append a note step to a finished analyst run (adoption fallbacks must be
    visible where the plan was written, not only in the journal)."""
    if not run_id:
        return
    import datetime as _dt

    from ...models import TipAnalystRun
    try:
        async with eng.sf() as session:
            row = await session.get(TipAnalystRun, run_id)
            if row is None:
                return
            trace = list(row.trace or [])
            trace.append({"seq": len(trace), "kind": "note", "text": text,
                          "at": _dt.datetime.now(_dt.timezone.utc).isoformat()})
            row.trace = trace
            await session.commit()
    except Exception:
        log.debug("run note append failed for %s", run_id)


async def resume_pending_adoptions(eng, *, days: float = 5.0) -> int:
    """Restart safety (ARM-PLAN P2/F6): an approved tip proposal whose order was
    still resting at shutdown gets its adopt-on-fill waiter re-armed on boot.
    Idempotent — a proposal whose order already lives in a managed position is
    skipped."""
    import datetime as _dt

    from sqlalchemy import select

    from ...models import ManagedPositionRow, Proposal

    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)
    async with eng.sf() as session:
        props = (await session.execute(
            select(Proposal).where(Proposal.status == "executed",
                                   Proposal.created_at >= cutoff))).scalars().all()
        props = [p for p in props
                 if (p.context or {}).get("techniqueId") == "tip" and p.order_id]
        rows = (await session.execute(
            select(ManagedPositionRow).where(ManagedPositionRow.technique == "tip",
                                             ManagedPositionRow.created_at >= cutoff)
        )).scalars().all()
    adopted = {str(leg.get("entryOrderId"))
               for r in rows for leg in (r.legs or []) if leg.get("entryOrderId")}
    from ...approvals.proposals import proposal_dict
    n = 0
    for p in props:
        if str(p.order_id) in adopted:
            continue
        asyncio.create_task(adopt_when_filled(eng, proposal_dict(p), {"id": p.order_id}),
                            name=f"tip-adopt-resume-{p.id[:8]}")
        n += 1
    if n:
        log.info("resumed %d pending tip adoption(s) after restart", n)
    return n


async def _unwind_or_adopt_naked_long(eng, *, portfolio_id: str, underlying: str,
                                      direction: str, long_leg: dict, qty: int,
                                      fill: float, entry_order_id: str, tags: list[str],
                                      gid: str, why: str, signal_id: str | None,
                                      analyst_run_id: str | None) -> bool:
    """The spread's short leg died: sell the long back at market, VERIFYING the
    fill and retrying (ARM-GAPS B3). If the rollback itself fails, journal a
    dedicated event, alert every channel, and adopt the naked long as an
    `attention` managed position with an emergency policy — never leave a filled
    leg invisible. Returns True when the long was successfully unwound."""
    from ... import bus as topics
    from ... import events as ev
    from ...orders import OrderIntent

    for attempt in range(3):
        try:
            o = await eng.orders.place(OrderIntent(
                portfolio_id=portfolio_id, symbol=long_leg["symbol"], sec_type="OPT",
                side="SELL", qty=qty, order_type="MKT", tif="DAY", source="technique",
                technique_id="tip", tags=tags, reduce_only=True))
        except Exception as exc:
            log.warning("spread rollback attempt %d errored: %s", attempt + 1, exc)
            await asyncio.sleep(1.0 * (attempt + 1))
            continue
        if o.get("status") not in ("REJECTED", "REJECTED_RISK", "ERROR"):
            deadline = asyncio.get_event_loop().time() + 30
            while asyncio.get_event_loop().time() < deadline:
                row = await _order_row(eng, o["id"])
                if (row or {}).get("status") == "FILLED":
                    log.info("spread %s rollback filled (%s)", gid, why)
                    return True
                if (row or {}).get("status") in ("CANCELLED", "REJECTED",
                                                 "REJECTED_RISK", "EXPIRED", "ERROR"):
                    break
                await asyncio.sleep(0.5)
        await asyncio.sleep(1.0 * (attempt + 1))

    # ---- rollback failed: loud, and the leg goes under management
    text = (f"{underlying} spread {gid}: {why} AND the long-leg rollback failed — "
            f"holding {qty} x {long_leg['symbol']} naked-long; adopted for ATTENTION, "
            f"verify at the broker")
    with contextlib_suppress():
        await eng.journal.append(ev.TIP_SPREAD_LEG_FAILED, {
            "spread": gid, "underlying": underlying, "why": why,
            "legSymbol": long_leg["symbol"], "qty": qty, "portfolioId": portfolio_id,
            **({"signalId": signal_id} if signal_id else {})},
            aggregate_type="signal", aggregate_id=signal_id or gid,
            portfolio_id=portfolio_id)
    with contextlib_suppress():
        eng.bus.publish(topics.TECHNIQUE, {"kind": "alert", "level": "critical",
                                           "text": text, "symbol": underlying})
    tg = getattr(eng, "telegram", None)
    if tg is not None:
        with contextlib_suppress():
            await tg.send(f"⚠ {text}")
    mgr = getattr(eng, "position_manager", None)
    if mgr is not None:
        with contextlib_suppress():
            pos = await mgr.adopt({
                "portfolioId": portfolio_id, "symbol": underlying,
                "direction": direction, "techniqueId": "tip",
                "tags": tags + ["exit:default", "spread-orphan"],
                "runId": analyst_run_id,
                "entry": float(long_leg.get("strike") or 0) or 1.0,
                "risk": max(fill, 0.01),
                "legs": [{"symbol": long_leg["symbol"], "secType": "OPT", "qty": qty,
                          "avgFill": fill, "multiplier": 100.0,
                          "entryOrderId": entry_order_id, "origin": "adoption"}],
                "overnight": "app_managed", "overnightAck": True,
                "policy": {"timeframe": "15m",
                           "stop": {"kind": "none",
                                    "guard": "orphaned spread long — max loss is the debit; "
                                             "premium stop + tight time box"},
                           "premium_stop_pct": 50.0, "time_stop_sessions": 1,
                           "dte_close": max(1, int(eng.settings.get("execution.min_dte", 1)))},
                "guardAccepted": True,
            })
            p = mgr.get(pos["id"])
            if p is not None:
                p.status = "attention"
                p.attention.append(text)
    return False


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

    # ---- wait for the fill (sim fills in ms; a live LMT may rest a while).
    # A PARTIAL fill is real money (ARM-GAPS B1): when the order goes terminal —
    # or the wait times out — with filled_qty > 0, the filled contracts are
    # adopted and the resting remainder is CANCELLED, never abandoned unmanaged.
    deadline = asyncio.get_event_loop().time() + FILL_WAIT_S
    row = None
    partial = False
    while True:
        row = await _order_row(eng, oid)
        st = (row or {}).get("status") or ""
        filled = float((row or {}).get("filledQty") or 0)
        if st == "FILLED":
            break
        if st in ("CANCELLED", "REJECTED", "REJECTED_RISK", "EXPIRED", "ERROR"):
            if filled > 0:
                partial = True
                log.warning("proposal %s order %s ended %s with %g filled — adopting the partial",
                            pid, oid, st, filled)
                break
            log.info("proposal %s order %s ended %s — nothing to manage", pid, oid, st)
            await note(ev.TIP_POSITION_NOT_ADOPTED, {"reason": f"order {st}"})
            return None
        if asyncio.get_event_loop().time() > deadline:
            import contextlib as _ctx
            with _ctx.suppress(Exception):
                await eng.orders.cancel(oid)
            await asyncio.sleep(POLL_S)                 # let the cancel settle
            row = await _order_row(eng, oid) or row
            filled = float((row or {}).get("filledQty") or 0)
            if filled > 0:
                partial = True
                log.warning("proposal %s order %s timed out with %g filled — remainder "
                            "cancelled, adopting the partial", pid, oid, filled)
                break
            log.warning("proposal %s order %s unfilled after %.0fh — cancelled, not adopted",
                        pid, oid, FILL_WAIT_S / 3600)
            await note(ev.TIP_POSITION_NOT_ADOPTED,
                       {"reason": "fill wait timed out", "cancelledResting": True})
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
        await _note_on_run(eng, ctx.get("analystRunId"),
                           f"Exit plan REJECTED by the position manager ({exc}) — the "
                           f"position ({pos['id'][:8]}) runs the default 50/50 ladder instead.")
        return pos
    await note(ev.TIP_POSITION_ADOPTED,
               {"positionId": pos["id"], "policy": policy,
                "exitPlan": plan, "runId": spec["runId"],
                **({"partial": True, "filled": qty,
                    "ordered": float(proposal.get("qty") or 0)} if partial else {})})
    log.info("proposal %s adopted as managed position %s (%s, %s)%s",
             pid, pos["id"], underlying, "OPT" if is_opt else "STK",
             " [partial]" if partial else "")
    return pos
